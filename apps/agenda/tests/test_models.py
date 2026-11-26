import datetime

from django.test import TestCase
from django.utils import timezone

from apps.agenda.models import Appointment
from apps.core.models import Case, Client


class AppointmentTests(TestCase):
    def setUp(self):
        self.client = Client.objects.create(
            name="García", phone="+527711234567", jid="5211@s.whatsapp.net"
        )
        self.case = Case.objects.create(
            client=self.client,
            reference="EXP-1",
            title="Laboral",
            opened_on=datetime.date(2026, 11, 2),
        )

    def test_defaults(self):
        appt = Appointment.objects.create(
            case=self.case,
            client=self.client,
            title="Visita",
            starts_at=timezone.now(),
        )
        self.assertEqual(appt.kind, Appointment.VISITA)
        self.assertEqual(appt.status, Appointment.PLANNED)
        self.assertEqual(appt.address_source, Appointment.NONE)
        self.assertEqual(appt.ics_sequence, 0)
        self.assertIsNotNone(appt.ics_uid)

    def test_ics_uid_is_unique_per_appointment(self):
        when = timezone.now()
        first = Appointment.objects.create(title="A", starts_at=when)
        second = Appointment.objects.create(title="B", starts_at=when)
        self.assertNotEqual(first.ics_uid, second.ics_uid)
