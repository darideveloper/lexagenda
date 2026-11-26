"""One visit's travel block: coordinates or nothing, ending at `starts_at - buffer_min`.

A visit is planned through a card whose point we resolved (PLAN D19); without coordinates
there is no honest drive time, so there is no block. Returns are not modelled (§7.3).
"""

import datetime

from django.utils import timezone

from apps.agenda.models import Appointment, TravelBlock
from apps.core.models import BaseLocation
from apps.integrations import maps


def compute_block(appointment, origin=None, travel_min=None, summary=None):
    """Persist the drive to one visit, or clear it when the visit cannot be located.

    `travel_min`/`summary` replay the leg a proposal already showed, so `confirm` writes
    exactly the block the lawyer read instead of spending a second route.
    """
    if not _located(appointment):
        _clear(appointment)
        return None
    origin = origin if origin is not None else origin_for(appointment.starts_at)
    if travel_min is None:
        leg = maps.route(origin, appointment.address, departure(appointment))
        if leg is None:
            _clear(appointment)
            return None
        travel_min = max(0, round(leg["duration_in_traffic_s"] / 60))
        summary = leg
    if not travel_min:
        _clear(appointment)
        return None
    block, _ = TravelBlock.objects.update_or_create(
        appointment=appointment,
        defaults={
            "starts_at": appointment.starts_at
            - datetime.timedelta(minutes=appointment.buffer_min + travel_min),
            "duration_min": travel_min,
            "route_summary": summary or {},
            "origin": origin,
            "destination": appointment.address,
        },
    )
    _set_travel(appointment, travel_min)
    return block


def recompute(appointment):
    """Regenerate one visit's block: after a move, an address change, or from the brief."""
    return compute_block(appointment)


def recompute_day(day=None):
    """Regenerate the blocks of one day, each leg starting where the previous stop ended."""
    start, end = _bounds(day)
    visits = Appointment.objects.filter(
        status=Appointment.PLANNED, starts_at__gte=start, starts_at__lt=end
    ).order_by("starts_at")
    origin, blocks = base_address(), []
    for appointment in visits:
        block = compute_block(appointment, origin=origin)
        if block is not None:
            blocks.append(block)
        if _located(appointment):
            origin = appointment.address
    return blocks


def origin_for(when):
    """Where the drive to `when` starts: the previous located stop, or the office."""
    start, _ = _bounds(when.date())
    previous = (
        Appointment.objects.filter(
            status=Appointment.PLANNED,
            starts_at__gte=start,
            starts_at__lt=when,
            lat__isnull=False,
            lng__isnull=False,
        )
        .order_by("-starts_at")
        .first()
    )
    return previous.address if previous else base_address()


def departure(appointment):
    """The moment the lawyer should leave: the buffer is not driving time."""
    return appointment.starts_at - datetime.timedelta(minutes=appointment.buffer_min)


def plan_leg(address, at, buffer_min=0):
    """The drive a proposal shows before the block exists: origin, minutes and the leg."""
    origin = origin_for(at)
    leg = maps.route(origin, address, at - datetime.timedelta(minutes=buffer_min))
    if leg is None:
        return origin, 0, {}
    return origin, max(0, round(leg["duration_in_traffic_s"] / 60)), leg


def base_address():
    base = BaseLocation.objects.filter(is_default=True).first() or BaseLocation.objects.first()
    return base.address if base else ""


def _located(appointment):
    return appointment.lat is not None and appointment.lng is not None


def _set_travel(appointment, travel_min):
    if appointment.travel_min != travel_min:
        appointment.travel_min = travel_min
        appointment.save(update_fields=["travel_min", "updated_at"])


def _clear(appointment):
    TravelBlock.objects.filter(appointment=appointment).delete()
    _set_travel(appointment, 0)


def _bounds(day):
    start = timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))
    return start, start + datetime.timedelta(days=1)
