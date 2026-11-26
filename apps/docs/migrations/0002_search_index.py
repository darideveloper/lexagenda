from django.db import migrations

TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION docs_document_search_vector() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('spanish', coalesce(NEW.filename, '')), 'A') ||
        setweight(to_tsvector('spanish', coalesce(NEW.extracted_text, '')), 'B');
    RETURN NEW;
END
$$ LANGUAGE plpgsql;
"""

CREATE_TRIGGER = """
CREATE TRIGGER docs_document_search_vector
BEFORE INSERT OR UPDATE ON docs_document
FOR EACH ROW EXECUTE FUNCTION docs_document_search_vector();
"""


class Migration(migrations.Migration):
    """pg_trgm, the Spanish tsvector trigger and the GIN indexes ship together (§10)."""

    dependencies = [("docs", "0001_initial")]

    operations = [
        migrations.RunSQL(
            "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            "DROP EXTENSION IF EXISTS pg_trgm;",
        ),
        migrations.RunSQL(
            TRIGGER_FUNCTION,
            "DROP FUNCTION IF EXISTS docs_document_search_vector();",
        ),
        migrations.RunSQL(
            CREATE_TRIGGER,
            "DROP TRIGGER IF EXISTS docs_document_search_vector ON docs_document;",
        ),
        # Existing rows (none on a fresh install) get their vector without a re-save.
        migrations.RunSQL(
            "UPDATE docs_document SET updated_at = updated_at;",
            migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            "CREATE INDEX docs_document_search_vector_gin "
            "ON docs_document USING gin (search_vector);",
            "DROP INDEX IF EXISTS docs_document_search_vector_gin;",
        ),
        migrations.RunSQL(
            "CREATE INDEX core_case_title_trgm ON core_case USING gin (title gin_trgm_ops);",
            "DROP INDEX IF EXISTS core_case_title_trgm;",
        ),
        migrations.RunSQL(
            "CREATE INDEX core_client_name_trgm ON core_client USING gin (name gin_trgm_ops);",
            "DROP INDEX IF EXISTS core_client_name_trgm;",
        ),
    ]
