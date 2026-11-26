from datetime import date

from django.db import connection
from django.test import TestCase

from apps.core.models import Case, Client
from apps.docs.models import Document


def make_case(reference="EXP-001", title="Laboral"):
    client_obj = Client.objects.create(
        name="Ana García", phone=f"+52551234{Client.objects.count():04d}", jid=f"521{Client.objects.count()}@s.whatsapp.net"
    )
    return Case.objects.create(
        client=client_obj,
        reference=reference,
        title=title,
        opened_on=date(2026, 11, 2),
    )


def make_document(case, text, filename="escrito.txt"):
    return Document.objects.create(
        case=case,
        client=case.client,
        filename=filename,
        mime="text/plain",
        size=len(text.encode()),
        sha256="0" * 64,
        extracted_text=text,
    )


class SearchIndexTests(TestCase):
    """The trigger keeps `search_vector` in Spanish; the GIN indexes make it a search."""

    def search_vector_matches(self, document, query):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT search_vector @@ websearch_to_tsquery('spanish', %s) "
                "FROM docs_document WHERE id = %s",
                [query, document.pk],
            )
            return cursor.fetchone()[0]

    def test_pg_trgm_and_the_indexes_exist(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
            self.assertIsNotNone(cursor.fetchone())

            cursor.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename IN "
                "('docs_document', 'core_case', 'core_client')"
            )
            names = {row[0] for row in cursor.fetchall()}

        self.assertIn("docs_document_search_vector_gin", names)
        self.assertIn("core_case_title_trgm", names)
        self.assertIn("core_client_name_trgm", names)

    def test_the_trigger_fills_the_spanish_vector_on_insert(self):
        document = make_document(make_case(), "La cláusula suelo es abusiva")

        self.assertTrue(self.search_vector_matches(document, "clausula"))
        self.assertTrue(self.search_vector_matches(document, "cláusulas"))

    def test_the_trigger_rewrites_the_vector_on_update(self):
        document = make_document(make_case(), "Contrato de arrendamiento")

        document.extracted_text = "Despido injustificado"
        document.save(update_fields=["extracted_text"])

        self.assertFalse(self.search_vector_matches(document, "arrendamiento"))
        self.assertTrue(self.search_vector_matches(document, "despido"))

    def test_the_gin_index_carries_the_query(self):
        make_document(make_case(), "La cláusula suelo es abusiva")

        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL enable_seqscan = off")
            cursor.execute(
                "EXPLAIN SELECT id FROM docs_document "
                "WHERE search_vector @@ websearch_to_tsquery('spanish', 'clausula')"
            )
            plan = "\n".join(row[0] for row in cursor.fetchall())

        self.assertIn("docs_document_search_vector_gin", plan)
