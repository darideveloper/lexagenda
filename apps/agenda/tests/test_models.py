import datetime

from django.test import TestCase
from django.utils import timezone

from apps.agenda.models import Appointment, Deadline
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


class DeadlineTests(TestCase):
    def setUp(self):
        self.client = Client.objects.create(
            name="Peralta", phone="+527719876543", jid="5222@s.whatsapp.net"
        )
        self.case = Case.objects.create(
            client=self.client,
            reference="EXP-2",
            title="Contestación",
            opened_on=datetime.date(2026, 10, 1),
        )

    def test_a_term_computes_the_due_date_and_marks_it(self):
        deadline = Deadline.objects.create(
            case=self.case,
            title="Contestación demanda laboral",
            notified_on=datetime.date(2026, 10, 30),
            term_value=20,
            term_unit=Deadline.DIAS_HABILES,
        )
        deadline.refresh_from_db()
        self.assertEqual(deadline.due_date, datetime.date(2026, 12, 2))
        self.assertTrue(deadline.computed)

    def test_a_hand_typed_date_is_not_computed(self):
        deadline = Deadline.objects.create(
            case=self.case, title="Cita con perito", due_date=datetime.date(2026, 12, 4)
        )
        self.assertFalse(deadline.computed)
        self.assertEqual(deadline.due_date, datetime.date(2026, 12, 4))

    def test_the_default_calendar_is_the_union_and_an_override_narrows_it(self):
        union = Deadline.objects.create(
            case=self.case,
            title="Termo con el calendario por defecto",
            notified_on=datetime.date(2026, 2, 4),
            term_value=1,
            term_unit=Deadline.DIAS_HABILES,
        )
        federal = Deadline.objects.create(
            case=self.case,
            title="Asunto administrativo",
            notified_on=datetime.date(2026, 2, 4),
            term_value=1,
            term_unit=Deadline.DIAS_HABILES,
            calendar_overrides=["federal"],
        )
        self.assertEqual(union.due_date, datetime.date(2026, 2, 6))
        self.assertEqual(federal.due_date, datetime.date(2026, 2, 5))

    def test_defaults(self):
        deadline = Deadline.objects.create(
            case=self.case, title="Revisión", due_date=datetime.date(2026, 12, 4)
        )
        self.assertEqual(deadline.kind, Deadline.PROCESAL)
        self.assertEqual(deadline.status, Deadline.OPEN)
        self.assertEqual(deadline.reminder_days, [7, 3, 1])
        self.assertEqual(deadline.calendar_names, ("federal", "oaj", "hidalgo"))
        self.assertIsNone(deadline.verified_by)
        self.assertEqual(deadline.verified_with_calendar, "")

    def test_reminder_days_is_not_a_shared_list(self):
        first = Deadline.objects.create(
            case=self.case, title="Uno", due_date=datetime.date(2026, 12, 4)
        )
        first.reminder_days.append(0)
        second = Deadline.objects.create(
            case=self.case, title="Dos", due_date=datetime.date(2026, 12, 5)
        )
        self.assertEqual(second.reminder_days, [7, 3, 1])
