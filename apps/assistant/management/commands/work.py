from django.core.management.base import BaseCommand

from apps.assistant import worker


class Command(BaseCommand):
    help = "Drain queued inbound messages (timer: every minute)."

    def add_arguments(self, parser):
        parser.add_argument("--max-jobs", type=int, default=20)

    def handle(self, *args, **options):
        processed = 0
        while processed < options["max_jobs"] and worker.run_once():
            processed += 1
        self.stdout.write(f"work: {processed} job(s)")
