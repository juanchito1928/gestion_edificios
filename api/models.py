import uuid
from django.db import models
from django.contrib.auth.models import User
from incidencias.models import Edificio, Incidencia


class ClaveIdempotencia(models.Model):
    edificio = models.ForeignKey(Edificio, on_delete=models.CASCADE, null=True, blank=True)
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    clave = models.CharField(max_length=128)
    ruta = models.CharField(max_length=255)
    cuerpo_hash = models.CharField(max_length=64)
    codigo_http = models.PositiveSmallIntegerField()
    respuesta_json = models.JSONField()
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['usuario', 'ruta', 'clave'],
                name='uq_idempotencia_usuario_ruta_clave',
            )
        ]

    def __str__(self):
        return f"{self.usuario.username} - {self.clave} ({self.codigo_http})"


class SuscripcionWebhook(models.Model):
    edificio = models.ForeignKey(Edificio, on_delete=models.CASCADE, related_name='webhooks')
    evento = models.CharField(max_length=100, default='incidencia.resuelta')
    url_destino = models.URLField(max_length=500)
    secreto_hmac = models.CharField(max_length=128)
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.evento}] -> {self.url_destino}"


class AdjuntoIncidencia(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    edificio = models.ForeignKey(Edificio, on_delete=models.CASCADE, null=True, blank=True)
    incidencia = models.ForeignKey(Incidencia, on_delete=models.CASCADE, related_name='adjuntos')
    subido_por = models.ForeignKey(User, on_delete=models.CASCADE)
    nombre_archivo = models.CharField(max_length=255)
    tipo_mime_declarado = models.CharField(max_length=100)
    tipo_mime_real = models.CharField(max_length=100, blank=True)
    archivo = models.FileField(upload_to='adjuntos_api/', blank=True, null=True)
    verificado = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.edificio_id and self.incidencia_id:
            self.edificio_id = self.incidencia.edificio_id
        super().save(*args, **kwargs)
