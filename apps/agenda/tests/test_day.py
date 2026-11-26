import datetime
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.agenda import day
from apps.agenda.models import Appointment, TravelBlock
from apps.core.models import BaseLocation

DAY = datetime.date(2026, 11, 26)


def at(hour, minute=0):
    return timezone.make_aware(datetime.datetime.combine(DAY, datetime.time(hour, minute)))


def leg(minutes):
    return {"distance_m": 12000, "duration_in_traffic_s": minutes * 60}


class DaySimulationTests(TestCase):
    def setUp(self):
        self.base = BaseLocation.objects.create(
            label="Oficina", address="Calle Allende 12, Pachuca", is_default=True
        )

    @mock.patch("apps.agenda.day.maps.route")
    def test_each_stop_gets_a_departure_from_the_base(self, route):
        route.return_value = leg(38)
        Appointment.objects.create(
            title="Visita García",
            address="Colonia Centro",
            starts_at=at(9, 30),
            buffer_min=7,
            duration_min=60,
        )

        result = day.simulate(DAY)

        stop = result["stops"][0]
        self.assertEqual(stop["travel_min"], 38)
        self.assertEqual(stop["depart_at"], "08:45")
        self.assertEqual(stop["late_by"], 0)
        self.assertFalse(result["degraded"])
        self.assertEqual(route.call_args[0][0], self.base.address)

    @mock.patch("apps.agenda.day.maps.route")
    def test_the_previous_stop_is_the_next_origin(self, route):
        route.side_effect = [leg(38), leg(22)]
        Appointment.objects.create(
            title="Visita García", address="Centro", starts_at=at(9, 30), duration_min=60
        )
        Appointment.objects.create(
            title="Audiencia", address="Juzgado 4°", starts_at=at(11, 0), duration_min=90
        )

        result = day.simulate(DAY)

        self.assertEqual(route.call_args_list[1][0][0], "Centro")
        self.assertEqual(result["stops"][1]["depart_at"], "10:38")
        self.assertEqual(result["stops"][1]["travel_min"], 22)

    @mock.patch("apps.agenda.day.maps.route")
    def test_an_impossible_day_reports_late_by_with_a_cause(self, route):
        route.return_value = leg(38)
        Appointment.objects.create(
            title="Visita García", address="Centro", starts_at=at(9, 30), duration_min=60
        )
        Appointment.objects.create(
            title="Junta Peralta", address="Otra", starts_at=at(10, 0), duration_min=60
        )

        result = day.simulate(DAY)

        conflict = result["conflicts"][0]
        self.assertEqual(conflict["late_by"], 68)
        self.assertIn("Visita García", conflict["cause"])
        self.assertEqual(result["stops"][1]["depart_at"], "10:30")

    @mock.patch("apps.agenda.day.maps.route")
    def test_only_the_first_three_conflicts_are_reported(self, route):
        route.return_value = leg(40)
        for hour in range(9, 14):
            Appointment.objects.create(
                title=f"Cita {hour}", address=f"Calle {hour}", starts_at=at(hour), duration_min=60
            )

        result = day.simulate(DAY)

        self.assertEqual(len(result["conflicts"]), 3)

    @mock.patch("apps.agenda.day.maps.route")
    def test_blocks_are_persisted_for_every_leg(self, route):
        route.return_value = leg(38)
        appt = Appointment.objects.create(
            title="Visita García", address="Centro", starts_at=at(9, 30), duration_min=60
        )

        day.simulate(DAY)

        block = TravelBlock.objects.get(appointment=appt)
        self.assertEqual(block.duration_min, 38)
        self.assertEqual(block.origin, self.base.address)
        self.assertEqual(block.destination, "Centro")
        self.assertEqual(block.route_summary["distance_m"], 12000)

    @mock.patch("apps.agenda.day.maps.route")
    def test_a_stop_without_an_address_costs_no_travel(self, route):
        Appointment.objects.create(title="Junta", starts_at=at(9, 30), buffer_min=5)

        result = day.simulate(DAY)

        self.assertEqual(result["stops"][0]["travel_min"], 0)
        self.assertTrue(result["stops"][0]["missing_address"])
        self.assertEqual(result["stops"][0]["depart_at"], "09:25")
        route.assert_not_called()
        self.assertFalse(TravelBlock.objects.exists())

    @mock.patch("apps.agenda.day.maps.route")
    def test_a_degraded_leg_keeps_the_stop_and_flags_the_day(self, route):
        route.return_value = None
        Appointment.objects.create(title="Visita", address="Centro", starts_at=at(9, 30))

        result = day.simulate(DAY)

        self.assertTrue(result["degraded"])
        self.assertEqual(result["stops"][0]["travel_min"], 0)
        self.assertEqual(result["stops"][0]["depart_at"], "09:30")
        self.assertFalse(TravelBlock.objects.exists())

    def test_without_a_base_location_the_day_still_walks(self):
        BaseLocation.objects.all().delete()
        Appointment.objects.create(title="Visita", address="Centro", starts_at=at(9, 30))

        result = day.simulate(DAY)

        self.assertTrue(result["degraded"])
        self.assertEqual(result["stops"][0]["depart_at"], "09:30")
