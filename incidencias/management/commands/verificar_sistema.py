from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Ejecuta una auditoría rápida de infraestructura, PostgreSQL RLS, extensiones y seguridad."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("=== AUDITORÍA TÉCNICA VECINOSAPP ==="))

        # 1. PostgreSQL y extensión pg_trgm
        with connection.cursor() as cursor:
            cursor.execute("SELECT version();")
            pg_version = cursor.fetchone()[0].split(",")[0]
            self.stdout.write(self.style.SUCCESS(f"[OK] Base de datos: {pg_version}"))

            cursor.execute("SELECT extname FROM pg_extension WHERE extname = 'pg_trgm';")
            trgm = cursor.fetchone()
            if trgm:
                self.stdout.write(self.style.SUCCESS("[OK] Extensión pg_trgm activa para búsqueda difusa."))
            else:
                self.stdout.write(self.style.WARNING("[WARN] Extensión pg_trgm no detectada."))

            # 2. Verificación de Row-Level Security (RLS)
            cursor.execute("""
                SELECT relname, relrowsecurity
                FROM pg_class
                WHERE relname IN ('incidencias_incidencia', 'incidencias_comentario', 'incidencias_unidad');
            """)
            tablas_rls = cursor.fetchall()
            for tabla, rls_activo in tablas_rls:
                estado = "ACTIVO" if rls_activo else "INACTIVO"
                estilo = self.style.SUCCESS if rls_activo else self.style.ERROR
                self.stdout.write(estilo(f"[{estado}] RLS en tabla {tabla}"))

        # 3. Configuración ASGI / Channels y Seguridad
        channel_backend = settings.CHANNEL_LAYERS["default"]["BACKEND"]
        self.stdout.write(self.style.SUCCESS(f"[OK] ASGI Channel Layer: {channel_backend}"))
        self.stdout.write(
            self.style.SUCCESS(
                f"[OK] Modo DEBUG={settings.DEBUG} | Celery Eager={settings.CELERY_TASK_ALWAYS_EAGER}"
            )
        )
        self.stdout.write(self.style.MIGRATE_HEADING("=== AUDITORÍA FINALIZADA ==="))