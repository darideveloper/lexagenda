from datetime import date
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.core.models import Case, Client
from apps.core.tests.test_dashboard import login_verified
from apps.core.tests.test_login import PASSWORD, totp_token
from apps.docs.models import Document


class DocumentsPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("abogado", password=PASSWORD)
        self.totp = TOTPDevice.objects.create(user=self.user, name="whatsapp", confirmed=True)
        StaticDevice.objects.create(user=self.user, name="recovery", confirmed=True)
        login_verified(self.client, self.user, self.totp)

        client_obj = Client.objects.create(
            name="Ana García", phone="+525512345678", jid="5215512345678@s.whatsapp.net"
        )
        self.case = Case.objects.create(
            client=client_obj,
            reference="EXP-001",
            title="Laboral",
            opened_on=date(2026, 11, 2),
        )
        self.document = Document.objects.create(
            case=self.case,
            client=client_obj,
            filename="demanda.pdf",
            mime="application/pdf",
            size=120,
            sha256="a" * 64,
            extracted_text="La cláusula suelo es abusiva.",
        )

    def test_the_page_needs_a_login(self):
        self.client.logout()

        response = self.client.get(reverse("documents"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_a_search_shows_the_snippet_and_the_case(self):
        response = self.client.get(reverse("documents"), {"q": "clausula suelo"})

        self.assertContains(response, "demanda.pdf")
        self.assertContains(response, "«cláusula»")
        self.assertContains(response, "«suelo»")
        self.assertContains(response, "EXP-001")

    def test_a_search_without_hits_says_so(self):
        response = self.client.get(reverse("documents"), {"q": "hipoteca"})

        self.assertContains(response, "Sin resultados")

    def test_the_listing_flags_a_document_without_a_text_layer(self):
        Document.objects.create(
            case=self.case,
            client=self.case.client,
            filename="escaneo.pdf",
            mime="application/pdf",
            size=120,
            sha256="b" * 64,
            no_text_layer=True,
        )

        response = self.client.get(reverse("documents"))

        self.assertContains(response, "escaneo.pdf")
        self.assertContains(response, "sin texto")

    def test_the_cap_warning_appears_at_80_percent(self):
        almost_full = int(420 * 1024 * 1024)

        with mock.patch("apps.docs.storage.instance_bytes", return_value=almost_full):
            response = self.client.get(reverse("documents"))

        self.assertContains(response, "500 MB")
        self.assertContains(response, "84%")
