import datetime
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.agenda import day as simulation
from apps.agenda.models import Appointment
from apps.core.models import BaseLocation, Case, Client


def monday():
    today = timezone.localdate()
    return today + datetime.timedelta(days=(0 - today.weekday()) % 7)


class SeedDemoTests(TestCase):
    def seed(self):
        out = StringIO()
        call_command("seed_demo", stdout=out)
        return out.getvalue()

    def test_seeds_five_clients_three_cases_and_a_base_location(self):
        self.seed()

        self.assertEqual(Client.objects.count(), 5)
        self.assertEqual(Case.objects.count(), 3)
        self.assertTrue(BaseLocation.objects.get(is_default=True).address)

    def test_seeding_twice_does_not_duplicate(self):
        self.seed()
        self.seed()

        self.assertEqual(Client.objects.count(), 5)
        self.assertEqual(Case.objects.count(), 3)

    def test_the_week_is_impossible_even_without_traffic(self):
        self.seed()

        conflicts = []
        for offset in range(5):
            result = simulation.simulate(monday() + datetime.timedelta(days=offset))
            conflicts.extend(result["conflicts"])

        self.assertGreaterEqual(len(conflicts), 3)
        self.assertTrue(all(conflict["late_by"] > 0 for conflict in conflicts))

    def test_the_seeded_week_renders_a_morning_brief(self):
        from apps.assistant import brief

        self.seed()

        text = brief.render("morning", monday())

        self.assertIn("Hoy tienes 1 compromiso", text)
        self.assertIn("García", text)

    def test_one_seeded_stop_has_no_address(self):
        self.seed()

        friday = monday() + datetime.timedelta(days=4)
        result = simulation.simulate(friday)

        self.assertTrue(any(stop["missing_address"] for stop in result["stops"]))
