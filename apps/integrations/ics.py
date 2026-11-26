"""iCalendar (RFC 5545): the three event shapes PLAN §7.2 defines.

A subscriber's client shows the calendar; the invite is the instant signal. Both read
the same events from here, so a moved visit can never disagree with its feed entry.
"""

import datetime
import os
import secrets

from django.conf import settings
from django.http import Http404, HttpResponse
from django.utils import timezone

from apps.agenda.models import Appointment, Deadline, TravelBlock

PRODID = "-//lexagenda//calendario//ES"
CRLF = "\r\n"
MAX_OCTETS = 75


def escape(value):
    """RFC 5545 §3.3.11: the four characters a TEXT value cannot carry raw."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def fold(line):
    """One logical line, cut to 75 octets and continued with CRLF + space (never mid-character)."""
    raw = line.encode("utf-8")
    if len(raw) <= MAX_OCTETS:
        return line
    chunks, limit = [], MAX_OCTETS
    while len(raw) > limit:
        cut = limit
        while raw[cut] & 0xC0 == 0x80:  # a continuation byte belongs to the character before it
            cut -= 1
        chunks.append(raw[:cut])
        raw = raw[cut:]
        limit = MAX_OCTETS - 1  # every continuation carries the leading space
    chunks.append(raw)
    return (CRLF + " ").join(chunk.decode("utf-8") for chunk in chunks)


def calendar(events, method="PUBLISH", name=""):
    """A VCALENDAR holding the given events, every physical line CRLF-terminated."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        f"METHOD:{method}",
    ]
    if name:
        lines.append(f"X-WR-CALNAME:{escape(name)}")
    for event in events:
        lines.extend(event)
    lines.append("END:VCALENDAR")
    return "".join(fold(line) + CRLF for line in lines)


def appointment_event(appointment):
    """Timed, opaque: the visit itself, with the client and the expediente in its description."""
    parts = []
    if appointment.client_id:
        parts.append(f"Cliente: {appointment.client.name}")
    if appointment.case_id:
        parts.append(f"Expediente: {appointment.case.reference}")
    end = appointment.starts_at + datetime.timedelta(minutes=appointment.duration_min)
    return [
        "BEGIN:VEVENT",
        f"UID:{appointment.ics_uid}",
        f"DTSTAMP:{_utc(timezone.now())}",
        f"SEQUENCE:{appointment.ics_sequence}",
        f"SUMMARY:{escape(appointment.title)}",
        f"DTSTART:{_utc(appointment.starts_at)}",
        f"DTEND:{_utc(end)}",
        f"LOCATION:{escape(appointment.address or appointment.location_name)}",
        f"DESCRIPTION:{escape(chr(10).join(parts))}",
        "STATUS:" + ("CANCELLED" if appointment.status == "cancelled" else "CONFIRMED"),
        "TRANSP:OPAQUE",
        "END:VEVENT",
    ]


def travel_event(block):
    """Timed, transparent: the drive must not make the lawyer look busy."""
    uid = f"{block.appointment.ics_uid}-traslado"
    end = block.starts_at + datetime.timedelta(minutes=block.duration_min)
    return [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_utc(timezone.now())}",
        "SEQUENCE:0",
        f"SUMMARY:{escape('Traslado → ' + block.destination)}",
        f"DTSTART:{_utc(block.starts_at)}",
        f"DTEND:{_utc(end)}",
        f"LOCATION:{escape(block.destination)}",
        f"DESCRIPTION:{escape('Salida: ' + (block.origin or '—'))}",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ]


def deadline_event(deadline):
    """All-day, with one display alarm per reminder day and the computed-date badge."""
    description = f"Expediente: {deadline.case.reference}"
    if deadline.computed:
        description += "\ncalculado — verifica"
    lines = [
        "BEGIN:VEVENT",
        f"UID:plazo-{deadline.pk}@lexagenda",
        f"DTSTAMP:{_utc(timezone.now())}",
        "SEQUENCE:0",
        f"SUMMARY:{escape(deadline.title)}",
        f"DTSTART;VALUE=DATE:{deadline.due_date:%Y%m%d}",
        f"DTEND;VALUE=DATE:{deadline.due_date + datetime.timedelta(days=1):%Y%m%d}",
        f"DESCRIPTION:{escape(description)}",
        "TRANSP:TRANSPARENT",
    ]
    for days in deadline.reminder_days:
        lines.extend(
            [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{escape(deadline.title)}",
                f"TRIGGER:-P{int(days)}D",
                "END:VALARM",
            ]
        )
    lines.append("END:VEVENT")
    return lines


def feed(request, token):
    """The subscriber's snapshot: no session, one shared secret, never indexed."""
    expected = _token()
    if not expected or not secrets.compare_digest(token, expected):
        raise Http404("calendario")
    response = HttpResponse(
        calendar(
            feed_events(),
            name=settings.CONFIG["name"],
        ),
        content_type="text/calendar; charset=utf-8",
    )
    response["X-Robots-Tag"] = "noindex"
    return response


def _token():
    """Read per request: rotating ICS_TOKEN retires the old URL at once, with no deploy."""
    return os.environ.get("ICS_TOKEN", "")


def feed_events():
    """Appointments, their travel blocks and open deadlines — the dashboard's own rows."""
    appointments = list(
        Appointment.objects.exclude(status=Appointment.CANCELLED).select_related("client", "case")
    )
    events = [appointment_event(appointment) for appointment in appointments]
    for block in TravelBlock.objects.filter(appointment__in=appointments).select_related(
        "appointment"
    ):
        events.append(travel_event(block))
    for deadline in Deadline.objects.exclude(status=Deadline.DONE).select_related("case"):
        events.append(deadline_event(deadline))
    return events


def _utc(moment):
    return moment.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
