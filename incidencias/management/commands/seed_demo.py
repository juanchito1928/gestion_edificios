from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from incidencias.models import Edificio, Organizacion, Perfil, Tecnico, Unidad
from incidencias.tenant import set_edificio_actual
from incidencias.use_cases import asignar_tecnico, cambiar_estado, crear_incidencia


class Command(BaseCommand):
    help = "Carga datos realistas de demostración de forma idempotente."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("=== CARGANDO DATOS DE DEMOSTRACIÓN VECINOSAPP ==="))

        org, _ = Organizacion.objects.get_or_create(nombre="Administración Horizontal Bogotá S.A.S.")

        ed_norte, _ = Edificio.objects.get_or_create(
            organizacion=org,
            nombre="Conjunto Residencial Mirador del Norte",
        )
        ed_sur, _ = Edificio.objects.get_or_create(
            organizacion=org,
            nombre="Torre Empresarial Santa Bárbara",
        )

        admin_norte, _ = User.objects.get_or_create(
            username="admin_mirador",
            defaults={"email": "admin@mirador.local", "is_staff": True},
        )
        admin_norte.set_password("Demo12345!")
        admin_norte.save()
        Perfil.objects.get_or_create(
            usuario=admin_norte,
            edificio=ed_norte,
            defaults={"rol": "ADMIN_EDIFICIO"},
        )

        residente_norte, _ = User.objects.get_or_create(
            username="residente_302",
            defaults={"email": "residente302@mirador.local"},
        )
        residente_norte.set_password("Demo12345!")
        residente_norte.save()
        Perfil.objects.get_or_create(
            usuario=residente_norte,
            edificio=ed_norte,
            defaults={"rol": "RESIDENTE"},
        )

        tec_user, _ = User.objects.get_or_create(
            username="tecnico_carlos",
            defaults={"email": "carlos.tec@mirador.local"},
        )
        tec_user.set_password("Demo12345!")
        tec_user.save()
        Perfil.objects.get_or_create(
            usuario=tec_user,
            edificio=ed_norte,
            defaults={"rol": "TECNICO"},
        )
        tecnico, _ = Tecnico.objects.get_or_create(
            usuario=tec_user,
            defaults={"especialidad": "Hidráulica y Redes"},
        )

        set_edificio_actual(ed_norte.id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_edificio_id', %s, false);", [str(ed_norte.id)])

        u_101, _ = Unidad.objects.get_or_create(edificio=ed_norte, numero="Apto 101")
        u_302, _ = Unidad.objects.get_or_create(edificio=ed_norte, numero="Apto 302")

        if not u_302.incidencias.exists():
            inc1 = crear_incidencia(
                residente_norte,
                "Filtración de agua en bajante principal",
                "Se presenta humedad constante en el muro del baño auxiliar.",
                u_302.id,
            )
            asignar_tecnico(inc1.id, tecnico.id, admin_norte, forzar=True)

            inc2 = crear_incidencia(
                residente_norte,
                "Falla en citófono de portería",
                "No se escucha el audio desde el lobby hacia el apartamento.",
                u_101.id,
            )
            asignar_tecnico(inc2.id, tecnico.id, admin_norte, forzar=True)
            cambiar_estado(inc2.id, "RESUELTA", admin_norte)

        set_edificio_actual(ed_sur.id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_edificio_id', %s, false);", [str(ed_sur.id)])

        Unidad.objects.get_or_create(edificio=ed_sur, numero="Oficina 804")

        self.stdout.write(self.style.SUCCESS("[OK] Edificios, unidades, usuarios e incidencias de demo listos."))
        self.stdout.write("    - Admin: admin_mirador / Demo12345!")
        self.stdout.write("    - Residente: residente_302 / Demo12345!")
        self.stdout.write("    - Técnico: tecnico_carlos / Demo12345!")