import tempfile
from datetime import date, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.models import Case, Client
from apps.docs import filing, ingest, purge, storage
from apps.docs.models import Document, InboundMedia


class PurgeTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        override = override_settings(MEDIA_ROOT=self.tmp.name)
        override.enable()
        self.addCleanup(override.disable)

        client_obj = Client.objects.create(
            name="Ana García", phone="+525512345678", jid="5215512345678@s.whatsapp.net"
        )
        self.case = Case.objects.create(
            client=client_obj,
            reference="EXP-001",
            title="Laboral",
            opened_on=date(2026, 11, 2),
        )

    def inbound(self, wamid="wamid-1", data=b"hola", days_ago=91):
        media = ingest.ingest(wamid, data, "text/plain", "nota.txt")
        InboundMedia.objects.filter(pk=media.pk).update(
            created_at=timezone.now() - timedelta(days=days_ago)
        )
        media.refresh_from_db()
        return media

    def test_unfiled_media_older_than_90_days_is_purged(self):
        media = self.inbound()
        blob = storage.abs_path(media.path)

        purged = purge.purge_inbound()

        media.refresh_from_db()
        self.assertEqual(purged, 1)
        self.assertIsNotNone(media.purged_at)
        self.assertFalse(blob.exists())

    def test_fresh_media_is_left_alone(self):
        media = self.inbound(days_ago=10)

        self.assertEqual(purge.purge_inbound(), 0)
        media.refresh_from_db()
        self.assertIsNone(media.purged_at)
        self.assertTrue(storage.abs_path(media.path).exists())

    def test_filed_media_survives_the_sweep(self):
        media = self.inbound()
        document = filing.file_document(self.case, media)

        self.assertEqual(purge.purge_inbound(), 0)

        media.refresh_from_db()
        document.refresh_from_db()
        self.assertIsNone(media.purged_at)
        self.assertTrue(document.is_active)
        self.assertTrue(storage.abs_path(media.path).exists())

    def test_a_shared_blob_survives_until_the_last_document_goes(self):
        media = self.inbound()
        first = filing.file_document(self.case, media)
        second = filing.file_document(self.case, media)
        blob = storage.abs_path(
            storage.document_relpath(self.case.pk, first.sha256, "txt")
        )

        purge.release_document(first)

        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertTrue(blob.exists())

        purge.release_document(second)

        second.refresh_from_db()
        self.assertFalse(second.is_active)
        self.assertFalse(blob.exists())

    def test_the_sweep_command_runs_the_purge(self):
        media = self.inbound()
        out = StringIO()

        call_command("sweep", stdout=out)

        media.refresh_from_db()
        self.assertIsNotNone(media.purged_at)
        self.assertIn("1 archivo(s)", out.getvalue())
