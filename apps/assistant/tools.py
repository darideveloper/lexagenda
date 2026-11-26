"""Read tools the model may call. `fn(thread, **args)` returns compact JSON (PLAN.md §3.2)."""

import datetime
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.agenda import day as simulation
from apps.agenda.models import Appointment
from apps.core.models import Case, Client


def agenda_today(thread):
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = Appointment.objects.filter(
        starts_at__gte=start, starts_at__lt=start + timedelta(days=1)
    ).select_related("client")
    return {
        "date": start.date().isoformat(),
        "count": len(rows),
        "appointments": [
            {
                "id": appt.pk,
                "time": timezone.localtime(appt.starts_at).strftime("%H:%M"),
                "kind": appt.kind,
                "title": appt.title,
                "location": appt.location_name or None,
                "client": appt.client.name if appt.client else None,
            }
            for appt in rows
        ],
    }


def case_search(thread, query):
    clients = Client.objects.filter(is_active=True, name__icontains=query).order_by("name")[:5]
    cases = Case.objects.filter(
        Q(reference__icontains=query) | Q(title__icontains=query)
    ).order_by("reference")[:5]
    return {
        "clients": [{"id": client.pk, "name": client.name, "phone": client.phone} for client in clients],
        "cases": [
            {
                "id": case.pk,
                "reference": case.reference,
                "title": case.title,
                "status": case.status,
            }
            for case in cases
        ],
    }


def case_summary(thread, case_id):
    try:
        case = Case.objects.select_related("client").get(pk=case_id)
    except Case.DoesNotExist:
        return {"error": f"no existe el expediente {case_id}"}
    upcoming = case.appointments.filter(
        starts_at__gte=timezone.now(), status=Appointment.PLANNED
    ).first()
    return {
        "case_id": case.pk,
        "reference": case.reference,
        "title": case.title,
        "court": case.court or None,
        "status": case.status,
        "opened_on": case.opened_on.isoformat(),
        "client": {"id": case.client.pk, "name": case.client.name, "phone": case.client.phone},
        "next_appointment": (
            {
                "id": upcoming.pk,
                "starts_at": timezone.localtime(upcoming.starts_at).isoformat(),
                "title": upcoming.title,
            }
            if upcoming
            else None
        ),
    }


def day_simulation(thread, date=None):
    """The §8.2 walk for one day: departures, lateness, first three conflicts."""
    when = parse_date(date) if date else None
    return simulation.simulate(when)


def find_free_slot(thread, duration, after, before):
    """The first three gaps of `duration` minutes that fit between after and before."""
    start = _moment(after)
    limit = _moment(before)
    if start is None or limit is None:
        return {"error": "after y before deben ser fechas ISO"}
    slots = simulation.find_free_slot(duration, start, limit)
    return {"duration": duration, "slots": [_clock(slot) for slot in slots]}


def llegada(thread, appointment_id, date=None):
    """¿Llego? — the lateness of one stop and up to three slots where it would fit."""
    when = parse_date(date) if date else None
    return simulation.llegada(appointment_id, when)


def _moment(value):
    moment = parse_datetime(value) if value else None
    if moment is not None and timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    return moment


def _clock(moment):
    return timezone.localtime(moment).strftime("%H:%M")


TOOLS = {
    "agenda_today": {
        "fn": agenda_today,
        "description": "Los compromisos de hoy, con hora, lugar y cliente.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "case_search": {
        "fn": case_search,
        "description": "Busca clientes y expedientes por nombre, referencia o título.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "case_summary": {
        "fn": case_summary,
        "description": "Resumen de un expediente: cliente, estado y próxima cita.",
        "parameters": {
            "type": "object",
            "properties": {"case_id": {"type": "integer"}},
            "required": ["case_id"],
            "additionalProperties": False,
        },
    },
    "day_simulation": {
        "fn": day_simulation,
        "description": "El día simulado: hora de salida de cada cita, traslados y choques.",
        "parameters": {
            "type": "object",
            "properties": {"date": {"type": "string", "description": "YYYY-MM-DD; hoy por defecto"}},
            "additionalProperties": False,
        },
    },
    "find_free_slot": {
        "fn": find_free_slot,
        "description": "Los primeros huecos libres de una duración, entre dos fechas ISO.",
        "parameters": {
            "type": "object",
            "properties": {
                "duration": {"type": "integer"},
                "after": {"type": "string"},
                "before": {"type": "string"},
            },
            "required": ["duration", "after", "before"],
            "additionalProperties": False,
        },
    },
    "llegada": {
        "fn": llegada,
        "description": "¿Llego? Minutos de retraso de una cita y hasta tres horarios donde cabe.",
        "parameters": {
            "type": "object",
            "properties": {
                "appointment_id": {"type": "integer"},
                "date": {"type": "string", "description": "YYYY-MM-DD; hoy por defecto"},
            },
            "required": ["appointment_id"],
            "additionalProperties": False,
        },
    },
}


def schemas():
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": tool["description"],
                "parameters": tool["parameters"],
            },
        }
        for name, tool in TOOLS.items()
    ]
