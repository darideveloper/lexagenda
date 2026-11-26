import datetime

from django.test import TestCase
from django.utils import timezone

from apps.agenda.models import Appointment, Deadline
from apps.assistant.models import Proposal, Thread
from apps.assistant.tools import TOOLS
from apps.core.models import Case, Client


class WriteToolTests(TestCase):
    """A write tool proposes; it never mutates (PLAN.md §5.2, §5.3)."""

    def setUp(self):
        self.thread = Thread.objects.create(jid="5211@s.whatsapp.net")
        self.client_obj = Client.objects.create(
            name="García", phone="+527711234567", jid="5211@s.whatsapp.net"
        )
        self.case = Case.objects.create(
            client=self.client_obj,
            reference="EXP-2026-1",
            title="Despido injustificado",
            opened_on=datetime.date(2026, 11, 2),
        )
        self.tomorrow = (timezone.localtime() + datetime.timedelta(days=1)).replace(
            hour=9, minute=30, second=0, microsecond=0
        )

    def test_appointment_create_proposes_and_writes_nothing(self):
        result = TOOLS["appointment_create"]["fn"](
            self.thread,
            title="Visita García",
            when=self.tomorrow.isoformat(),
            location_name="Colonia Centro",
        )

        self.assertEqual(Appointment.objects.count(), 0)
        proposal = Proposal.objects.get(pk=result["proposal_id"])
        self.assertEqual(proposal.status, Proposal.PROPOSED)
        self.assertEqual(proposal.summary, result["summary"])
        self.assertIn("Nueva cita: «Visita García»", proposal.summary)
        self.assertIn("¿La agendo?", proposal.summary)
        self.assertEqual(proposal.steps[0]["tool"], "appointment_create")
        self.assertEqual(proposal.steps[0]["args"]["duration_min"], 60)

    def test_appointment_create_uses_the_kind_defaults_and_takes_the_case(self):
        result = TOOLS["appointment_create"]["fn"](
            self.thread,
            title="Audiencia",
            when=self.tomorrow.isoformat(),
            kind="audiencia",
            case_id=self.case.pk,
        )

        args = Proposal.objects.get(pk=result["proposal_id"]).steps[0]["args"]
        self.assertEqual(args["duration_min"], 90)
        self.assertEqual(args["buffer_min"], 30)
        self.assertEqual(args["case_id"], self.case.pk)
        self.assertEqual(args["client_id"], self.client_obj.pk)

    def test_confirming_an_appointment_create_inserts_it(self):
        result = TOOLS["appointment_create"]["fn"](
            self.thread, title="Visita García", when=self.tomorrow.isoformat()
        )

        TOOLS["confirm"]["fn"](self.thread, proposal_id=result["proposal_id"])

        appointment = Appointment.objects.get()
        self.assertEqual(appointment.title, "Visita García")
        self.assertEqual(timezone.localtime(appointment.starts_at).hour, 9)

    def test_appointment_create_refuses_a_past_hour_and_an_unknown_kind(self):
        past = (timezone.now() - datetime.timedelta(hours=1)).isoformat()

        late = TOOLS["appointment_create"]["fn"](self.thread, title="X", when=past)
        unknown = TOOLS["appointment_create"]["fn"](
            self.thread, title="X", when=self.tomorrow.isoformat(), kind="boda"
        )

        self.assertIn("error", late)
        self.assertIn("error", unknown)
        self.assertEqual(Proposal.objects.count(), 0)

    def test_a_second_write_supersedes_the_first(self):
        first = TOOLS["appointment_create"]["fn"](
            self.thread, title="Visita", when=self.tomorrow.isoformat()
        )
        second = TOOLS["appointment_create"]["fn"](
            self.thread, title="Junta", when=self.tomorrow.isoformat()
        )

        self.assertEqual(Proposal.objects.get(pk=first["proposal_id"]).status, Proposal.SUPERSEDED)
        self.assertEqual(Proposal.objects.filter(status=Proposal.PROPOSED).count(), 1)
        self.assertIn("quedó sin efecto", second["summary"])

    def test_the_proposal_expires_at_the_appointment_start_when_it_comes_first(self):
        soon = (timezone.now() + datetime.timedelta(hours=2)).replace(second=0, microsecond=0)

        result = TOOLS["appointment_create"]["fn"](
            self.thread, title="Visita", when=soon.isoformat()
        )

        proposal = Proposal.objects.get(pk=result["proposal_id"])
        self.assertEqual(proposal.expires_at.timestamp(), soon.timestamp())


class RescheduleToolTests(TestCase):
    def setUp(self):
        self.thread = Thread.objects.create(jid="5211@s.whatsapp.net")
        self.start = (timezone.localtime() + datetime.timedelta(days=1)).replace(
            hour=17, minute=0, second=0, microsecond=0
        )
        self.appointment = Appointment.objects.create(
            title="Visita García", starts_at=self.start, duration_min=60
        )

    def test_reschedule_proposes_without_moving(self):
        new_start = self.start + datetime.timedelta(days=1)

        result = TOOLS["reschedule"]["fn"](
            self.thread,
            appointment_id=self.appointment.pk,
            new_start=new_start.isoformat(),
        )

        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.starts_at, self.start)
        self.assertIn("Mueve: «Visita García»", result["summary"])
        self.assertIn("¿La muevo?", result["summary"])

    def test_reschedule_names_the_collision(self):
        Appointment.objects.create(
            title="Junta Peralta",
            starts_at=self.start + datetime.timedelta(minutes=30),
            duration_min=60,
        )

        result = TOOLS["reschedule"]["fn"](
            self.thread,
            appointment_id=self.appointment.pk,
            new_start=(self.start + datetime.timedelta(days=1)).isoformat(),
        )
        self.assertNotIn("No cabe", result["summary"])

        other = Appointment.objects.create(
            title="Junta Peralta",
            starts_at=self.start + datetime.timedelta(days=1, minutes=30),
            duration_min=60,
        )
        result = TOOLS["reschedule"]["fn"](
            self.thread,
            appointment_id=self.appointment.pk,
            new_start=(self.start + datetime.timedelta(days=1)).isoformat(),
        )

        self.assertIn(f"«{other.title}»", result["summary"])

    def test_reschedule_refuses_an_unknown_appointment(self):
        result = TOOLS["reschedule"]["fn"](
            self.thread, appointment_id=999999, new_start=self.start.isoformat()
        )

        self.assertIn("error", result)
        self.assertEqual(Proposal.objects.count(), 0)


class DeadlineToolTests(TestCase):
    def setUp(self):
        self.thread = Thread.objects.create(jid="5211@s.whatsapp.net")
        client = Client.objects.create(
            name="Peralta", phone="+527719999999", jid="5219@s.whatsapp.net"
        )
        self.case = Case.objects.create(
            client=client,
            reference="EXP-2026-2",
            title="Laboral",
            opened_on=datetime.date(2026, 11, 2),
        )

    def test_deadline_create_computes_with_the_calendar_union_and_says_verifica(self):
        result = TOOLS["deadline_create"]["fn"](
            self.thread,
            case_id=self.case.pk,
            title="Contestación demanda",
            notified_on="2026-11-03",
            term_value=20,
            term_unit="dias_habiles",
        )

        self.assertIn("Vence el jue 3 dic 2026", result["summary"])
        self.assertIn("calculado (20 días hábiles desde notificación mar 3 nov 2026)", result["summary"])
        self.assertIn("verifica", result["summary"])
        self.assertIn("¿Lo apunto?", result["summary"])
        self.assertNotIn("sin calendario", result["summary"])
        step = Proposal.objects.get(pk=result["proposal_id"]).steps[0]
        self.assertEqual(step["tool"], "deadline_create")
        self.assertEqual(step["args"]["notified_on"], "2026-11-03")
        self.assertEqual(step["args"]["term_unit"], "dias_habiles")
        self.assertNotIn("due_date", step["args"])

    def test_natural_days_and_months_apply_the_prologue(self):
        natural = TOOLS["deadline_create"]["fn"](
            self.thread,
            case_id=self.case.pk,
            title="X",
            notified_on="2026-11-06",
            term_value=1,
            term_unit="dias_naturales",
        )
        months = TOOLS["deadline_create"]["fn"](
            self.thread,
            case_id=self.case.pk,
            title="Y",
            notified_on="2026-10-31",
            term_value=1,
            term_unit="meses",
        )

        self.assertIn("Vence el lun 9 nov 2026", natural["summary"])
        self.assertIn("Vence el lun 30 nov 2026", months["summary"])

    def test_confirming_a_deadline_create_inserts_a_computed_deadline(self):
        result = TOOLS["deadline_create"]["fn"](
            self.thread,
            case_id=self.case.pk,
            title="Contestación demanda",
            notified_on="2026-11-03",
            term_value=20,
            term_unit="dias_habiles",
        )

        confirmation = TOOLS["confirm"]["fn"](self.thread, proposal_id=result["proposal_id"])

        self.assertTrue(confirmation["ok"])
        deadline = Deadline.objects.get()
        self.assertEqual(deadline.due_date, datetime.date(2026, 12, 3))
        self.assertTrue(deadline.computed)
        self.assertEqual(deadline.case, self.case)

    def test_undo_of_a_deadline_removes_it(self):
        result = TOOLS["deadline_create"]["fn"](
            self.thread,
            case_id=self.case.pk,
            title="X",
            notified_on="2026-11-03",
            term_value=20,
            term_unit="dias_habiles",
        )
        TOOLS["confirm"]["fn"](self.thread, proposal_id=result["proposal_id"])

        TOOLS["undo"]["fn"](self.thread, proposal_id=result["proposal_id"])

        self.assertEqual(Deadline.objects.count(), 0)

    def test_deadline_create_refuses_an_unknown_case_or_unit(self):
        unknown_case = TOOLS["deadline_create"]["fn"](
            self.thread,
            case_id=999999,
            title="X",
            notified_on="2026-11-03",
            term_value=20,
            term_unit="dias_habiles",
        )
        unknown_unit = TOOLS["deadline_create"]["fn"](
            self.thread,
            case_id=self.case.pk,
            title="X",
            notified_on="2026-11-03",
            term_value=20,
            term_unit="semanas",
        )

        self.assertIn("error", unknown_case)
        self.assertIn("error", unknown_unit)
        self.assertEqual(Proposal.objects.count(), 0)
