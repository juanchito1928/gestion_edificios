from datetime import timedelta
from celery import shared_task
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from api.webhooks import despachar_webhook
from incidencias.models import Incidencia
from .models import EstadoOutbox, MensajeOutbox, PreferenciaNotificacion, RegistroEntrega


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,       # Espera exponencial: 1s, 2s, 4s, 8s...
    retry_backoff_max=60,
    max_retries=5,
)
def procesar_mensaje_outbox(self, mensaje_id: str):
    """
    Procesa un mensaje del Outbox de forma idempotente:
    - Si el worker se cae a mitad de camino y reintenta, RegistroEntrega evita duplicar envíos.
    """
    with transaction.atomic():
        mensaje = MensajeOutbox.objects.select_for_update().get(id=mensaje_id)
        if mensaje.estado == EstadoOutbox.ENVIADO:
            return f"Mensaje {mensaje_id} ya fue enviado previamente."

        mensaje.estado = EstadoOutbox.EN_PROCESO
        mensaje.intentos += 1
        mensaje.save(update_fields=['estado', 'intentos'])

    try:
        datos = mensaje.payload
        email_destino = datos.get('email_destino')

        # 1. Canal Email (idempotente mediante RegistroEntrega)
        if email_destino:
            ya_enviado_email = RegistroEntrega.objects.filter(
                mensaje=mensaje, canal='email', destinatario=email_destino
            ).exists()
            if not ya_enviado_email:
                send_mail(
                    subject=f"[VecinosApp] {mensaje.tipo_evento}: {datos.get('titulo', '')}",
                    message=datos.get('detalle', f"Actualización de incidencia #{datos.get('incidencia_id')}"),
                    from_email=None,
                    recipient_list=[email_destino],
                    fail_silently=False,
                )
                RegistroEntrega.objects.create(
                    mensaje=mensaje, canal='email', destinatario=email_destino
                )

        # 2. Canal Webhook HMAC (idempotente mediante RegistroEntrega)
        if mensaje.edificio_id:
            ya_enviado_wh = RegistroEntrega.objects.filter(
                mensaje=mensaje, canal='webhook', destinatario=f"edificio_{mensaje.edificio_id}"
            ).exists()
            if not ya_enviado_wh:
                despachar_webhook(mensaje.edificio_id, mensaje.tipo_evento, datos)
                RegistroEntrega.objects.create(
                    mensaje=mensaje, canal='webhook', destinatario=f"edificio_{mensaje.edificio_id}"
                )

        mensaje.estado = EstadoOutbox.ENVIADO
        mensaje.fecha_procesado = timezone.now()
        mensaje.save(update_fields=['estado', 'fecha_procesado'])
        return f"Mensaje {mensaje_id} procesado correctamente."

    except Exception as exc:
        mensaje.ultimo_error = str(exc)
        if mensaje.intentos >= mensaje.max_intentos:
            mensaje.estado = EstadoOutbox.FALLIDO
        else:
            mensaje.estado = EstadoOutbox.PENDIENTE
        mensaje.save(update_fields=['estado', 'ultimo_error'])
        raise exc


@shared_task
def rescatar_mensajes_outbox_pendientes():
    """Tarea periódica: rescata mensajes que quedaron PENDIENTE o atascados en EN_PROCESO."""
    limite_atasco = timezone.now() - timedelta(minutes=2)
    pendientes = MensajeOutbox.objects.filter(estado=EstadoOutbox.PENDIENTE)[:50]
    atascados = MensajeOutbox.objects.filter(
        estado=EstadoOutbox.EN_PROCESO, fecha_creacion__lt=limite_atasco
    )[:50]

    total = 0
    for msg in list(pendientes) + list(atascados):
        procesar_mensaje_outbox.delay(str(msg.id))
        total += 1
    return f"Rescatados {total} mensajes del outbox."


@shared_task
def escalar_incidencias_sla():
    """Tarea periódica: detecta incidencias en PENDIENTE > 24h y genera alerta SLA en el Outbox."""
    from .outbox import publicar_evento_outbox

    limite_sla = timezone.now() - timedelta(hours=24)
    vencidas = Incidencia.sin_filtro.filter(
        estado='PENDIENTE',
        fecha_creacion__lt=limite_sla,
    ).select_related('reportado_por')

    escaladas = 0
    for inc in vencidas:
        publicar_evento_outbox(
            edificio_id=inc.edificio_id,
            tipo_evento='sla.incidencia_vencida',
            clave_idempotencia=f"sla-inc-{inc.id}-{timezone.now().strftime('%Y%m%d')}",
            payload={
                'incidencia_id': inc.id,
                'titulo': inc.titulo,
                'email_destino': inc.reportado_por.email or 'admin@vecinosapp.local',
                'detalle': f"Alerta SLA: La incidencia '{inc.titulo}' lleva más de 24 horas pendiente.",
            },
        )
        escaladas += 1
    return f"Escaladas {escaladas} incidencias por SLA."