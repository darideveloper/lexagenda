from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.agenda.models import Appointment
from apps.core.models import Case, Client
from apps.core.tests.test_login import PASSWORD, totp_token


def login_verified(http, user, totp):
    """Log a user in through the real login view, TOTP included."""
    return http.post(
        reverse("login"),
        {"username": user.username, "password": PASSWORD, "code": totp_token(totp)},
    )


class DashboardBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("abogado", password=PASSWORD)
        self.totp = TOTPDevice.objects.create(user=self.user, name="whatsapp", confirmed=True)
        StaticDevice.objects.create(user=self.user, name="recovery", confirmed=True)
        login_verified(self.client, self.user, self.totp)

        self.client_obj = Client.objects.create(
            name="Ana García", phone="+525512345678", jid="5215512345678@s.whatsapp.net"
        )
        self.case = Case.objects.create(
            client=self.client_obj,
            reference="EXP-001",
            title="Laboral",
            court="JLCA CDMX",
            opened_on=date(2026, 11, 2),
        )


class ClientsPageTests(DashboardBase):
    def test_pages_need_a_login(self):
        self.client.logout()
        for name, args in (("clients", []), ("client", [self.client_obj.pk]), ("case", [self.case.pk])):
            with self.subTest(page=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response["Location"])

    def test_list_shows_the_clients_and_a_case_count(self):
        other = Client.objects.create(name="Luis Pérez", phone="+525587654321")
        Case.objects.create(
            client=other, reference="EXP-002", title="Mercantil", opened_on=date(2026, 1, 5)
        )
        Case.objects.create(
            client=other,
            reference="EXP-003",
            title="Cerrado",
            opened_on=date(2025, 1, 5),
            status=Case.CLOSED,
        )
        response = self.client.get(reverse("clients"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ana García")
        bodies = [c.name for c in response.context["clients"]]
        self.assertEqual(bodies, ["Ana García", "Luis Pérez"])
        counts = {c.name: c.open_cases for c in response.context["clients"]}
        self.assertEqual(counts, {"Ana García": 1, "Luis Pérez": 1})

    def test_detail_shows_the_cases_and_their_links(self):
        response = self.client.get(reverse("client", args=[self.client_obj.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ana García")
        self.assertContains(response, "EXP-001")
        self.assertContains(response, reverse("case", args=[self.case.pk]))

    def test_detail_edits_only_phone_email_and_notes(self):
        response = self.client.post(
            reverse("client", args=[self.client_obj.pk]),
            {
                "phone": "+525500000000",
                "email": "ana@example.com",
                "notes": "Prefiere WhatsApp por la tarde.",
                "name": "Nombre inyectado",
                "is_active": "",
            },
        )
        self.assertRedirects(response, reverse("client", args=[self.client_obj.pk]))
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.phone, "+525500000000")
        self.assertEqual(self.client_obj.email, "ana@example.com")
        self.assertEqual(self.client_obj.notes, "Prefiere WhatsApp por la tarde.")
        self.assertEqual(self.client_obj.name, "Ana García")
        self.assertTrue(self.client_obj.is_active)


class CasePageTests(DashboardBase):
    def test_detail_shows_the_case_and_its_appointments(self):
        Appointment.objects.create(
            case=self.case,
            client=self.client_obj,
            title="Audiencia inicial",
            starts_at=timezone.now(),
        )
        response = self.client.get(reverse("case", args=[self.case.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "EXP-001")
        self.assertContains(response, "Laboral")
        self.assertContains(response, "Audiencia inicial")
        self.assertContains(response, "abierto")

    def test_status_change_writes_closed_on(self):
        response = self.client.post(reverse("case", args=[self.case.pk]), {"status": Case.CLOSED})
        self.assertRedirects(response, reverse("case", args=[self.case.pk]))
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, Case.CLOSED)
        self.assertEqual(self.case.closed_on, timezone.localdate())
        self.assertEqual(self.case.reference, "EXP-001")

    def test_reopening_clears_closed_on(self):
        self.case.status = Case.CLOSED
        self.case.closed_on = date(2026, 11, 10)
        self.case.save()
        self.client.post(reverse("case", args=[self.case.pk]), {"status": Case.OPEN})
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, Case.OPEN)
        self.assertIsNone(self.case.closed_on)

    def test_appointments_are_not_editable_here(self):
        appointment = Appointment.objects.create(
            case=self.case, title="Visita", starts_at=timezone.now()
        )
        self.client.post(
            reverse("case", args=[self.case.pk]),
            {"status": Case.OPEN, "title": "otra cosa", "appointment_title": "cambiada"},
        )
        appointment.refresh_from_db()
        self.assertEqual(appointment.title, "Visita")
