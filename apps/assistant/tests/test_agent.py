from unittest.mock import patch

from django.test import TestCase

from apps.assistant import agent
from apps.assistant.models import AuditLog, Message, Thread


def reply(text="", tool_calls=None, model="test-model", tokens_in=3, tokens_out=4):
    return {
        "text": text,
        "tool_calls": tool_calls or [],
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }


def call(name, arguments="{}", call_id="call-1"):
    return {"id": call_id, "function": {"name": name, "arguments": arguments}}


class AgentTests(TestCase):
    def setUp(self):
        self.thread = Thread.objects.create(jid="521771234567@s.whatsapp.net")
        self.inbound = Message.objects.create(
            thread=self.thread, role=Message.USER, text="hola", wamid="w-1"
        )

    @patch("apps.assistant.agent.llm.chat")
    def test_plain_reply_is_persisted_once(self, chat):
        chat.return_value = reply("Buen día, no tiene compromisos hoy.")

        text = agent.run(self.thread, "hola", exclude_pk=self.inbound.pk)

        self.assertEqual(text, "Buen día, no tiene compromisos hoy.")
        stored = Message.objects.get(role=Message.ASSISTANT)
        self.assertEqual(stored.text, text)
        self.assertEqual(stored.tokens_out, 4)
        self.assertEqual(AuditLog.objects.count(), 0)

    @patch("apps.assistant.agent.llm.chat")
    def test_tool_call_is_audited_and_answered(self, chat):
        chat.side_effect = [
            reply(tool_calls=[call("agenda_today")]),
            reply("Hoy no tiene nada."),
        ]

        text = agent.run(self.thread, "hola", exclude_pk=self.inbound.pk)

        self.assertEqual(text, "Hoy no tiene nada.")
        audit = AuditLog.objects.get()
        self.assertEqual(audit.tool, "agenda_today")
        self.assertTrue(audit.ok)
        self.assertEqual(audit.result["count"], 0)

    @patch("apps.assistant.agent.llm.chat")
    def test_unknown_tool_is_audited_not_fatal(self, chat):
        chat.side_effect = [
            reply(tool_calls=[call("delete_everything")]),
            reply("No puedo hacer eso."),
        ]

        text = agent.run(self.thread, "hola", exclude_pk=self.inbound.pk)

        self.assertEqual(text, "No puedo hacer eso.")
        self.assertFalse(AuditLog.objects.get().ok)

    @patch("apps.assistant.agent.llm.chat")
    def test_loop_is_capped_at_four_steps(self, chat):
        chat.side_effect = lambda *args, **kwargs: reply(tool_calls=[call("agenda_today")])

        text = agent.run(self.thread, "hola", exclude_pk=self.inbound.pk)

        self.assertEqual(text, agent.FALLBACK)
        self.assertEqual(chat.call_count, agent.MAX_STEPS)
        self.assertEqual(AuditLog.objects.count(), agent.MAX_STEPS)
