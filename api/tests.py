import hashlib
import hmac
from unittest.mock import MagicMock, patch
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient
from incidencias.models import Edificio, Incidencia, Organizacion, Perfil, Unidad
from .models import SuscripcionWebhook


class ProduccionAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organizacion.objects.create(nombre="Conjunto Residencial Norte")
        self.edificio = Edificio.objects.create(organizacion=self.org, nombre="Torre A")
        self.unidad = Unidad.objects.create(edificio=self.edificio, numero="Apto 101")

        self.user = User.objects.create_user(username="residente_api", password="Password123!")
        Perfil.objects.create(usuario=self.user, edificio=self.edificio, rol="RESIDENTE")

        # Obtener JWT
        resp = self.client.post(
            "/api/v1/token/",
            {"username": "residente_api", "password": "Password123!"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.token = resp.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def test_idempotencia_post_no_duplica_incidencia(self):
        """Reintentar POST con la misma Idempotency-Key devuelve 201 sin duplicar registro."""
        payload = {
            "titulo": "Fuga en lavadero",
            "descripcion": "Goteo constante en tubería",
            "unidad_id": self.unidad.id,
        }
        headers = {"HTTP_IDEMPOTENCY_KEY": "clave-unica-001"}

        resp1 = self.client.post("/api/v1/incidencias/", payload, format="json", **headers)
        resp2 = self.client.post("/api/v1/incidencias/", payload, format="json", **headers)

        self.assertEqual(resp1.status_code, 201)
        self.assertEqual(resp2.status_code, 201)
        self.assertEqual(resp1.data["id"], resp2.data["id"])

        # Verificar vía API (con contexto RLS activo) que solo existe 1 incidencia
        resp_lista = self.client.get("/api/v1/incidencias/")
        titulos = [item["titulo"] for item in resp_lista.data["results"]]
        self.assertEqual(titulos.count("Fuga en lavadero"), 1)

    def test_etag_y_peticion_condicional_304(self):
        """GET detalle entrega ETag y responde 304 Not Modified si If-None-Match coincide."""
        resp_post = self.client.post(
            "/api/v1/incidencias/",
            {"titulo": "Luz pasillo", "descripcion": "Bombillo fundido", "unidad_id": self.unidad.id},
            format="json",
        )
        inc_id = resp_post.data["id"]

        resp_get = self.client.get(f"/api/v1/incidencias/{inc_id}/")
        self.assertEqual(resp_get.status_code, 200)
        etag = resp_get.headers.get("ETag")
        self.assertIsNotNone(etag)

        resp_304 = self.client.get(f"/api/v1/incidencias/{inc_id}/", HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(resp_304.status_code, 304)

    @patch("api.webhooks.urllib.request.urlopen")
    def test_webhook_incidencia_resuelta_firmado_hmac(self, mock_urlopen):
        """Al pasar a RESUELTA dispara webhook con firma HMAC-SHA256 válida."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        secreto = "mi_secreto_super_seguro"
        SuscripcionWebhook.objects.create(
            edificio=self.edificio,
            evento="incidencia.resuelta",
            url_destino="https://webhook.ejemplo.com/receptor",
            secreto_hmac=secreto,
        )

        resp_post = self.client.post(
            "/api/v1/incidencias/",
            {"titulo": "Puerta garaje", "descripcion": "No abre", "unidad_id": self.unidad.id},
            format="json",
        )
        inc_id = resp_post.data["id"]

        self.client.post(f"/api/v1/incidencias/{inc_id}/cambiar-estado/", {"nuevo_estado": "EN_PROCESO"}, format="json")
        resp_res = self.client.post(f"/api/v1/incidencias/{inc_id}/cambiar-estado/", {"nuevo_estado": "RESUELTA"}, format="json")
        self.assertEqual(resp_res.status_code, 200)
        self.assertTrue(mock_urlopen.called)

        req_enviada = mock_urlopen.call_args[0][0]
        ts = req_enviada.headers["X-webhook-timestamp"]
        firma_recibida = req_enviada.headers["X-webhook-signature"]
        cuerpo = req_enviada.data.decode("utf-8")
        firma_esperada = "sha256=" + hmac.new(secreto.encode(), f"{ts}.{cuerpo}".encode(), hashlib.sha256).hexdigest()
        self.assertEqual(firma_recibida, firma_esperada)

    def test_subida_prefirmada_y_verificacion_magic_bytes(self):
        """Acepta PNG real por URL prefirmada y rechaza un .exe disfrazado de PNG."""
        resp_post = self.client.post(
            "/api/v1/incidencias/",
            {"titulo": "Humedad muro", "descripcion": "Mancha en pared", "unidad_id": self.unidad.id},
            format="json",
        )
        inc_id = resp_post.data["id"]

        resp_url = self.client.post(
            f"/api/v1/incidencias/{inc_id}/adjuntos/solicitar-subida/",
            {"nombre_archivo": "evidencia.png", "tipo_mime_declarado": "image/png"},
            format="json",
        )
        self.assertEqual(resp_url.status_code, 201)
        upload_url = resp_url.data["upload_url"]

        # 1. Intentar subir archivo falso (sin magic bytes PNG) -> debe dar 422
        archivo_falso = SimpleUploadedFile("evidencia.png", b"MZ_ESTO_NO_ES_UN_PNG", content_type="image/png")
        resp_falso = self.client.put(upload_url, {"file": archivo_falso}, format="multipart")
        self.assertEqual(resp_falso.status_code, 422)

        # 2. Subir cabecera PNG real -> debe dar 200 y verificado=True
        png_valido = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        archivo_real = SimpleUploadedFile("evidencia.png", png_valido, content_type="image/png")
        resp_real = self.client.put(upload_url, {"file": archivo_real}, format="multipart")
        self.assertEqual(resp_real.status_code, 200)
        self.assertTrue(resp_real.data["verificado"])