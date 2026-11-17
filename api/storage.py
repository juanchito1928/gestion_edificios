from django.core import signing
from django.urls import reverse

SALT_SUBIDA = 'vecinos-adjunto-prefirmado-v1'


def generar_url_prefirmada(request, adjunto_id: str, expiracion_segundos: int = 600) -> str:
    token = signing.dumps({'adjunto_id': str(adjunto_id)}, salt=SALT_SUBIDA)
    ruta = reverse('adjunto-upload-directo', kwargs={'token': token})
    return request.build_absolute_uri(ruta)


def validar_token_prefirmado(token: str, max_age: int = 600) -> str:
    data = signing.loads(token, salt=SALT_SUBIDA, max_age=max_age)
    return data['adjunto_id']


def detectar_mime_real(archivo) -> str:
    """Inspecciona los primeros bytes reales (magic bytes) del archivo subido."""
    pos = archivo.tell()
    cabecera = archivo.read(16)
    archivo.seek(pos)

    if cabecera.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if cabecera.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if cabecera.startswith(b'%PDF-'):
        return 'application/pdf'
    if cabecera.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if cabecera.startswith(b'RIFF') and cabecera[8:12] == b'WEBP':
        return 'image/webp'
    return 'application/octet-stream'