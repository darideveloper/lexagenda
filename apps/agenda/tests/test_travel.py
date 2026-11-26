import datetime

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from apps.agenda.models import Appointment, TravelBlock


class TravelBlockTests(TestCase):
    def setUp(self):
        self.appt = Appointment.objects.create(
            title="Visita García",
            starts_at=timezone.now() + datetime.timedelta(hours=2),
            location_name="Colonia Centro",
        )

    def test_block_belongs_to_one_appointment(self):
        block = TravelBlock.objects.create(
            appointment=self.appt,
            starts_at=self.appt.starts_at - datetime.timedelta(minutes=45),
            duration_min=38,
            origin="Oficina",
            destination="Colonia Centro",
            route_summary={"duration_in_traffic": 2280, "distance": 12400},
        )

        self.assertEqual(self.appt.travel_block, block)
        self.assertEqual(block.duration_min, 38)
        self.assertEqual(block.route_summary["distance"], 12400)
        self.assertIsNotNone(block.computed_at)

    def test_one_block_per_appointment(self):
        TravelBlock.objects.create(appointment=self.appt, starts_at=timezone.now(), duration_min=10)

        with self.assertRaises(IntegrityError):
            TravelBlock.objects.create(
                appointment=self.appt, starts_at=timezone.now(), duration_min=12
            )

    def test_block_is_deleted_with_its_appointment(self):
        block = TravelBlock.objects.create(
            appointment=self.appt, starts_at=timezone.now(), duration_min=10
        )

        self.appt.delete()

        self.assertFalse(TravelBlock.objects.filter(pk=block.pk).exists())

    def test_label_names_the_destination(self):
        block = TravelBlock.objects.create(
            appointment=self.appt,
            starts_at=timezone.now(),
            duration_min=10,
            destination="Juzgado 4°",
        )

        self.assertEqual(str(block), "Traslado → Juzgado 4°")
