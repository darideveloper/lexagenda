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
