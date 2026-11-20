from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'^ws/incidencias/$', consumers.IncidenciaConsumer.as_asgi()),
    re_path(r'^ws/incidencias/(?P<incidencia_id>\d+)/$', consumers.IncidenciaConsumer.as_asgi()),
]