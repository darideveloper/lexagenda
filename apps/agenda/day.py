"""The day simulation: sequential, deterministic, never rewrites the day (PLAN §8.2)."""

import datetime

from django.utils import timezone

from apps.agenda.models import Appointment, TravelBlock
from apps.core.models import BaseLocation
from apps.integrations import maps

SLOT_MINUTES = 5
MAX_FIXES = 3
MAX_CONFLICTS = 3


def find_free_slot(duration_min, after, before, exclude=()):
    """The first free starts of `duration_min`, rounded up to 5 min, never past `before`."""
    duration = _minutes(duration_min)
    busy = _busy(after, before, exclude)
    slots = []
    candidate = _round_up(after)
    while len(slots) < MAX_FIXES and candidate + duration <= before:
        end = candidate + duration
        clash = next(
            ((start, stop) for start, stop in busy if candidate < stop and end > start), None
        )
        if clash is None:
            slots.append(candidate)
            candidate = _round_up(end + _minutes(SLOT_MINUTES))
        else:
            candidate = _round_up(max(candidate, clash[1]))
    return slots


def llegada(appointment_id, day=None):
    """¿Llego? — the lateness of one stop and up to three slots where it would fit."""
    simulation = simulate(day)
    stop = next((item for item in simulation["stops"] if item["id"] == appointment_id), None)
    if stop is None:
        return {"error": f"no hay cita {appointment_id} ese día"}
    answer = {
        "id": stop["id"],
        "title": stop["title"],
        "at": stop["at"],
        "late_by": stop["late_by"],
        "cause": stop.get("cause"),
        "fixes": [],
    }
    if stop["late_by"] > 0:
        appt = Appointment.objects.get(pk=appointment_id)
        clears = appt.starts_at + _minutes(stop["late_by"])
        answer["fixes"] = [
            _hhmm(slot)
            for slot in find_free_slot(
                appt.duration_min, clears, _bounds(day)[1], exclude=[appt.pk]
            )
        ]
    return answer


def _busy(after, before, exclude):
    rows = Appointment.objects.filter(
        status=Appointment.PLANNED,
        starts_at__lt=before,
        starts_at__gte=after - datetime.timedelta(hours=12),
    ).exclude(pk__in=list(exclude))
    return [
        (row.starts_at, row.starts_at + _minutes(row.duration_min + row.buffer_min))
        for row in rows
    ]


def _round_up(moment):
    floor = moment.replace(
        minute=moment.minute - moment.minute % SLOT_MINUTES, second=0, microsecond=0
    )
    if floor == moment:
        return floor
    return floor + _minutes(SLOT_MINUTES)


def simulate(day=None):
    """Walk the day from the base location and persist one TravelBlock per computed leg."""
    start, end = _bounds(day)
    appointments = list(
        Appointment.objects.filter(
            status=Appointment.PLANNED, starts_at__gte=start, starts_at__lt=end
        ).order_by("starts_at")
    )
    base = BaseLocation.objects.filter(is_default=True).first() or BaseLocation.objects.first()
    origin = base.address if base else ""

    stops, conflicts, legs = [], [], []
    cursor = None
    previous = None
    degraded = False

    for appt in appointments:
        destination = appt.address.strip()
        missing_address = not destination
        travel_min, summary = 0, {}
        leg_degraded = False
        if not missing_address and origin:
            slot = cursor if cursor is not None else appt.starts_at - _minutes(appt.buffer_min)
            leg = maps.route(origin, destination, slot)
            if leg is None:
                degraded = leg_degraded = True
            else:
                travel_min = max(0, round(leg["duration_in_traffic_s"] / 60))
                summary = leg
                legs.append((appt, origin, destination, travel_min, summary))
        elif destination and not origin:
            degraded = leg_degraded = True

        depart = appt.starts_at - _minutes(travel_min + appt.buffer_min)
        if cursor is not None and depart < cursor:
            depart = cursor
        ready = depart + _minutes(travel_min + appt.buffer_min)
        late_by = max(0, int((ready - appt.starts_at).total_seconds() // 60))

        stops.append(
            {
                "id": appt.pk,
                "title": appt.title,
                "kind": appt.kind,
                "at": _hhmm(appt.starts_at),
                "depart_at": _hhmm(depart),
                "travel_min": travel_min,
                "buffer_min": appt.buffer_min,
                "late_by": late_by,
                "degraded": leg_degraded,
                "cause": _cause(previous, appt, travel_min, late_by) if late_by > 0 else None,
                "missing_address": missing_address,
            }
        )
        if late_by > 0 and len(conflicts) < MAX_CONFLICTS:
            conflicts.append(
                {
                    "appointment_id": appt.pk,
                    "title": appt.title,
                    "at": _hhmm(appt.starts_at),
                    "late_by": late_by,
                    "cause": _cause(previous, appt, travel_min, late_by),
                }
            )

        cursor = max(appt.starts_at, ready) + _minutes(appt.duration_min)
        previous = appt
        origin = destination or origin

    _persist(appointments, legs)

    return {
        "date": start.date().isoformat(),
        "base": base.label if base else None,
        "stops": stops,
        "conflicts": conflicts,
        "degraded": degraded,
    }


def _cause(previous, appt, travel_min, late_by):
    if previous is None:
        return f"el traslado tarda {travel_min} min y no cabe antes de las {_hhmm(appt.starts_at)}"
    return (
        f"sales de {previous.title} con {travel_min} min de traslado: "
        f"llegas {late_by} min tarde a las {_hhmm(appt.starts_at)}"
    )


def _persist(appointments, legs):
    TravelBlock.objects.filter(appointment__in=appointments).delete()
    TravelBlock.objects.bulk_create(
        [
            TravelBlock(
                appointment=appt,
                starts_at=appt.starts_at - _minutes(appt.buffer_min + travel_min),
                duration_min=travel_min,
                route_summary=summary,
                origin=origin,
                destination=destination,
            )
            for appt, origin, destination, travel_min, summary in legs
        ]
    )


def _bounds(day=None):
    day = day or timezone.localdate()
    start = timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))
    return start, start + datetime.timedelta(days=1)


def _minutes(value):
    return datetime.timedelta(minutes=value)


def _hhmm(moment):
    return timezone.localtime(moment).strftime("%H:%M")
