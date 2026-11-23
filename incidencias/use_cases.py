from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from mensajeria.outbox import publicar_evento_outbox
from .models import EventoIncidencia, Incidencia, Tecnico, Unidad

ESTADOS_ACTIVOS = ['PENDIENTE', 'EN_PROCESO']

TRANSICIONES_PERMITIDAS = {
    'PENDIENTE': ['EN_PROCESO', 'CERRADA'],
    'EN_PROCESO': ['RESUELTA', 'PENDIENTE'],
    'RESUELTA': ['CERRADA', 'PENDIENTE'],
    'CERRADA': ['PENDIENTE'],
}


def tecnico_esta_ocupado(tecnico, excluir_incidencia_id=None):
    qs = Incidencia.sin_filtro.filter(
        tecnico_asignado=tecnico,
        estado__in=ESTADOS_ACTIVOS,
    )
    if excluir_incidencia_id:
        qs = qs.exclude(pk=excluir_incidencia_id)
    return qs.exists()


def registrar_evento(incidencia, tipo_evento, usuario_actor, datos_previos=None, datos_nuevos=None):
    EventoIncidencia.objects.create(
        incidencia=incidencia,
        tipo_evento=tipo_evento,
        usuario_actor=usuario_actor,
        datos_previos=datos_previos,
        datos_nuevos=datos_nuevos
    )


def _notificar_tiempo_real(incidencia, tipo_evento, mensaje_extra=None):
    def _enviar():
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        payload = {
            'tipo': tipo_evento,
            'incidencia_id': incidencia.id,
            'titulo': incidencia.titulo,
            'estado': incidencia.estado,
            'estado_display': incidencia.get_estado_display(),
            'tiempo_estimado': incidencia.tiempo_estimado or '',
            'instrucciones_tecnico': incidencia.instrucciones_tecnico or '',
            'mensaje_extra': mensaje_extra or '',
            'tecnico': (
                incidencia.tecnico_asignado.usuario.get_full_name()
                or incidencia.tecnico_asignado.usuario.username
                if incidencia.tecnico_asignado else 'Sin asignar'
            ),
        }
        mensaje = {'type': 'incidencia_actualizada', 'data': payload}
        async_to_sync(channel_layer.group_send)(f"edificio_{incidencia.edificio_id}", mensaje)
        async_to_sync(channel_layer.group_send)(f"incidencia_{incidencia.id}", mensaje)

    transaction.on_commit(_enviar)


@transaction.atomic
def crear_incidencia(usuario, titulo, descripcion, unidad_id, foto=None, categoria=None, tiempo_estimado=None):
    unidad = Unidad.objects.get(id=unidad_id)

    incidencia = Incidencia.objects.create(
        titulo=titulo,
        descripcion=descripcion,
        categoria=(categoria or '').strip() or None,
        tiempo_estimado=(tiempo_estimado or '').strip() or None,
        unidad=unidad,
        reportado_por=usuario,
        foto=foto,
        estado='PENDIENTE'
    )

    registrar_evento(
        incidencia=incidencia,
        tipo_evento='INCIDENCIA_CREADA',
        usuario_actor=usuario,
        datos_nuevos={
            'titulo': titulo,
            'unidad_id': unidad_id,
            'categoria': incidencia.categoria,
            'tiempo_estimado': incidencia.tiempo_estimado,
            'estado': 'PENDIENTE',
        }
    )

    publicar_evento_outbox(
        edificio_id=incidencia.edificio_id,
        tipo_evento='incidencia.creada',
        clave_idempotencia=f"inc-creada-{incidencia.id}",
        payload={
            'incidencia_id': incidencia.id,
            'titulo': incidencia.titulo,
            'estado': incidencia.estado,
            'tiempo_estimado': incidencia.tiempo_estimado or 'Por definir',
            'email_destino': usuario.email or 'residente@vecinosapp.local',
            'detalle': f"Se ha registrado tu incidencia '{incidencia.titulo}'.",
        },
    )

    _notificar_tiempo_real(incidencia, 'incidencia.creada')

    return incidencia


@transaction.atomic
def cambiar_estado(incidencia_id, nuevo_estado, usuario_actor):
    incidencia = Incidencia.objects.select_for_update().get(id=incidencia_id)
    estado_anterior = incidencia.estado

    if nuevo_estado not in TRANSICIONES_PERMITIDAS.get(estado_anterior, []):
        raise ValidationError(
            f"Transición no permitida: No se puede pasar de '{estado_anterior}' a '{nuevo_estado}'."
        )

    incidencia.estado = nuevo_estado
    incidencia.save()

    registrar_evento(
        incidencia=incidencia,
        tipo_evento='ESTADO_CAMBIADO',
        usuario_actor=usuario_actor,
        datos_previos={'estado': estado_anterior},
        datos_nuevos={'estado': nuevo_estado}
    )

    publicar_evento_outbox(
        edificio_id=incidencia.edificio_id,
        tipo_evento='incidencia.resuelta' if nuevo_estado == 'RESUELTA' else 'incidencia.estado_cambiado',
        clave_idempotencia=f"inc-estado-{incidencia.id}-v{incidencia.version}-{nuevo_estado}",
        payload={
            'incidencia_id': incidencia.id,
            'titulo': incidencia.titulo,
            'estado_anterior': estado_anterior,
            'estado_nuevo': nuevo_estado,
            'email_destino': incidencia.reportado_por.email or 'residente@vecinosapp.local',
            'detalle': f"Tu incidencia '{incidencia.titulo}' pasó de {estado_anterior} a {nuevo_estado}.",
        },
    )

    _notificar_tiempo_real(incidencia, 'incidencia.estado_cambiado')

    return incidencia


@transaction.atomic
def asignar_tecnico(incidencia_id, tecnico_id, usuario_actor, tiempo_estimado="", instrucciones_tecnico="", forzar=False):
    incidencia = Incidencia.objects.select_for_update().get(id=incidencia_id)
    tecnico = Tecnico.objects.select_related('usuario').get(id=tecnico_id)

    if not forzar and tecnico_esta_ocupado(tecnico, excluir_incidencia_id=incidencia.id):
        raise ValidationError(
            f"El técnico {tecnico.usuario.username} ya tiene una incidencia activa asignada y estará disponible cuando la termine."
        )

    tecnico_anterior_id = incidencia.tecnico_asignado_id if incidencia.tecnico_asignado else None

    incidencia.tecnico_asignado = tecnico
    incidencia.fecha_asignacion = timezone.now()
    if (tiempo_estimado or '').strip():
        incidencia.tiempo_estimado = tiempo_estimado.strip()
    if (instrucciones_tecnico or '').strip():
        incidencia.instrucciones_tecnico = instrucciones_tecnico.strip()

    if incidencia.estado == 'PENDIENTE':
        incidencia.estado = 'EN_PROCESO'

    incidencia.save()

    registrar_evento(
        incidencia=incidencia,
        tipo_evento='TECNICO_ASIGNADO',
        usuario_actor=usuario_actor,
        datos_previos={'tecnico_id': tecnico_anterior_id},
        datos_nuevos={
            'tecnico_id': tecnico.id,
            'estado': incidencia.estado,
            'fecha_asignacion': incidencia.fecha_asignacion.isoformat(),
            'tiempo_estimado': incidencia.tiempo_estimado,
            'instrucciones_tecnico': incidencia.instrucciones_tecnico,
        }
    )

    mensaje_tec = (
        f"Nueva tarea asignada: '{incidencia.titulo}' en {incidencia.unidad}. "
        f"Tiempo estimado: {incidencia.tiempo_estimado or 'No especificado'}. "
        f"Mensaje: {incidencia.instrucciones_tecnico or 'Atender según prioridad.'}"
    )

    publicar_evento_outbox(
        edificio_id=incidencia.edificio_id,
        tipo_evento='incidencia.tecnico_asignado',
        clave_idempotencia=f"inc-tecnico-{incidencia.id}-v{incidencia.version}-tec{tecnico.id}",
        payload={
            'incidencia_id': incidencia.id,
            'titulo': incidencia.titulo,
            'tecnico_id': tecnico.id,
            'tecnico_username': tecnico.usuario.username,
            'estado': incidencia.estado,
            'tiempo_estimado': incidencia.tiempo_estimado or '',
            'instrucciones_tecnico': incidencia.instrucciones_tecnico or '',
            'email_destino': tecnico.usuario.email or 'tecnico@vecinosapp.local',
            'detalle': mensaje_tec,
        },
    )

    _notificar_tiempo_real(incidencia, 'incidencia.tecnico_asignado', mensaje_extra=mensaje_tec)

    return incidencia


@transaction.atomic
def reabrir_incidencia(incidencia_id, usuario_actor, motivo=""):
    return cambiar_estado(incidencia_id, 'PENDIENTE', usuario_actor)