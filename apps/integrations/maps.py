"""Routes API v2: one traffic-aware call per leg, cached 30 min, capped daily (PLAN §8.2, §16)."""

import hashlib
import json
import urllib.request
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

SLOT_MINUTES = 5
CACHE_SECONDS = 30 * 60
FIELD_MASK = "routes.duration,routes.distanceMeters,routes.legs.steps.navigationInstruction"


def route(origin, destination, at=None):
    """Return distance and traffic-aware duration for one leg, or None when degraded.

    None is the degradation the brief renders as "sin cálculo de traslado": no key,
    a failed call, or the day's cap already spent. A cached leg never spends it again.
    """
    if not settings.ROUTES_API_KEY:
        return None
    at = at or timezone.now()
    key = _key(origin, destination, at)
    cached = cache.get(key)
    if cached is not None:
        return cached
    if not _spend():
        return None
    try:
        summary = _call(origin, destination, at)
    except (OSError, ValueError, KeyError, IndexError):
        return None
    cache.set(key, summary, CACHE_SECONDS)
    return summary


def _slot(at):
    return at.replace(minute=at.minute - at.minute % SLOT_MINUTES, second=0, microsecond=0)


def _key(origin, destination, at):
    leg = "{}|{}|{}".format(
        origin.strip().lower(), destination.strip().lower(), _slot(at).isoformat()
    )
    return f"routes:{hashlib.sha1(leg.encode()).hexdigest()}"


def _spend():
    today = timezone.localdate()
    key = f"routes:calls:{today.isoformat()}"
    cache.add(key, 0, timeout=_seconds_until_midnight(today))
    if cache.get(key, 0) >= settings.ROUTES_DAILY_CAP:
        return False
    try:
        cache.incr(key)
    except ValueError:  # the key expired between add and incr
        return False
    return True


def _seconds_until_midnight(today):
    tomorrow = datetime.combine(today + timedelta(days=1), time.min)
    return max(1, int((timezone.make_aware(tomorrow) - timezone.now()).total_seconds()))


def _call(origin, destination, at):
    payload = {
        "origin": {"address": origin},
        "destination": {"address": destination},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
        "departureTime": at.isoformat(),
    }
    request = urllib.request.Request(
        settings.ROUTES_URL.rstrip("/") + "/directions/v2:computeRoutes",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": settings.ROUTES_API_KEY,
            "X-Goog-FieldMask": FIELD_MASK,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=settings.ROUTES_TIMEOUT) as response:
        data = json.load(response)

    best = data["routes"][0]
    return {
        "distance_m": int(best["distanceMeters"]),
        "duration_in_traffic_s": int(str(best["duration"]).rstrip("s")),
    }
