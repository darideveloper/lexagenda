import datetime
import hashlib
import hmac
import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.agenda.models import Appointment
from apps.assistant.models import AuditLog, Job, Message, Thread

SECRET = "secreto-e2e"
DEVICE_A = "521771111111@s.whatsapp.net"
LAWYER_JID = "521771234567@s.whatsapp.net"
REPLY = "Hoy tiene una visita a las 09:30."


@override_settings(WEBHOOK_SECRET=SECRET, GOWA_DEVICE_A=DEVICE_A, LAWYER_JID=LAWYER_JID)
class WalkingSkeletonEndToEndTests(TestCase):
    """One WhatsApp text in, one agent reply out, through every real join."""

    def signed_post(self, event):
        body = json.dumps(event).encode()
        signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(
            reverse("gowa_webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256=signature,
        )

    @patch("apps.assistant.worker.send_text")
    @patch("apps.assistant.agent.llm.chat")
    def test_hola_in_one_reply_out(self, chat, send):
        today = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        Appointment.objects.create(
            title="Visita García", starts_at=today + datetime.timedelta(hours=9, minutes=30)
        )
        event = {
            "event": "message",
            "device_id": DEVICE_A,
            "payload": {
                "id": "wamid-e2e-1",
                "chat_id": LAWYER_JID,
                "from": LAWYER_JID,
                "timestamp": "2026-11-26T09:00:00Z",
                "is_from_me": False,
                "body": "¿qué tengo hoy?",
            },
        }
        chat.side_effect = [
            {
                "text": "",
                "tool_calls": [
                    {"id": "call-1", "function": {"name": "agenda_today", "arguments": "{}"}}
                ],
                "model": "stub-model",
                "tokens_in": 11,
                "tokens_out": 7,
            },
            {"text": REPLY, "tool_calls": [], "model": "stub-model", "tokens_in": 20, "tokens_out": 9},
        ]

        response = self.signed_post(event)
        self.assertEqual(response.status_code, 200)
        inbound = Message.objects.get(wamid="wamid-e2e-1")
        self.assertIsNone(inbound.replied_at)
        self.assertEqual(Job.objects.get().payload, {"message_id": inbound.pk})

        # The stub calls agenda_today for real, so the tool row carries today's appointment.
        call_command("work", stdout=StringIO())

        first_call = chat.call_args_list[0].kwargs
        self.assertEqual(
            [schema["function"]["name"] for schema in first_call["tools"]],
            [
                "agenda_today",
                "case_search",
                "case_summary",
                "document_search",
                "day_simulation",
                "find_free_slot",
                "llegada",
                "appointment_create",
                "reschedule",
                "deadline_create",
                "file_document",
                "confirm",
                "cancel",
                "undo",
            ],
        )
        inbound.refresh_from_db()
        self.assertIsNotNone(inbound.replied_at)
        self.assertEqual(Job.objects.get().status, Job.DONE)
        audit = AuditLog.objects.get()
        self.assertEqual(audit.tool, "agenda_today")
        self.assertTrue(audit.ok)
        self.assertEqual(audit.result["appointments"][0]["title"], "Visita García")
        self.assertEqual(Message.objects.get(role=Message.ASSISTANT).text, REPLY)
        send.assert_called_once_with(Thread.objects.get().jid, REPLY)
