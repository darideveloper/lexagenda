"""The instant signal: one iCalendar REQUEST per change, mailed to the lawyer only (PLAN §7.1).

Client recipients are out of scope for v0.1: the feed is the view, this is the nudge.
"""

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils import timezone

from apps.agenda.models import Appointment
from apps.integrations import ics


def invite(appointment):
    """Mail the appointment's current state; silence when there is no lawyer address."""
    lawyer = User.objects.filter(username=settings.LAWYER_USERNAME).first()
    if lawyer is None or not lawyer.email:
        return False
    cancelled = appointment.status == Appointment.CANCELLED
    method = "CANCEL" if cancelled else "REQUEST"
    message = EmailMessage(
        subject=f"{'Cancelada' if cancelled else 'Cita'}: {appointment.title}",
        body=render_to_string(
            "email/ics_cancel.txt" if cancelled else "email/ics_invite.txt",
            {
                "appointment": appointment,
                "starts_at": timezone.localtime(appointment.starts_at),
            },
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[lawyer.email],
    )
    message.attach(
        f"{appointment.ics_uid}.ics",
        ics.calendar([ics.appointment_event(appointment)], method=method),
        f"text/calendar; charset=utf-8; method={method}",
    )
    try:
        message.send()
    except Exception:  # a dead SMTP must never undo a confirmed appointment
        return False
    return True
