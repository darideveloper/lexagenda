from django.conf import settings
from django.test import SimpleTestCase

import yaml

from apps.assistant.tools import TOOLS

DECISIONS = ["confirm", "cancel", "nothing"]


class CanaryTests(SimpleTestCase):
    """The 20 + 20 corpus exists and names only tools and decisions that exist (PLAN.md §5.6)."""

    def setUp(self):
        path = settings.BASE_DIR / "apps" / "assistant" / "canaries.yaml"
        self.canaries = yaml.safe_load(path.read_text())

    def test_twenty_requests_to_route_and_twenty_replies_to_decide(self):
        self.assertEqual(len(self.canaries["route"]), 20)
        self.assertEqual(len(self.canaries["decide"]), 20)

    def test_every_route_names_a_real_tool_and_every_required_argument(self):
        for item in self.canaries["route"]:
            self.assertIn(item["tool"], TOOLS, item["request"])
            parameters = TOOLS[item["tool"]]["parameters"]
            self.assertEqual(
                sorted(item["args"]), sorted(parameters.get("required", [])), item["request"]
            )
            self.assertIn(item["request"], item["request"])

    def test_every_decision_is_confirm_cancel_or_nothing(self):
        for item in self.canaries["decide"]:
            self.assertIn(item["decision"], DECISIONS, item["request"])

    def test_the_three_decisions_are_all_exercised(self):
        self.assertEqual({item["decision"] for item in self.canaries["decide"]}, set(DECISIONS))

    def test_no_duplicate_prompts(self):
        route = [item["request"] for item in self.canaries["route"]]
        decide = [item["request"] for item in self.canaries["decide"]]
        self.assertEqual(len(route), len(set(route)))
        self.assertEqual(len(decide), len(set(decide)))
