import time
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import TOTP
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.agenda.models import Appointment

PASSWORD = "clave-de-prueba"


def totp_token(device):
    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    totp.time = time.time()
    return f"{totp.token():0{device.digits}d}"


class LoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("abogado", password=PASSWORD)
        self.totp = TOTPDevice.objects.create(user=self.user, name="whatsapp", confirmed=True)
        self.static = StaticDevice.objects.create(user=self.user, name="recovery", confirmed=True)
        StaticToken.objects.create(device=self.static, token="cafe0001")

    def post(self, code, password=PASSWORD):
        return self.client.post(
            reverse("login"), {"username": "abogado", "password": password, "code": code}
        )

    def test_agenda_needs_a_login(self):
        response = self.client.get(reverse("agenda"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('agenda')}")

    def test_password_without_code_does_not_enter(self):
        response = self.post("")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "incorrectos")

    def test_wrong_code_does_not_enter(self):
        response = self.post("000000")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_wrong_password_does_not_enter(self):
        response = self.post(totp_token(self.totp), password="nope")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_password_plus_totp_opens_the_agenda(self):
        Appointment.objects.create(title="Visita García", starts_at=timezone.localtime())
        response = self.post(totp_token(self.totp))
        self.assertRedirects(response, reverse("agenda"))
        page = self.client.get(reverse("agenda"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Visita García")

    def test_unverified_session_cannot_see_the_agenda(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("agenda"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_recovery_code_works_once(self):
        self.assertRedirects(self.post("cafe0001"), reverse("agenda"))
        self.client.logout()
        response = self.post("cafe0001")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)


class SetupLawyerTests(TestCase):
    def test_creates_ten_recovery_codes(self):
        out = StringIO()
        call_command("setup_lawyer", username="nuevo", password="x", stdout=out)

        user = User.objects.get(username="nuevo")
        self.assertTrue(TOTPDevice.objects.get(user=user).confirmed)
        static = StaticDevice.objects.get(user=user)
        self.assertEqual(static.token_set.count(), 10)
        self.assertIn("otpauth:", out.getvalue())
