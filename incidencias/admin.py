from django.contrib import admin
from .models import (
    Organizacion, Edificio, Unidad, Perfil, 
    Tecnico, Incidencia, Comentario, EventoIncidencia
)

@admin.register(Organizacion)
class OrganizacionAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'fecha_creacion')

@admin.register(Edificio)
class EdificioAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'organizacion')

@admin.register(Unidad)
class UnidadAdmin(admin.ModelAdmin):
    list_display = ('id', 'numero', 'edificio')

@admin.register(Incidencia)
class IncidenciaAdmin(admin.ModelAdmin):
    list_display = ('id', 'titulo', 'estado', 'unidad', 'reportado_por', 'fecha_creacion')
    list_filter = ('estado', 'unidad__edificio')

@admin.register(EventoIncidencia)
class EventoIncidenciaAdmin(admin.ModelAdmin):
    list_display = ('id', 'incidencia', 'tipo_evento', 'usuario_actor', 'fecha_evento')
    readonly_fields = ('incidencia', 'tipo_evento', 'datos_previos', 'datos_nuevos', 'usuario_actor', 'fecha_evento')

admin.site.register(Perfil)
admin.site.register(Tecnico)
admin.site.register(Comentario)