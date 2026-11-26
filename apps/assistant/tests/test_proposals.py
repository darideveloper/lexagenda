from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.assistant import envelope
from apps.assistant.models import Proposal, Thread


class ProposalModelTests(TestCase):
    def setUp(self):
        self.thread = Thread.objects.create(jid="5211@s.whatsapp.net")

    def test_a_proposal_starts_open_and_expires_before_it_is_stored(self):
        proposal = Proposal.objects.create(
            thread=self.thread,
            steps=[{"tool": "appointment_create", "args": {"title": "Visita"}}],
            summary="¿La agendo?",
            expires_at=timezone.now() + timedelta(hours=1),
        )

        self.assertEqual(proposal.status, Proposal.PROPOSED)
        self.assertIsNone(proposal.committed_at)
        self.assertEqual(proposal.steps[0]["tool"], "appointment_create")

    def test_only_one_open_proposal_per_thread(self):
        expires = timezone.now() + timedelta(hours=1)
        Proposal.objects.create(thread=self.thread, summary="uno", expires_at=expires)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Proposal.objects.create(thread=self.thread, summary="dos", expires_at=expires)

    def test_a_closed_proposal_does_not_block_a_new_one(self):
        expires = timezone.now() + timedelta(hours=1)
        first = Proposal.objects.create(thread=self.thread, summary="uno", expires_at=expires)
        first.status = Proposal.COMMITTED
        first.save(update_fields=["status"])

        second = Proposal.objects.create(thread=self.thread, summary="dos", expires_at=expires)

        self.assertEqual(second.status, Proposal.PROPOSED)


class EnvelopeTests(TestCase):
    def setUp(self):
        self.thread = Thread.objects.create(jid="5211@s.whatsapp.net")

    def test_propose_stores_the_summary_that_was_shown(self):
        proposal = envelope.propose(
            self.thread,
            steps=[{"tool": "appointment_create", "args": {"title": "Visita García"}}],
            summary="Nueva cita: «Visita García»\n¿La agendo?",
        )

        self.assertEqual(proposal.status, Proposal.PROPOSED)
        self.assertEqual(proposal.summary, "Nueva cita: «Visita García»\n¿La agendo?")
        self.assertEqual(Proposal.objects.count(), 1)

    def test_a_second_proposal_supersedes_the_first_and_says_so(self):
        first = envelope.propose(self.thread, steps=[], summary="primera")
        second = envelope.propose(self.thread, steps=[], summary="segunda")

        first.refresh_from_db()
        self.assertEqual(first.status, Proposal.SUPERSEDED)
        self.assertEqual(second.status, Proposal.PROPOSED)
        self.assertTrue(second.summary.startswith("segunda"))
        self.assertIn(envelope.SUPERSEDED_LINE, second.summary)
        self.assertEqual(Proposal.objects.filter(status=Proposal.PROPOSED).count(), 1)

    def test_expiry_defaults_to_twelve_hours(self):
        before = timezone.now()
        proposal = envelope.propose(self.thread, steps=[], summary="x")

        self.assertGreaterEqual(proposal.expires_at, before + envelope.TTL)
        self.assertLessEqual(proposal.expires_at, timezone.now() + envelope.TTL)

    @patch("apps.assistant.envelope.TTL", timedelta(hours=12))
    def test_an_earlier_deadline_wins(self):
        start = timezone.now() + timedelta(hours=2)

        proposal = envelope.propose(self.thread, steps=[], summary="x", expires_at=start)

        self.assertEqual(proposal.expires_at, start)
        self.assertLess(proposal.expires_at, timezone.now() + envelope.TTL)

    def test_open_proposal_returns_the_live_one(self):
        self.assertIsNone(envelope.open_proposal(self.thread))
        proposal = envelope.propose(self.thread, steps=[], summary="x")

        self.assertEqual(envelope.open_proposal(self.thread), proposal)
