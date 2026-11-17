import hashlib
import json
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.signing import BadSignature, SignatureExpired
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils.http import quote_etag
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from incidencias.models import Comentario, Incidencia, Unidad
from incidencias.use_cases import asignar_tecnico, cambiar_estado, crear_incidencia
from .models import AdjuntoIncidencia, ClaveIdempotencia, SuscripcionWebhook
from .permissions import ContextoEdificioRLSPermission
from .serializers import (
    AdjuntoIncidenciaSerializer,
    AsignarTecnicoInputSerializer,
    CambiarEstadoInputSerializer,
    ComentarioSerializer,
    CrearIncidenciaInputSerializer,
    IncidenciaSerializer,
    SolicitarSubidaInputSerializer,
    SuscripcionWebhookSerializer,
)
from .storage import detectar_mime_real, generar_url_prefirmada, validar_token_prefirmado
from .webhooks import despachar_webhook


class IncidenciaViewSet(viewsets.ModelViewSet):
    serializer_class = IncidenciaSerializer
    permission_classes = [ContextoEdificioRLSPermission]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        return IncidenciaSerializer.optimizar_queryset(Incidencia.objects.all())

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        etag_valor = quote_etag(f"inc-{instance.id}-v{instance.version}-{int(instance.fecha_actualizacion.timestamp())}")

        if request.headers.get('If-None-Match') == etag_valor:
            return Response(status=status.HTTP_304_NOT_MODIFIED, headers={'ETag': etag_valor})

        serializer = self.get_serializer(instance)
        return Response(serializer.data, headers={'ETag': etag_valor})

    @extend_schema(
        request=CrearIncidenciaInputSerializer,
        responses={201: IncidenciaSerializer, 200: IncidenciaSerializer},
        parameters=[
            OpenApiParameter(
                name='Idempotency-Key',
                type=str,
                location=OpenApiParameter.HEADER,
                required=False,
                description='Clave única para evitar duplicados al reintentar POST',
            )
        ],
    )
    def create(self, request, *args, **kwargs):
        clave_idem = request.headers.get('Idempotency-Key', '').strip()
        cuerpo_hash = hashlib.sha256(
            json.dumps(request.data, sort_keys=True, default=str).encode('utf-8')
        ).hexdigest()

        if clave_idem:
            existente = ClaveIdempotencia.objects.filter(
                usuario=request.user,
                ruta=request.path,
                clave=clave_idem,
            ).first()
            if existente:
                if existente.cuerpo_hash != cuerpo_hash:
                    return Response(
                        {'detail': 'Idempotency-Key ya utilizada con un cuerpo diferente.'},
                        status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    )
                return Response(existente.respuesta_json, status=existente.codigo_http)

        input_ser = CrearIncidenciaInputSerializer(data=request.data)
        input_ser.is_valid(raise_exception=True)
        datos = input_ser.validated_data

        try:
            with transaction.atomic():
                incidencia = crear_incidencia(
                    usuario=request.user,
                    titulo=datos['titulo'],
                    descripcion=datos['descripcion'],
                    unidad_id=datos['unidad_id'],
                )
                salida = IncidenciaSerializer(incidencia).data
                if clave_idem:
                    ClaveIdempotencia.objects.create(
                        edificio=incidencia.edificio,
                        usuario=request.user,
                        clave=clave_idem,
                        ruta=request.path,
                        cuerpo_hash=cuerpo_hash,
                        codigo_http=status.HTTP_201_CREATED,
                        respuesta_json=salida,
                    )
        except Unidad.DoesNotExist:
            return Response({'detail': 'Unidad no encontrada en este edificio.'}, status=status.HTTP_404_NOT_FOUND)
        except IntegrityError:
            return Response(
                {'detail': 'Ya existe una incidencia abierta con ese título en la unidad.'},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(salida, status=status.HTTP_201_CREATED)

    @extend_schema(request=CambiarEstadoInputSerializer, responses={200: IncidenciaSerializer})
    @action(detail=True, methods=['post'], url_path='cambiar-estado')
    def cambiar_estado_action(self, request, pk=None):
        incidencia = self.get_object()
        input_ser = CambiarEstadoInputSerializer(data=request.data)
        input_ser.is_valid(raise_exception=True)
        nuevo_estado = input_ser.validated_data['nuevo_estado']

        try:
            incidencia = cambiar_estado(incidencia.id, nuevo_estado, request.user)
        except DjangoValidationError as exc:
            return Response({'detail': exc.message}, status=status.HTTP_400_BAD_REQUEST)

        salida = IncidenciaSerializer(incidencia).data
        if nuevo_estado == 'RESUELTA':
            despachar_webhook(incidencia.edificio_id, 'incidencia.resuelta', salida)

        return Response(salida, status=status.HTTP_200_OK)

    @extend_schema(request=AsignarTecnicoInputSerializer, responses={200: IncidenciaSerializer})
    @action(detail=True, methods=['post'], url_path='asignar-tecnico')
    def asignar_tecnico_action(self, request, pk=None):
        incidencia = self.get_object()
        input_ser = AsignarTecnicoInputSerializer(data=request.data)
        input_ser.is_valid(raise_exception=True)

        try:
            incidencia = asignar_tecnico(
                incidencia.id,
                input_ser.validated_data['tecnico_id'],
                request.user,
            )
        except Exception as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(IncidenciaSerializer(incidencia).data, status=status.HTTP_200_OK)

    @extend_schema(request=ComentarioSerializer, responses={201: ComentarioSerializer, 200: ComentarioSerializer(many=True)})
    @action(detail=True, methods=['get', 'post'], url_path='comentarios')
    def comentarios(self, request, pk=None):
        incidencia = self.get_object()
        if request.method == 'GET':
            qs = Comentario.objects.filter(incidencia=incidencia).select_related('autor')
            return Response(ComentarioSerializer(qs, many=True).data)

        serializer = ComentarioSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comentario = Comentario.objects.create(
            edificio=incidencia.edificio,
            incidencia=incidencia,
            autor=request.user,
            texto=serializer.validated_data['texto'],
        )
        return Response(ComentarioSerializer(comentario).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=SolicitarSubidaInputSerializer, responses={201: dict})
    @action(detail=True, methods=['post'], url_path='adjuntos/solicitar-subida')
    def solicitar_subida(self, request, pk=None):
        incidencia = self.get_object()
        input_ser = SolicitarSubidaInputSerializer(data=request.data)
        input_ser.is_valid(raise_exception=True)

        adjunto = AdjuntoIncidencia.objects.create(
            edificio=incidencia.edificio,
            incidencia=incidencia,
            subido_por=request.user,
            nombre_archivo=input_ser.validated_data['nombre_archivo'],
            tipo_mime_declarado=input_ser.validated_data['tipo_mime_declarado'],
        )
        url_prefirmada = generar_url_prefirmada(request, str(adjunto.id))
        return Response(
            {
                'adjunto_id': str(adjunto.id),
                'upload_url': url_prefirmada,
                'expira_en_segundos': 600,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['get'], url_path='adjuntos')
    def listar_adjuntos(self, request, pk=None):
        incidencia = self.get_object()
        qs = AdjuntoIncidencia.objects.filter(incidencia=incidencia)
        return Response(AdjuntoIncidenciaSerializer(qs, many=True).data)


class SubidaPrefirmadaView(APIView):
    """
    Endpoint destino de la URL prefirmada: recibe el binario y verifica
    los magic bytes reales contra el tipo MIME declarado (Reto avanzado M4).
    """
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser]

    def put(self, request, token):
        try:
            adjunto_id = validar_token_prefirmado(token)
        except (BadSignature, SignatureExpired):
            return Response({'detail': 'URL prefirmada inválida o expirada.'}, status=status.HTTP_403_FORBIDDEN)

        adjunto = get_object_or_404(AdjuntoIncidencia, id=adjunto_id)
        archivo = request.FILES.get('file')
        if not archivo:
            return Response({'detail': 'Debe enviar el campo "file".'}, status=status.HTTP_400_BAD_REQUEST)

        mime_real = detectar_mime_real(archivo)
        adjunto.tipo_mime_real = mime_real

        if mime_real != adjunto.tipo_mime_declarado:
            adjunto.verificado = False
            adjunto.save(update_fields=['tipo_mime_real', 'verificado'])
            return Response(
                {
                    'detail': 'Contenido real del archivo no coincide con el tipo declarado.',
                    'declarado': adjunto.tipo_mime_declarado,
                    'detectado': mime_real,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        adjunto.archivo = archivo
        adjunto.verificado = True
        adjunto.save()
        return Response(AdjuntoIncidenciaSerializer(adjunto).data, status=status.HTTP_200_OK)


class SuscripcionWebhookViewSet(viewsets.ModelViewSet):
    serializer_class = SuscripcionWebhookSerializer
    permission_classes = [ContextoEdificioRLSPermission]

    def get_queryset(self):
        return SuscripcionWebhook.objects.filter(edificio_id=self.request.user.perfil.edificio_id)

    def perform_create(self, serializer):
        serializer.save(edificio_id=self.request.user.perfil.edificio_id)