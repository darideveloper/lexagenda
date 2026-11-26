"""The delivery caps (PLAN §6.3): 20 an hour, 60 a day, 2 s apart.

These are not politeness — they are what keeps a companion device from looking like a
spam account, which is what gets the lawyer's number banned. A cap that refuses always
says why, in Spanish, so the lawyer knows what happened and what to do.
"""

import time
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.channel.models import SendLog


class Refused(RuntimeError):
    """The caps do not allow this send; the sentence is what the lawyer reads."""


def caps():
    raw = settings.CONFIG.get("caps") or {}
    return (
        int(raw.get("hourly", 20)),
        int(raw.get("daily", 60)),
        int(raw.get("delay_seconds", 2)),
    )


def sent_since(moment):
    return SendLog.objects.filter(mode=SendLog.SENT, created_at__gte=moment).count()


def guard(now=None):
    """Refuse the send the caps do not allow, before anything reaches gowa."""
    hourly, daily, _ = caps()
    now = now or timezone.now()
    if sent_since(now - timedelta(hours=1)) >= hourly:
        raise Refused(
            f"ya mandé {hourly} mensajes en la última hora; espera un rato y te lo reenvío"
        )
    if sent_since(now - timedelta(days=1)) >= daily:
        raise Refused(f"ya van {daily} mensajes hoy; mañana sigo, o lo reenvías tú")


def wait():
    """Hold the 2 s between messages, minus whatever already passed."""
    _, _, delay = caps()
    if delay <= 0:
        return
    last = SendLog.objects.filter(mode=SendLog.SENT).order_by("-created_at").first()
    if last is None:
        return
    pause = delay - (timezone.now() - last.created_at).total_seconds()
    if pause > 0:
        time.sleep(pause)
