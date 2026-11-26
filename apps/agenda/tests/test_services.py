import datetime
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.agenda import services
from apps.agenda.models import Appointment
from apps.core.models import BaseLocation, Case, Client

AT = timezone.make_aware(datetime.datetime(2026, 11, 26, 11, 0))


class SequenceRuleTests(TestCase):
    """SEQUENCE moves on create, move, cancel and re-address — and on nothing else (PLAN §7.1)."""

    def test_create_starts_the_sequence_at_one(self):
        appointment = services.create(title="Visita", starts_at=AT)
        self.assertEqual(appointment.ics_sequence, 1)

    def test_move_raises_it_by_exactly_one(self):
        appointment = services.create(title="Visita", starts_at=AT)
        services.reschedule(appointment, AT + datetime.timedelta(hours=2))
        appointment.refresh_from_db()
        self.assertEqual(appointment.ics_sequence, 2)
        self.assertEqual(appointment.starts_at, AT + datetime.timedelta(hours=2))

    def test_moving_to_the_same_time_is_not_a_change(self):
        appointment = services.create(title="Visita", starts_at=AT)
        services.reschedule(appointment, AT)
        appointment.refresh_from_db()
        self.assertEqual(appointment.ics_sequence, 1)

    def test_cancel_raises_it_and_a_second_cancel_does_not(self):
        appointment = services.create(title="Visita", starts_at=AT)
        services.cancel(appointment)
        services.cancel(appointment)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.CANCELLED)
        self.assertEqual(appointment.ics_sequence, 2)

    def test_readdressing_raises_it_and_the_same_address_does_not(self):
        appointment = services.create(title="Visita", starts_at=AT)
        services.readdress(appointment, "Av. Juárez 100", "Juzgado 4°")
        services.readdress(appointment, "Av. Juárez 100", "Juzgado 4°")
        appointment.refresh_from_db()
        self.assertEqual(appointment.address, "Av. Juárez 100")
        self.assertEqual(appointment.ics_sequence, 2)

    def test_a_plain_save_never_touches_the_sequence(self):
        appointment = services.create(title="Visita", starts_at=AT)
        appointment.title = "Otra cosa"
        appointment.save()
        self.assertEqual(appointment.ics_sequence, 1)


class TravelRecomputeTests(TestCase):
    """A recompute changes the blocks, never the appointment's calendar identity."""

    def setUp(self):
        BaseLocation.objects.create(label="Oficina", address="Calle 1", is_default=True)
        client = Client.objects.create(name="García", phone="+527711234567", jid="5211@s.whatsapp.net")
        self.case = Case.objects.create(
            client=client, reference="EXP-1", title="Laboral", opened_on=datetime.date(2026, 11, 2)
        )

    @mock.patch("apps.agenda.day.maps.route")
    def test_simulating_the_day_leaves_sequence_alone(self, route):
        from apps.agenda import day

        route.side_effect = [
            {"duration_in_traffic_s": 1800, "distanceMeters": 8000},
            {"duration_in_traffic_s": 2400, "distanceMeters": 12000},
        ]
        appointment = services.create(
            case=self.case,
            title="Visita",
            starts_at=timezone.make_aware(
                datetime.datetime.combine(timezone.localdate(), datetime.time(11, 0))
            ),
            address="Av. Juárez 100",
            buffer_min=10,
        )
        day.simulate()
        first = appointment.travel_block.starts_at
        day.simulate()
        appointment.refresh_from_db()
        self.assertEqual(appointment.ics_sequence, 1)
        self.assertNotEqual(appointment.travel_block.starts_at, first)
