import time

from django.contrib import admin
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.core.models import BaseLocation

PASSWORD = "clave-admin"


def totp_token(device):
    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    totp.time = time.time()
    return f"{totp.token():0{device.digits}d}"


class AdminTOTPTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("jefa", password=PASSWORD, is_staff=True)
        self.totp = TOTPDevice.objects.create(user=self.staff, name="whatsapp", confirmed=True)

    def admin_login(self, username="jefa", password=PASSWORD, device=None, otp=None):
        data = {"username": username, "password": password}
        if device is not None:
            data["otp_device"] = device.persistent_id
        if otp is not None:
            data["otp_token"] = otp
        return self.client.post(reverse("admin:login"), data)

    def test_password_only_never_authenticates(self):
        response = self.admin_login()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)

    def test_password_plus_totp_opens_the_admin(self):
        response = self.admin_login(device=self.totp, otp=totp_token(self.totp))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def test_non_staff_is_refused_even_with_a_valid_token(self):
        other = User.objects.create_user("abogado", password=PASSWORD)
        device = TOTPDevice.objects.create(user=other, name="whatsapp", confirmed=True)

        response = self.admin_login(
            username="abogado", device=device, otp=totp_token(device)
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)

    def test_password_session_without_totp_cannot_reach_the_admin(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response["Location"])

    def test_base_location_is_editable_in_the_admin(self):
        self.assertTrue(admin.site.is_registered(BaseLocation))
