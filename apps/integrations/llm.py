"""One OpenAI-compatible client pointed at OpenRouter, so the model is an env var (D8)."""

import json
import urllib.request

from django.conf import settings


class LLMError(RuntimeError):
    pass


def chat(messages, tools=None, model=None):
    if not settings.LLM_API_KEY:
        raise LLMError("LLM_API_KEY is not set")
    payload = {"model": model or settings.LLM_MODEL, "messages": messages}
    if tools:
        payload["tools"] = tools

    request = urllib.request.Request(
        settings.LLM_BASE_URL.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.LLM_API_KEY}",
            "HTTP-Referer": settings.LLM_REFERER,
            "X-Title": settings.LLM_TITLE,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
    except OSError as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc

    message = data["choices"][0]["message"]
    usage = data.get("usage") or {}
    return {
        "text": message.get("content") or "",
        "tool_calls": message.get("tool_calls") or [],
        "model": data.get("model") or payload["model"],
        "tokens_in": usage.get("prompt_tokens", 0),
        "tokens_out": usage.get("completion_tokens", 0),
    }
