from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.exceptions import ValidationError
from django.db import transaction

from mensajeria.outbox import publicar_evento_outbox
from .models import EventoIncidencia, Incidencia, Tecnico, Unidad

# Definición explícita de la Máquina de Estados (Módulo 1)
TRANSICIONES_PERMITIDAS = {
    'PENDIENTE': ['EN_PROCESO', 'CERRADA'],
    'EN_PROCESO': ['RESUELTA', 'PENDIENTE'],
    'RESUELTA': ['CERRADA', 'PENDIENTE'],  # 'PENDIENTE' representa la reapertura
    'CERRADA': ['PENDIENTE'],              # Reapertura desde cerrada
}


def registrar_evento(incidencia, tipo_evento, usuario_actor, datos_previos=None, datos_nuevos=None):
    """
    Función auxiliar de solo anexado (append-only) para guardar 
    el historial inmutable de auditoría.
    """
    EventoIncidencia.objects.create(
        incidencia=incidencia,
        tipo_evento=tipo_evento,
        usuario_actor=usuario_actor,
        datos_previos=datos_previos,
        datos_nuevos=datos_nuevos
    )


def _notificar_tiempo_real(incidencia, tipo_evento):
    """Publica el evento por WebSocket a los grupos del edificio y de la incidencia tras el commit (Módulo 6)."""
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
def crear_incidencia(usuario, titulo, descripcion, unidad_id, foto=None):
    """Caso de uso: Crear una nueva incidencia y publicar evento en el Outbox"""
    unidad = Unidad.objects.get(id=unidad_id)
    
    incidencia = Incidencia.objects.create(
        titulo=titulo,
        descripcion=descripcion,
        unidad=unidad,
        reportado_por=usuario,
        foto=foto,
        estado='PENDIENTE'
    )
    
    registrar_evento(
        incidencia=incidencia,
        tipo_evento='INCIDENCIA_CREADA',
        usuario_actor=usuario,
        datos_nuevos={'titulo': titulo, 'unidad_id': unidad_id, 'estado': 'PENDIENTE'}
    )

    publicar_evento_outbox(
        edificio_id=incidencia.edificio_id,
        tipo_evento='incidencia.creada',
        clave_idempotencia=f"inc-creada-{incidencia.id}",
        payload={
            'incidencia_id': incidencia.id,
            'titulo': incidencia.titulo,
            'estado': incidencia.estado,
            'email_destino': usuario.email or 'residente@vecinosapp.local',
            'detalle': f"Se ha registrado tu incidencia '{incidencia.titulo}'.",
        },
    )

    _notificar_tiempo_real(incidencia, 'incidencia.creada')
    
    return incidencia


@transaction.atomic
def cambiar_estado(incidencia_id, nuevo_estado, usuario_actor):
    """Caso de uso: Cambiar estado con validación estricta y publicación en Outbox"""
    incidencia = Incidencia.objects.select_for_update().get(id=incidencia_id)
    estado_anterior = incidencia.estado

    # Validar transición según la máquina de estados
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
def asignar_tecnico(incidencia_id, tecnico_id, usuario_actor):
    """Caso de uso: Asignar un técnico especializado a la incidencia"""
    incidencia = Incidencia.objects.select_for_update().get(id=incidencia_id)
    tecnico = Tecnico.objects.get(id=tecnico_id)
    
    tecnico_anterior_id = incidencia.tecnico_asignado_id if incidencia.tecnico_asignado else None
    
    incidencia.tecnico_asignado = tecnico
    
    # Si estaba en PENDIENTE, al asignar técnico pasa a EN_PROCESO
    if incidencia.estado == 'PENDIENTE':
        incidencia.estado = 'EN_PROCESO'
        
    incidencia.save()

    registrar_evento(
        incidencia=incidencia,
        tipo_evento='TECNICO_ASIGNADO',
        usuario_actor=usuario_actor,
        datos_previos={'tecnico_id': tecnico_anterior_id},
        datos_nuevos={'tecnico_id': tecnico.id, 'estado': incidencia.estado}
    )

    publicar_evento_outbox(
        edificio_id=incidencia.edificio_id,
        tipo_evento='incidencia.tecnico_asignado',
        clave_idempotencia=f"inc-tecnico-{incidencia.id}-v{incidencia.version}-tec{tecnico.id}",
        payload={
            'incidencia_id': incidencia.id,
            'titulo': incidencia.titulo,
            'tecnico_id': tecnico.id,
            'estado': incidencia.estado,
            'email_destino': tecnico.usuario.email or 'tecnico@vecinosapp.local',
            'detalle': f"Se te ha asignado la incidencia '{incidencia.titulo}'.",
        },
    )

    _notificar_tiempo_real(incidencia, 'incidencia.tecnico_asignado')
    
    return incidencia


@transaction.atomic
def reabrir_incidencia(incidencia_id, usuario_actor, motivo=""):
    """Caso de uso: Reabrir una incidencia resuelta o cerrada"""
    return cambiar_estado(incidencia_id, 'PENDIENTE', usuario_actor)