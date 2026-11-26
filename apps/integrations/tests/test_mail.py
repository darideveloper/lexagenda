import datetime
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from apps.agenda import services
from apps.agenda.models import Appointment
from apps.core.models import Case, Client

AT = timezone.make_aware(datetime.datetime(2026, 11, 26, 11, 0))


class InviteTests(TestCase):
    """One REQUEST per real change, to the lawyer only (PLAN §7.1)."""

    def setUp(self):
        self.lawyer = User.objects.create(
            username="abogado", email="abogado@despacho.mx"
        )
        self.client_row = Client.objects.create(
            name="García", phone="+527711234567", jid="5211@s.whatsapp.net", email="garcia@cliente.mx"
        )
        self.case = Case.objects.create(
            client=self.client_row,
            reference="EXP-1",
            title="Laboral",
            opened_on=datetime.date(2026, 11, 2),
        )

    def appointment(self):
        return services.create(
            case=self.case,
            client=self.client_row,
            title="Visita",
            starts_at=AT,
            address="Av. Juárez 100",
        )

    def test_create_mails_one_request_with_sequence_one(self):
        appointment = self.appointment()
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.lawyer.email])
        self.assertNotIn(self.client_row.email, message.to)
        filename, body, mimetype = message.attachments[0]
        self.assertEqual(filename, f"{appointment.ics_uid}.ics")
        self.assertIn("text/calendar", mimetype)
        self.assertIn("METHOD:REQUEST", body)
        self.assertIn(f"UID:{appointment.ics_uid}", body)
        self.assertIn("SEQUENCE:1", body)

    def test_a_move_mails_the_same_uid_one_sequence_higher(self):
        appointment = self.appointment()
        mail.outbox.clear()
        services.reschedule(appointment, AT + datetime.timedelta(hours=3))
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].attachments[0][1]
        self.assertIn(f"UID:{appointment.ics_uid}", body)
        self.assertIn("SEQUENCE:2", body)
        self.assertIn("DTSTART:20261126T200000Z", body)

    def test_cancel_mails_a_cancel_with_the_same_uid(self):
        appointment = self.appointment()
        mail.outbox.clear()
        services.cancel(appointment)
        body = mail.outbox[0].attachments[0][1]
        self.assertIn("METHOD:CANCEL", body)
        self.assertIn("STATUS:CANCELLED", body)
        self.assertIn(f"UID:{appointment.ics_uid}", body)
        self.assertIn("Cancelada", mail.outbox[0].subject)

    def test_readdress_mails_a_new_sequence(self):
        appointment = self.appointment()
        mail.outbox.clear()
        services.readdress(appointment, "Calle Nueva 20", "Juzgado 2°")
        body = mail.outbox[0].attachments[0][1]
        self.assertIn("SEQUENCE:2", body)
        self.assertIn("LOCATION:Calle Nueva 20", body)

    def test_no_change_no_mail(self):
        appointment = self.appointment()
        services.reschedule(appointment, AT)
        services.cancel(appointment)
        services.cancel(appointment)
        services.readdress(appointment, "Av. Juárez 100", "")
        # the second cancel and the no-op reads stay quiet; only the first cancel mailed
        self.assertEqual(len(mail.outbox), 2)

    def test_without_a_lawyer_email_the_write_still_stands(self):
        self.lawyer.email = ""
        self.lawyer.save()
        appointment = self.appointment()
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Appointment.objects.filter(pk=appointment.pk).count(), 1)

    @mock.patch("apps.integrations.mail.EmailMessage.send", side_effect=OSError("smtp caído"))
    def test_a_dead_smtp_never_undoes_the_change(self, _send):
        appointment = self.appointment()
        self.assertEqual(appointment.ics_sequence, 1)
        self.assertTrue(Appointment.objects.filter(pk=appointment.pk).exists())


class TravelRecomputeMailTests(TestCase):
    """The recompute changes times; the mail count never moves."""

    def setUp(self):
        User.objects.create(username="abogado", email="abogado@despacho.mx")

    @mock.patch("apps.agenda.day.maps.route")
    def test_simulating_the_day_sends_nothing(self, route):
        from apps.agenda import day
        from apps.core.models import BaseLocation

        BaseLocation.objects.create(label="Oficina", address="Calle 1", is_default=True)
        route.return_value = {"duration_in_traffic_s": 1800, "distanceMeters": 8000}
        services.create(
            title="Visita",
            starts_at=timezone.make_aware(
                datetime.datetime.combine(timezone.localdate(), datetime.time(11, 0))
            ),
            address="Av. Juárez 100",
        )
        mail.outbox.clear()
        day.simulate()
        day.simulate()
        self.assertEqual(len(mail.outbox), 0)
