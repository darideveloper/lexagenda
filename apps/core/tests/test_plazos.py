import datetime
import time

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.agenda import calendars
from apps.agenda.models import Deadline
from apps.core.models import Case, Client

PASSWORD = "clave-de-prueba"


class PlazosTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("abogado", password=PASSWORD)
        self.device = TOTPDevice.objects.create(user=self.user, name="whatsapp", confirmed=True)
        client = Client.objects.create(
            name="García", phone="+527711234567", jid="5211@s.whatsapp.net"
        )
        self.case = Case.objects.create(
            client=client,
            reference="EXP-1",
            title="Laboral",
            opened_on=datetime.date(2026, 10, 1),
        )
        self.deadline = Deadline.objects.create(
            case=self.case,
            title="Contestación demanda laboral",
            notified_on=datetime.date(2026, 10, 30),
            term_value=20,
        )
        totp = TOTP(
            self.device.bin_key,
            self.device.step,
            self.device.t0,
            self.device.digits,
            self.device.drift,
        )
        totp.time = time.time()
        self.client.post(
            reverse("login"),
            {"username": "abogado", "password": PASSWORD, "code": f"{totp.token():06d}"},
        )

    def test_plazos_needs_a_verified_login(self):
        self.client.logout()
        response = self.client.get(reverse("plazos"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_a_computed_date_shows_the_calculado_badge(self):
        page = self.client.get(reverse("plazos"))
        self.assertContains(page, "Contestación demanda laboral")
        self.assertContains(page, "calculado — verifica")
        self.assertContains(page, "20 días hábiles desde notificación")

    def test_verify_stamps_user_time_and_calendar_and_keeps_the_badge(self):
        response = self.client.post(reverse("plazos_verify", args=[self.deadline.pk]))
        self.assertRedirects(response, reverse("plazos"))
        deadline = Deadline.objects.get(pk=self.deadline.pk)
        self.assertEqual(deadline.verified_by, self.user)
        self.assertIsNotNone(deadline.verified_at)
        self.assertEqual(deadline.verified_with_calendar, calendars.version())
        page = self.client.get(reverse("plazos"))
        self.assertContains(page, "verificado")
        self.assertContains(page, "calculado — verifica")

    def test_an_older_calendar_version_is_flagged(self):
        Deadline.objects.filter(pk=self.deadline.pk).update(
            verified_by=self.user,
            verified_at=timezone.now(),
            verified_with_calendar="2025.4",
        )
        page = self.client.get(reverse("plazos"))
        self.assertContains(page, "calendario actualizado — re-verifica")

    def test_verify_is_post_only(self):
        response = self.client.get(reverse("plazos_verify", args=[self.deadline.pk]))
        self.assertEqual(response.status_code, 405)
