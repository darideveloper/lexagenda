from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.assistant.models import AuditLog, Job, Message, Proposal, Thread
from apps.core.tests.test_login import PASSWORD, totp_token

LOCMEM = "django.core.mail.backends.locmem.EmailBackend"


class OpsBase(TestCase):
    def setUp(self):
        self.thread = Thread.objects.create(jid="5215512345678@s.whatsapp.net")
        self.staff = User.objects.create_user(
            "ops", password=PASSWORD, email="ops@example.com", is_staff=True
        )
        self.totp = TOTPDevice.objects.create(user=self.staff, name="whatsapp", confirmed=True)
        StaticDevice.objects.create(user=self.staff, name="recovery", confirmed=True)
        self.lawyer = User.objects.create_user(
            "abogado", password=PASSWORD, email="abogado@example.com"
        )
        self.lawyer_totp = TOTPDevice.objects.create(
            user=self.lawyer, name="whatsapp", confirmed=True
        )
        self.lawyer_static = StaticDevice.objects.create(
            user=self.lawyer, name="recovery", confirmed=True
        )
        StaticToken.objects.create(device=self.lawyer_static, token="cafe0001")
        self.login(self.staff, self.totp)

    def login(self, user, totp):
        return self.client.post(
            reverse("login"),
            {"username": user.username, "password": PASSWORD, "code": totp_token(totp)},
        )


class OpsAccessTests(OpsBase):
    def test_ops_needs_a_login(self):
        self.client.logout()
        response = self.client.get(reverse("ops"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_a_non_staff_user_is_kept_out(self):
        self.client.logout()
        self.login(self.lawyer, self.lawyer_totp)
        response = self.client.get(reverse("ops"))
        self.assertEqual(response.status_code, 302)


class OpsConsoleTests(OpsBase):
    def test_the_console_shows_messages_audit_and_failed_jobs(self):
        Message.objects.create(thread=self.thread, role=Message.USER, text="hola, ¿llego?")
        AuditLog.objects.create(tool="agenda_today", ok=False)
        Job.objects.create(kind=Job.INBOUND, status=Job.FAILED, attempts=3, error="gowa 500")
        response = self.client.get(reverse("ops"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "hola, ¿llego?")
        self.assertContains(response, "agenda_today")
        self.assertContains(response, "gowa 500")
        self.assertContains(response, "Restablecer 2FA")

    def test_the_console_lists_proposals_with_their_thread_and_expiry(self):
        Proposal.objects.create(
            thread=self.thread,
            summary="Mover la cita de las 17:00 al jueves",
            expires_at=timezone.now() + timedelta(hours=2),
        )
        response = self.client.get(reverse("ops"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Propuestas")
        self.assertContains(response, "Mover la cita de las 17:00 al jueves")
        self.assertContains(response, "5215512345678@s.whatsapp.net")
        self.assertContains(response, "propuesta")  # the status label
        self.assertEqual(response.context["proposals"].count(), 1)

    def test_retrying_a_failed_job_queues_it_again(self):
        job = Job.objects.create(
            kind=Job.INBOUND, status=Job.FAILED, attempts=3, error="gowa 500", locked_at=timezone.now()
        )
        response = self.client.post(reverse("ops_job_retry", args=[job.pk]))
        self.assertRedirects(response, reverse("ops"))
        job.refresh_from_db()
        self.assertEqual(job.status, Job.QUEUED)
        self.assertEqual(job.attempts, 0)
        self.assertEqual(job.error, "")
        self.assertIsNone(job.locked_at)

    def test_a_done_job_is_not_retried(self):
        job = Job.objects.create(kind=Job.INBOUND, status=Job.DONE, attempts=1)
        self.client.post(reverse("ops_job_retry", args=[job.pk]))
        job.refresh_from_db()
        self.assertEqual(job.status, Job.DONE)

    def test_retry_is_post_only(self):
        job = Job.objects.create(kind=Job.INBOUND, status=Job.FAILED)
        response = self.client.get(reverse("ops_job_retry", args=[job.pk]))
        self.assertEqual(response.status_code, 405)


@override_settings(EMAIL_BACKEND=LOCMEM)
class TwoFactorResetTests(OpsBase):
    def test_reset_clears_both_devices_audits_and_emails_the_lawyer(self):
        response = self.client.post(reverse("ops_reset_2fa"))
        self.assertRedirects(response, reverse("ops"))
        self.assertFalse(TOTPDevice.objects.filter(user=self.lawyer).exists())
        self.assertFalse(StaticDevice.objects.filter(user=self.lawyer).exists())
        self.assertTrue(TOTPDevice.objects.filter(user=self.staff).exists())

        audit = AuditLog.objects.get(tool="2fa_reset")
        self.assertEqual(audit.args, {"operator": "ops"})
        self.assertEqual(audit.result, {"devices_removed": 2, "emailed": True})

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["abogado@example.com"])
        self.assertIn("dos pasos", mail.outbox[0].subject)

    def test_reset_without_a_lawyer_account_does_not_crash(self):
        self.lawyer.delete()
        response = self.client.post(reverse("ops_reset_2fa"), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No hay abogado configurado")

    def test_reset_without_an_email_still_resets_and_audits(self):
        self.lawyer.email = ""
        self.lawyer.save()
        self.client.post(reverse("ops_reset_2fa"))
        self.assertFalse(TOTPDevice.objects.filter(user=self.lawyer).exists())
        audit = AuditLog.objects.get(tool="2fa_reset")
        self.assertFalse(audit.result["emailed"])
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_is_post_only(self):
        response = self.client.get(reverse("ops_reset_2fa"))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(TOTPDevice.objects.filter(user=self.lawyer).exists())

    def test_non_staff_cannot_reset(self):
        self.client.logout()
        self.login(self.lawyer, self.lawyer_totp)
        self.client.post(reverse("ops_reset_2fa"))
        self.assertTrue(TOTPDevice.objects.filter(user=self.lawyer).exists())
        self.assertFalse(AuditLog.objects.filter(tool="2fa_reset").exists())
