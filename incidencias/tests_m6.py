import json
from asgiref.sync import async_to_sync, sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from .models import Edificio, Organizacion, Perfil, Tecnico, Unidad
from .routing import websocket_urlpatterns
from .tenant import set_edificio_actual
from .use_cases import cambiar_estado, crear_incidencia


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class Modulo6TiempoRealYPanelTests(TestCase):
    def setUp(self):
        self.org = Organizacion.objects.create(nombre="Organización M6")
        self.ed1 = Edificio.objects.create(organizacion=self.org, nombre="Torre Norte")
        self.ed2 = Edificio.objects.create(organizacion=self.org, nombre="Torre Sur")
        self.unidad1 = Unidad.objects.create(edificio=self.ed1, numero="101")

        self.user1 = User.objects.create_user(username="residente_norte", password="Password123!")
        Perfil.objects.create(usuario=self.user1, edificio=self.ed1, rol="RESIDENTE")

        self.user2 = User.objects.create_user(username="residente_sur", password="Password123!")
        Perfil.objects.create(usuario=self.user2, edificio=self.ed2, rol="RESIDENTE")

        self.tec_user = User.objects.create_user(username="tecnico_m6", password="Password123!")
        Perfil.objects.create(usuario=self.tec_user, edificio=self.ed1, rol="TECNICO")
        self.tecnico = Tecnico.objects.create(usuario=self.tec_user, especialidad="Electricidad")

        set_edificio_actual(self.ed1.id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_edificio_id', %s, false);", [str(self.ed1.id)])

    def test_websocket_autenticado_aislamiento_y_tiempo_real(self):
        async def _run():
            inc = await sync_to_async(crear_incidencia)(
                self.user1, "Falla eléctrica", "Tablero principal", self.unidad1.id
            )

            app = URLRouter(websocket_urlpatterns)

            # 1. Usuario de otro edificio es rechazado (4003)
            comm_intruso = WebsocketCommunicator(app, f"/ws/incidencias/{inc.id}/")
            comm_intruso.scope["user"] = self.user2
            connected_intruso, code = await comm_intruso.connect()
            self.assertFalse(connected_intruso)
            self.assertEqual(code, 4003)

            # 2. Residente del mismo edificio se conecta y recibe el cambio en vivo sin recargar
            comm_ok = WebsocketCommunicator(app, f"/ws/incidencias/{inc.id}/")
            comm_ok.scope["user"] = self.user1
            connected_ok, _ = await comm_ok.connect()
            self.assertTrue(connected_ok)

            def _cambiar_y_ejecutar_callbacks():
                with self.captureOnCommitCallbacks(execute=True):
                    cambiar_estado(inc.id, "EN_PROCESO", self.tec_user)

            await sync_to_async(_cambiar_y_ejecutar_callbacks)()
            evento = await comm_ok.receive_json_from(timeout=2)
            self.assertEqual(evento["incidencia_id"], inc.id)
            self.assertEqual(evento["estado"], "EN_PROCESO")
            await comm_ok.disconnect()

        async_to_sync(_run)()

    def test_panel_indicadores_4_kpis_y_filtros(self):
        inc1 = crear_incidencia(self.user1, "Bomba agua", "Sin presión", self.unidad1.id)
        cambiar_estado(inc1.id, "EN_PROCESO", self.tec_user)
        cambiar_estado(inc1.id, "RESUELTA", self.tec_user)
        cambiar_estado(inc1.id, "PENDIENTE", self.user1)

        crear_incidencia(self.user1, "Luz pasillo", "Bombillo quemado", self.unidad1.id)

        # 1. Un residente normal no debe tener acceso al panel (403 Forbidden)
        self.client.force_login(self.user1)
        resp_prohibido = self.client.get(reverse("incidencias:panel_indicadores"))
        self.assertEqual(resp_prohibido.status_code, 403)

        # 2. Un rol autorizado (Técnico / Admin / Auditor) sí accede a los 4 KPIs
        self.client.force_login(self.tec_user)
        resp = self.client.get(reverse("incidencias:api_indicadores_json"), {"edificio": self.ed1.id})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertIn("mttr_horas", data)
        self.assertIn("cumplimiento_sla", data)
        self.assertEqual(data["casos_abiertos"], 2)
        self.assertEqual(data["tasa_reapertura"], 50.0)

    def test_pwa_y_sincronizacion_cola_offline(self):
        inc = crear_incidencia(self.user1, "Portón garaje", "No abre", self.unidad1.id)
        self.client.force_login(self.tec_user)

        resp_manifest = self.client.get("/manifest.json")
        self.assertEqual(resp_manifest.status_code, 200)
        resp_sw = self.client.get("/sw.js")
        self.assertEqual(resp_sw.status_code, 200)

        resp_sync = self.client.post(
            reverse("incidencias:sincronizar_offline", args=[inc.id]),
            data=json.dumps({"texto": "Revisado motor en sótano", "creado_en": "14:20:00"}),
            content_type="application/json",
        )
        self.assertEqual(resp_sync.status_code, 201)
        self.assertIn("Sincronizado offline", resp_sync.json()["texto"])