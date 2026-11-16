from django.db import migrations


SQL_CREAR_MV = """
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_resumen_panel_edificio AS
SELECT
    e.id AS edificio_id,
    e.nombre AS edificio_nombre,
    COUNT(i.id) AS total_incidencias,
    COUNT(i.id) FILTER (WHERE i.estado = 'PENDIENTE') AS pendientes,
    COUNT(i.id) FILTER (WHERE i.estado = 'EN_PROCESO') AS en_proceso,
    COUNT(i.id) FILTER (WHERE i.estado = 'RESUELTA') AS resueltas,
    COUNT(i.id) FILTER (WHERE i.estado = 'CERRADA') AS cerradas,
    COALESCE(
        AVG(EXTRACT(EPOCH FROM (i.fecha_actualizacion - i.fecha_creacion)) / 3600.0)
        FILTER (WHERE i.estado IN ('RESUELTA', 'CERRADA')),
        0
    )::numeric(10, 2) AS horas_promedio_resolucion
FROM incidencias_edificio e
LEFT JOIN incidencias_incidencia i ON i.edificio_id = e.id
GROUP BY e.id, e.nombre;

CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_resumen_panel_edificio
ON mv_resumen_panel_edificio (edificio_id);
"""

SQL_ELIMINAR_MV = """
DROP MATERIALIZED VIEW IF EXISTS mv_resumen_panel_edificio;
"""


class Migration(migrations.Migration):

    dependencies = [ ('incidencias', '0006_incidencia_version_and_more'), 
    ]

    operations = [
        migrations.RunSQL(sql=SQL_CREAR_MV, reverse_sql=SQL_ELIMINAR_MV),
    ]
