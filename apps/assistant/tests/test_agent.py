import json
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.agenda.models import Appointment
from apps.assistant import agent, envelope
from apps.assistant.models import AuditLog, Message, Proposal, Thread


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


class ProposalTurnTests(TestCase):
    """One open proposal, and the lawyer's words decide it (PLAN.md §5.3)."""

    def setUp(self):
        self.thread = Thread.objects.create(jid="521771234567@s.whatsapp.net")
        self.inbound = Message.objects.create(
            thread=self.thread, role=Message.USER, text="sí", wamid="w-9"
        )
        self.proposal = envelope.propose(
            self.thread,
            steps=[
                {
                    "tool": "appointment_create",
                    "args": {"title": "Visita García", "starts_at": "2026-11-27T09:30"},
                }
            ],
            summary="Nueva cita: «Visita García»\n¿La agendo?",
        )

    @patch("apps.assistant.agent.llm.chat")
    def test_the_open_proposal_is_in_the_system_prompt(self, chat):
        chat.return_value = reply("Claro, ¿la agendo?")

        agent.run(self.thread, "¿qué hay mañana?", exclude_pk=self.inbound.pk)

        system = chat.call_args_list[0].args[0][0]["content"]
        self.assertIn(f"#{self.proposal.pk}", system)
        self.assertIn("¿La agendo?", system)

    @patch("apps.assistant.agent.llm.chat")
    def test_a_question_does_not_commit(self, chat):
        chat.return_value = reply("La muevo porque a las 17:00 choca con la junta.")

        agent.run(self.thread, "¿por qué la mueves?", exclude_pk=self.inbound.pk)

        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, Proposal.PROPOSED)
        self.assertEqual(Appointment.objects.count(), 0)

    @patch("apps.assistant.agent.llm.chat")
    def test_confirm_through_the_loop_applies_and_records_raw_words(self, chat):
        chat.side_effect = [
            reply(tool_calls=[call("confirm", json.dumps({"proposal_id": self.proposal.pk}))]),
            reply("Listo."),
        ]

        agent.run(self.thread, "sí, agéndala", exclude_pk=self.inbound.pk)

        audit = AuditLog.objects.get(tool="confirm")
        self.assertEqual(audit.raw_words, "sí, agéndala")
        self.assertTrue(audit.ok)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, Proposal.COMMITTED)
        self.assertEqual(Appointment.objects.get().title, "Visita García")

    @patch("apps.assistant.agent.llm.chat")
    def test_confirm_with_a_payload_from_the_model_is_refused(self, chat):
        chat.side_effect = [
            reply(
                tool_calls=[
                    call(
                        "confirm",
                        json.dumps(
                            {"proposal_id": self.proposal.pk, "title": "Otra cosa"}
                        ),
                    )
                ]
            ),
            reply("No puedo confirmar eso así."),
        ]

        agent.run(self.thread, "sí, pero cámbiale el título", exclude_pk=self.inbound.pk)

        self.assertEqual(Appointment.objects.count(), 0)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, Proposal.PROPOSED)
        self.assertFalse(AuditLog.objects.get().ok)


@override_settings(LLM_FALLBACK_MODEL="modelo-fuerte")
class FallbackRouterTests(TestCase):
    """PLAN.md §5.6: the stronger model answers exactly three cases."""

    def setUp(self):
        self.thread = Thread.objects.create(jid="521771234567@s.whatsapp.net")
        self.inbound = Message.objects.create(
            thread=self.thread, role=Message.USER, text="sí", wamid="w-10"
        )
        self.proposal = envelope.propose(
            self.thread,
            steps=[
                {
                    "tool": "appointment_create",
                    "args": {"title": "Visita García", "starts_at": "2026-11-27T09:30"},
                }
            ],
            summary="Nueva cita: «Visita García»\n¿La agendo?",
        )

    def _close_proposal(self):
        Proposal.objects.filter(pk=self.proposal.pk).update(status=Proposal.CANCELLED)

    @patch("apps.assistant.agent.llm.chat")
    def test_an_ignored_open_proposal_is_asked_again_on_the_stronger_model(self, chat):
        chat.side_effect = [
            reply("Claro, su cita es el viernes."),
            reply(
                tool_calls=[call("confirm", json.dumps({"proposal_id": self.proposal.pk}))],
                model="modelo-fuerte",
            ),
            reply("Listo.", model="modelo-fuerte"),
        ]

        agent.run(self.thread, "sí", exclude_pk=self.inbound.pk)

        self.assertEqual(chat.call_args_list[1].kwargs["model"], "modelo-fuerte")
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, Proposal.COMMITTED)

    @patch("apps.assistant.agent.llm.chat")
    def test_an_unknown_tool_escalates(self, chat):
        self._close_proposal()
        chat.side_effect = [
            reply(tool_calls=[call("delete_everything")]),
            reply(tool_calls=[call("agenda_today")], model="modelo-fuerte"),
            reply("Hoy no tiene nada.", model="modelo-fuerte"),
        ]

        text = agent.run(self.thread, "¿qué tengo hoy?", exclude_pk=self.inbound.pk)

        self.assertEqual(chat.call_args_list[1].kwargs["model"], "modelo-fuerte")
        self.assertEqual(text, "Hoy no tiene nada.")
        self.assertTrue(AuditLog.objects.get(tool="agenda_today").ok)

    @patch("apps.assistant.agent.llm.chat")
    def test_malformed_arguments_escalate(self, chat):
        self._close_proposal()
        chat.side_effect = [
            reply(tool_calls=[call("agenda_today", arguments="{no es json")]),
            reply(tool_calls=[call("agenda_today")], model="modelo-fuerte"),
            reply("Hoy no tiene nada.", model="modelo-fuerte"),
        ]

        agent.run(self.thread, "¿qué tengo hoy?", exclude_pk=self.inbound.pk)

        self.assertEqual(chat.call_args_list[1].kwargs["model"], "modelo-fuerte")

    @patch("apps.assistant.agent.llm.chat")
    def test_a_rejected_tool_argument_retries_on_the_stronger_model(self, chat):
        self._close_proposal()
        chat.side_effect = [
            reply(tool_calls=[call("reschedule", json.dumps({"appointment_id": 999999}))]),
            reply(tool_calls=[call("agenda_today")], model="modelo-fuerte"),
            reply("Hoy no tiene nada.", model="modelo-fuerte"),
        ]

        agent.run(self.thread, "mueve la cita al jueves", exclude_pk=self.inbound.pk)

        self.assertEqual(chat.call_args_list[1].kwargs["model"], "modelo-fuerte")

    @patch("apps.assistant.agent.llm.chat")
    def test_a_plain_question_without_a_proposal_stays_on_the_cheap_model(self, chat):
        self.proposal.status = Proposal.CANCELLED
        self.proposal.save(update_fields=["status"])
        chat.return_value = reply("Hoy no tiene nada.")

        agent.run(self.thread, "¿qué tengo hoy?", exclude_pk=self.inbound.pk)

        self.assertEqual(chat.call_count, 1)
        self.assertNotIn("model", chat.call_args_list[0].kwargs)
