import datetime
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.agenda.models import Appointment
from apps.assistant import brief
from apps.core.models import BaseLocation

DAY = datetime.date(2026, 11, 26)


def at(day, hour, minute=0):
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(hour, minute)))


def leg(minutes):
    return {"distance_m": 12400, "duration_in_traffic_s": minutes * 60}


class BriefTests(TestCase):
    def setUp(self):
        BaseLocation.objects.create(label="Oficina", address="Allende 12", is_default=True)

    @mock.patch("apps.agenda.day.maps.route")
    def test_morning_names_each_stop_and_its_departure(self, route):
        route.side_effect = [leg(38), leg(22)]
        Appointment.objects.create(
            title="García",
            address="Centro",
            starts_at=at(DAY, 9, 30),
            buffer_min=7,
            duration_min=60,
        )
        Appointment.objects.create(
            title="Audiencia", address="Juzgado 4°", starts_at=at(DAY, 11, 0), duration_min=90
        )

        text = brief.render("morning", DAY)

        self.assertIn("Hoy tienes 2 compromisos", text)
        self.assertIn("09:30  Visita — García", text)
        self.assertIn("Sal de Oficina a las 08:45 (38 min de traslado + 7 de margen)", text)
        self.assertIn("Traslado desde la anterior: 22 min", text)

    @mock.patch("apps.agenda.day.maps.route")
    def test_morning_says_sin_direccion_once(self, route):
        route.return_value = leg(20)
        Appointment.objects.create(title="Junta", starts_at=at(DAY, 12, 0))
        Appointment.objects.create(
            title="Visita", address="Centro", starts_at=at(DAY, 9, 0), duration_min=60
        )

        text = brief.render("morning", DAY)

        self.assertEqual(text.count("Sin dirección"), 1)

    @mock.patch("apps.agenda.day.maps.route")
    def test_morning_flags_the_impossible_stop(self, route):
        route.return_value = leg(40)
        Appointment.objects.create(
            title="Visita", address="Centro", starts_at=at(DAY, 9, 30), duration_min=60
        )
        Appointment.objects.create(
            title="Junta", address="Otra", starts_at=at(DAY, 10, 0), duration_min=60
        )

        text = brief.render("morning", DAY)

        self.assertIn("Ojo:", text)
        self.assertIn("70 min tarde", text)

    @mock.patch("apps.agenda.day.maps.route")
    def test_a_degraded_leg_reads_sin_calculo_de_traslado(self, route):
        route.return_value = None
        Appointment.objects.create(title="Visita", address="Centro", starts_at=at(DAY, 9, 30))

        text = brief.render("morning", DAY)

        self.assertIn("sin cálculo de traslado", text)

    @mock.patch("apps.agenda.day.maps.route")
    def test_an_empty_day_says_so(self, route):
        text = brief.render("morning", DAY)

        self.assertIn("Hoy no tienes compromisos", text)
        route.assert_not_called()

    @mock.patch("apps.agenda.day.maps.route")
    def test_evening_previews_tomorrow(self, route):
        route.return_value = leg(30)
        Appointment.objects.create(
            title="Visita", address="Centro", starts_at=at(DAY + datetime.timedelta(days=1), 9, 0)
        )

        text = brief.render("evening", DAY)

        self.assertIn("Mañana", text)
        self.assertIn("Visita", text)

    @mock.patch("apps.integrations.llm.chat")
    @mock.patch("apps.agenda.day.maps.route")
    def test_both_briefs_render_without_a_model_call(self, route, chat):
        route.return_value = leg(20)
        Appointment.objects.create(
            title="Visita", address="Centro", starts_at=at(DAY, 9, 30), duration_min=30
        )

        brief.render("morning", DAY)
        brief.render("evening", DAY)

        chat.assert_not_called()

    @mock.patch("apps.integrations.llm.chat")
    @mock.patch("apps.agenda.day.maps.route")
    def test_the_command_prints_the_morning_brief(self, route, chat):
        route.return_value = leg(20)
        Appointment.objects.create(
            title="Visita", address="Centro", starts_at=at(DAY, 9, 30), duration_min=30
        )
        out = StringIO()

        call_command("brief", "--kind=morning", date=DAY.isoformat(), stdout=out)

        self.assertIn("Buenos días", out.getvalue())
        self.assertIn("Visita", out.getvalue())
        chat.assert_not_called()

    def test_an_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError):
            brief.render("noon", DAY)
