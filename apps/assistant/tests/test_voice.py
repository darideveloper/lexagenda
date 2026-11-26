import tempfile
from datetime import date
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.assistant import worker
from apps.assistant.models import AuditLog, Job, Message, Thread
from apps.core.models import Case, Client, Note
from apps.docs import storage
from apps.docs.models import InboundMedia
from apps.integrations import stt

TRANSCRIPT = "El cliente firmó el convenio el lunes."


class VoiceNoteTests(TestCase):
    """An inbound voice note is transcribed in the worker and lands as one case note (§6.4)."""

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
        self.thread = Thread.objects.create(jid="521771234567@s.whatsapp.net")
        storage.write("media/inbound/2026/11/abc.ogg", b"OggS-audio")
        self.media = InboundMedia.objects.create(
            wamid="w-voice",
            path="media/inbound/2026/11/abc.ogg",
            mime="audio/ogg",
            filename="nota.ogg",
            size=10,
            sha256="abc",
        )
        self.message = Message.objects.create(
            thread=self.thread, role=Message.USER, text="", wamid="w-voice"
        )
        self.job = Job.objects.create(
            payload={"message_id": self.message.pk, "media_id": self.media.pk, "kind": "audio"}
        )
        # The lawyer had just asked about this case: it is the one in context.
        AuditLog.objects.create(
            thread=self.thread, tool="case_summary", args={"case_id": self.case.pk}, result={}
        )

    def audio(self, **payload):
        return {**{"message_id": self.message.pk, "media_id": self.media.pk, "kind": "audio"}, **payload}

    @patch("apps.assistant.worker.send_text")
    @patch("apps.assistant.worker.stt.transcribe", return_value=(TRANSCRIPT, "small"))
    def test_a_voice_note_becomes_exactly_one_note(self, transcribe, send):
        self.assertTrue(worker.run_once())

        note = Note.objects.get()
        self.assertEqual(note.case, self.case)
        self.assertEqual(note.source, Note.VOICE)
        self.assertEqual(note.body, TRANSCRIPT)
        self.assertEqual(note.media, self.media)
        self.assertEqual(note.transcript_model, "small")
        self.assertIsNone(note.client)

        self.message.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.message.text, TRANSCRIPT)
        self.assertIsNotNone(self.message.replied_at)
        self.assertEqual(self.job.status, Job.DONE)
        self.assertEqual(self.job.attempts, 1)
        transcribe.assert_called_once_with(storage.abs_path(self.media.path))
        send.assert_called_once()
        self.assertIn("EXP-001", send.call_args.args[1])

    @patch("apps.assistant.worker.send_text")
    @patch("apps.assistant.worker.stt.transcribe", return_value=(TRANSCRIPT, "small"))
    def test_a_second_run_never_duplicates_the_note(self, transcribe, send):
        worker.run_once()
        self.assertFalse(worker.run_once())

        self.assertEqual(Note.objects.count(), 1)
        self.assertEqual(send.call_count, 1)

    @patch("apps.assistant.worker.send_text")
    @patch("apps.assistant.worker.stt.transcribe", return_value=(TRANSCRIPT, "small"))
    def test_the_only_open_case_is_the_one_in_context(self, transcribe, send):
        AuditLog.objects.all().delete()

        worker.run_once()

        self.assertEqual(Note.objects.get().case, self.case)

    @patch("apps.assistant.worker.send_text")
    @patch("apps.assistant.worker.stt.transcribe", return_value=(TRANSCRIPT, "small"))
    def test_without_a_case_it_says_so_and_writes_no_note(self, transcribe, send):
        AuditLog.objects.all().delete()
        Case.objects.create(
            client=self.client_obj, reference="EXP-002", title="Mercantil", opened_on=date(2026, 1, 5)
        )

        self.assertTrue(worker.run_once())

        self.assertFalse(Note.objects.exists())
        self.assertIn("expediente", send.call_args.args[1])
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.DONE)

    @patch("apps.assistant.worker.send_text")
    @patch("apps.assistant.worker.stt.transcribe", side_effect=stt.TooLong(600))
    def test_over_cap_audio_gets_one_line_and_no_note(self, transcribe, send):
        self.assertTrue(worker.run_once())

        self.assertFalse(Note.objects.exists())
        send.assert_called_once()
        self.assertIn("dos minutos", send.call_args.args[1])
        self.job.refresh_from_db()
        self.message.refresh_from_db()
        self.assertEqual(self.job.status, Job.DONE)
        self.assertEqual(self.job.attempts, 1)
        self.assertIsNotNone(self.message.replied_at)

    @patch("apps.assistant.worker.send_text")
    @patch("apps.assistant.worker.stt.transcribe", side_effect=stt.Unreadable("no decodifica"))
    def test_unreadable_audio_gets_one_line_and_no_note(self, transcribe, send):
        self.assertTrue(worker.run_once())

        self.assertFalse(Note.objects.exists())
        send.assert_called_once()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.DONE)
        self.assertEqual(self.job.attempts, 1)

    @patch("apps.assistant.worker.send_text")
    @patch("apps.assistant.worker.stt.transcribe", side_effect=RuntimeError("ffmpeg roto"))
    def test_an_unexpected_failure_still_respects_the_retry_cap(self, transcribe, send):
        for _ in range(worker.MAX_ATTEMPTS):
            worker.run_once()
            self.job.refresh_from_db()
            self.job.run_after = timezone.now()
            self.job.save()

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.FAILED)
        self.assertEqual(self.job.attempts, worker.MAX_ATTEMPTS)
        self.assertGreaterEqual(self.job.attempts, 1)
