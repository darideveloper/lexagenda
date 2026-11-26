import tempfile

from django.test import TestCase, override_settings

from apps.docs import ingest
from apps.docs.models import InboundMedia


class IngestTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        override = override_settings(MEDIA_ROOT=self.tmp.name)
        override.enable()
        self.addCleanup(override.disable)

    def test_a_document_lands_under_media_inbound(self):
        data = b"%PDF-1.4 hola"
        media = ingest.ingest("wamid-1", data, "application/pdf", "demanda.pdf")

        self.assertRegex(media.path, r"^media/inbound/\d{4}/\d{2}/[0-9a-f]{64}\.pdf$")
        self.assertEqual(media.size, len(data))
        self.assertEqual(media.sha256, ingest.storage.sha256_bytes(data))
        self.assertTrue(ingest.storage.abs_path(media.path).is_file())

    def test_the_same_message_is_ingested_once(self):
        first = ingest.ingest("wamid-1", b"hola", "text/plain", "nota.txt")
        second = ingest.ingest("wamid-1", b"hola", "text/plain", "nota.txt")

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(InboundMedia.objects.count(), 1)

    def test_a_file_over_25_mb_is_refused(self):
        with self.assertRaises(ingest.TooLarge):
            ingest.ingest("wamid-1", b"x" * (ingest.MAX_BYTES + 1), "application/pdf", "pesado.pdf")

        self.assertEqual(InboundMedia.objects.count(), 0)

    def test_exactly_25_mb_is_accepted(self):
        media = ingest.ingest("wamid-1", b"x" * ingest.MAX_BYTES, "application/pdf", "justo.pdf")

        self.assertEqual(media.size, ingest.MAX_BYTES)
