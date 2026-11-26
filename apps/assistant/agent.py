"""The tool loop (PLAN.md §5.1): reads read, nothing mutates, every call is audited."""

import json
import time

from django.utils import timezone

from apps.assistant.models import AuditLog, Message
from apps.assistant.tools import TOOLS, schemas
from apps.integrations import llm

MAX_STEPS = 4
FALLBACK = "No he podido terminar con esto, lo reviso yo."
SYSTEM_PROMPT = """Eres el asistente de agenda de un abogado en Hidalgo, México.
Hoy es {today} ({weekday}) en America/Mexico_City.
Respondes en español, de usted, breve, como por WhatsApp: sin tablas ni markdown.
Solo puedes consultar datos con las herramientas; no inventes citas, clientes, direcciones ni fechas.
Si una herramienta no responde, dilo y ofrece revisarlo; nunca supongas el dato."""


def system_prompt():
    today = timezone.localtime()
    return SYSTEM_PROMPT.format(
        today=today.strftime("%Y-%m-%d"), weekday=today.strftime("%A")
    )


def history(thread, exclude_pk=None):
    messages = thread.messages.filter(role__in=[Message.USER, Message.ASSISTANT]).order_by(
        "-created_at"
    )[:20]
    messages = list(messages)[::-1]
    return [
        {"role": message.role, "content": message.text}
        for message in messages
        if message.pk != exclude_pk
    ]


def run(thread, user_text, *, exclude_pk=None):
    messages = (
        [{"role": "system", "content": system_prompt()}]
        + history(thread, exclude_pk=exclude_pk)
        + [{"role": "user", "content": user_text}]
    )
    for _ in range(MAX_STEPS):
        reply = llm.chat(messages, tools=schemas())
        if not reply["tool_calls"]:
            return _save_reply(thread, reply)

        messages.append(
            {
                "role": "assistant",
                "content": reply["text"],
                "tool_calls": reply["tool_calls"],
            }
        )
        for call in reply["tool_calls"]:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except ValueError:
                args = {}
            started = time.monotonic()
            tool = TOOLS.get(name)
            try:
                result = tool["fn"](thread, **args) if tool else {"error": f"herramienta desconocida: {name}"}
            except Exception as exc:  # a bad argument must not kill the reply
                result = {"error": f"{type(exc).__name__}: {exc}"}
            AuditLog.objects.create(
                thread=thread,
                tool=name,
                args=args,
                result=result,
                model=reply["model"],
                latency_ms=int((time.monotonic() - started) * 1000),
                ok=tool is not None and "error" not in result,
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    _save_reply(thread, {"text": FALLBACK, "tokens_in": 0, "tokens_out": 0})
    return FALLBACK


def _save_reply(thread, reply):
    Message.objects.create(
        thread=thread,
        role=Message.ASSISTANT,
        text=reply["text"],
        tokens_in=reply.get("tokens_in", 0),
        tokens_out=reply.get("tokens_out", 0),
    )
    return reply["text"]
