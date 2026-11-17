import hashlib
import hmac
import json
import time
import urllib.request
from .models import SuscripcionWebhook


def generar_firma_webhook(secreto: str, timestamp: str, payload_str: str) -> str:
    mensaje = f"{timestamp}.{payload_str}".encode('utf-8')
    digest = hmac.new(secreto.encode('utf-8'), mensaje, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def despachar_webhook(edificio_id: int, evento: str, datos: dict) -> list[dict]:
    """
    Busca suscripciones activas del edificio para el evento y firma el payload
    con HMAC-SHA256 y marca de tiempo (X-Webhook-Timestamp / X-Webhook-Signature).
    """
    suscripciones = SuscripcionWebhook.objects.filter(
        edificio_id=edificio_id,
        evento=evento,
        activo=True,
    )
    resultados = []
    timestamp = str(int(time.time()))
    payload_str = json.dumps({'evento': evento, 'timestamp': timestamp, 'data': datos}, default=str)

    for sub in suscripciones:
        firma = generar_firma_webhook(sub.secreto_hmac, timestamp, payload_str)
        headers = {
            'Content-Type': 'application/json',
            'X-Webhook-Event': evento,
            'X-Webhook-Timestamp': timestamp,
            'X-Webhook-Signature': firma,
        }
        try:
            req = urllib.request.Request(
                sub.url_destino,
                data=payload_str.encode('utf-8'),
                headers=headers,
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                resultados.append({'url': sub.url_destino, 'status': resp.status, 'firma': firma})
        except Exception as exc:
            resultados.append({'url': sub.url_destino, 'status': 'error', 'detalle': str(exc), 'firma': firma})

    return resultados