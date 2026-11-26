import datetime
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.agenda import planner
from apps.agenda.models import Appointment, TravelBlock
from apps.assistant.models import Proposal, Thread
from apps.assistant.tools import TOOLS
from apps.core.models import BaseLocation, Case, Client

CARD = {
    "address_source": Appointment.PLACES,
    "address": "Av. Roma 12, Col. Roma",
    "location_name": "Centro Médico Roma",
    "lat": "19.416667",
    "lng": "-99.162001",
    "maps_url": "https://maps.google.com/?cid=1",
}

LINK = {
    "address_source": Appointment.LINK,
    "address": "frente al Soriana",
    "location_name": "frente al Soriana",
    "lat": None,
    "lng": None,
    "maps_url": "https://www.google.com/maps/search/?api=1&query=frente%20al%20Soriana",
}


def leg(minutes):
    return {"distance_m": 4000, "duration_in_traffic_s": minutes * 60}


class PlanVisitProposalTests(TestCase):
    """`plan_visit` proposes one card; nothing is written until confirm (PLAN §5.2)."""

    def setUp(self):
        BaseLocation.objects.create(label="Oficina", address="Allende 12", is_default=True)
        self.thread = Thread.objects.create(jid="5211@s.whatsapp.net")
        self.client = Client.objects.create(
            name="García", phone="+527711234567", jid="5211@s.whatsapp.net"
        )
        self.case = Case.objects.create(
            client=self.client,
            reference="EXP-2026-1",
            title="Despido injustificado",
            opened_on=datetime.date(2026, 11, 2),
        )
        self.tomorrow = (timezone.localtime() + datetime.timedelta(days=1)).replace(
            hour=11, minute=0, second=0, microsecond=0
        )

    def plan(self, **overrides):
        args = {"case_id": self.case.pk, "when": self.tomorrow.isoformat(), "address": "frente al Soriana"}
        args.update(overrides)
        return TOOLS["plan_visit"]["fn"](self.thread, **args)

    @mock.patch("apps.agenda.planner.maps.route")
    @mock.patch("apps.assistant.tools.maps.resolve")
    def test_a_resolved_card_is_proposed_and_nothing_is_written(self, resolve, route):
        resolve.return_value = CARD
        route.return_value = leg(32)

        result = self.plan()

        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(TravelBlock.objects.count(), 0)
        proposal = Proposal.objects.get(pk=result["proposal_id"])
        self.assertEqual(proposal.status, Proposal.PROPOSED)
        self.assertIn("Centro Médico Roma", proposal.summary)
        self.assertIn("Av. Roma 12, Col. Roma", proposal.summary)
        step = proposal.steps[0]
        self.assertEqual(step["tool"], "plan_visit")
        self.assertEqual(step["args"]["address_source"], Appointment.PLACES)
        self.assertEqual(step["args"]["lat"], "19.416667")
        self.assertEqual(step["args"]["travel_min"], 32)
        self.assertEqual(step["args"]["route_summary"]["distance_m"], 4000)
        self.assertEqual(step["args"]["origin"], "Allende 12")

    @mock.patch("apps.agenda.planner.maps.route")
    @mock.patch("apps.assistant.tools.maps.resolve")
    def test_the_last_resolved_address_is_reused_before_any_search(self, resolve, route):
        route.return_value = leg(20)
        Appointment.objects.create(
            client=self.client,
            title="Visita García",
            starts_at=timezone.now() - datetime.timedelta(days=30),
            address="Av. Roma 12, Col. Roma",
            location_name="Centro Médico Roma",
            address_source=Appointment.PLACES,
            lat="19.416667",
            lng="-99.162001",
        )

        result = self.plan(address="av. roma 12, col. roma ")

        resolve.assert_not_called()
        step = Proposal.objects.get(pk=result["proposal_id"]).steps[0]
        self.assertEqual(step["args"]["address"], "Av. Roma 12, Col. Roma")
        self.assertEqual(step["args"]["lat"], "19.416667")
        self.assertEqual(step["args"]["location_name"], "Centro Médico Roma")

    @mock.patch("apps.agenda.planner.maps.route")
    @mock.patch("apps.assistant.tools.maps.resolve")
    def test_without_a_last_address_it_searches_once(self, resolve, route):
        resolve.return_value = CARD
        route.return_value = leg(32)

        self.plan()

        resolve.assert_called_once_with("frente al Soriana")

    @mock.patch("apps.agenda.planner.maps.route")
    @mock.patch("apps.assistant.tools.maps.resolve")
    def test_a_link_card_offers_the_map_and_no_block(self, resolve, route):
        resolve.return_value = LINK

        result = self.plan()

        route.assert_not_called()
        proposal = Proposal.objects.get(pk=result["proposal_id"])
        self.assertIn("sin dirección verificada", proposal.summary)
        self.assertIn("google.com/maps/search", proposal.summary)
        self.assertNotIn("Salida:", proposal.summary)
        step = proposal.steps[0]
        self.assertEqual(step["args"]["address_source"], Appointment.LINK)
        self.assertIsNone(step["args"]["lat"])
        self.assertEqual(step["args"]["travel_min"], 0)

    @mock.patch("apps.agenda.planner.maps.route")
    @mock.patch("apps.assistant.tools.maps.resolve")
    def test_the_card_shows_when_to_leave(self, resolve, route):
        resolve.return_value = CARD
        route.return_value = leg(32)

        result = self.plan(kind="visita")

        summary = result["summary"]
        self.assertIn("11:00", summary)
        self.assertIn("Salida: 10:13 (32 min de traslado + 15 de margen)", summary)
        self.assertIn("¿La agendo?", summary)

    @mock.patch("apps.assistant.tools.maps.resolve")
    def test_a_past_hour_is_refused(self, resolve):
        past = (timezone.localtime() - datetime.timedelta(days=1)).isoformat()

        result = self.plan(when=past)

        self.assertIn("error", result)
        self.assertEqual(Proposal.objects.count(), 0)

    @mock.patch("apps.assistant.tools.maps.resolve")
    def test_an_unknown_argument_is_refused(self, resolve):
        result = self.plan(place_id="xyz")

        self.assertIn("error", result)

    @mock.patch("apps.agenda.planner.maps.route")
    @mock.patch("apps.assistant.tools.maps.resolve")
    def test_an_empty_address_with_no_history_asks_for_one(self, resolve, route):
        result = self.plan(address="")

        self.assertIn("error", result)
        resolve.assert_not_called()
        self.assertEqual(Proposal.objects.count(), 0)

    def test_the_tool_is_declared_with_its_schema(self):
        parameters = TOOLS["plan_visit"]["parameters"]

        self.assertIn("address", parameters["properties"])
        self.assertIn("when", parameters["required"])
        self.assertFalse(parameters["additionalProperties"])


class PlanVisitConfirmTests(TestCase):
    """The displayed card and block are written on confirm, and nothing before (PLAN §5.3)."""

    def setUp(self):
        BaseLocation.objects.create(label="Oficina", address="Allende 12", is_default=True)
        self.thread = Thread.objects.create(jid="5211@s.whatsapp.net")
        self.client = Client.objects.create(
            name="García", phone="+527711234567", jid="5211@s.whatsapp.net"
        )
        self.case = Case.objects.create(
            client=self.client,
            reference="EXP-2026-1",
            title="Despido injustificado",
            opened_on=datetime.date(2026, 11, 2),
        )
        self.starts_at = (timezone.localtime() + datetime.timedelta(days=1)).replace(
            hour=11, minute=0, second=0, microsecond=0
        )

    def propose(self, card=CARD, minutes=32):
        with mock.patch("apps.agenda.planner.maps.route") as route, mock.patch(
            "apps.assistant.tools.maps.resolve"
        ) as resolve:
            route.return_value = leg(minutes) if minutes else None
            resolve.return_value = card
            result = TOOLS["plan_visit"]["fn"](
                self.thread,
                case_id=self.case.pk,
                when=self.starts_at.isoformat(),
                address=card["address"],
            )
        return result["proposal_id"]

    def test_confirm_writes_the_card_and_the_block_without_a_second_route(self):
        proposal_id = self.propose()

        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(TravelBlock.objects.count(), 0)

        with mock.patch("apps.agenda.planner.maps.route") as route:
            result = TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal_id)

        route.assert_not_called()
        self.assertTrue(result["ok"])
        appointment = Appointment.objects.get()
        self.assertEqual(appointment.address, "Av. Roma 12, Col. Roma")
        self.assertEqual(appointment.address_source, Appointment.PLACES)
        self.assertEqual(appointment.location_name, "Centro Médico Roma")
        self.assertEqual(str(appointment.lat), "19.416667")
        self.assertEqual(str(appointment.lng), "-99.162001")
        self.assertEqual(appointment.travel_min, 32)
        block = appointment.travel_block
        self.assertEqual(block.starts_at, self.starts_at - datetime.timedelta(minutes=47))
        self.assertEqual(block.duration_min, 32)
        self.assertEqual(block.origin, "Allende 12")
        self.assertIn("Sales a las 10:13", result["text"])

    def test_cancel_writes_nothing(self):
        proposal_id = self.propose()

        TOOLS["cancel"]["fn"](self.thread, proposal_id=proposal_id)

        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(TravelBlock.objects.count(), 0)

    def test_a_link_confirm_has_no_block_and_says_so(self):
        proposal_id = self.propose(card=LINK, minutes=0)

        result = TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal_id)

        appointment = Appointment.objects.get()
        self.assertEqual(appointment.address_source, Appointment.LINK)
        self.assertIsNone(appointment.lat)
        self.assertEqual(appointment.travel_min, 0)
        self.assertFalse(TravelBlock.objects.filter(appointment=appointment).exists())
        self.assertIn("Sin dirección verificada", result["text"])

    def test_undo_removes_the_visit_and_its_block(self):
        proposal_id = self.propose()
        applied = TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal_id)

        TOOLS["undo"]["fn"](self.thread, proposal_id=applied["proposal_id"])

        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(TravelBlock.objects.count(), 0)


class RecomputeTests(TestCase):
    """A move, an address change and the brief regenerate the block (PLAN §7.3)."""

    def setUp(self):
        BaseLocation.objects.create(label="Oficina", address="Allende 12", is_default=True)
        self.thread = Thread.objects.create(jid="5211@s.whatsapp.net")
        self.now = timezone.localtime()

    @mock.patch("apps.agenda.planner.maps.route")
    def test_confirming_a_move_moves_the_block(self, route):
        route.return_value = leg(20)
        starts_at = (self.now + datetime.timedelta(days=1)).replace(
            hour=11, minute=0, second=0, microsecond=0
        )
        appointment = Appointment.objects.create(
            title="Visita",
            starts_at=starts_at,
            address="Av. Roma 12, Col. Roma",
            address_source=Appointment.PLACES,
            lat="19.416667",
            lng="-99.162001",
            buffer_min=15,
        )
        planner.compute_block(appointment)
        proposal = Proposal.objects.create(
            thread=self.thread,
            steps=[
                {
                    "tool": "reschedule",
                    "args": {
                        "appointment_id": appointment.pk,
                        "new_start": (starts_at + datetime.timedelta(hours=2)).isoformat(),
                    },
                }
            ],
            summary="Mueve la visita",
            expires_at=starts_at,
        )

        TOOLS["confirm"]["fn"](self.thread, proposal_id=proposal.pk)

        block = TravelBlock.objects.get(appointment=appointment)
        self.assertEqual(
            block.starts_at, starts_at + datetime.timedelta(minutes=120 - 35)
        )
        self.assertEqual(block.duration_min, 20)
