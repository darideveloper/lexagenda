import tempfile
from pathlib import Path
from unittest import mock

import yaml
from django.conf import settings
from django.test import TestCase, override_settings

from apps.assistant.models import Thread
from apps.assistant.tools import TOOLS
from apps.channel.models import SendLog
from apps.core.models import Client

DEVICE_B = "device-b"
OUTBOUND = "Hola Juan: el juicio se movió al 3 de diciembre."


class DeliveryModeTests(TestCase):
    """`delivery_mode` is read at send time: auto→draft takes effect with no restart (§6.3)."""

    def setUp(self):
        self.thread = Thread.objects.create(jid="5211@s.whatsapp.net")
        self.client = Client.objects.create(
            name="Juan Pérez", phone="+527712345678", jid="527712345678@s.whatsapp.net"
        )
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "config.yaml"
        self.write_config("draft")

    def write_config(self, mode):
        self.path.write_text(
            yaml.safe_dump(
                {
                    "name": "Despacho de prueba",
                    "delivery_mode": mode,
                    "kinds": {"visita": {"duration": 60, "buffer": 15}},
                    "caps": {"hourly": 20, "daily": 60, "delay_seconds": 2},
                }
            )
        )

    def confirm(self):
        proposal = TOOLS["client_update"]["fn"](
            self.thread, client_id=self.client.pk, text=OUTBOUND
        )
        with mock.patch("apps.channel.gowa.send_text") as send:
            result = TOOLS["confirm"]["fn"](
                self.thread, proposal_id=proposal["proposal_id"]
            )
        return result, send

    def test_in_draft_mode_the_send_becomes_a_draft_and_nothing_leaves(self):
        with override_settings(CONFIG_PATH=self.path, GOWA_DEVICE_B=DEVICE_B):
            result, send = self.confirm()

        self.assertEqual(settings.CONFIG["delivery_mode"], "auto")
        send.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertIn("Borrador", result["text"])
        self.assertIn(OUTBOUND, result["text"])
        row = SendLog.objects.get()
        self.assertEqual(row.mode, SendLog.DRAFT)
        self.assertEqual(row.text, OUTBOUND)

    def test_flipping_the_file_back_to_auto_sends_without_a_restart(self):
        with override_settings(CONFIG_PATH=self.path, GOWA_DEVICE_B=DEVICE_B):
            drafted, send = self.confirm()
            self.write_config("auto")
            sent, send_again = self.confirm()

        self.assertIn("Borrador", drafted["text"])
        send.assert_not_called()
        self.assertTrue(sent["ok"])
        send_again.assert_called_once()
        self.assertEqual(
            SendLog.objects.filter(mode=SendLog.SENT).count(), 1
        )

    def test_auto_mode_sends(self):
        self.write_config("auto")

        with override_settings(CONFIG_PATH=self.path, GOWA_DEVICE_B=DEVICE_B):
            result, send = self.confirm()

        self.assertTrue(result["ok"])
        send.assert_called_once_with(
            self.client.jid, OUTBOUND, device=DEVICE_B
        )
