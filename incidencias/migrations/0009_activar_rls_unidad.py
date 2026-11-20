from django.db import migrations


SQL_UP = """
ALTER TABLE incidencias_unidad ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS unidad_aislamiento_edificio ON incidencias_unidad;

CREATE POLICY unidad_aislamiento_edificio ON incidencias_unidad
    USING (
        NULLIF(current_setting('app.current_edificio_id', true), '') IS NOT NULL
        AND edificio_id = NULLIF(current_setting('app.current_edificio_id', true), '')::bigint
    )
    WITH CHECK (
        NULLIF(current_setting('app.current_edificio_id', true), '') IS NOT NULL
        AND edificio_id = NULLIF(current_setting('app.current_edificio_id', true), '')::bigint
    );
"""

SQL_DOWN = """
DROP POLICY IF EXISTS unidad_aislamiento_edificio ON incidencias_unidad;
ALTER TABLE incidencias_unidad DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('incidencias', '0008_indice_gin_trigramas'),
    ]

    operations = [
        migrations.RunSQL(sql=SQL_UP, reverse_sql=SQL_DOWN),
    ]