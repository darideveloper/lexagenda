from datetime import date

from django.test import TestCase

from apps.assistant import tools
from apps.assistant.models import Thread
from apps.core.models import Case, Client, Note
from apps.docs.models import InboundMedia

SHAPE = {"id", "source", "body", "created_at", "media_id", "transcript_model"}


class CaseNotesReadTests(TestCase):
    """`case_notes` and `case_summary` read the same notes in the same shape (PLAN §5.2)."""

    def setUp(self):
        client = Client.objects.create(
            name="Ana García", phone="+525512345678", jid="5215512345678@s.whatsapp.net"
        )
        self.case = Case.objects.create(
            client=client,
            reference="EXP-001",
            title="Laboral",
            opened_on=date(2026, 11, 2),
        )
        self.thread = Thread.objects.create(jid="521771234567@s.whatsapp.net")
        self.media = InboundMedia.objects.create(
            wamid="w-1",
            path="media/inbound/2026/11/abc.ogg",
            mime="audio/ogg",
            filename="nota.ogg",
            size=10,
            sha256="abc",
        )
        Note.objects.create(case=self.case, body="Llamar al juzgado.")
        Note.objects.create(
            case=self.case,
            body="El cliente firmó el convenio.",
            source=Note.VOICE,
            media=self.media,
            transcript_model="small",
        )

    def notes(self, **kwargs):
        kwargs.setdefault("case_id", self.case.pk)
        return tools.case_notes(self.thread, **kwargs)

    def test_case_notes_returns_the_recent_notes_newest_first(self):
        result = self.notes()

        self.assertEqual(result["case_id"], self.case.pk)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["notes"][0]["body"], "El cliente firmó el convenio.")
        self.assertEqual(result["notes"][1]["body"], "Llamar al juzgado.")

    def test_a_voice_note_and_a_typed_note_share_one_shape(self):
        result = self.notes()
        voice, typed = result["notes"]

        self.assertEqual(set(voice), SHAPE)
        self.assertEqual(set(typed), SHAPE)
        self.assertEqual(voice["source"], Note.VOICE)
        self.assertEqual(voice["media_id"], self.media.pk)
        self.assertEqual(voice["transcript_model"], "small")
        self.assertEqual(typed["source"], Note.TEXT)
        self.assertIsNone(typed["media_id"])
        self.assertIsNone(typed["transcript_model"])

    def test_the_limit_keeps_the_newest(self):
        result = self.notes(limit=1)

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["notes"][0]["source"], Note.VOICE)

    def test_case_summary_carries_the_same_notes(self):
        summary = tools.case_summary(self.thread, case_id=self.case.pk)

        self.assertEqual(
            [note["body"] for note in summary["notes"]],
            ["El cliente firmó el convenio.", "Llamar al juzgado."],
        )
        self.assertEqual(set(summary["notes"][0]), SHAPE)

    def test_an_unknown_case_is_an_error_not_a_crash(self):
        self.assertIn("error", self.notes(case_id=999999))
        self.assertIn("error", tools.case_summary(self.thread, case_id=999999))
