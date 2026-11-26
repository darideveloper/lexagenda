from django.test import TestCase

from apps.assistant.models import Proposal, Thread
from apps.assistant.tools import TOOLS
from apps.core.models import Client, jid_for_phone


class ClientCreateTests(TestCase):
    """A typed number is not a client until its card is confirmed (PLAN §5.2)."""

    def setUp(self):
        self.thread = Thread.objects.create(jid="5211@s.whatsapp.net")

    def propose(self, **args):
        return TOOLS["client_create"]["fn"](self.thread, **args)

    def test_a_typed_number_becomes_a_jid_and_writes_nothing(self):
        result = self.propose(name="Juan Pérez", phone="+52 771 234 5678")

        self.assertEqual(Client.objects.count(), 0)
        proposal = Proposal.objects.get(pk=result["proposal_id"])
        self.assertEqual(proposal.status, Proposal.PROPOSED)
        self.assertEqual(proposal.steps[0]["tool"], "client_create")
        self.assertEqual(proposal.steps[0]["args"]["jid"], "527712345678@s.whatsapp.net")
        self.assertIn("Nuevo cliente: «Juan Pérez»", result["summary"])
        self.assertIn("¿Lo doy de alta?", result["summary"])

    def test_a_local_ten_digit_number_gets_the_country_code(self):
        self.assertEqual(jid_for_phone("771 234 5678"), "527712345678@s.whatsapp.net")

        result = self.propose(name="X", phone="7712345678")

        proposal = Proposal.objects.get(pk=result["proposal_id"])
        self.assertEqual(proposal.steps[0]["args"]["jid"], "527712345678@s.whatsapp.net")

    def test_the_whatsapp_display_name_is_shown_on_the_card(self):
        result = self.propose(
            name="Juan Pérez", phone="7712345678", wa_name="Juanito 🌮"
        )

        self.assertIn("En WhatsApp aparece como «Juanito 🌮»", result["summary"])

    def test_confirm_creates_the_client_once(self):
        result = self.propose(name="Juan Pérez", phone="7712345678", wa_name="Juanito")

        confirmation = TOOLS["confirm"]["fn"](self.thread, proposal_id=result["proposal_id"])
        again = TOOLS["confirm"]["fn"](self.thread, proposal_id=result["proposal_id"])

        self.assertTrue(confirmation["ok"])
        self.assertIn("dí de alta", confirmation["text"])
        self.assertTrue(again["duplicate"])
        client = Client.objects.get()
        self.assertEqual(client.name, "Juan Pérez")
        self.assertEqual(client.phone, "7712345678")
        self.assertEqual(client.jid, "527712345678@s.whatsapp.net")
        self.assertEqual(client.wa_name, "Juanito")

    def test_a_number_already_in_the_book_is_refused(self):
        Client.objects.create(
            name="García", phone="+527711234567", jid="527711234567@s.whatsapp.net"
        )

        result = self.propose(name="Otro", phone="7711234567")

        self.assertIn("error", result)
        self.assertIn("ya está en la agenda", result["error"])
        self.assertEqual(Proposal.objects.count(), 0)

    def test_a_number_that_is_not_a_phone_is_refused(self):
        for phone in ("", "123", "no tengo el número"):
            self.assertIn("error", self.propose(name="X", phone=phone))

        self.assertEqual(Proposal.objects.count(), 0)

    def test_a_missing_name_is_refused(self):
        result = self.propose(name="   ", phone="7712345678")

        self.assertIn("error", result)
        self.assertEqual(Proposal.objects.count(), 0)
