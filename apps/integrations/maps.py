"""Places Text Search and Routes API v2: one card, one traffic-aware call per leg (PLAN §8.2, D19)."""

import hashlib
import json
import urllib.parse
import urllib.request
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

SLOT_MINUTES = 5
CACHE_SECONDS = 30 * 60
FIELD_MASK = "routes.duration,routes.distanceMeters,routes.legs.steps.navigationInstruction"
PLACES_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.location,places.googleMapsUri"
)
PLACES = "places"
LINK = "link"
LINK_URL = "https://www.google.com/maps/search/?api=1&query={}"


def resolve(address):
    """One Places Text Search → a single candidate card, or a Maps link and no coordinates.

    A link is the honest answer when Places has no key, no candidate or a bad call: the
    lawyer opens the map himself instead of trusting a pin we guessed (PLAN D19).
    """
    query = (address or "").strip()
    if not query:
        return None
    if not settings.PLACES_API_KEY:
        return _link(query)
    try:
        place = _place(query)
    except (OSError, ValueError, KeyError, IndexError):
        return _link(query)
    if place is None:
        return _link(query)
    return place


def _link(query):
    return {
        "address_source": LINK,
        "address": query,
        "location_name": query,
        "lat": None,
        "lng": None,
        "maps_url": LINK_URL.format(urllib.parse.quote(query)),
    }


def _place(query):
    payload = {
        "textQuery": query,
        "languageCode": "es",
        "regionCode": "MX",
        "maxResultCount": 1,
    }
    request = urllib.request.Request(
        settings.PLACES_URL.rstrip("/") + "/v1/places:searchText",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": settings.PLACES_API_KEY,
            "X-Goog-FieldMask": PLACES_FIELD_MASK,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=settings.PLACES_TIMEOUT) as response:
        data = json.load(response)

    places = data.get("places") or []
    if not places:
        return None
    best = places[0]
    location = best["location"]
    return {
        "address_source": PLACES,
        "address": best["formattedAddress"],
        "location_name": best["displayName"]["text"],
        "lat": _coordinate(location["latitude"]),
        "lng": _coordinate(location["longitude"]),
        "maps_url": best.get("googleMapsUri", ""),
    }


def _coordinate(value):
    return str(Decimal(str(value)).quantize(Decimal("0.000001")))


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
