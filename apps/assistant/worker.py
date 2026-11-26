"""`manage.py work`: claim one job, transcribe or run the agent, send, stamp `replied_at` (PLAN D9)."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.assistant import agent
from apps.assistant.models import AuditLog, Job, Message, Proposal
from apps.channel.send import send_text
from apps.core.models import Case, Note
from apps.docs import storage
from apps.docs.models import InboundMedia
from apps.integrations import stt

MAX_ATTEMPTS = 3
AUDIO = "audio"

SAVED = "Guardé la nota en «{reference} — {title}»: «{text}»"
NO_CASE = "Le escuché la nota, pero no sé a qué expediente va. Dígame el expediente y la guardo."
OVER_CAP = "La nota dura más de dos minutos. Mándeme una más corta o escríbame lo importante."
UNREADABLE = "No pude escuchar esa nota. Mándemela otra vez o escríbame lo importante."


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

    if job.payload.get("kind") == AUDIO and job.payload.get("media_id"):
        return _voice_note(job, message)

    reply = agent.run(message.thread, message.text, exclude_pk=message.pk)
    send_text(message.thread.jid, reply)
    _stamp(message)
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


def _voice_note(job, message):
    """Transcribe one voice note into one `Note(source=voice)`; a refusal is a single line (§6.4).

    A refusal answers and finishes the job instead of raising: retrying an audio file that is
    unreadable or too long only burns three minutes of CPU to say the same sentence.
    """
    media = InboundMedia.objects.filter(pk=job.payload.get("media_id")).first()
    if media is None or media.purged_at is not None:
        return _answer(job, message, UNREADABLE)

    case = _case_in_context(message.thread, job.payload.get("case_id"))
    if case is None:
        return _answer(job, message, NO_CASE)

    try:
        text, model = stt.transcribe(storage.abs_path(media.path))
    except stt.TooLong:
        return _answer(job, message, OVER_CAP)
    except stt.Unreadable:
        return _answer(job, message, UNREADABLE)

    Note.objects.get_or_create(
        media=media,
        defaults={
            "case": case,
            "body": text,
            "source": Note.VOICE,
            "transcript_model": model,
        },
    )
    return _answer(
        job,
        message,
        SAVED.format(reference=case.reference, title=case.title, text=text),
        spoken=text,
    )


def _case_in_context(thread, case_id):
    """The job's case, else the one the thread last talked about, else the only open one."""
    if case_id:
        return Case.objects.filter(pk=case_id).first()

    audit = (
        AuditLog.objects.filter(thread=thread)
        .exclude(args__case_id=None)
        .order_by("-created_at")
        .first()
    )
    case = Case.objects.filter(pk=(audit.args or {}).get("case_id")).first() if audit else None
    if case is not None:
        return case

    for proposal in Proposal.objects.filter(thread=thread).order_by("-created_at")[:10]:
        for step in proposal.steps or []:
            case_id = (step.get("args") or {}).get("case_id")
            case = Case.objects.filter(pk=case_id).first() if case_id else None
            if case is not None:
                return case

    open_cases = Case.objects.filter(status=Case.OPEN)
    return open_cases.first() if open_cases.count() == 1 else None


def _answer(job, message, text, spoken=None):
    send_text(message.thread.jid, text)
    _stamp(message, spoken=spoken)
    _finish(job)
    return True


def _stamp(message, spoken=None):
    """The reply is out; a voice note also keeps its transcript as the message text."""
    message.replied_at = timezone.now()
    fields = ["replied_at"]
    if spoken is not None:
        message.text = spoken
        fields.append("text")
    message.save(update_fields=fields)
    message.thread.last_activity_at = message.replied_at
    message.thread.save(update_fields=["last_activity_at"])


def _finish(job):
    job.status = Job.DONE
    job.error = ""
    job.save(update_fields=["status", "error"])
