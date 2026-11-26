from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.agenda.models import Deadline
from apps.assistant.models import Proposal


class Command(BaseCommand):
    help = "Mark overdue deadlines missed and expire unanswered proposals (timers)."

    def handle(self, *args, **options):
        missed = Deadline.objects.filter(
            status=Deadline.OPEN, due_date__lt=timezone.localdate()
        ).update(status=Deadline.MISSED)
        expired = Proposal.objects.filter(
            status=Proposal.PROPOSED, expires_at__lte=timezone.now()
        ).update(status=Proposal.EXPIRED)
        self.stdout.write(f"sweep: {missed} plazo(s) vencido(s)")
        self.stdout.write(f"sweep: {expired} propuesta(s) caducada(s)")
