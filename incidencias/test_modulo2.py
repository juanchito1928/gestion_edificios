from django.test import TestCase
from django.contrib.auth.models import User
from django.db import connection
from .models import Organizacion, Edificio, Unidad, Perfil, Tecnico, Incidencia, RolUsuario
from .tenant import set_edificio_actual


class AislamientoMultiEdificioYRLSTests(TestCase):
    def setUp(self):
        self.org = Organizacion.objects.create(nombre="Constructora Horizonte")
        self.edificio_a = Edificio.objects.create(organizacion=self.org, nombre="Torre A")
        self.edificio_b = Edificio.objects.create(organizacion=self.org, nombre="Torre B")

        self.unidad_a = Unidad.objects.create(edificio=self.edificio_a, numero="A-101")
        self.unidad_b = Unidad.objects.create(edificio=self.edificio_b, numero="B-202")

        self.user_a = User.objects.create_user(username="residente_a", password="Password123!")
        Perfil.objects.create(usuario=self.user_a, edificio=self.edificio_a, rol=RolUsuario.RESIDENTE)

        self.user_b = User.objects.create_user(username="residente_b", password="Password123!")
        Perfil.objects.create(usuario=self.user_b, edificio=self.edificio_b, rol=RolUsuario.RESIDENTE)

        # Crear incidencia en Edificio A
        self._activar_contexto(self.edificio_a.id)
        self.inc_a = Incidencia.objects.create(
            edificio=self.edificio_a,
            unidad=self.unidad_a,
            titulo="Fuga en Torre A",
            descripcion="Tubería rota",
            reportado_por=self.user_a,
        )

        # Crear incidencia en Edificio B
        self._activar_contexto(self.edificio_b.id)
        self.inc_b = Incidencia.objects.create(
            edificio=self.edificio_b,
            unidad=self.unidad_b,
            titulo="Ascensor Torre B",
            descripcion="No sube al piso 5",
            reportado_por=self.user_b,
        )
        self._activar_contexto(None)

    def tearDown(self):
        self._activar_contexto(None)

    def _activar_contexto(self, edificio_id):
        set_edificio_actual(edificio_id)
        with connection.cursor() as cursor:
            if edificio_id is not None:
                cursor.execute("SELECT set_config('app.current_edificio_id', %s, false);", [str(edificio_id)])
            else:
                cursor.execute("RESET app.current_edificio_id;")

    def test_manager_por_edificio_aisla_consultas(self):
        self._activar_contexto(self.edificio_a.id)
        qs = Incidencia.objects.all()
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().id, self.inc_a.id)
        self.assertFalse(qs.filter(id=self.inc_b.id).exists())

    def test_rls_postgresql_bloquea_incluso_sin_filtro_de_vista(self):
        """
        Criterio clave M2: Aunque una vista olvide filtrar usando sin_filtro.all(),
        PostgreSQL RLS impide leer filas de otro edificio.
        """
        self._activar_contexto(self.edificio_a.id)
        # Usamos el manager sin_filtro (simula una vista mal programada que omite el filtro)
        filas_visibles = list(Incidencia.sin_filtro.all())
        self.assertEqual(len(filas_visibles), 1)
        self.assertEqual(filas_visibles[0].id, self.inc_a.id)


class MatrizPermisosRolesTests(TestCase):
    def setUp(self):
        self.org = Organizacion.objects.create(nombre="Grupo Residencial")
        self.edificio = Edificio.objects.create(organizacion=self.org, nombre="Edificio Central")
        self.unidad = Unidad.objects.create(edificio=self.edificio, numero="301")

        # Crear usuarios para los 4 roles
        self.residente = User.objects.create_user(username="residente", password="Password123!")
        Perfil.objects.create(usuario=self.residente, edificio=self.edificio, rol=RolUsuario.RESIDENTE)

        self.admin_ed = User.objects.create_user(username="admin_ed", password="Password123!")
        Perfil.objects.create(usuario=self.admin_ed, edificio=self.edificio, rol=RolUsuario.ADMIN_EDIFICIO)

        self.tecnico_user = User.objects.create_user(username="tecnico", password="Password123!")
        Perfil.objects.create(usuario=self.tecnico_user, edificio=self.edificio, rol=RolUsuario.TECNICO)
        self.tecnico_obj = Tecnico.objects.create(usuario=self.tecnico_user, especialidad="Plomería")
        self.tecnico_obj.edificios_asignados.add(self.edificio)

        self.auditor = User.objects.create_user(username="auditor", password="Password123!")
        Perfil.objects.create(usuario=self.auditor, edificio=self.edificio, rol=RolUsuario.AUDITOR)

        # Incidencia reportada por el residente y asignada al técnico
        set_edificio_actual(self.edificio.id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_edificio_id', %s, false);", [str(self.edificio.id)])

        self.incidencia = Incidencia.objects.create(
            edificio=self.edificio,
            unidad=self.unidad,
            titulo="Humedad techo",
            descripcion="Filtra agua cuando llueve",
            reportado_por=self.residente,
            tecnico_asignado=self.tecnico_obj,
        )

    def tearDown(self):
        set_edificio_actual(None)
        with connection.cursor() as cursor:
            cursor.execute("RESET app.current_edificio_id;")

    def test_matriz_4_roles_por_8_acciones(self):
        matriz_esperada = [
            # (usuario, permiso, objeto, esperado)
            # 1. RESIDENTE (autor)
            (self.residente, 'incidencias.ver_incidencia', self.incidencia, True),
            (self.residente, 'incidencias.crear_incidencia', None, True),
            (self.residente, 'incidencias.editar_incidencia', self.incidencia, True),
            (self.residente, 'incidencias.asignar_tecnico', self.incidencia, False),
            (self.residente, 'incidencias.cambiar_estado_tecnico', self.incidencia, False),
            (self.residente, 'incidencias.cerrar_incidencia', self.incidencia, False),
            (self.residente, 'incidencias.comentar_incidencia', self.incidencia, True),
            (self.residente, 'incidencias.ver_auditoria', self.incidencia, False),

            # 2. ADMIN_EDIFICIO
            (self.admin_ed, 'incidencias.ver_incidencia', self.incidencia, True),
            (self.admin_ed, 'incidencias.crear_incidencia', None, True),
            (self.admin_ed, 'incidencias.editar_incidencia', self.incidencia, True),
            (self.admin_ed, 'incidencias.asignar_tecnico', self.incidencia, True),
            (self.admin_ed, 'incidencias.cambiar_estado_tecnico', self.incidencia, True),
            (self.admin_ed, 'incidencias.cerrar_incidencia', self.incidencia, True),
            (self.admin_ed, 'incidencias.comentar_incidencia', self.incidencia, True),
            (self.admin_ed, 'incidencias.ver_auditoria', self.incidencia, True),

            # 3. TECNICO (asignado)
            (self.tecnico_user, 'incidencias.ver_incidencia', self.incidencia, True),
            (self.tecnico_user, 'incidencias.crear_incidencia', None, False),
            (self.tecnico_user, 'incidencias.editar_incidencia', self.incidencia, False),
            (self.tecnico_user, 'incidencias.asignar_tecnico', self.incidencia, False),
            (self.tecnico_user, 'incidencias.cambiar_estado_tecnico', self.incidencia, True),
            (self.tecnico_user, 'incidencias.cerrar_incidencia', self.incidencia, False),
            (self.tecnico_user, 'incidencias.comentar_incidencia', self.incidencia, True),
            (self.tecnico_user, 'incidencias.ver_auditoria', self.incidencia, False),

            # 4. AUDITOR (solo lectura + auditoría)
            (self.auditor, 'incidencias.ver_incidencia', self.incidencia, True),
            (self.auditor, 'incidencias.crear_incidencia', None, False),
            (self.auditor, 'incidencias.editar_incidencia', self.incidencia, False),
            (self.auditor, 'incidencias.asignar_tecnico', self.incidencia, False),
            (self.auditor, 'incidencias.cambiar_estado_tecnico', self.incidencia, False),
            (self.auditor, 'incidencias.cerrar_incidencia', self.incidencia, False),
            (self.auditor, 'incidencias.comentar_incidencia', self.incidencia, False),
            (self.auditor, 'incidencias.ver_auditoria', self.incidencia, True),
        ]

        for usuario, permiso, obj, esperado in matriz_esperada:
            with self.subTest(rol=usuario.perfil.rol, permiso=permiso):
                self.assertEqual(usuario.has_perm(permiso, obj), esperado)