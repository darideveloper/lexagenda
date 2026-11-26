import tempfile
from datetime import date

from django.test import TestCase, override_settings

from apps.assistant import envelope, tools
from apps.assistant.models import Proposal, Thread
from apps.core.models import Case, Client
from apps.docs import filing, ingest, storage
from apps.docs.models import Document


class FilingTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        override = override_settings(MEDIA_ROOT=self.tmp.name)
        override.enable()
        self.addCleanup(override.disable)

        self.client_obj = Client.objects.create(
            name="Ana García", phone="+525512345678", jid="5215512345678@s.whatsapp.net"
        )
        self.case = Case.objects.create(
            client=self.client_obj,
            reference="EXP-001",
            title="Laboral",
            opened_on=date(2026, 11, 2),
        )
        self.media = ingest.ingest("wamid-1", b"hola mundo", "text/plain", "nota.txt")

    def test_filing_copies_the_blob_under_the_case(self):
        document = filing.file_document(self.case, self.media)

        expected = storage.document_relpath(self.case.pk, document.sha256, "txt")
        self.assertEqual(document.case, self.case)
        self.assertEqual(document.client, self.client_obj)
        self.assertEqual(document.media, self.media)
        self.assertEqual(document.source, Document.WHATSAPP)
        self.assertEqual(document.filename, "nota.txt")
        self.assertEqual(document.size, len(b"hola mundo"))
        self.assertTrue(storage.abs_path(expected).is_file())

    def test_filing_twice_shares_one_blob(self):
        first = filing.file_document(self.case, self.media)
        second = filing.file_document(self.case, self.media)

        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(len(list(storage.MEDIA_ROOT().rglob("*.txt"))), 2)  # inbound + documents
        documents = list((storage.MEDIA_ROOT() / "media/documents").rglob(f"{first.sha256}.txt"))
        self.assertEqual(len(documents), 1)

    def test_filing_the_last_inbound_file_through_the_tool(self):
        thread = Thread.objects.create(channel="control", jid="5215512345678@s.whatsapp.net")
        out = tools.TOOLS["file_document"]["fn"](thread, case_id=self.case.pk)
        proposal = Proposal.objects.get(pk=out["proposal_id"])

        self.assertEqual(proposal.steps[0]["tool"], "file_document")
        self.assertIn("EXP-001", out["summary"])
        self.assertEqual(Document.objects.count(), 0)

        result = envelope.confirm(thread, proposal.pk)

        self.assertTrue(result["ok"])
        document = Document.objects.get()
        self.assertEqual(document.case, self.case)
        self.assertEqual(document.media, self.media)

    def test_filing_indexes_the_text_and_flags_a_scanned_pdf(self):
        from apps.docs.tests.test_extraction import make_pdf

        text_media = ingest.ingest(
            "wamid-pdf", make_pdf("Clausula suelo"), "application/pdf", "demanda.pdf"
        )
        document = filing.file_document(self.case, text_media)
        scanned_media = ingest.ingest(
            "wamid-scan", make_pdf(), "application/pdf", "escaneo.pdf"
        )
        scanned = filing.file_document(self.case, scanned_media)

        self.assertIn("Clausula suelo", document.extracted_text)
        self.assertFalse(document.no_text_layer)
        self.assertEqual(scanned.extracted_text, "")
        self.assertTrue(scanned.no_text_layer)

    def test_a_purged_or_missing_file_stays_a_refusal(self):
        thread = Thread.objects.create(channel="control", jid="5215512345678@s.whatsapp.net")
        out = tools.TOOLS["file_document"]["fn"](
            thread, case_id=self.case.pk, media_id=self.media.pk
        )
        storage.delete(self.media.path)

        result = envelope.confirm(thread, out["proposal_id"])

        self.assertFalse(result["ok"])
        self.assertIn("ya no está", result["text"])
        self.assertEqual(Document.objects.count(), 0)
