from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class Modulo10OperacionYCierreTests(TestCase):
    def test_endpoints_health_y_metrics_y_seed_demo(self):
        # 1. /health/ responde 200 OK
        resp_health = self.client.get("/health/")
        self.assertEqual(resp_health.status_code, 200)
        self.assertEqual(resp_health.json().get("status"), "ok")

        # 2. /metrics/ bloquea usuarios anónimos (403) y permite staff (200)
        resp_metrics_anon = self.client.get("/metrics/")
        self.assertEqual(resp_metrics_anon.status_code, 403)

        # 3. Ejecutar seed_demo dos veces verifica idempotencia
        out = StringIO()
        call_command("seed_demo", stdout=out)
        call_command("seed_demo", stdout=out)
        self.assertIn("[OK]", out.getvalue())

        admin = User.objects.get(username="admin_mirador")
        self.client.force_login(admin)
        resp_metrics_staff = self.client.get("/metrics/")
        self.assertEqual(resp_metrics_staff.status_code, 200)
        self.assertIn("incidencias_por_estado", resp_metrics_staff.json())