import datetime
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.agenda import day, planner
from apps.agenda.models import Appointment, TravelBlock
from apps.core.models import BaseLocation

DAY = datetime.date(2026, 11, 26)


def at(hour, minute=0):
    return timezone.make_aware(datetime.datetime.combine(DAY, datetime.time(hour, minute)))


def leg(minutes, distance_m=4000):
    return {"distance_m": distance_m, "duration_in_traffic_s": minutes * 60}


def visit(**kwargs):
    fields = {
        "title": "Visita",
        "starts_at": at(11, 0),
        "address": "Av. Roma 12, Col. Roma",
        "address_source": Appointment.PLACES,
        "lat": "19.416667",
        "lng": "-99.162001",
    }
    fields.update(kwargs)
    return Appointment.objects.create(**fields)


class BlockTests(TestCase):
    """One block per visit: travel first, then the buffer, then the appointment (PLAN §7.3)."""

    def setUp(self):
        BaseLocation.objects.create(label="Oficina", address="Allende 12", is_default=True)

    @mock.patch("apps.agenda.planner.maps.route")
    def test_the_block_ends_at_starts_at_minus_the_buffer(self, route):
        route.return_value = leg(32)
        appt = visit(buffer_min=8)

        block = planner.compute_block(appt)

        self.assertEqual(
            block.starts_at, at(11, 0) - datetime.timedelta(minutes=40)
        )
        self.assertEqual(block.duration_min, 32)
        self.assertEqual(block.origin, "Allende 12")
        self.assertEqual(block.destination, "Av. Roma 12, Col. Roma")
        appt.refresh_from_db()
        self.assertEqual(appt.travel_min, 32)

    @mock.patch("apps.agenda.planner.maps.route")
    def test_without_coordinates_there_is_no_block_and_no_travel(self, route):
        appt = visit(
            address="frente al Soriana", address_source=Appointment.LINK, lat=None, lng=None
        )

        self.assertIsNone(planner.compute_block(appt))

        appt.refresh_from_db()
        self.assertEqual(appt.travel_min, 0)
        self.assertFalse(TravelBlock.objects.filter(appointment=appt).exists())
        route.assert_not_called()

    @mock.patch("apps.agenda.planner.maps.route")
    def test_a_degraded_leg_leaves_no_block(self, route):
        route.return_value = None
        appt = visit()

        self.assertIsNone(planner.compute_block(appt))
        self.assertEqual(TravelBlock.objects.filter(appointment=appt).count(), 0)

    @mock.patch("apps.agenda.planner.maps.route")
    def test_a_visit_with_coordinates_loses_a_stale_block(self, route):
        appt = visit()
        TravelBlock.objects.create(appointment=appt, starts_at=at(10, 0), duration_min=9)
        appt.lat = appt.lng = None
        appt.address_source = Appointment.LINK
        appt.save()

        planner.recompute(appt)

        appt.refresh_from_db()
        self.assertEqual(appt.travel_min, 0)
        self.assertFalse(TravelBlock.objects.filter(appointment=appt).exists())

    @mock.patch("apps.agenda.planner.maps.route")
    def test_moving_the_appointment_regenerates_its_block(self, route):
        route.return_value = leg(20)
        appt = visit()
        planner.compute_block(appt)

        appt.starts_at = at(13, 0)
        appt.save(update_fields=["starts_at"])
        planner.recompute(appt)

        block = TravelBlock.objects.get(appointment=appt)
        self.assertEqual(block.starts_at, at(12, 40))
        self.assertEqual(TravelBlock.objects.filter(appointment=appt).count(), 1)

    @mock.patch("apps.agenda.planner.maps.route")
    def test_the_origin_is_the_previous_stop_of_the_day(self, route):
        route.side_effect = [leg(20), leg(15)]
        first = visit(title="García", starts_at=at(9, 0), address="Colonia Centro")
        second = visit(title="Peralta", starts_at=at(11, 0), address="Juzgado 4°")

        planner.recompute_day(DAY)

        self.assertEqual(TravelBlock.objects.get(appointment=first).origin, "Allende 12")
        self.assertEqual(TravelBlock.objects.get(appointment=second).origin, "Colonia Centro")

    def test_the_origin_for_a_new_stop_is_its_previous_stop(self):
        visit(starts_at=at(9, 0), address="Colonia Centro")

        self.assertEqual(planner.origin_for(at(11, 0)), "Colonia Centro")
        self.assertEqual(planner.origin_for(at(8, 0)), "Allende 12")


class LinkVisitTests(TestCase):
    """A link visit has no coordinates, so it gets no block and reads sin dirección."""

    def setUp(self):
        BaseLocation.objects.create(label="Oficina", address="Allende 12", is_default=True)

    @mock.patch("apps.agenda.day.maps.route")
    def test_a_link_visit_is_sin_direccion_and_never_routed(self, route):
        Appointment.objects.create(
            title="Visita",
            starts_at=at(9, 30),
            address="frente al Soriana",
            address_source=Appointment.LINK,
        )

        result = day.simulate(DAY)

        self.assertTrue(result["stops"][0]["missing_address"])
        self.assertEqual(result["stops"][0]["travel_min"], 0)
        self.assertEqual(TravelBlock.objects.count(), 0)
        route.assert_not_called()

    @mock.patch("apps.agenda.planner.maps.route")
    def test_changing_the_address_regenerates_the_block(self, route):
        route.return_value = leg(20)
        appt = visit()
        planner.compute_block(appt)
        route.return_value = leg(45)

        appt.address = "Juzgado 4° de lo Laboral"
        appt.save(update_fields=["address"])
        planner.recompute(appt)

        block = TravelBlock.objects.get(appointment=appt)
        self.assertEqual(block.destination, "Juzgado 4° de lo Laboral")
        self.assertEqual(block.duration_min, 45)
        self.assertEqual(block.starts_at, at(10, 15))
