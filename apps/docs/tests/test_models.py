from datetime import date

from django.test import TestCase

from apps.core.models import Case, Client
from apps.docs.models import Document, InboundMedia


class ModelTests(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(
            name="Ana García", phone="+525512345678", jid="5215512345678@s.whatsapp.net"
        )
        self.case = Case.objects.create(
            client=self.client_obj,
            reference="EXP-001",
            title="Laboral",
            opened_on=date(2026, 11, 2),
        )

    def test_inbound_media_records_the_content_address(self):
        media = InboundMedia.objects.create(
            wamid="wamid-1",
            path="media/inbound/2026/11/abc.pdf",
            mime="application/pdf",
            filename="demanda.pdf",
            size=12,
            sha256="abc",
        )

        self.assertIsNone(media.purged_at)
        self.assertEqual(str(media), "demanda.pdf")

    def test_document_hangs_off_a_case_and_starts_indexable(self):
        document = Document.objects.create(
            case=self.case,
            client=self.client_obj,
            filename="demanda.pdf",
            mime="application/pdf",
            size=12,
            sha256="abc",
            source=Document.WHATSAPP,
        )

        self.assertTrue(document.is_active)
        self.assertFalse(document.no_text_layer)
        self.assertEqual(self.case.documents.get(), document)
        self.assertEqual(document.client, self.client_obj)
