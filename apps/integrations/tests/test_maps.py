import io
import json
import urllib.error
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.integrations import maps

AT = timezone.now().replace(minute=12, second=0, microsecond=0)


def response(duration_s=2280, distance_m=12400):
    body = {
        "routes": [
            {
                "duration": f"{duration_s}s",
                "distanceMeters": distance_m,
                "legs": [{"steps": [{"navigationInstruction": {"instructions": "Ve al norte"}}]}],
            }
        ]
    }
    handle = io.BytesIO(json.dumps(body).encode())
    handle.__enter__ = lambda: handle
    handle.__exit__ = lambda *args: False
    return handle


@override_settings(ROUTES_API_KEY="test-key", ROUTES_DAILY_CAP=100)
class RouteTests(TestCase):
    def setUp(self):
        cache.clear()

    @mock.patch("apps.integrations.maps.urllib.request.urlopen")
    def test_one_call_per_leg_within_the_cache_window(self, urlopen):
        urlopen.return_value = response()

        first = maps.route("Oficina", "Juzgado 4°", AT)
        second = maps.route("Oficina", "Juzgado 4°", AT.replace(minute=14))

        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(first["duration_in_traffic_s"], 2280)
        self.assertEqual(first["distance_m"], 12400)

    @mock.patch("apps.integrations.maps.urllib.request.urlopen")
    def test_a_new_departure_slot_is_a_new_call(self, urlopen):
        urlopen.return_value = response()

        maps.route("Oficina", "Juzgado 4°", AT)
        maps.route("Oficina", "Juzgado 4°", AT.replace(minute=18))

        self.assertEqual(urlopen.call_count, 2)

    @override_settings(ROUTES_DAILY_CAP=1)
    @mock.patch("apps.integrations.maps.urllib.request.urlopen")
    def test_past_the_daily_cap_the_leg_degrades_without_a_call(self, urlopen):
        urlopen.return_value = response()

        first = maps.route("Oficina", "Juzgado 4°", AT)
        second = maps.route("Oficina", "Tribunal", AT)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(urlopen.call_count, 1)

    @override_settings(ROUTES_DAILY_CAP=1)
    @mock.patch("apps.integrations.maps.urllib.request.urlopen")
    def test_a_cached_leg_does_not_spend_the_cap_twice(self, urlopen):
        urlopen.return_value = response()

        maps.route("Oficina", "Juzgado 4°", AT)
        cached = maps.route("Oficina", "Juzgado 4°", AT)
        other = maps.route("Oficina", "Tribunal", AT)

        self.assertIsNotNone(cached)
        self.assertIsNone(other)
        self.assertEqual(urlopen.call_count, 1)

    @override_settings(ROUTES_API_KEY="")
    @mock.patch("apps.integrations.maps.urllib.request.urlopen")
    def test_without_a_key_the_leg_degrades(self, urlopen):
        self.assertIsNone(maps.route("Oficina", "Juzgado 4°", AT))
        urlopen.assert_not_called()

    @mock.patch("apps.integrations.maps.urllib.request.urlopen")
    def test_a_failed_call_degrades_instead_of_raising(self, urlopen):
        urlopen.side_effect = urllib.error.URLError("boom")

        self.assertIsNone(maps.route("Oficina", "Juzgado 4°", AT))


def handle(body):
    stream = io.BytesIO(json.dumps(body).encode())
    stream.__enter__ = lambda: stream
    stream.__exit__ = lambda *args: False
    return stream


def places_response(name="Centro Médico Roma", address="Av. Roma 12, Col. Roma", lat=19.416667, lng=-99.162001):
    return handle({
        "places": [
            {
                "id": "ChIJ123",
                "displayName": {"text": name},
                "formattedAddress": address,
                "location": {"latitude": lat, "longitude": lng},
                "googleMapsUri": "https://maps.google.com/?cid=1",
            }
        ]
    })


EMPTY_PLACES = {"places": []}


@override_settings(PLACES_API_KEY="test-key")
class ResolveTests(TestCase):
    """One column of text becomes one card, or a link — never a guessed pin (PLAN D19)."""

    def setUp(self):
        cache.clear()

    @mock.patch("apps.integrations.maps.urllib.request.urlopen")
    def test_one_search_returns_one_candidate_card(self, urlopen):
        urlopen.return_value = places_response()

        card = maps.resolve("frente al Soriana")

        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(card["address_source"], "places")
        self.assertEqual(card["location_name"], "Centro Médico Roma")
        self.assertEqual(card["address"], "Av. Roma 12, Col. Roma")
        self.assertEqual(card["lat"], "19.416667")
        self.assertEqual(card["lng"], "-99.162001")
        self.assertEqual(card["maps_url"], "https://maps.google.com/?cid=1")

    @override_settings(PLACES_API_KEY="")
    @mock.patch("apps.integrations.maps.urllib.request.urlopen")
    def test_without_a_key_it_offers_a_maps_link_and_no_coordinates(self, urlopen):
        card = maps.resolve("frente al Soriana")

        self.assertEqual(card["address_source"], "link")
        self.assertIsNone(card["lat"])
        self.assertIsNone(card["lng"])
        self.assertIn("google.com/maps/search", card["maps_url"])
        self.assertIn("frente%20al%20Soriana", card["maps_url"])
        urlopen.assert_not_called()

    @override_settings(PLACES_API_KEY="")
    def test_a_link_never_carries_a_pin(self):
        card = maps.resolve("Colonia Centro")

        self.assertEqual(card["address_source"], "link")
        self.assertIsNone(card["lat"])

    @mock.patch("apps.integrations.maps.urllib.request.urlopen")
    def test_a_failed_call_degrades_to_the_link(self, urlopen):
        urlopen.side_effect = urllib.error.URLError("boom")

        card = maps.resolve("frente al Soriana")

        self.assertEqual(card["address_source"], "link")
        self.assertIsNone(card["lat"])

    @mock.patch("apps.integrations.maps.urllib.request.urlopen")
    def test_no_candidate_degrades_to_the_link(self, urlopen):
        urlopen.return_value = handle(EMPTY_PLACES)

        card = maps.resolve("frente al Soriana")

        self.assertEqual(card["address_source"], "link")

    def test_an_empty_address_resolves_to_nothing(self):
        self.assertIsNone(maps.resolve("   "))
