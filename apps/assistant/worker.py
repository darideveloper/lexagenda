"""`manage.py work`: claim one job, run the agent, send, stamp `replied_at` (PLAN.md D9)."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.assistant import agent
from apps.assistant.models import Job, Message
from apps.channel.send import send_text

MAX_ATTEMPTS = 3


def claim_next():
    with transaction.atomic():
        job = (
            Job.objects.select_for_update(skip_locked=True)
            .filter(status=Job.QUEUED, run_after__lte=timezone.now())
            .order_by("run_after", "id")
            .first()
        )
        if job is None:
            return None
        job.status = Job.RUNNING
        job.attempts += 1
        job.locked_at = timezone.now()
        job.save(update_fields=["status", "attempts", "locked_at"])
        return job


def process(job):
    message = Message.objects.select_related("thread").get(pk=job.payload["message_id"])
    if message.replied_at is not None:
        _finish(job)
        return False

    reply = agent.run(message.thread, message.text, exclude_pk=message.pk)
    send_text(message.thread.jid, reply)
    message.replied_at = timezone.now()
    message.save(update_fields=["replied_at"])
    message.thread.last_activity_at = message.replied_at
    message.thread.save(update_fields=["last_activity_at"])
    _finish(job)
    return True


def run_once():
    job = claim_next()
    if job is None:
        return False
    try:
        process(job)
    except Exception as exc:
        job.error = f"{type(exc).__name__}: {exc}"[:2000]
        if job.attempts < MAX_ATTEMPTS:
            job.status = Job.QUEUED
            job.run_after = timezone.now() + timedelta(minutes=job.attempts)
        else:
            job.status = Job.FAILED
        job.save(update_fields=["error", "status", "run_after"])
    return True


def _finish(job):
    job.status = Job.DONE
    job.error = ""
    job.save(update_fields=["status", "error"])
