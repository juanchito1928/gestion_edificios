from rest_framework import serializers
from incidencias.models import Incidencia, Comentario, EventoIncidencia
from .models import AdjuntoIncidencia, SuscripcionWebhook


class EventoIncidenciaSerializer(serializers.ModelSerializer):
    usuario_actor = serializers.CharField(source='usuario_actor.username', read_only=True)

    class Meta:
        model = EventoIncidencia
        fields = ['id', 'tipo_evento', 'datos_previos', 'datos_nuevos', 'usuario_actor', 'fecha_evento']


class ComentarioSerializer(serializers.ModelSerializer):
    autor = serializers.CharField(source='autor.username', read_only=True)

    class Meta:
        model = Comentario
        fields = ['id', 'autor', 'texto', 'fecha_creacion']
        read_only_fields = ['id', 'autor', 'fecha_creacion']


class AdjuntoIncidenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdjuntoIncidencia
        fields = [
            'id', 'nombre_archivo', 'tipo_mime_declarado',
            'tipo_mime_real', 'verificado', 'archivo', 'fecha_creacion',
        ]
        read_only_fields = ['id', 'tipo_mime_real', 'verificado', 'archivo', 'fecha_creacion']


class IncidenciaSerializer(serializers.ModelSerializer):
    reportado_por = serializers.CharField(source='reportado_por.username', read_only=True)
    unidad_numero = serializers.CharField(source='unidad.numero', read_only=True)
    tecnico_username = serializers.CharField(source='tecnico_asignado.usuario.username', read_only=True, default=None)
    comentarios = ComentarioSerializer(many=True, read_only=True)
    adjuntos = AdjuntoIncidenciaSerializer(many=True, read_only=True)

    class Meta:
        model = Incidencia
        fields = [
            'id', 'titulo', 'descripcion', 'categoria', 'prioridad',
            'estado', 'version', 'unidad', 'unidad_numero',
            'reportado_por', 'tecnico_asignado', 'tecnico_username',
            'fecha_creacion', 'fecha_actualizacion',
            'comentarios', 'adjuntos',
        ]
        read_only_fields = ['id', 'estado', 'version', 'reportado_por', 'fecha_creacion', 'fecha_actualizacion']

    @staticmethod
    def optimizar_queryset(queryset):
        return queryset.select_related(
            'edificio', 'unidad', 'reportado_por', 'tecnico_asignado__usuario'
        ).prefetch_related('comentarios__autor', 'adjuntos')


class CrearIncidenciaInputSerializer(serializers.Serializer):
    titulo = serializers.CharField(max_length=200)
    descripcion = serializers.CharField()
    unidad_id = serializers.IntegerField()


class CambiarEstadoInputSerializer(serializers.Serializer):
    nuevo_estado = serializers.ChoiceField(choices=['PENDIENTE', 'EN_PROCESO', 'RESUELTA', 'CERRADA'])


class AsignarTecnicoInputSerializer(serializers.Serializer):
    tecnico_id = serializers.IntegerField()


class SolicitarSubidaInputSerializer(serializers.Serializer):
    nombre_archivo = serializers.CharField(max_length=255)
    tipo_mime_declarado = serializers.ChoiceField(
        choices=['image/jpeg', 'image/png', 'image/webp', 'application/pdf']
    )


class SuscripcionWebhookSerializer(serializers.ModelSerializer):
    class Meta:
        model = SuscripcionWebhook
        fields = ['id', 'evento', 'url_destino', 'secreto_hmac', 'activo', 'fecha_creacion']
        read_only_fields = ['id', 'fecha_creacion']