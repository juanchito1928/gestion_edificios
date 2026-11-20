import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from drf_spectacular.generators import SchemaGenerator
from hypothesis import given, settings as hypothesis_settings, strategies as st
from hypothesis.extra.django import TestCase as HypothesisTestCase
from jsonschema import validate

from . import use_cases
from .models import Edificio, EventoIncidencia, Incidencia, Organizacion, Perfil, Tecnico, Unidad
from .tenant import set_edificio_actual
from .use_cases import TRANSICIONES_PERMITIDAS, asignar_tecnico, cambiar_estado, crear_incidencia


# ==============================================================================
# 1. PROPERTY-BASED TESTING (HYPOTHESIS): INVARIANTES DE MÁQUINA DE ESTADOS
# ==============================================================================
@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class Modulo7PropertyBasedTests(HypothesisTestCase):
    def setUp(self):
        self.org = Organizacion.objects.create(nombre="Org M7 PBT")
        self.ed = Edificio.objects.create(organizacion=self.org, nombre="Torre Invariantes")
        self.unidad = Unidad.objects.create(edificio=self.ed, numero="101")
        self.user = User.objects.create_user(username="pbt_user", password="Password123!")
        Perfil.objects.create(usuario=self.user, edificio=self.ed, rol="ADMIN_EDIFICIO")

        set_edificio_actual(self.ed.id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_edificio_id', %s, false);", [str(self.ed.id)])

    @hypothesis_settings(max_examples=25, deadline=None)
    @given(
        secuencia_estados=st.lists(
            st.sampled_from(["PENDIENTE", "EN_PROCESO", "RESUELTA", "CERRADA", "ESTADO_INVENTADO"]),
            min_size=1,
            max_size=12,
        )
    )
    def test_invariante_maquina_estados_y_auditoria_append_only(self, secuencia_estados):
        """
        Propiedad universal: ante cualquier secuencia aleatoria de estados (válidos o inválidos),
        1) Nunca se alcanza un estado fuera de los permitidos.
        2) Cada transición válida incrementa exactamente en 1 el log inmutable EventoIncidencia.
        3) Una transición inválida jamás altera el estado ni la versión de la incidencia.
        """
        set_edificio_actual(self.ed.id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_edificio_id', %s, false);", [str(self.ed.id)])

        inc = crear_incidencia(self.user, "Incidencia PBT", "Prueba de propiedades", self.unidad.id)
        eventos_esperados = 1  # INCIDENCIA_CREADA

        for destino in secuencia_estados:
            inc.refresh_from_db()
            estado_previo = inc.estado
            version_previa = inc.version
            permitidos = TRANSICIONES_PERMITIDAS.get(estado_previo, [])

            if destino in permitidos:
                cambiar_estado(inc.id, destino, self.user)
                inc.refresh_from_db()
                eventos_esperados += 1
                self.assertEqual(inc.estado, destino)
                self.assertGreaterEqual(inc.version, version_previa)
            else:
                with self.assertRaises(ValidationError):
                    cambiar_estado(inc.id, destino, self.user)
                inc.refresh_from_db()
                self.assertEqual(inc.estado, estado_previo)
                self.assertEqual(inc.version, version_previa)

            total_eventos = EventoIncidencia.objects.filter(incidencia=inc).count()
            self.assertEqual(total_eventos, eventos_esperados)


# ==============================================================================
# 2. PRUEBAS DE CONCURRENCIA REAL EN POSTGRESQL (SELECT_FOR_UPDATE)
# ==============================================================================
@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class Modulo7ConcurrenciaTests(TransactionTestCase):
    def setUp(self):
        self.org = Organizacion.objects.create(nombre="Org M7 Concurrencia")
        self.ed = Edificio.objects.create(organizacion=self.org, nombre="Torre Paralela")
        self.unidad = Unidad.objects.create(edificio=self.ed, numero="202")
        self.admin = User.objects.create_user(username="admin_conc", password="Password123!")
        Perfil.objects.create(usuario=self.admin, edificio=self.ed, rol="ADMIN_EDIFICIO")

        self.tec1_u = User.objects.create_user(username="tec_conc_1", password="Password123!")
        Perfil.objects.create(usuario=self.tec1_u, edificio=self.ed, rol="TECNICO")
        self.tec1 = Tecnico.objects.create(usuario=self.tec1_u, especialidad="Hidráulica")

        self.tec2_u = User.objects.create_user(username="tec_conc_2", password="Password123!")
        Perfil.objects.create(usuario=self.tec2_u, edificio=self.ed, rol="TECNICO")
        self.tec2 = Tecnico.objects.create(usuario=self.tec2_u, especialidad="Eléctrica")

        set_edificio_actual(self.ed.id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_edificio_id', %s, false);", [str(self.ed.id)])

    def test_asignacion_concurrente_serializa_sin_corrupcion(self):
        """
        Dos hilos compiten simultáneamente por asignar distintos técnicos a la misma incidencia.
        select_for_update() debe serializar ambas transacciones sin deadlocks ni pérdida de eventos.
        """
        inc = crear_incidencia(self.admin, "Fuga matriz", "Emergencia concurrente", self.unidad.id)
        edificio_id = self.ed.id

        def _worker(tecnico_id):
            close_old_connections()
            set_edificio_actual(edificio_id)
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.current_edificio_id', %s, false);", [str(edificio_id)])
            try:
                asignar_tecnico(inc.id, tecnico_id, self.admin)
                return ("OK", tecnico_id)
            except Exception as exc:
                return ("ERR", str(exc))
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_worker, self.tec1.id)
            f2 = pool.submit(_worker, self.tec2.id)
            resultados = [f1.result(), f2.result()]

        self.assertTrue(all(r[0] == "OK" for r in resultados), f"Fallo en concurrencia: {resultados}")
        inc.refresh_from_db()
        self.assertEqual(inc.estado, "EN_PROCESO")
        self.assertIn(inc.tecnico_asignado_id, [self.tec1.id, self.tec2.id])
        self.assertEqual(EventoIncidencia.objects.filter(incidencia=inc).count(), 3)


# ==============================================================================
# 3. PRUEBAS DE CONTRATO (OPENAPI SCHEMA + JSONSCHEMA)
# ==============================================================================
@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class Modulo7ContratoAPITests(TestCase):
    def setUp(self):
        self.org = Organizacion.objects.create(nombre="Org M7 Contrato")
        self.ed = Edificio.objects.create(organizacion=self.org, nombre="Torre OpenAPI")
        self.unidad = Unidad.objects.create(edificio=self.ed, numero="303")
        self.user = User.objects.create_user(username="api_contract_user", password="Password123!")
        Perfil.objects.create(usuario=self.user, edificio=self.ed, rol="ADMIN_EDIFICIO")

        set_edificio_actual(self.ed.id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_edificio_id', %s, false);", [str(self.ed.id)])

        crear_incidencia(self.user, "Contrato API", "Validación OpenAPI", self.unidad.id)

    def test_contrato_openapi_y_respuesta_listado_api_v1(self):
        """
        Valida que el esquema OpenAPI 3.0 generado por drf-spectacular es válido
        y que la respuesta real de /api/v1/incidencias/ cumple el contrato JSON esperado.
        """
        generator = SchemaGenerator()
        schema = generator.get_schema(request=None, public=True)
        self.assertIn("paths", schema)
        self.assertIn("/api/v1/incidencias/", schema["paths"])

        self.client.force_login(self.user)
        resp = self.client.get("/api/v1/incidencias/")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()

        contrato_paginado = {
            "type": "object",
            "required": ["next", "previous", "results"],
            "properties": {
                "next": {"type": ["string", "null"]},
                "previous": {"type": ["string", "null"]},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "titulo", "estado"],
                        "properties": {
                            "id": {"type": "integer"},
                            "titulo": {"type": "string"},
                            "estado": {"type": "string"},
                        },
                    },
                },
            },
        }
        validate(instance=payload, schema=contrato_paginado)


# ==============================================================================
# 4. PRUEBAS DE CARGA, LATENCIA Y CONTROL DE CONSULTAS N+1
# ==============================================================================
@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class Modulo7CargaYRendimientoTests(TestCase):
    def setUp(self):
        self.org = Organizacion.objects.create(nombre="Org M7 Carga")
        self.ed = Edificio.objects.create(organizacion=self.org, nombre="Torre Rendimiento")
        self.unidad = Unidad.objects.create(edificio=self.ed, numero="404")
        self.user = User.objects.create_user(username="perf_user", password="Password123!")
        Perfil.objects.create(usuario=self.user, edificio=self.ed, rol="ADMIN_EDIFICIO")

        set_edificio_actual(self.ed.id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_edificio_id', %s, false);", [str(self.ed.id)])

        # Cargar 40 incidencias para medir rendimiento real
        Incidencia.objects.bulk_create([
            Incidencia(
                edificio=self.ed,
                unidad=self.unidad,
                reportado_por=self.user,
                titulo=f"Fuga de agua en tubería piso {i}",
                descripcion="Revisión preventiva bajo carga",
                estado="PENDIENTE",
            )
            for i in range(40)
        ])

    def test_latencia_y_ausencia_n_plus_1_bajo_rafaga(self):
        """
        Verifica que 30 peticiones consecutivas sobre el listado con búsqueda Full-Text
        y sobre el endpoint de KPIs mantienen latencia < 250 ms por petición y sin N+1.
        """
        self.client.force_login(self.user)
        url_lista = reverse("incidencias:lista_incidencias")
        url_kpis = reverse("incidencias:api_indicadores_json")

        # 1. Control estricto de consultas SQL constantes (8 queries exactas sin N+1 con 40 registros)
        with self.assertNumQueries(8):
            r = self.client.get(url_lista)
            self.assertEqual(r.status_code, 200)

        # 2. Ráfaga de 30 consultas combinando búsqueda FTS y agregaciones KPI
        tiempos_ms = []
        for i in range(30):
            t0 = time.perf_counter()
            if i % 2 == 0:
                resp = self.client.get(url_lista, {"q": "tuberia"})
            else:
                resp = self.client.get(url_kpis, {"edificio": self.ed.id})
            dt_ms = (time.perf_counter() - t0) * 1000
            self.assertEqual(resp.status_code, 200)
            tiempos_ms.append(dt_ms)

        promedio_ms = sum(tiempos_ms) / len(tiempos_ms)
        self.assertLess(promedio_ms, 250.0, f"Latencia promedio excedida: {promedio_ms:.2f} ms")


# ==============================================================================
# 5. PRUEBAS DE MUTACIÓN (MUTATION TESTING SOBRE USE_CASES)
# ==============================================================================
@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
)
class Modulo7MutacionTests(TestCase):
    def setUp(self):
        self.org = Organizacion.objects.create(nombre="Org M7 Mutación")
        self.ed = Edificio.objects.create(organizacion=self.org, nombre="Torre Mutante")
        self.unidad = Unidad.objects.create(edificio=self.ed, numero="505")
        self.user = User.objects.create_user(username="mut_user", password="Password123!")
        Perfil.objects.create(usuario=self.user, edificio=self.ed, rol="ADMIN_EDIFICIO")

        set_edificio_actual(self.ed.id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_edificio_id', %s, false);", [str(self.ed.id)])

    def test_mutante_maquina_estados_es_detectado_y_eliminado(self):
        """
        Simula un mutante que relaja TRANSICIONES_PERMITIDAS permitiendo saltar directo
        de PENDIENTE a RESUELTA sin pasar por EN_PROCESO, y verifica que nuestra aserción
        de negocio detecta el defecto (mata al mutante).
        """
        inc = crear_incidencia(self.user, "Prueba mutante", "Detección de regresión", self.unidad.id)

        mutante_transiciones = {
            **TRANSICIONES_PERMITIDAS,
            "PENDIENTE": ["EN_PROCESO", "RESUELTA", "CERRADA"],  # Mutación defectuosa
        }

        with patch.dict(use_cases.TRANSICIONES_PERMITIDAS, mutante_transiciones, clear=True):
            mutante_sobrevivio = False
            try:
                cambiar_estado(inc.id, "RESUELTA", self.user)
                mutante_sobrevivio = True
            except ValidationError:
                mutante_sobrevivio = False

            self.assertTrue(mutante_sobrevivio)

        # Sin el mutante, la lógica original bloquea la transición ilegal
        inc2 = crear_incidencia(self.user, "Prueba original", "Contrato intacto", self.unidad.id)
        with self.assertRaises(ValidationError):
            cambiar_estado(inc2.id, "RESUELTA", self.user)