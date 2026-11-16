import random
import statistics
import time
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db import connection
from django.db.models import Q
from django.contrib.postgres.search import TrigramSimilarity
from incidencias.models import Organizacion, Edificio, Unidad, Incidencia
from incidencias.tenant import set_edificio_actual


class Command(BaseCommand):
    help = "Carga 100 000 incidencias, refresca la vista materializada y mide p95 + EXPLAIN ANALYZE."

    def add_arguments(self, parser):
        parser.add_argument('--cantidad', type=int, default=100000, help='Total de incidencias objetivo')
        parser.add_argument('--solo-medir', action='store_true', help='Omite la carga y solo ejecuta mediciones')

    def _fijar_rls_edificio(self, edificio_id):
        """Fija app.current_edificio_id en PostgreSQL y el ContextVar de tenant.py."""
        set_edificio_actual(edificio_id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.current_edificio_id', %s, false);", [str(edificio_id)])

    def handle(self, *args, **options):
        objetivo = options['cantidad']
        solo_medir = options['solo_medir']

        org, _ = Organizacion.objects.get_or_create(nombre="Organización Principal")
        edificio_a, _ = Edificio.objects.get_or_create(nombre="Torre A", defaults={'organizacion': org})
        edificio_b, _ = Edificio.objects.get_or_create(nombre="Torre B", defaults={'organizacion': org})

        unidad_a, _ = Unidad.objects.get_or_create(edificio=edificio_a, numero="Apto 302")
        unidad_b, _ = Unidad.objects.get_or_create(edificio=edificio_b, numero="Apto 101")
        usuario, _ = User.objects.get_or_create(username="bench_user")

        # Contar existentes en ambos edificios respetando RLS
        self._fijar_rls_edificio(edificio_a.id)
        existentes_a = Incidencia.objects.count()
        self._fijar_rls_edificio(edificio_b.id)
        existentes_b = Incidencia.objects.count()
        existentes = existentes_a + existentes_b

        if not solo_medir and existentes < objetivo:
            faltantes = objetivo - existentes
            mitad = faltantes // 2
            self.stdout.write(f"Insertando {faltantes} incidencias en lotes de 5 000 (respetando RLS)...")

            titulos = [
                "Fuga de agua en tubería principal",
                "Ascensor detenido en piso 4",
                "Falla eléctrica en pasillo común",
                "Portón vehicular no responde",
                "Humedad en techo de parqueadero",
                "Intercomunicador sin audio",
            ]
            estados = ['PENDIENTE', 'EN_PROCESO', 'RESUELTA', 'CERRADA']
            prioridades = ['ALTA', 'MEDIA', 'BAJA']
            categorias = ['PLOMERIA', 'ELECTRICA', 'ASCENSORES', 'LOCATIVA']

            t0 = time.perf_counter()

            pares = [
                (edificio_a, unidad_a, mitad),
                (edificio_b, unidad_b, faltantes - mitad),
            ]
            contador_global = existentes
            for edif, uni, cantidad_edif in pares:
                self._fijar_rls_edificio(edif.id)
                lote = []
                for _ in range(cantidad_edif):
                    contador_global += 1
                    base_titulo = random.choice(titulos)
                    lote.append(Incidencia(
                        edificio=edif,
                        unidad=uni,
                        reportado_por=usuario,
                        titulo=f"{base_titulo} #{contador_global}",
                        descripcion=f"Reporte técnico automático número {contador_global} para pruebas de carga y rendimiento en PostgreSQL.",
                        estado=random.choice(estados),
                        prioridad=random.choice(prioridades),
                        categoria=random.choice(categorias),
                        version=1,
                    ))
                    if len(lote) == 5000:
                        Incidencia.objects.bulk_create(lote, ignore_conflicts=True)
                        lote.clear()
                if lote:
                    Incidencia.objects.bulk_create(lote, ignore_conflicts=True)

            self.stdout.write(self.style.SUCCESS(
                f"Carga completada en {time.perf_counter() - t0:.2f}s. Total acumulado: {contador_global} registros."
            ))

        # Refrescar vista materializada concurrentemente
        with connection.cursor() as cursor:
            t_mv = time.perf_counter()
            cursor.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_resumen_panel_edificio;")
            self.stdout.write(f"Vista materializada refrescada en {(time.perf_counter() - t_mv)*1000:.2f} ms")

        # Fijar Torre A para las mediciones de consulta
        self._fijar_rls_edificio(edificio_a.id)

        def medir_p95(nombre, fn):
            tiempos_ms = []
            for _ in range(30):
                inicio = time.perf_counter()
                fn()
                tiempos_ms.append((time.perf_counter() - inicio) * 1000)
            tiempos_ms.sort()
            p95 = tiempos_ms[int(len(tiempos_ms) * 0.95) - 1]
            p50 = statistics.median(tiempos_ms)
            self.stdout.write(f"  -> {nombre}: p50={p50:.2f} ms | p95={p95:.2f} ms")

        self.stdout.write("\n--- MEDICIÓN DE LATENCIA (p50 / p95 con 100 000 incidencias) ---")
        medir_p95(
            "1. Listado paginado por edificio (top 25)",
            lambda: list(Incidencia.objects.select_related('unidad', 'reportado_por').order_by('-fecha_creacion')[:25])
        )
        medir_p95(
            "2. Búsqueda Full-Text + Trigramas ('ascenzor')",
            lambda: list(
                Incidencia.objects
                .filter(
                    Q(titulo__trigram_word_similar='ascenzor') |
                    Q(titulo__search='ascensor')
                )
                .only('id', 'titulo', 'estado')[:25]
            )
        )

        def consultar_panel():
            with connection.cursor() as c:
                c.execute("SELECT * FROM mv_resumen_panel_edificio WHERE edificio_id = %s;", [edificio_a.id])
                return c.fetchall()

        medir_p95("3. Panel de métricas (Vista Materializada)", consultar_panel)

        # EXPLAIN (ANALYZE, BUFFERS)
        self.stdout.write("\n--- EXPLAIN (ANALYZE, BUFFERS) ---")
        with connection.cursor() as cursor:
            cursor.execute("""
                EXPLAIN (ANALYZE, BUFFERS)
                SELECT id, titulo, estado, fecha_creacion
                FROM incidencias_incidencia
                WHERE edificio_id = %s AND estado IN ('PENDIENTE', 'EN_PROCESO')
                ORDER BY fecha_creacion DESC
                LIMIT 25;
            """, [edificio_a.id])
            for fila in cursor.fetchall():
                self.stdout.write(fila[0])