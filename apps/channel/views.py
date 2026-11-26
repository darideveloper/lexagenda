import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.assistant.models import Job, Message, Thread
from apps.docs import ingest

from .signature import verify

logger = logging.getLogger(__name__)

MEDIA_KEYS = ("audio", "image", "document", "video", "sticker", "location", "contacts")


def _ok(status):
    # Every answer is 200: a non-200 makes gowa retry and duplicate the conversation.
    return JsonResponse({"status": status})


@csrf_exempt
@require_POST
def gowa_webhook(request):
    try:
        return _handle(request)
    except Exception:
        logger.exception("gowa webhook failed")
        return _ok("error")


def _handle(request):
    body = request.body
    if not verify(settings.WEBHOOK_SECRET, body, request.headers.get("X-Hub-Signature-256")):
        return _ok("bad signature")

    try:
        event = json.loads(body)
    except ValueError:
        return _ok("bad json")
    if not isinstance(event, dict):
        return _ok("bad json")

    message = _lawyer_text(event)
    if message is None:
        media = _lawyer_media(event)
        if media is None:
            return _ok("ignored")
        return _queue_media(event, media)
    device_id, wamid, jid, text = message

    if device_id != settings.GOWA_DEVICE_A:
        return _ok("device ignored")
    if Message.objects.filter(wamid=wamid).exists():
        return _ok("duplicate")
    if jid != settings.LAWYER_JID:
        return _ok("foreign jid")

    thread, _ = Thread.objects.get_or_create(channel="control", jid=jid)
    stored, created = Message.objects.get_or_create(
        wamid=wamid,
        defaults={"thread": thread, "role": Message.USER, "text": text, "raw": event},
    )
    if not created:
        return _ok("duplicate")

    Job.objects.create(kind=Job.INBOUND, payload={"message_id": stored.pk})
    thread.last_activity_at = timezone.now()
    thread.save(update_fields=["last_activity_at"])
    return _ok("queued")


def _lawyer_text(event):
    """gowa v9 envelope to (device_id, wamid, jid, text), or None when it is not a 1:1 text."""
    if event.get("event") != "message":
        return None
    data = event.get("payload")
    if not isinstance(data, dict) or data.get("is_from_me"):
        return None
    chat_id = data.get("chat_id", "")
    if chat_id.endswith("@g.us") or chat_id == "status@broadcast":
        return None
    if any(key in data for key in MEDIA_KEYS):
        return None
    wamid = data.get("id")
    if not wamid:
        return None
    return event.get("device_id", ""), wamid, data.get("from", ""), data.get("body", "")


def _lawyer_media(event):
    """gowa v9 envelope to (device, wamid, jid, kind, ref, mime, filename), or None."""
    if event.get("event") != "message":
        return None
    data = event.get("payload")
    if not isinstance(data, dict) or data.get("is_from_me"):
        return None
    chat_id = data.get("chat_id", "")
    if chat_id.endswith("@g.us") or chat_id == "status@broadcast":
        return None
    wamid = data.get("id")
    if not wamid:
        return None
    for kind in ("document", "image"):
        ref = data.get(kind)
        if ref:
            return (
                event.get("device_id", ""),
                wamid,
                data.get("from", ""),
                kind,
                ref,
                data.get("mimetype") or data.get("mime_type") or "",
                data.get("filename") or "",
            )
    return None


def _queue_media(event, media):
    device_id, wamid, jid, kind, ref, mime, filename = media
    if device_id != settings.GOWA_DEVICE_A:
        return _ok("device ignored")
    if Message.objects.filter(wamid=wamid).exists():
        return _ok("duplicate")
    if jid != settings.LAWYER_JID:
        return _ok("foreign jid")

    thread, _ = Thread.objects.get_or_create(channel="control", jid=jid)
    stored, created = Message.objects.get_or_create(
        wamid=wamid,
        defaults={"thread": thread, "role": Message.USER, "text": "", "raw": event},
    )
    if not created:
        return _ok("duplicate")
    try:
        attachment = ingest.ingest_from_gowa(wamid, ref, mime=mime, filename=filename)
    except ingest.TooLarge:
        logger.info("gowa media over 25 MB refused: %s", wamid)
        return _ok("file too large")

    Job.objects.create(
        kind=Job.INBOUND,
        payload={"message_id": stored.pk, "media_id": attachment.pk, "kind": kind},
    )
    thread.last_activity_at = timezone.now()
    thread.save(update_fields=["last_activity_at"])
    return _ok("queued")
