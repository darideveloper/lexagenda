import datetime

from django.test import TestCase
from django.utils import timezone

from apps.agenda.models import Appointment, Deadline, TravelBlock
from apps.core.models import Case, Client
from apps.integrations import ics


def unfold(text):
    """RFC 5545 §3.1: a CRLF followed by one space is a continuation, not a line break."""
    return text.replace("\r\n ", "")


class ShapeTests(TestCase):
    def setUp(self):
        self.client_row = Client.objects.create(
            name="García", phone="+527711234567", jid="5211@s.whatsapp.net"
        )
        self.case = Case.objects.create(
            client=self.client_row,
            reference="EXP-1",
            title="Laboral",
            opened_on=datetime.date(2026, 11, 2),
        )
        self.appointment = Appointment.objects.create(
            case=self.case,
            client=self.client_row,
            title="Visita",
            starts_at=timezone.make_aware(datetime.datetime(2026, 11, 26, 11, 0)),
            duration_min=60,
            location_name="Juzgado 4°",
            address="Av. Juárez 100, Pachuca",
        )

    def test_appointment_event_is_timed_and_opaque(self):
        event = unfold(ics.calendar([ics.appointment_event(self.appointment)]))
        self.assertIn("BEGIN:VEVENT", event)
        self.assertIn(f"UID:{self.appointment.ics_uid}", event)
        self.assertIn("DTSTART:20261126T170000Z", event)
        self.assertIn("DTEND:20261126T180000Z", event)
        self.assertIn("LOCATION:Av. Juárez 100\\, Pachuca", event)
        self.assertIn("DESCRIPTION:Cliente: García\\nExpediente: EXP-1", event)
        self.assertIn("TRANSP:OPAQUE", event)
        self.assertIn("STATUS:CONFIRMED", event)
        self.assertIn("SEQUENCE:0", event)

    def test_cancelled_appointment_says_so(self):
        self.appointment.status = Appointment.CANCELLED
        event = unfold(ics.calendar([ics.appointment_event(self.appointment)]))
        self.assertIn("STATUS:CANCELLED", event)

    def test_travel_block_is_transparent(self):
        block = TravelBlock.objects.create(
            appointment=self.appointment,
            starts_at=timezone.make_aware(datetime.datetime(2026, 11, 26, 9, 55)),
            duration_min=38,
            origin="Oficina",
            destination="Juzgado 4°",
        )
        event = unfold(ics.calendar([ics.travel_event(block)]))
        self.assertIn("SUMMARY:Traslado → Juzgado 4°", event)
        self.assertIn("TRANSP:TRANSPARENT", event)
        self.assertIn("DTSTART:20261126T155500Z", event)
        self.assertIn(f"UID:{self.appointment.ics_uid}-traslado", event)

    def test_deadline_is_an_all_day_event_with_alarms(self):
        deadline = Deadline.objects.create(
            case=self.case,
            title="Contestación",
            notified_on=datetime.date(2026, 11, 20),
            term_value=5,
            term_unit=Deadline.DIAS_HABILES,
            reminder_days=[7, 3, 1],
        )
        event = unfold(ics.calendar([ics.deadline_event(deadline)]))
        self.assertIn(f"UID:plazo-{deadline.pk}@lexagenda", event)
        self.assertIn(f"DTSTART;VALUE=DATE:{deadline.due_date:%Y%m%d}", event)
        self.assertIn("calculado — verifica", event)
        self.assertEqual(event.count("BEGIN:VALARM"), 3)
        self.assertIn("TRIGGER:-P7D", event)
        self.assertIn("TRIGGER:-P1D", event)


class FormatTests(TestCase):
    def test_every_physical_line_ends_crlf(self):
        body = ics.calendar([])
        self.assertTrue(body.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertNotIn("\n", body.replace("\r\n", ""))
        self.assertTrue(body.endswith("END:VCALENDAR\r\n"))

    def test_long_values_are_folded_at_75_octets(self):
        appointment = Appointment.objects.create(
            title="Audiencia " + "muy larga " * 15,
            starts_at=timezone.now(),
        )
        body = ics.calendar([ics.appointment_event(appointment)])
        for line in body.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75)
        self.assertTrue(body.count("\r\n ") >= 1)
        self.assertIn(appointment.title, unfold(body))

    def test_text_values_are_escaped(self):
        appointment = Appointment.objects.create(
            title="Junta; con, todos\\ y\nuna segunda línea",
            starts_at=timezone.now(),
        )
        event = unfold(ics.calendar([ics.appointment_event(appointment)]))
        self.assertIn("SUMMARY:Junta\\; con\\, todos\\\\ y\\nuna segunda línea", event)
