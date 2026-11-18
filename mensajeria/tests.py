from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth.models import User
from django.core import mail
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from api.models import SuscripcionWebhook
from incidencias.models import Edificio, Incidencia, Organizacion, Perfil, Unidad
from incidencias.tenant import set_edificio_actual
from incidencias.use_cases import cambiar_estado, crear_incidencia
from .models import EstadoOutbox, MensajeOutbox, RegistroEntrega
from .tasks import escalar_incidencias_sla, procesar_mensaje_outbox, rescatar_mensajes_outbox_pendientes


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
class MensajeriaOutboxCaosTests(TransactionTestCase):
    def setUp(self):
        self.org = Organizacion.objects.create(nombre="Conjunto Residencial Sur")
        self.edificio = Edificio.objects.create(organizacion=self.org, nombre="Torre B")
        self.unidad = Unidad.objects.create(edificio=self.edificio, numero="Apto 202")
        self.user = User.objects.create_user(
            username="residente_m5",
            email="residente@vecinosapp.local",
            password="Password123!",
        )
        Perfil.objects.create(usuario=self.user, edificio=self.edificio, rol="RESIDENTE")

        # Activar contexto RLS tanto en Python como en la sesión de PostgreSQL
        set_edificio_actual(self.edificio.id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_edificio_id', %s, false);", [str(self.edificio.id)])

    @patch("mensajeria.tasks.despachar_webhook")
    def test_flujo_completo_outbox_correo_y_webhook_al_resolver(self, mock_webhook):
        """Al crear y resolver incidencia, Outbox envía correo y webhook HMAC una sola vez."""
        SuscripcionWebhook.objects.create(
            edificio=self.edificio,
            evento="incidencia.resuelta",
            url_destino="https://webhook.ejemplo.com/m5",
            secreto_hmac="secreto_m5",
        )

        inc = crear_incidencia(self.user, "Ascensor detenido", "Piso 4", self.unidad.id)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("incidencia.creada", mail.outbox[0].subject)

        cambiar_estado(inc.id, "EN_PROCESO", self.user)
        cambiar_estado(inc.id, "RESUELTA", self.user)

        self.assertEqual(len(mail.outbox), 3)
        self.assertTrue(mock_webhook.called)
        self.assertEqual(MensajeOutbox.objects.filter(estado=EstadoOutbox.ENVIADO).count(), 3)

    @patch("mensajeria.tasks.despachar_webhook")
    def test_caos_caida_worker_a_mitad_de_envio_no_pierde_ni_duplica(self, mock_webhook):
        """
        RETO AVANZADO (Prueba de caos):
        Simula que el worker muere justo después de enviar el correo y antes de
        despachar el webhook o marcar el Outbox como ENVIADO.
        Al reiniciar/rescatar, el webhook se envía y el correo NO se duplica.
        """
        with patch("mensajeria.outbox._encolar_seguro"):
            inc = crear_incidencia(self.user, "Tubería rota", "Sótano 1", self.unidad.id)

        mensaje = MensajeOutbox.objects.get(clave_idempotencia=f"inc-creada-{inc.id}")
        self.assertEqual(mensaje.estado, EstadoOutbox.PENDIENTE)
        self.assertEqual(len(mail.outbox), 0)

        mock_webhook.side_effect = RuntimeError("CAOS: Worker terminado abruptamente")
        with self.assertRaises(RuntimeError):
            procesar_mensaje_outbox.run(str(mensaje.id))

        mensaje.refresh_from_db()
        self.assertEqual(mensaje.estado, EstadoOutbox.PENDIENTE)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(RegistroEntrega.objects.filter(mensaje=mensaje, canal='email').count(), 1)

        mock_webhook.side_effect = None
        rescatar_mensajes_outbox_pendientes()

        # 4. Aserciones finales: el mensaje terminó ENVIADO, el correo sigue en 1 (sin duplicar) y el webhook se entregó 1 vez
        mensaje.refresh_from_db()
        self.assertEqual(mensaje.estado, EstadoOutbox.ENVIADO)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(RegistroEntrega.objects.filter(mensaje=mensaje, canal='email').count(), 1)
        self.assertEqual(RegistroEntrega.objects.filter(mensaje=mensaje, canal='webhook').count(), 1)
        self.assertEqual(RegistroEntrega.objects.filter(mensaje=mensaje).count(), 2)

    @patch("mensajeria.tasks.despachar_webhook")
    def test_tarea_programada_escalamiento_sla(self, mock_webhook):
        """Incidencias en PENDIENTE > 24h generan alerta automática de escalamiento SLA."""
        with patch("mensajeria.outbox._encolar_seguro"):
            inc = crear_incidencia(self.user, "Gotera techo", "Apto 202", self.unidad.id)

        hace_26h = timezone.now() - timedelta(hours=26)
        Incidencia.sin_filtro.filter(id=inc.id).update(fecha_creacion=hace_26h)

        escalar_incidencias_sla()

        alerta = MensajeOutbox.objects.filter(tipo_evento='sla.incidencia_vencida').first()
        self.assertIsNotNone(alerta)
        self.assertEqual(alerta.estado, EstadoOutbox.ENVIADO)