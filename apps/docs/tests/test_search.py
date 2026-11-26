from datetime import date

from django.test import TestCase

from apps.assistant import tools
from apps.assistant.models import Thread
from apps.core.models import Case, Client
from apps.docs import search
from apps.docs.models import Document


def make_case(reference, title="Laboral"):
    client_obj = Client.objects.create(
        name=f"Cliente {reference}", phone=f"+5255{reference}", jid=f"{reference}@s.whatsapp.net"
    )
    return Case.objects.create(
        client=client_obj,
        reference=reference,
        title=title,
        opened_on=date(2026, 11, 2),
    )


def make_document(case, text, filename="escrito.txt", no_text_layer=False):
    return Document.objects.create(
        case=case,
        client=case.client,
        filename=filename,
        mime="text/plain",
        size=max(len(text.encode()), 1),
        sha256="0" * 64,
        extracted_text=text,
        no_text_layer=no_text_layer,
    )


class SearchTests(TestCase):
    def setUp(self):
        self.case = make_case("EXP-001")
        self.document = make_document(
            self.case,
            "La cláusula suelo es abusiva y por eso el juez la anula en la sentencia.",
            "demanda.txt",
        )

    def test_a_phrase_returns_its_snippet_and_case(self):
        rows = search.search("clausula suelo")

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["id"], self.document.pk)
        self.assertEqual(row["filename"], "demanda.txt")
        self.assertEqual(row["case_reference"], "EXP-001")
        self.assertIn("«", row["snippet"])
        self.assertIn("«cláusula»", row["snippet"])
        self.assertIn("«suelo»", row["snippet"])

    def test_accents_come_and_go(self):
        rows = search.search("clausula")

        self.assertEqual([row["id"] for row in rows], [self.document.pk])

    def test_a_case_id_narrows_the_search(self):
        other = make_case("EXP-002")
        make_document(other, "La cláusula suelo también aparece aquí.")

        rows = search.search("clausula", case_id=other.pk)

        self.assertEqual([row["case_reference"] for row in rows], ["EXP-002"])

    def test_a_trigram_match_on_the_case_title_boosts_the_hit(self):
        plain = make_case("EXP-010", title="Otro asunto")
        titled = make_case("EXP-011", title="Escrito")
        make_document(plain, "escrito presentado")
        boosted = make_document(titled, "escrito presentado")

        rows = search.search("escrito")

        self.assertEqual(rows[0]["id"], boosted.pk)
        self.assertEqual(rows[0]["case_reference"], "EXP-011")

    def test_a_soft_deleted_document_is_hidden(self):
        self.document.is_active = False
        self.document.save(update_fields=["is_active"])

        self.assertEqual(search.search("clausula"), [])

    def test_an_empty_query_returns_nothing(self):
        self.assertEqual(search.search("   "), [])

    def test_the_whatsapp_tool_reads_the_same_snippet(self):
        thread = Thread.objects.create(jid="5215512345678@s.whatsapp.net")

        result = tools.TOOLS["document_search"]["fn"](thread, query="clausula suelo")

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["document_id"], self.document.pk)
        self.assertEqual(result["results"][0]["case"], "EXP-001 — Laboral")
        self.assertIn("cláusula", result["results"][0]["snippet"].lower())
