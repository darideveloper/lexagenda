import hashlib
import hmac
import json
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.assistant.models import Job, Message, Proposal, Thread
from apps.assistant.tools import TOOLS
from apps.core.models import Client

SECRET = "secreto-de-prueba"
DEVICE_A = "521771111111@s.whatsapp.net"
LAWYER_JID = "521771234567@s.whatsapp.net"
FOREIGN = "521700000000@s.whatsapp.net"


@override_settings(WEBHOOK_SECRET=SECRET, GOWA_DEVICE_A=DEVICE_A, LAWYER_JID=LAWYER_JID)
class ContactCardTests(TestCase):
    """A forwarded contact card reaches the same client card as a typed number (PLAN §6.2)."""

    def event(self, *, name="Juan Pérez", waid="5217712345678", wamid="wamid-c1", device_id=DEVICE_A, sender=LAWYER_JID):
        vcard = (
            "BEGIN:VCARD\nVERSION:3.0\n"
            f"FN:{name}\n"
            f"TEL;type=CELL;waid={waid}:+{waid}\n"
            "END:VCARD"
        )
        return {
            "event": "message",
            "device_id": device_id,
            "payload": {
                "id": wamid,
                "chat_id": sender,
                "from": sender,
                "timestamp": "2026-11-26T09:00:00Z",
                "is_from_me": False,
                "contacts": [{"displayName": name, "vcard": vcard}],
            },
        }

    def post(self, event):
        body = json.dumps(event).encode()
        signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(
            reverse("gowa_webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
        )

    def test_a_forwarded_card_becomes_a_client_card(self):
        with mock.patch("apps.channel.views.send_text") as send:
            response = self.post(self.event())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Client.objects.count(), 0)
        proposal = Proposal.objects.get(status=Proposal.PROPOSED)
        self.assertEqual(proposal.steps[0]["tool"], "client_create")
        self.assertEqual(proposal.steps[0]["args"]["jid"], "5217712345678@s.whatsapp.net")
        self.assertEqual(proposal.steps[0]["args"]["wa_name"], "Juan Pérez")
        self.assertIn("Nuevo cliente: «Juan Pérez»", proposal.summary)
        self.assertIn("En WhatsApp aparece como «Juan Pérez»", proposal.summary)
        self.assertIn("¿Lo doy de alta?", proposal.summary)
        send.assert_called_once_with(LAWYER_JID, proposal.summary)
        self.assertEqual(Job.objects.count(), 0)

    def test_the_card_is_answered_and_confirm_creates_the_client(self):
        with mock.patch("apps.channel.views.send_text"):
            self.post(self.event())

        proposal = Proposal.objects.get()
        Thread.objects.get(jid=LAWYER_JID)
        self.assertTrue(Message.objects.filter(role=Message.ASSISTANT, text=proposal.summary).exists())

        thread = proposal.thread
        TOOLS["confirm"]["fn"](thread, proposal_id=proposal.pk)

        client = Client.objects.get()
        self.assertEqual(client.name, "Juan Pérez")
        self.assertEqual(client.jid, "5217712345678@s.whatsapp.net")

    def test_a_card_and_a_typed_number_are_the_same_card(self):
        with mock.patch("apps.channel.views.send_text"):
            self.post(self.event(name="Juan Pérez", waid="527712345678"))

        typed_thread = Thread.objects.create(jid="5211@s.whatsapp.net")
        typed = TOOLS["client_create"]["fn"](
            typed_thread, name="Juan Pérez", phone="771 234 5678"
        )

        from_card = Proposal.objects.get(thread__jid=LAWYER_JID)
        from_typing = Proposal.objects.get(pk=typed["proposal_id"])
        self.assertEqual(
            from_card.steps[0]["args"]["jid"], from_typing.steps[0]["args"]["jid"]
        )
        for line in ("Nuevo cliente: «Juan Pérez»", "¿Lo doy de alta?"):
            self.assertIn(line, from_card.summary)
            self.assertIn(line, from_typing.summary)

    def test_a_normalised_contact_payload_works_too(self):
        event = self.event()
        event["payload"] = {
            "id": "wamid-c2",
            "from": LAWYER_JID,
            "chat_id": LAWYER_JID,
            "is_from_me": False,
            "contact_name": "Ana López",
            "contact_phone": "5217799887766",
        }

        with mock.patch("apps.channel.views.send_text"):
            self.post(event)

        proposal = Proposal.objects.get()
        self.assertEqual(proposal.steps[0]["args"]["jid"], "5217799887766@s.whatsapp.net")

    def test_a_card_from_device_b_is_dropped(self):
        with mock.patch("apps.channel.views.send_text") as send:
            response = self.post(self.event(device_id="device-b"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Proposal.objects.count(), 0)
        self.assertEqual(Message.objects.count(), 0)
        send.assert_not_called()

    def test_a_card_from_a_foreign_jid_is_dropped(self):
        with mock.patch("apps.channel.views.send_text") as send:
            response = self.post(self.event(sender=FOREIGN))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Proposal.objects.count(), 0)
        send.assert_not_called()

    def test_the_same_card_twice_makes_one_proposal(self):
        with mock.patch("apps.channel.views.send_text"):
            self.post(self.event())
            response = self.post(self.event())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Proposal.objects.count(), 1)
        self.assertEqual(Message.objects.filter(role=Message.USER).count(), 1)

    def test_a_number_already_in_the_book_is_refused_out_loud(self):
        Client.objects.create(
            name="García", phone="+527712345678", jid="5217712345678@s.whatsapp.net"
        )

        with mock.patch("apps.channel.views.send_text") as send:
            response = self.post(self.event())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Proposal.objects.count(), 0)
        self.assertEqual(Client.objects.count(), 1)
        spoken = send.call_args[0][1]
        self.assertIn("ya está en la agenda", spoken)
