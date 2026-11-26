from datetime import date

from django.test import TestCase

from apps.assistant import tools
from apps.assistant.models import Proposal, Thread
from apps.core.models import Case, Client, Note


class NoteAddTests(TestCase):
    """`note_add` is a proposal: the note exists only after `confirm` (PLAN §5.2)."""

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

    def propose(self, body="Llamar al juzgado el jueves."):
        return tools.note_add(self.thread, case_id=self.case.pk, body=body)

    def test_the_note_is_only_shown_until_the_lawyer_confirms(self):
        result = self.propose()

        self.assertIn("proposal_id", result)
        self.assertIn("Llamar al juzgado el jueves.", result["summary"])
        self.assertEqual(Note.objects.count(), 0)
        self.assertEqual(Proposal.objects.get().status, Proposal.PROPOSED)

    def test_confirm_writes_one_text_note(self):
        result = self.propose()

        out = tools.confirm(self.thread, proposal_id=result["proposal_id"])

        self.assertTrue(out["ok"])
        note = Note.objects.get()
        self.assertEqual(note.case, self.case)
        self.assertEqual(note.body, "Llamar al juzgado el jueves.")
        self.assertEqual(note.source, Note.TEXT)
        self.assertIsNone(note.media)

    def test_cancel_writes_nothing(self):
        result = self.propose()

        out = tools.cancel(self.thread, proposal_id=result["proposal_id"])

        self.assertTrue(out["ok"])
        self.assertFalse(Note.objects.exists())

    def test_undo_removes_the_note_it_wrote(self):
        result = self.propose()
        tools.confirm(self.thread, proposal_id=result["proposal_id"])

        out = tools.undo(self.thread, proposal_id=result["proposal_id"])

        self.assertTrue(out["ok"])
        self.assertFalse(Note.objects.exists())

    def test_a_note_needs_a_real_case_and_a_body(self):
        self.assertIn("error", tools.note_add(self.thread, case_id=999999, body="x"))
        self.assertIn("error", tools.note_add(self.thread, case_id=self.case.pk, body="  "))
        self.assertFalse(Note.objects.exists())
