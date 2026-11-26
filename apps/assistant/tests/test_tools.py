import datetime

from django.test import TestCase
from django.utils import timezone

from apps.agenda.models import Appointment
from apps.assistant.models import Thread
from apps.assistant.tools import TOOLS, schemas
from apps.core.models import Case, Client


class ToolTests(TestCase):
    def setUp(self):
        self.thread = Thread.objects.create(jid="521771234567@s.whatsapp.net")
        self.client_obj = Client.objects.create(
            name="García", phone="+527711234567", jid="5211@s.whatsapp.net"
        )
        self.case = Case.objects.create(
            client=self.client_obj,
            reference="EXP-2026-1",
            title="Despido injustificado",
            opened_on=datetime.date(2026, 11, 2),
        )

    def test_agenda_today_lists_only_today(self):
        today = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        Appointment.objects.create(
            case=self.case,
            client=self.client_obj,
            title="Visita García",
            starts_at=today + datetime.timedelta(hours=9, minutes=30),
            location_name="Colonia Centro",
        )
        Appointment.objects.create(
            title="Mañana",
            starts_at=today + datetime.timedelta(days=1, hours=9),
        )

        result = TOOLS["agenda_today"]["fn"](self.thread)

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["date"], today.date().isoformat())
        self.assertEqual(result["appointments"][0]["time"], "09:30")
        self.assertEqual(result["appointments"][0]["client"], "García")

    def test_case_search_by_client_name_and_reference(self):
        by_name = TOOLS["case_search"]["fn"](self.thread, query="garc")
        by_ref = TOOLS["case_search"]["fn"](self.thread, query="2026-1")

        self.assertEqual([c["name"] for c in by_name["clients"]], ["García"])
        self.assertEqual([c["reference"] for c in by_ref["cases"]], ["EXP-2026-1"])

    def test_case_summary_has_client_status_and_next_appointment(self):
        Appointment.objects.create(
            case=self.case,
            title="Audiencia",
            starts_at=timezone.now() + datetime.timedelta(days=2),
        )

        result = TOOLS["case_summary"]["fn"](self.thread, case_id=self.case.pk)

        self.assertEqual(result["reference"], "EXP-2026-1")
        self.assertEqual(result["client"]["name"], "García")
        self.assertEqual(result["status"], Case.OPEN)
        self.assertEqual(result["next_appointment"]["title"], "Audiencia")

    def test_case_summary_unknown_id_is_an_error_not_a_crash(self):
        result = TOOLS["case_summary"]["fn"](self.thread, case_id=999999)

        self.assertIn("error", result)

    def test_three_tools_are_exported_as_openai_schemas(self):
        names = [schema["function"]["name"] for schema in schemas()]

        self.assertEqual(names, ["agenda_today", "case_search", "case_summary"])
        for schema in schemas():
            self.assertEqual(schema["function"]["parameters"]["type"], "object")
