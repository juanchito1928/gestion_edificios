from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connection
from .models import Organizacion, Edificio, Unidad, EventoIncidencia
from .tenant import set_edificio_actual
from . import use_cases


class DominioIncidenciasTestCase(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username='residente1', password='password123')
        self.org = Organizacion.objects.create(nombre="Organización Test")
        self.edificio = Edificio.objects.create(organizacion=self.org, nombre="Edificio 1")
        self.unidad = Unidad.objects.create(edificio=self.edificio, numero="101")

        # Fijar contexto del edificio activo para PorEdificioManager y PostgreSQL RLS
        set_edificio_actual(self.edificio.id)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.current_edificio_id', %s, false);",
                [str(self.edificio.id)],
            )

    def tearDown(self):
        set_edificio_actual(None)
        with connection.cursor() as cursor:
            cursor.execute("RESET app.current_edificio_id;")

    def test_crear_incidencia_genera_evento_inmutable(self):
        incidencia = use_cases.crear_incidencia(
            usuario=self.usuario,
            titulo="Fuga de agua",
            descripcion="Hay una fuga en el baño",
            unidad_id=self.unidad.id
        )
        self.assertEqual(incidencia.estado, 'PENDIENTE')
        self.assertEqual(EventoIncidencia.objects.filter(incidencia=incidencia).count(), 1)

    def test_transicion_valida_estado(self):
        incidencia = use_cases.crear_incidencia(self.usuario, "Prueba", "Desc", self.unidad.id)
        incidencia_actualizada = use_cases.cambiar_estado(incidencia.id, 'EN_PROCESO', self.usuario)
        self.assertEqual(incidencia_actualizada.estado, 'EN_PROCESO')

    def test_transicion_invalida_rechazada(self):
        """Verifica que saltar de PENDIENTE a RESUELTA sin pasar por EN_PROCESO lance ValidationError"""
        incidencia = use_cases.crear_incidencia(self.usuario, "Prueba", "Desc", self.unidad.id)
        with self.assertRaises(ValidationError):
            use_cases.cambiar_estado(incidencia.id, 'RESUELTA', self.usuario)