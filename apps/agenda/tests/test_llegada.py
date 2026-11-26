import datetime
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.agenda import day
from apps.agenda.models import Appointment
from apps.core.models import BaseLocation

DAY = datetime.date(2026, 11, 26)


def at(hour, minute=0):
    return timezone.make_aware(datetime.datetime.combine(DAY, datetime.time(hour, minute)))


def leg(minutes):
    return {"distance_m": 1000, "duration_in_traffic_s": minutes * 60}


class FindFreeSlotTests(TestCase):
    def test_rounds_up_to_five_minutes(self):
        slots = day.find_free_slot(30, at(9, 3), at(18, 0))

        self.assertEqual(day._hhmm(slots[0]), "09:05")

    def test_three_alternatives_that_fit(self):
        slots = day.find_free_slot(60, at(9, 0), at(18, 0))

        self.assertEqual([day._hhmm(slot) for slot in slots], ["09:00", "10:05", "11:10"])

    def test_skips_a_busy_block(self):
        Appointment.objects.create(title="Audiencia", starts_at=at(9, 0), duration_min=60)

        slots = day.find_free_slot(30, at(9, 0), at(18, 0))

        self.assertEqual(day._hhmm(slots[0]), "10:00")

    def test_never_past_the_window(self):
        slots = day.find_free_slot(60, at(17, 30), at(18, 0))

        self.assertEqual(slots, [])

    def test_an_excluded_appointment_does_not_block_itself(self):
        appt = Appointment.objects.create(title="Visita", starts_at=at(9, 0), duration_min=60)

        slots = day.find_free_slot(60, at(9, 0), at(18, 0), exclude=[appt.pk])

        self.assertEqual(day._hhmm(slots[0]), "09:00")


class LlegadaTests(TestCase):
    def setUp(self):
        BaseLocation.objects.create(label="Oficina", address="Allende 12", is_default=True)

    @mock.patch("apps.agenda.day.maps.route")
    def test_on_time_has_no_fixes(self, route):
        route.return_value = leg(20)
        appt = Appointment.objects.create(
            title="Visita", address="Centro", starts_at=at(12, 30), duration_min=60
        )

        answer = day.llegada(appt.pk, DAY)

        self.assertEqual(answer["late_by"], 0)
        self.assertEqual(answer["fixes"], [])

    @mock.patch("apps.agenda.day.maps.route")
    def test_late_answers_with_lateness_and_three_fixes(self, route):
        route.return_value = leg(40)
        Appointment.objects.create(
            title="Visita García", address="Centro", starts_at=at(9, 30), duration_min=60
        )
        late = Appointment.objects.create(
            title="Junta Peralta", address="Otra", starts_at=at(10, 0), duration_min=60
        )

        answer = day.llegada(late.pk, DAY)

        self.assertEqual(answer["late_by"], 70)
        self.assertIn("Visita García", answer["cause"])
        self.assertEqual(len(answer["fixes"]), 3)
        self.assertEqual(answer["fixes"][0], "11:10")

    @mock.patch("apps.agenda.day.maps.route")
    def test_a_fix_never_lands_on_another_appointment(self, route):
        route.return_value = leg(40)
        Appointment.objects.create(
            title="Visita García", address="Centro", starts_at=at(9, 30), duration_min=60
        )
        late = Appointment.objects.create(
            title="Junta Peralta", address="Otra", starts_at=at(10, 0), duration_min=60
        )
        Appointment.objects.create(title="Audiencia", starts_at=at(11, 10), duration_min=120)

        answer = day.llegada(late.pk, DAY)

        self.assertEqual(answer["fixes"][0], "13:10")
