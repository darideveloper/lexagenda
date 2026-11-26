import hashlib
import hmac
import json
import tempfile
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.assistant.models import Job, Message, Thread
from apps.channel.signature import verify
from apps.docs.models import InboundMedia

SECRET = "secreto-de-prueba"
DEVICE_A = "521771111111@s.whatsapp.net"
LAWYER_JID = "521771234567@s.whatsapp.net"


@override_settings(
    WEBHOOK_SECRET=SECRET,
    GOWA_DEVICE_A=DEVICE_A,
    LAWYER_JID=LAWYER_JID,
)
class WebhookTests(TestCase):
    """Payloads mirror the gowa v9 webhook envelope, not a normalised shape."""

    def event(self, **overrides):
        data = {
            "id": "wamid-1",
            "chat_id": LAWYER_JID,
            "from": LAWYER_JID,
            "timestamp": "2026-11-26T09:00:00Z",
            "is_from_me": False,
            "body": "hola",
        }
        data.update(overrides)
        return {"event": "message", "device_id": DEVICE_A, "payload": data}

    def post(self, event, secret=SECRET):
        body = json.dumps(event).encode()
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(
            reverse("gowa_webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
        )

    def test_lawyer_text_is_persisted_as_a_job(self):
        response = self.post(self.event())

        self.assertEqual(response.status_code, 200)
        message = Message.objects.get(wamid="wamid-1")
        self.assertEqual(message.text, "hola")
        self.assertEqual(message.role, Message.USER)
        self.assertEqual(Job.objects.get().payload, {"message_id": message.pk})
        self.assertEqual(Thread.objects.get().jid, LAWYER_JID)

    def test_bad_signature_is_200_and_writes_nothing(self):
        response = self.post(self.event(), secret="otro")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Message.objects.count(), 0)
        self.assertEqual(Job.objects.count(), 0)

    def test_device_b_is_dropped(self):
        response = self.post(
            {"event": "message", "device_id": "device-b", "payload": self.event()["payload"]}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Message.objects.count(), 0)

    def test_foreign_jid_is_dropped(self):
        foreign = "521700000000@s.whatsapp.net"
        response = self.post(self.event(from_jid=foreign, **{"from": foreign, "chat_id": foreign}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Message.objects.count(), 0)

    @mock.patch("apps.docs.ingest.download", return_value=b"OggS-nota")
    def test_a_voice_note_is_ingested_and_queued(self, download):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        override = override_settings(MEDIA_ROOT=tmp.name)
        override.enable()
        self.addCleanup(override.disable)

        response = self.post(
            self.event(audio="statics/media/nota.ogg", body="", mimetype="audio/ogg")
        )

        self.assertEqual(response.status_code, 200)
        media = InboundMedia.objects.get(wamid="wamid-1")
        message = Message.objects.get(wamid="wamid-1")
        self.assertEqual(media.mime, "audio/ogg")
        self.assertEqual(media.path.rsplit(".", 1)[-1], "ogg")
        self.assertEqual(
            Job.objects.get().payload,
            {"message_id": message.pk, "media_id": media.pk, "kind": "audio"},
        )

    def test_our_own_message_is_dropped(self):
        response = self.post(self.event(is_from_me=True))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Message.objects.count(), 0)

    def test_group_and_ack_events_are_dropped(self):
        group = self.event(chat_id="120363012345678901@g.us")
        self.post(group)
        self.post({"event": "message.ack", "device_id": DEVICE_A, "payload": {"id": "x"}})

        self.assertEqual(Message.objects.count(), 0)

    def test_duplicate_wamid_makes_one_message_and_one_job(self):
        self.post(self.event())
        response = self.post(self.event())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(Job.objects.count(), 1)

    def test_invalid_json_is_200(self):
        body = b"{nope"
        signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        response = self.client.post(
            reverse("gowa_webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Message.objects.count(), 0)


class SignatureTests(TestCase):
    def test_round_trip(self):
        body = b'{"a": 1}'
        header = "sha256=" + hmac.new(b"k", body, hashlib.sha256).hexdigest()

        self.assertTrue(verify("k", body, header))
        self.assertFalse(verify("k", body + b" ", header))
        self.assertFalse(verify("", body, header))
