import base64
import json
import urllib.request

from django.conf import settings


class SendError(RuntimeError):
    pass


def send_text(jid, text, device=None):
    """Send one plain message through gowa; device A is the control session."""
    headers = {"Content-Type": "application/json"}
    if settings.GOWA_BASIC_AUTH:
        token = base64.b64encode(settings.GOWA_BASIC_AUTH.encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    device = device or settings.GOWA_DEVICE_A
    if device:
        headers["X-Device-Id"] = device

    request = urllib.request.Request(
        settings.GOWA_URL.rstrip("/") + "/send/message",
        data=json.dumps({"phone": jid, "message": text}).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            json.load(response)
    except OSError as exc:
        raise SendError(f"gowa send failed: {exc}") from exc
    return True
