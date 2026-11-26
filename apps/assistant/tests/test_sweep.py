import datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.agenda.models import Deadline
from apps.core.models import Case, Client


class SweepDeadlineTests(TestCase):
    def setUp(self):
        client = Client.objects.create(
            name="García", phone="+527711234567", jid="5211@s.whatsapp.net"
        )
        self.case = Case.objects.create(
            client=client,
            reference="EXP-1",
            title="Laboral",
            opened_on=datetime.date(2026, 10, 1),
        )
        self.today = timezone.localdate()

    def deadline(self, day, status=Deadline.OPEN):
        return Deadline.objects.create(
            case=self.case, title=f"Plazo del {day}", due_date=day, status=status
        )

    def sweep(self):
        out = StringIO()
        call_command("sweep", stdout=out)
        return out.getvalue()

    def test_an_overdue_open_deadline_turns_missed(self):
        overdue = self.deadline(self.today - datetime.timedelta(days=1))
        self.sweep()
        overdue.refresh_from_db()
        self.assertEqual(overdue.status, Deadline.MISSED)

    def test_a_deadline_due_today_stays_open(self):
        due_today = self.deadline(self.today)
        self.sweep()
        due_today.refresh_from_db()
        self.assertEqual(due_today.status, Deadline.OPEN)

    def test_a_done_deadline_stays_done(self):
        done = self.deadline(self.today - datetime.timedelta(days=3), Deadline.DONE)
        self.sweep()
        done.refresh_from_db()
        self.assertEqual(done.status, Deadline.DONE)

    def test_it_reports_how_many_it_missed(self):
        self.deadline(self.today - datetime.timedelta(days=1))
        self.deadline(self.today - datetime.timedelta(days=10))
        self.assertIn("2", self.sweep())
