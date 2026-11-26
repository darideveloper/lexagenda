import json
import logging
import re

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.assistant.models import Job, Message, Thread
from apps.assistant.tools import client_create_from_contact
from apps.channel.send import SendError, send_text
from apps.docs import ingest

from .signature import verify

logger = logging.getLogger(__name__)

MEDIA_KEYS = ("audio", "image", "document", "video", "sticker", "location", "contacts")
VCARD_NAME = re.compile(r"^FN:(.+)$", re.MULTILINE)
VCARD_WAID = re.compile(r"waid=(\d+)")
VCARD_TEL = re.compile(r"^TEL[^:]*:(.+)$", re.MULTILINE)


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

    card = _contact_card(event)
    if card is not None:
        return _handle_contact(event, card)

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


def _contact_card(event):
    """(name, phone) from a forwarded contact card, or None when the event is not one.

    gowa sends the card as a vcard under `contacts`; the normalised contract (PLAN §6.2)
    carries `contact_name` and `contact_phone` instead. Both land on the same card.
    """
    if event.get("event") != "message":
        return None
    data = event.get("payload")
    if not isinstance(data, dict) or data.get("is_from_me"):
        return None
    name = " ".join(str(data.get("contact_name") or "").split())
    phone = "".join(ch for ch in str(data.get("contact_phone") or "") if ch.isdigit())
    if name and phone:
        return name, phone
    cards = data.get("contacts")
    if not isinstance(cards, list) or not cards or not isinstance(cards[0], dict):
        return None
    vcard = str(cards[0].get("vcard") or "")
    waid = VCARD_WAID.search(vcard)
    tel = VCARD_TEL.search(vcard)
    phone = waid.group(1) if waid else "".join(
        ch for ch in (tel.group(1) if tel else "") if ch.isdigit()
    )
    label = VCARD_NAME.search(vcard)
    name = " ".join(str(label.group(1) if label else cards[0].get("displayName") or "").split())
    if not phone:
        return None
    return name, phone


def _handle_contact(event, card):
    """The card is a write the lawyer already made by forwarding: propose it and answer."""
    data = event["payload"]
    if event.get("device_id", "") != settings.GOWA_DEVICE_A:
        return _ok("device ignored")
    wamid = data.get("id")
    if not wamid:
        return _ok("ignored")
    if Message.objects.filter(wamid=wamid).exists():
        return _ok("duplicate")
    if data.get("from", "") != settings.LAWYER_JID:
        return _ok("foreign jid")

    thread, _ = Thread.objects.get_or_create(channel="control", jid=settings.LAWYER_JID)
    name, phone = card
    Message.objects.create(
        thread=thread,
        role=Message.USER,
        text=f"Contacto: {name} — {phone}",
        wamid=wamid,
        raw=event,
    )
    result = client_create_from_contact(thread, name=name, phone=phone)
    _say(thread, result.get("summary") or result.get("error") or "No pude leer la tarjeta.")
    thread.last_activity_at = timezone.now()
    thread.save(update_fields=["last_activity_at"])
    return _ok("contact")


def _say(thread, text):
    """Answer on session A; a gowa failure is logged, never a non-200 (webhook contract)."""
    Message.objects.create(thread=thread, role=Message.ASSISTANT, text=text)
    try:
        send_text(settings.LAWYER_JID, text)
    except SendError:
        logger.exception("gowa could not deliver the contact-card answer")
