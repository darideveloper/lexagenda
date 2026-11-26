"""Read tools the model may call. `fn(thread, **args)` returns compact JSON (PLAN.md §3.2)."""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

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
