from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('incidencias', '0007_vista_materializada_panel'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE EXTENSION IF NOT EXISTS btree_gin;
            DROP INDEX IF EXISTS idx_incidencia_titulo_trgm;
            CREATE INDEX idx_incidencia_edif_titulo_trgm
            ON incidencias_incidencia USING GIN (edificio_id, titulo gin_trgm_ops);
            """,
            reverse_sql="DROP INDEX IF EXISTS idx_incidencia_edif_titulo_trgm;",
        ),
    ]