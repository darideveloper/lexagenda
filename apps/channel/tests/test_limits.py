from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.assistant.models import Proposal, Thread
from apps.assistant.tools import TOOLS
from apps.channel.models import SendLog
from apps.core.models import Client

DEVICE_B = "device-b"
JID = "527712345678@s.whatsapp.net"
OUTBOUND = "Hola Juan: el juicio se movió al 3 de diciembre."


@override_settings(GOWA_DEVICE_B=DEVICE_B)
class SendLogTests(TestCase):
    """One row per delivery, with the rendered text, so a complaint can be answered."""

    def setUp(self):
        self.thread = Thread.objects.create(jid="5211@s.whatsapp.net")
        self.client = Client.objects.create(
            name="Juan Pérez", phone="+527712345678", jid=JID
        )

    def propose(self, text=OUTBOUND):
        return TOOLS["client_update"]["fn"](
            self.thread, client_id=self.client.pk, text=text
        )["proposal_id"]

    def confirm(self, text=OUTBOUND):
        proposal_id = self.propose(text)
        with mock.patch("apps.channel.gowa.send_text"):
            return TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal_id)

    def log_rows(self, count, *, mode=SendLog.SENT, minutes_ago=30):
        now = timezone.now()
        for index in range(count):
            row = SendLog.objects.create(
                client=self.client, jid=JID, text=f"previo {index}", mode=mode
            )
            SendLog.objects.filter(pk=row.pk).update(
                created_at=now - timedelta(minutes=minutes_ago)
            )

    def test_every_delivery_leaves_one_row_with_the_text(self):
        result = self.confirm()

        self.assertTrue(result["ok"])
        row = SendLog.objects.get()
        self.assertEqual(row.jid, JID)
        self.assertEqual(row.text, OUTBOUND)
        self.assertEqual(row.client, self.client)
        self.assertEqual(row.mode, SendLog.SENT)


@override_settings(GOWA_DEVICE_B=DEVICE_B)
class CapTests(TestCase):
    """20 messages an hour, 60 a day, 2 s apart (PLAN §6.3, §5.5)."""

    def setUp(self):
        self.thread = Thread.objects.create(jid="5211@s.whatsapp.net")
        self.client = Client.objects.create(
            name="Juan Pérez", phone="+527712345678", jid=JID
        )

    def confirm(self):
        proposal = TOOLS["client_update"]["fn"](
            self.thread, client_id=self.client.pk, text=OUTBOUND
        )
        with mock.patch("apps.channel.gowa.send_text") as send:
            result = TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal["proposal_id"])
        return result, send

    def log_rows(self, count, *, mode=SendLog.SENT, minutes_ago=30):
        now = timezone.now()
        for index in range(count):
            row = SendLog.objects.create(
                client=self.client, jid=JID, text=f"previo {index}", mode=mode
            )
            SendLog.objects.filter(pk=row.pk).update(
                created_at=now - timedelta(minutes=minutes_ago)
            )

    def test_the_twenty_first_message_in_an_hour_is_refused_out_loud(self):
        self.log_rows(20)

        result, send = self.confirm()

        self.assertFalse(result["ok"])
        self.assertIn("20 mensajes en la última hora", result["text"])
        send.assert_not_called()
        self.assertEqual(SendLog.objects.filter(mode=SendLog.SENT).count(), 20)

    def test_nineteen_in_an_hour_still_goes(self):
        self.log_rows(19)

        result, send = self.confirm()

        self.assertTrue(result["ok"])
        send.assert_called_once()

    def test_messages_older_than_an_hour_do_not_count(self):
        self.log_rows(20, minutes_ago=120)

        result, send = self.confirm()

        self.assertTrue(result["ok"])
        send.assert_called_once()

    def test_the_sixty_first_message_of_the_day_is_refused(self):
        self.log_rows(60, minutes_ago=120)

        result, send = self.confirm()

        self.assertFalse(result["ok"])
        self.assertIn("60 mensajes hoy", result["text"])
        send.assert_not_called()

    def test_drafts_never_count_against_the_caps(self):
        self.log_rows(20, mode=SendLog.DRAFT)

        result, send = self.confirm()

        self.assertTrue(result["ok"])
        send.assert_called_once()

    def test_two_messages_are_two_seconds_apart(self):
        with mock.patch("apps.channel.gowa.send_text"), mock.patch(
            "apps.channel.limits.time.sleep"
        ) as sleep:
            result, _ = self.confirm()
            sleep.assert_not_called()
            second, _ = self.confirm()

        self.assertTrue(result["ok"])
        self.assertTrue(second["ok"])
        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args[0][0], 2, delta=1.5)

    def test_the_delay_is_skipped_when_the_last_send_is_old(self):
        self.log_rows(1, minutes_ago=5)
        self.log_rows(1, minutes_ago=120)

        with mock.patch("apps.channel.limits.time.sleep") as sleep:
            result, send = self.confirm()

        self.assertTrue(result["ok"])
        sleep.assert_not_called()
