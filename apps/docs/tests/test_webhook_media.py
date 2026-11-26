import hashlib
import hmac
import json
import tempfile
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.assistant.models import Job, Message, Thread
from apps.docs.models import InboundMedia

SECRET = "secreto-de-prueba"
DEVICE_A = "521771111111@s.whatsapp.net"
LAWYER_JID = "521771234567@s.whatsapp.net"


@override_settings(
    WEBHOOK_SECRET=SECRET,
    GOWA_DEVICE_A=DEVICE_A,
    LAWYER_JID=LAWYER_JID,
)
class MediaWebhookTests(TestCase):
    """A forwarded file is persisted as InboundMedia and queues a job (§6.2)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        override = override_settings(MEDIA_ROOT=self.tmp.name)
        override.enable()
        self.addCleanup(override.disable)

    def event(self, **overrides):
        data = {
            "id": "wamid-1",
            "chat_id": LAWYER_JID,
            "from": LAWYER_JID,
            "timestamp": "2026-11-26T09:00:00Z",
            "is_from_me": False,
            "body": "",
        }
        data.update(overrides)
        return {"event": "message", "device_id": DEVICE_A, "payload": data}

    def post(self, event):
        body = json.dumps(event).encode()
        signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(
            reverse("gowa_webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
        )

    @mock.patch("apps.docs.ingest.download", return_value=b"%PDF-1.4 demanda")
    def test_a_forwarded_pdf_is_ingested_and_queued(self, download):
        response = self.post(
            self.event(
                document="statics/media/demanda.pdf",
                mimetype="application/pdf",
                filename="demanda.pdf",
            )
        )

        self.assertEqual(response.status_code, 200)
        download.assert_called_once_with("statics/media/demanda.pdf")
        media = InboundMedia.objects.get(wamid="wamid-1")
        message = Message.objects.get(wamid="wamid-1")
        self.assertEqual(message.role, Message.USER)
        self.assertEqual(message.text, "")
        self.assertEqual(media.filename, "demanda.pdf")
        self.assertEqual(media.mime, "application/pdf")
        self.assertEqual(
            Job.objects.get().payload,
            {"message_id": message.pk, "media_id": media.pk, "kind": "document"},
        )
        self.assertEqual(Thread.objects.get().jid, LAWYER_JID)

    @mock.patch("apps.docs.ingest.download", return_value=b"x" * (25 * 1024 * 1024 + 1))
    def test_a_file_over_the_cap_is_refused(self, download):
        response = self.post(self.event(document="statics/media/pesado.pdf"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(InboundMedia.objects.count(), 0)
        self.assertEqual(Job.objects.count(), 0)

    def test_an_image_is_ingested(self):
        with mock.patch("apps.docs.ingest.download", return_value=b"\xff\xd8jpeg"):
            response = self.post(self.event(image="statics/media/foto.jpg"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(InboundMedia.objects.get().mime, "")
        self.assertEqual(Job.objects.get().payload["kind"], "image")

    @mock.patch("apps.docs.ingest.download", return_value=b"hola")
    def test_the_same_file_twice_makes_one_row(self, download):
        event = self.event(document="statics/media/nota.txt", filename="nota.txt")
        self.post(event)
        self.post(event)

        self.assertEqual(InboundMedia.objects.count(), 1)
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(Job.objects.count(), 1)
