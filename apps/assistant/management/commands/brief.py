"""`manage.py brief --kind=morning|evening` — pure template rendering (PLAN §8.1)."""

import datetime

from django.core.management.base import BaseCommand

from apps.assistant import brief
from apps.core import health


class Command(BaseCommand):
    help = "Render the morning or evening brief from the day simulation; no model call."

    def add_arguments(self, parser):
        parser.add_argument("--kind", default=brief.MORNING, choices=brief.KINDS)
        parser.add_argument("--date", default=None, help="YYYY-MM-DD; today by default")

    def handle(self, *args, **options):
        try:
            day = datetime.date.fromisoformat(options["date"]) if options["date"] else None
            text = brief.render(options["kind"], day)
        except Exception:
            health.ping("brief", ok=False)
            raise
        health.ping("brief")
        self.stdout.write(text)
