import json
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from .models import Incidencia, Perfil


class IncidenciaConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return

        self.incidencia_id = self.scope['url_route']['kwargs'].get('incidencia_id')
        edificio_id = await self._verificar_autorizacion(user, self.incidencia_id)

        if not edificio_id:
            await self.close(code=4003)
            return

        self.edificio_id = edificio_id
        self.grupo_edificio = f"edificio_{self.edificio_id}"
        await self.channel_layer.group_add(self.grupo_edificio, self.channel_name)

        if self.incidencia_id:
            self.grupo_incidencia = f"incidencia_{self.incidencia_id}"
            await self.channel_layer.group_add(self.grupo_incidencia, self.channel_name)
        else:
            self.grupo_incidencia = None

        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'grupo_edificio') and self.grupo_edificio:
            await self.channel_layer.group_discard(self.grupo_edificio, self.channel_name)
        if hasattr(self, 'grupo_incidencia') and self.grupo_incidencia:
            await self.channel_layer.group_discard(self.grupo_incidencia, self.channel_name)

    async def incidencia_actualizada(self, event):
        """Reenvía el cambio de estado o asignación al navegador del cliente en tiempo real."""
        await self.send(text_data=json.dumps(event['data']))

    @database_sync_to_async
    def _verificar_autorizacion(self, user, incidencia_id=None):
        perfil = Perfil.objects.filter(usuario=user).first()
        if not perfil or not perfil.edificio_id:
            return None

        if incidencia_id:
            pertenece = Incidencia.sin_filtro.filter(
                id=incidencia_id,
                edificio_id=perfil.edificio_id,
            ).exists()
            if not pertenece:
                return None

        return perfil.edificio_id