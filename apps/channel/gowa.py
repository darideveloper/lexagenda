"""Delivery on session B: the lawyer's own number, the stored bytes, the book only (PLAN §6.3).

Session A talks to the lawyer; this module is the only path that writes to a client.
"""

from django.conf import settings

from apps.channel import limits
from apps.channel.models import SendLog
from apps.channel.send import SendError, delivery_mode, send_text
from apps.core.models import Client


class DeliveryRefused(RuntimeError):
    """The send was refused before it reached gowa; the sentence is what the lawyer reads."""


def deliver(proposal, jid):
    """Send `proposal.outbound_text` to one book-only JID. Returns (result, undo, text)."""
    text = proposal.outbound_text
    if not text:
        raise DeliveryRefused("esa propuesta no trae el texto que te mostré")
    target = (jid or "").strip()
    client = Client.objects.filter(jid=target, is_active=True).first() if target else None
    if client is None:
        raise DeliveryRefused("ese número no está en la agenda; no mando a quien no conozco")

    if delivery_mode() == "draft":
        # No message leaves: the lawyer forwards it from his phone.
        SendLog.objects.create(client=client, jid=target, text=text, mode=SendLog.DRAFT)
        return (
            {"draft": target},
            [],
            f"Borrador para «{client.name}», reenvíalo tú:\n{text}",
        )

    try:
        limits.guard()
    except limits.Refused as exc:
        raise DeliveryRefused(str(exc)) from exc
    limits.wait()

    try:
        send_text(target, text, device=settings.GOWA_DEVICE_B)
    except SendError as exc:
        raise DeliveryRefused("WhatsApp no aceptó el envío; no se mandó nada") from exc
    SendLog.objects.create(client=client, jid=target, text=text, mode=SendLog.SENT)
    # A sent message cannot be unsent: undo offers a correction, never a delete.
    return {"sent": target}, [], f"Listo: se lo mandé a «{client.name}»."
