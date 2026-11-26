from datetime import date

from django.test import TestCase

from apps.core.models import Case, Client, Note
from apps.docs.models import InboundMedia


def a_case(reference="EXP-001"):
    client = Client.objects.create(
        name="Ana García", phone="+525512345678", jid="5215512345678@s.whatsapp.net"
    )
    return Case.objects.create(
        client=client, reference=reference, title="Laboral", opened_on=date(2026, 11, 2)
    )


class NoteModelTests(TestCase):
    """core.Note is the one shape a voice note and a typed note share (PLAN §5.2)."""

    def test_a_voice_note_keeps_its_media_and_model(self):
        case = a_case()
        media = InboundMedia.objects.create(
            wamid="w-1",
            path="media/inbound/2026/11/abc.ogg",
            mime="audio/ogg",
            filename="nota.ogg",
            size=1024,
            sha256="abc",
        )

        note = Note.objects.create(
            case=case,
            body="El cliente firmó el convenio.",
            source=Note.VOICE,
            media=media,
            transcript_model="small",
        )

        self.assertEqual(note.case, case)
        self.assertEqual(note.source, Note.VOICE)
        self.assertEqual(note.media, media)
        self.assertEqual(note.transcript_model, "small")
        self.assertIsNone(note.client)

    def test_a_typed_note_has_the_same_fields_without_media(self):
        case = a_case()
        note = Note.objects.create(case=case, body="Llamar al juzgado.")

        self.assertEqual(note.source, Note.TEXT)
        self.assertIsNone(note.media)
        self.assertEqual(note.transcript_model, "")

    def test_notes_read_newest_first_and_die_with_the_case(self):
        case = a_case()
        first = Note.objects.create(case=case, body="primera")
        second = Note.objects.create(case=case, body="segunda")

        self.assertEqual([note.pk for note in case.notes.all()], [second.pk, first.pk])

        case.delete()
        self.assertFalse(Note.objects.exists())

    def test_a_note_can_be_about_the_client(self):
        case = a_case()
        note = Note.objects.create(case=case, client=case.client, body="Prefiere WhatsApp.")

        self.assertEqual(note.client, case.client)
        self.assertEqual(list(case.client.case_notes.all()), [note])
