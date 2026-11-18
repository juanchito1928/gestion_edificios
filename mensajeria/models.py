import uuid
from django.db import models
from django.contrib.auth.models import User
from incidencias.models import Edificio


class EstadoOutbox(models.TextChoices):
    PENDIENTE = 'PENDIENTE', 'Pendiente'
    EN_PROCESO = 'EN_PROCESO', 'En Proceso'
    ENVIADO = 'ENVIADO', 'Enviado'
    FALLIDO = 'FALLIDO', 'Fallido (Dead Letter Queue)'


class MensajeOutbox(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    edificio = models.ForeignKey(Edificio, on_delete=models.CASCADE, null=True, blank=True)
    tipo_evento = models.CharField(max_length=100)
    clave_idempotencia = models.CharField(max_length=150, unique=True)
    payload = models.JSONField()
    estado = models.CharField(
        max_length=20,
        choices=EstadoOutbox.choices,
        default=EstadoOutbox.PENDIENTE,
        db_index=True,
    )
    intentos = models.PositiveSmallIntegerField(default=0)
    max_intentos = models.PositiveSmallIntegerField(default=5)
    ultimo_error = models.TextField(blank=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_procesado = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['estado', 'fecha_creacion'], name='idx_outbox_estado_fecha'),
        ]

    def __str__(self):
        return f"[{self.estado}] {self.tipo_evento} ({self.id})"


class RegistroEntrega(models.Model):
    mensaje = models.ForeignKey(MensajeOutbox, on_delete=models.CASCADE, related_name='entregas')
    canal = models.CharField(max_length=30)
    destinatario = models.CharField(max_length=255)
    fecha_entrega = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['mensaje', 'canal', 'destinatario'],
                name='uq_entrega_unica_mensaje_canal_dest',
            )
        ]


class PreferenciaNotificacion(models.Model):
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='preferencia_notificacion')
    recibir_email = models.BooleanField(default=True)
    recibir_push = models.BooleanField(default=True)
    recibir_mensajeria = models.BooleanField(default=False)

    def __str__(self):
        return f"Preferencias de {self.usuario.username}"