import tempfile

from django.test import TestCase, override_settings

from apps.docs import storage


class StorageTests(TestCase):
    """Storage is content-addressed: the same bytes are one blob, whatever the name."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        override = override_settings(MEDIA_ROOT=self.tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.media = storage.MEDIA_ROOT()

    def test_same_bytes_share_one_blob(self):
        first = storage.write_inbound(b"hola", "txt")
        second = storage.write_inbound(b"hola", "txt")

        self.assertEqual(first, second)
        self.assertEqual(len(list(self.media.rglob("*.txt"))), 1)
        self.assertEqual(first, f"media/inbound/{storage.today_path()}/{storage.sha256_bytes(b'hola')}.txt")

    def test_different_bytes_land_apart(self):
        one = storage.write_inbound(b"uno", "txt")
        other = storage.write_inbound(b"dos", "txt")

        self.assertNotEqual(one, other)
        self.assertEqual(len(list(self.media.rglob("*.txt"))), 2)

    def test_document_path_is_addressed_by_case_and_hash(self):
        relpath = storage.write_document(7, b"contrato", "pdf")
        sha = storage.sha256_bytes(b"contrato")

        self.assertEqual(relpath, f"media/documents/7/{sha[:2]}/{sha}.pdf")
        self.assertTrue(storage.abs_path(relpath).is_file())

    def test_extension_falls_back_to_the_mime_type(self):
        self.assertEqual(storage.ext_for("", "application/pdf"), "pdf")
        self.assertEqual(storage.ext_for("DEMANDA.PDF", ""), "pdf")
        self.assertEqual(storage.ext_for("nota", ""), "bin")

    def test_delete_removes_the_blob(self):
        relpath = storage.write_inbound(b"borrame", "txt")

        self.assertTrue(storage.delete(relpath))
        self.assertFalse(storage.abs_path(relpath).exists())
        self.assertFalse(storage.delete(relpath))

    def test_instance_bytes_and_cap(self):
        storage.write_inbound(b"x" * 100, "txt")
        storage.write_document(1, b"y" * 50, "txt")

        self.assertEqual(storage.instance_bytes(), 150)
        self.assertFalse(storage.cap_warning())
        self.assertAlmostEqual(storage.cap_ratio(), 150 / storage.SOFT_CAP)
