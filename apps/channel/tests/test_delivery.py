from unittest import mock

from django.test import TestCase, override_settings

from apps.assistant.models import Proposal, Thread
from apps.assistant.tools import TOOLS
from apps.channel.gowa import DeliveryRefused, deliver
from apps.channel.send import SendError
from apps.core.models import Client, jid_for_phone

DEVICE_B = "device-b"
OUTBOUND = "Hola Juan:\n\nEl juicio se movió al 3 de diciembre, 9:30.  ¿Te confirmo el viernes?"


@override_settings(GOWA_DEVICE_B=DEVICE_B, GOWA_DEVICE_A="device-a")
class ClientUpdateTests(TestCase):
    """`client_update` stores the exact bytes; the send never re-renders them (PLAN §6.3)."""

    def setUp(self):
        self.thread = Thread.objects.create(jid="5211@s.whatsapp.net")
        self.client = Client.objects.create(
            name="Juan Pérez",
            phone="+527712345678",
            jid="527712345678@s.whatsapp.net",
        )

    def propose(self, text=OUTBOUND):
        return TOOLS["client_update"]["fn"](
            self.thread, client_id=self.client.pk, text=text
        )

    def test_client_update_stores_the_exact_text_and_writes_nothing(self):
        result = self.propose()

        proposal = Proposal.objects.get(pk=result["proposal_id"])
        self.assertEqual(proposal.status, Proposal.PROPOSED)
        self.assertEqual(proposal.outbound_text, OUTBOUND)
        self.assertEqual(proposal.steps, [{"tool": "client_update", "args": {"client_id": self.client.pk}}])
        self.assertIn(OUTBOUND, result["summary"])
        self.assertIn("«Juan Pérez»", result["summary"])
        self.assertIn("¿Lo mando?", result["summary"])

    def test_confirm_sends_the_stored_bytes_on_device_b(self):
        proposal = Proposal.objects.get(pk=self.propose()["proposal_id"])

        with mock.patch("apps.channel.gowa.send_text") as send:
            result = TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal.pk)

        self.assertTrue(result["ok"])
        send.assert_called_once_with(self.client.jid, OUTBOUND, device=DEVICE_B)

    def test_a_rephrase_after_the_card_does_not_change_what_is_sent(self):
        proposal = Proposal.objects.get(pk=self.propose()["proposal_id"])
        proposal.summary = "Aviso para Juan Pérez:\notra cosa distinta"
        proposal.save(update_fields=["summary"])

        with mock.patch("apps.channel.gowa.send_text") as send:
            TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal.pk)

        self.assertEqual(send.call_args[0][1], OUTBOUND)

    def test_a_jid_outside_the_book_is_refused(self):
        proposal = Proposal.objects.get(pk=self.propose()["proposal_id"])

        with mock.patch("apps.channel.gowa.send_text") as send:
            with self.assertRaises(DeliveryRefused) as refused:
                deliver(proposal, "521700000000@s.whatsapp.net")

        self.assertIn("no está en la agenda", str(refused.exception))
        send.assert_not_called()

    def test_an_inactive_client_is_not_a_destination(self):
        proposal = Proposal.objects.get(pk=self.propose()["proposal_id"])
        self.client.is_active = False
        self.client.save(update_fields=["is_active"])

        with mock.patch("apps.channel.gowa.send_text") as send:
            with self.assertRaises(DeliveryRefused):
                deliver(proposal, self.client.jid)

        send.assert_not_called()

    def test_a_proposal_without_text_is_refused(self):
        proposal = Proposal.objects.get(pk=self.propose()["proposal_id"])
        proposal.outbound_text = ""
        proposal.save(update_fields=["outbound_text"])

        with mock.patch("apps.channel.gowa.send_text") as send:
            with self.assertRaises(DeliveryRefused):
                deliver(proposal, self.client.jid)

        send.assert_not_called()

    def test_a_gowa_failure_is_a_sentence_not_a_crash(self):
        proposal = Proposal.objects.get(pk=self.propose()["proposal_id"])

        with mock.patch("apps.channel.gowa.send_text", side_effect=SendError("boom")):
            result = TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal.pk)

        self.assertFalse(result["ok"])
        self.assertIn("WhatsApp", result["text"])
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.FAILED)

    def test_client_update_refuses_an_unknown_client_or_empty_text(self):
        unknown = TOOLS["client_update"]["fn"](self.thread, client_id=999999, text="x")
        empty = self.propose(text="   ")

        self.assertIn("error", unknown)
        self.assertIn("error", empty)
        self.assertEqual(Proposal.objects.count(), 0)

    def test_a_local_number_and_a_stored_jid_resolve_the_same(self):
        self.assertEqual(jid_for_phone(self.client.phone), self.client.jid)
