import datetime

from django.apps import apps
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.agenda.models import Appointment, Deadline
from apps.assistant.models import AuditLog, Job, Message, Thread
from apps.core.models import BaseLocation, Case, Client

DOMAIN = {
    "BaseLocation",
    "Client",
    "Case",
    "Appointment",
    "Deadline",
    "Thread",
    "Message",
    "Job",
    "AuditLog",
}


class ModelSetTests(TestCase):
    def test_exactly_the_domain_models(self):
        found = {
            m.__name__
            for m in apps.get_models()
            if m._meta.app_label in {"core", "agenda", "assistant"}
        }
        self.assertEqual(found, DOMAIN)

    def test_no_missing_migrations(self):
        call_command("makemigrations", "--check", "--dry-run", verbosity=0)

    def test_one_default_base_location(self):
        BaseLocation.objects.create(label="Oficina", address="Calle 1", is_default=True)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BaseLocation.objects.create(label="Casa", address="Calle 2", is_default=True)

    def test_case_hangs_off_a_client(self):
        client = Client.objects.create(name="García", phone="+527711234567", jid="5211@s.whatsapp.net")
        case = Case.objects.create(
            client=client,
            reference="EXP-1",
            title="Laboral",
            opened_on=datetime.date(2026, 11, 2),
        )
        self.assertEqual(case.status, Case.OPEN)
        self.assertEqual(client.cases.get(), case)
