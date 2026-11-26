from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.agenda.models import Deadline


class Command(BaseCommand):
    help = "Mark overdue open deadlines missed (timer: once a day)."

    def handle(self, *args, **options):
        missed = Deadline.objects.filter(
            status=Deadline.OPEN, due_date__lt=timezone.localdate()
        ).update(status=Deadline.MISSED)
        self.stdout.write(f"sweep: {missed} plazo(s) vencido(s)")
