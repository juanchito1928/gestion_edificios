from django.contrib import admin
from .models import MensajeOutbox, PreferenciaNotificacion, RegistroEntrega


@admin.register(MensajeOutbox)
class MensajeOutboxAdmin(admin.ModelAdmin):
    list_display = ('tipo_evento', 'estado', 'intentos', 'edificio', 'fecha_creacion', 'fecha_procesado')
    list_filter = ('estado', 'tipo_evento')
    search_fields = ('clave_idempotencia', 'tipo_evento')
    readonly_fields = ('id', 'fecha_creacion', 'fecha_procesado')


@admin.register(RegistroEntrega)
class RegistroEntregaAdmin(admin.ModelAdmin):
    list_display = ('mensaje', 'canal', 'destinatario', 'fecha_entrega')
    list_filter = ('canal',)


@admin.register(PreferenciaNotificacion)
class PreferenciaNotificacionAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'recibir_email', 'recibir_push', 'recibir_mensajeria')