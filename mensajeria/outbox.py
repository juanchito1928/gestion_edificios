from django.db import transaction
from .models import MensajeOutbox


def publicar_evento_outbox(edificio_id: int, tipo_evento: str, clave_idempotencia: str, payload: dict) -> MensajeOutbox:
    """
    Guarda el evento en la tabla Outbox dentro de la transacción actual.
    Cuando la transacción hace commit exitosamente, encola la tarea en Celery.
    """
    mensaje, creado = MensajeOutbox.objects.get_or_create(
        clave_idempotencia=clave_idempotencia,
        defaults={
            'edificio_id': edificio_id,
            'tipo_evento': tipo_evento,
            'payload': payload,
        },
    )

    if creado:
        from .tasks import procesar_mensaje_outbox
        mensaje_id_str = str(mensaje.id)
        transaction.on_commit(lambda: _encolar_seguro(mensaje_id_str))

    return mensaje


def _encolar_seguro(mensaje_id: str):
    """Encola en Celery; si Redis está caído, el Outbox ya quedó guardado en BD para rescate."""
    from .tasks import procesar_mensaje_outbox
    try:
        procesar_mensaje_outbox.delay(mensaje_id)
    except Exception:
        # El cron de rescate recogerá el mensaje PENDIENTE cuando Redis vuelva
        pass