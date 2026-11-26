from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.agenda.models import Appointment
from apps.assistant import envelope
from apps.assistant.models import AuditLog, Proposal, Thread
from apps.assistant.tools import TOOLS


def create_steps(title="Visita García", when="2026-11-27T09:30"):
    return [
        {
            "tool": "appointment_create",
            "args": {"title": title, "starts_at": when, "duration_min": 60},
        }
    ]


class ConfirmTests(TestCase):
    def setUp(self):
        self.thread = Thread.objects.create(jid="5211@s.whatsapp.net")

    def open_proposal(self, summary="Nueva cita: «Visita García»\n¿La agendo?"):
        return envelope.propose(self.thread, steps=create_steps(), summary=summary)

    def test_confirm_applies_the_stored_steps_and_keeps_the_undo(self):
        proposal = self.open_proposal()

        result = TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal.pk)

        self.assertTrue(result["ok"])
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.COMMITTED)
        self.assertIsNotNone(proposal.committed_at)
        appointment = Appointment.objects.get()
        self.assertEqual(appointment.title, "Visita García")
        self.assertEqual(proposal.result["undo"][0]["tool"], "appointment_delete")
        self.assertIn("agendé", result["text"])

    def test_double_confirm_commits_once(self):
        proposal = self.open_proposal()

        first = TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal.pk)
        second = TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal.pk)

        self.assertTrue(first["ok"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["text"], "Ya estaba hecho.")
        self.assertEqual(Appointment.objects.count(), 1)

    def test_confirm_refuses_a_proposal_from_another_thread(self):
        proposal = self.open_proposal()
        other = Thread.objects.create(jid="5299@s.whatsapp.net")

        result = TOOLS["confirm"]["fn"](other, proposal_id=proposal.pk)

        self.assertFalse(result["ok"])
        self.assertEqual(Appointment.objects.count(), 0)

    def test_confirm_takes_no_other_argument(self):
        proposal = self.open_proposal()

        result = TOOLS["confirm"]["fn"](
            self.thread,
            proposal_id=proposal.pk,
            steps=create_steps(title="Otra cosa"),
            title="Otra cosa",
        )

        self.assertIn("error", result)
        self.assertEqual(Appointment.objects.count(), 0)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.PROPOSED)

    def test_a_cancelled_proposal_cannot_commit(self):
        proposal = self.open_proposal()
        TOOLS["cancel"]["fn"](self.thread, proposal_id=proposal.pk)

        result = TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal.pk)

        self.assertFalse(result["ok"])
        self.assertEqual(Appointment.objects.count(), 0)

    def test_an_unknown_tool_leaves_the_proposal_failed_and_nothing_written(self):
        proposal = envelope.propose(
            self.thread, steps=[{"tool": "plan_visit", "args": {}}], summary="x"
        )

        result = TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal.pk)

        self.assertFalse(result["ok"])
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.FAILED)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_cancel_changes_nothing(self):
        proposal = self.open_proposal()

        result = TOOLS["cancel"]["fn"](self.thread, proposal_id=proposal.pk)

        self.assertTrue(result["ok"])
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.CANCELLED)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_a_committed_proposal_cannot_be_cancelled(self):
        proposal = self.open_proposal()
        TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal.pk)

        result = TOOLS["cancel"]["fn"](self.thread, proposal_id=proposal.pk)

        self.assertFalse(result["ok"])
        self.assertEqual(Appointment.objects.count(), 1)


class ExpiryTests(TestCase):
    def setUp(self):
        self.thread = Thread.objects.create(jid="5211@s.whatsapp.net")

    def expire(self, proposal):
        Proposal.objects.filter(pk=proposal.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )

    def test_confirm_refuses_an_expired_proposal_and_changes_nothing(self):
        proposal = envelope.propose(self.thread, steps=create_steps(), summary="¿La agendo?")
        self.expire(proposal)

        result = TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal.pk)

        self.assertFalse(result["ok"])
        self.assertIn("caducó", result["text"])
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.EXPIRED)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_sweep_expires_only_the_stale_open_proposals(self):
        stale = envelope.propose(self.thread, steps=create_steps(), summary="vieja")
        self.expire(stale)

        out = StringIO()
        call_command("sweep", stdout=out)

        stale.refresh_from_db()
        self.assertEqual(stale.status, Proposal.EXPIRED)
        self.assertIn("1 propuesta(s) caducada(s)", out.getvalue())

    def test_sweep_leaves_a_live_proposal_alone(self):
        live = envelope.propose(self.thread, steps=create_steps(), summary="viva")

        call_command("sweep", stdout=StringIO())

        live.refresh_from_db()
        self.assertEqual(live.status, Proposal.PROPOSED)

    def test_sweep_leaves_a_committed_proposal_alone(self):
        committed = envelope.propose(self.thread, steps=create_steps(), summary="hecha")
        TOOLS["confirm"]["fn"](self.thread, proposal_id=committed.pk)
        Proposal.objects.filter(pk=committed.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )

        call_command("sweep", stdout=StringIO())

        committed.refresh_from_db()
        self.assertEqual(committed.status, Proposal.COMMITTED)


class UndoTests(TestCase):
    def setUp(self):
        self.thread = Thread.objects.create(jid="5211@s.whatsapp.net")

    def test_undo_of_a_creation_removes_the_appointment(self):
        proposal = envelope.propose(self.thread, steps=create_steps(), summary="¿La agendo?")
        TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal.pk)

        result = TOOLS["undo"]["fn"](self.thread, proposal_id=proposal.pk)

        self.assertTrue(result["ok"])
        self.assertEqual(Appointment.objects.count(), 0)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.UNDONE)
        self.assertEqual(Proposal.objects.get(undo_of=proposal).status, Proposal.COMMITTED)

    def test_undo_of_a_reschedule_restores_the_previous_time(self):
        appointment = Appointment.objects.create(
            title="Visita", starts_at=envelope.parse_when("2026-11-27T17:00")
        )
        proposal = envelope.propose(
            self.thread,
            steps=[
                {
                    "tool": "reschedule",
                    "args": {
                        "appointment_id": appointment.pk,
                        "new_start": "2026-11-28T10:00",
                    },
                }
            ],
            summary="¿La muevo?",
        )
        TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal.pk)
        appointment.refresh_from_db()
        self.assertEqual(timezone.localtime(appointment.starts_at).hour, 10)
        moved_sequence = appointment.ics_sequence

        TOOLS["undo"]["fn"](self.thread, proposal_id=proposal.pk)

        appointment.refresh_from_db()
        self.assertEqual(timezone.localtime(appointment.starts_at).hour, 17)
        self.assertEqual(appointment.ics_sequence, moved_sequence + 1)

    def test_undo_outside_the_24_hour_window_is_refused(self):
        proposal = envelope.propose(self.thread, steps=create_steps(), summary="¿La agendo?")
        TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal.pk)
        Proposal.objects.filter(pk=proposal.pk).update(
            committed_at=timezone.now() - timedelta(hours=25)
        )

        result = TOOLS["undo"]["fn"](self.thread, proposal_id=proposal.pk)

        self.assertFalse(result["ok"])
        self.assertEqual(Appointment.objects.count(), 1)

    def test_undo_of_an_open_proposal_does_nothing(self):
        proposal = envelope.propose(self.thread, steps=create_steps(), summary="¿La agendo?")

        result = TOOLS["undo"]["fn"](self.thread, proposal_id=proposal.pk)

        self.assertFalse(result["ok"])
        self.assertEqual(Appointment.objects.count(), 0)
