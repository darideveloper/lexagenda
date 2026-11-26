import datetime
import os
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.agenda.models import Appointment, Deadline, TravelBlock
from apps.core.models import Case, Client

TOKEN = "secreto-de-prueba"
AT = timezone.make_aware(datetime.datetime(2026, 11, 26, 11, 0))


class FeedTests(TestCase):
    """GET /calendar/<token>.ics: read-only, unauthenticated, and unindexable (PLAN §7.1)."""

    def setUp(self):
        self.client_row = Client.objects.create(
            name="García", phone="+527711234567", jid="5211@s.whatsapp.net", email="garcia@cliente.mx"
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
            starts_at=AT,
            address="Av. Juárez 100",
        )
        TravelBlock.objects.create(
            appointment=self.appointment,
            starts_at=AT - datetime.timedelta(minutes=45),
            duration_min=30,
            origin="Oficina",
            destination="Av. Juárez 100",
        )
        self.deadline = Deadline.objects.create(
            case=self.case,
            title="Contestación",
            due_date=datetime.date(2026, 12, 2),
            reminder_days=[7],
        )

    def get(self, token=TOKEN):
        return self.client.get(f"/calendar/{token}.ics")

    def test_the_right_token_serves_the_three_shapes(self):
        with mock.patch.dict(os.environ, {"ICS_TOKEN": TOKEN}):
            response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/calendar", response["Content-Type"])
        self.assertEqual(response["X-Robots-Tag"], "noindex")
        body = response.content.decode()
        self.assertIn(f"UID:{self.appointment.ics_uid}", body)
        self.assertIn(f"UID:{self.appointment.ics_uid}-traslado", body)
        self.assertIn(f"UID:plazo-{self.deadline.pk}@lexagenda", body)
        self.assertIn("METHOD:PUBLISH", body)

    def test_the_feed_is_crlf_only(self):
        with mock.patch.dict(os.environ, {"ICS_TOKEN": TOKEN}):
            body = self.get().content.decode()
        self.assertNotIn("\n", body.replace("\r\n", ""))

    def test_a_wrong_token_is_a_404(self):
        with mock.patch.dict(os.environ, {"ICS_TOKEN": TOKEN}):
            self.assertEqual(self.get("otro").status_code, 404)
            self.assertEqual(self.get("").status_code, 404)

    def test_no_configured_token_serves_nothing(self):
        with mock.patch.dict(os.environ, {"ICS_TOKEN": ""}):
            self.assertEqual(self.get("").status_code, 404)

    def test_cancelled_appointments_and_done_deadlines_stay_out(self):
        self.appointment.status = Appointment.CANCELLED
        self.appointment.save()
        self.deadline.status = Deadline.DONE
        self.deadline.save()
        with mock.patch.dict(os.environ, {"ICS_TOKEN": TOKEN}):
            body = self.get().content.decode()
        self.assertNotIn(f"UID:{self.appointment.ics_uid}", body)
        self.assertNotIn("plazo-", body)

    def test_a_client_email_never_appears_in_the_feed(self):
        with mock.patch.dict(os.environ, {"ICS_TOKEN": TOKEN}):
            body = self.get().content.decode()
        self.assertNotIn(self.client_row.email, body)


class RotationTests(TestCase):
    """Rotating the token retires the old URL at once, with no cached copy."""

    def test_the_old_url_404s_the_moment_the_token_changes(self):
        with mock.patch.dict(os.environ, {"ICS_TOKEN": "primero"}):
            self.assertEqual(self.client.get("/calendar/primero.ics").status_code, 200)
        with mock.patch.dict(os.environ, {"ICS_TOKEN": "segundo"}):
            self.assertEqual(self.client.get("/calendar/segundo.ics").status_code, 200)
            self.assertEqual(self.client.get("/calendar/primero.ics").status_code, 404)

    def test_a_non_ascii_token_is_a_404_and_never_a_500(self):
        with mock.patch.dict(os.environ, {"ICS_TOKEN": "secreto"}):
            self.assertEqual(self.client.get("/calendar/%C3%B1.ics").status_code, 404)

    def test_a_non_ascii_configured_token_still_works(self):
        with mock.patch.dict(os.environ, {"ICS_TOKEN": "ñ"}):
            self.assertEqual(self.client.get("/calendar/%C3%B1.ics").status_code, 200)
