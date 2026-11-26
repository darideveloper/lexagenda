"""The proposal envelope (PLAN.md §5.3, D7).

A write tool validates its arguments and stores what it *would* do; nothing in the
domain is touched until `confirm` applies the stored steps in plain Python.
"""

from datetime import date, datetime, timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.assistant.models import Proposal

TTL = timedelta(hours=12)
UNDO_TTL = timedelta(hours=24)
SUPERSEDED_LINE = "La propuesta anterior quedó sin efecto."


class ProposalError(RuntimeError):
    """The stored steps cannot be applied; the transaction keeps nothing."""


def propose(thread, *, steps, summary, outbound_text="", expires_at=None, source=Proposal.CHAT):
    """Store one open proposal, superseding the thread's previous one. Writes no domain row."""
    now = timezone.now()
    expires = min(now + TTL, expires_at) if expires_at else now + TTL
    with transaction.atomic():
        superseded = Proposal.objects.filter(thread=thread, status=Proposal.PROPOSED).update(
            status=Proposal.SUPERSEDED
        )
        summary = summary if not superseded else f"{summary}\n\n{SUPERSEDED_LINE}"
        return Proposal.objects.create(
            thread=thread,
            steps=steps,
            summary=summary,
            outbound_text=outbound_text,
            source=source,
            expires_at=expires,
        )


def open_proposal(thread):
    return Proposal.objects.filter(thread=thread, status=Proposal.PROPOSED).first()


def confirm(thread, proposal_id):
    """Apply the stored steps of one proposal. No argument beyond its id reaches the payload."""
    with transaction.atomic():
        proposal = _locked(thread, proposal_id)
        if proposal is None:
            return _reply(False, "No encuentro esa propuesta.")
        if proposal.status == Proposal.COMMITTED:
            return _reply(True, "Ya estaba hecho.", proposal, duplicate=True)
        if proposal.status != Proposal.PROPOSED:
            return _reply(False, f"Esa propuesta ya no está abierta ({proposal.get_status_display()}).", proposal)
        if proposal.expires_at <= timezone.now():
            _close(proposal, Proposal.EXPIRED)
            return _reply(False, "Esa propuesta caducó. Dime otra vez qué quieres y la preparo.", proposal)

        inverse, texts = [], []
        try:
            with transaction.atomic():
                for step in proposal.steps:
                    applier = APPLIERS.get(step.get("tool"))
                    if applier is None:
                        raise ProposalError(f"paso desconocido: {step.get('tool')}")
                    result, undo_steps, text = applier(step.get("args") or {})
                    inverse.extend(undo_steps)
                    texts.append(text)
        except (ProposalError, ObjectDoesNotExist, KeyError, TypeError, ValueError) as exc:
            proposal.status = Proposal.FAILED
            proposal.result = {"error": str(exc)}
            proposal.save(update_fields=["status", "result", "updated_at"])
            return _reply(False, f"No pude aplicarlo: {exc}", proposal)

        proposal.status = Proposal.COMMITTED
        proposal.committed_at = timezone.now()
        proposal.result = {"text": "\n".join(texts), "undo": inverse}
        proposal.save(update_fields=["status", "committed_at", "result", "updated_at"])
        return _reply(True, "\n".join(texts), proposal)


def cancel(thread, proposal_id):
    with transaction.atomic():
        proposal = _locked(thread, proposal_id)
        if proposal is None:
            return _reply(False, "No encuentro esa propuesta.")
        if proposal.status == Proposal.CANCELLED:
            return _reply(True, "Ya estaba cancelada.", proposal)
        if proposal.status != Proposal.PROPOSED:
            return _reply(
                False,
                f"No puedo cancelarla: ya está {proposal.get_status_display().lower()}.",
                proposal,
            )
        _close(proposal, Proposal.CANCELLED)
        return _reply(True, "Cancelado. No cambié nada.", proposal)


def undo(thread, proposal_id):
    """Build the compensating proposal and commit it at once (PLAN.md §5.3.6)."""
    with transaction.atomic():
        original = _locked(thread, proposal_id)
        if original is None:
            return _reply(False, "No encuentro esa propuesta.")
        if original.status != Proposal.COMMITTED:
            return _reply(False, "Esa propuesta no llegó a aplicarse; no hay nada que deshacer.", original)
        if timezone.now() - original.committed_at > UNDO_TTL:
            return _reply(False, "Ya pasaron más de 24 horas; no puedo deshacerlo solo.", original)
        inverse = (original.result or {}).get("undo") or []
        if not inverse:
            return _reply(False, "Esa propuesta no dejó nada que deshacer.", original)

        compensation = Proposal.objects.create(
            thread=thread,
            steps=inverse,
            summary=f"Deshacer: {original.summary}",
            status=Proposal.COMMITTED,
            expires_at=timezone.now(),
            committed_at=timezone.now(),
            undo_of=original,
        )
        texts = []
        try:
            with transaction.atomic():
                for step in inverse:
                    applier = APPLIERS.get(step.get("tool"))
                    if applier is None:
                        raise ProposalError(f"paso desconocido: {step.get('tool')}")
                    _, _, text = applier(step.get("args") or {})
                    texts.append(text)
        except (ProposalError, ObjectDoesNotExist, KeyError, TypeError, ValueError) as exc:
            compensation.status = Proposal.FAILED
            compensation.result = {"error": str(exc)}
            compensation.save(update_fields=["status", "result", "updated_at"])
            return _reply(False, f"No pude deshacerlo: {exc}", original)

        original.status = Proposal.UNDONE
        original.save(update_fields=["status", "updated_at"])
        compensation.result = {"text": "\n".join(texts), "undo": []}
        compensation.save(update_fields=["result", "updated_at"])
        return _reply(True, "\n".join(texts), compensation)


# --- appliers: the only code that mutates during a commit -------------------


def _apply_appointment_create(args):
    from apps.agenda import services
    from apps.agenda.models import Appointment

    starts_at = parse_when(args["starts_at"])
    appointment = services.create(
        title=args["title"],
        kind=args.get("kind") or Appointment.VISITA,
        starts_at=starts_at,
        duration_min=int(args.get("duration_min") or 60),
        location_name=args.get("location_name") or "",
        address=args.get("address") or "",
        buffer_min=int(args.get("buffer_min") or 0),
        case_id=args.get("case_id") or None,
        client_id=args.get("client_id") or None,
    )
    text = f"Listo: agendé «{appointment.title}» el {format_when(starts_at)}."
    return (
        {"appointment_id": appointment.pk},
        [{"tool": "appointment_delete", "args": {"appointment_id": appointment.pk}}],
        text,
    )


def _apply_appointment_delete(args):
    from apps.agenda.models import Appointment

    Appointment.objects.filter(pk=args["appointment_id"]).delete()
    return {"deleted": args["appointment_id"]}, [], "Quité la cita que había creado."


def _apply_reschedule(args):
    from apps.agenda import planner, services
    from apps.agenda.models import Appointment

    appointment = Appointment.objects.get(pk=args["appointment_id"])
    previous = appointment.starts_at
    services.reschedule(appointment, parse_when(args["new_start"]))
    planner.recompute(appointment)
    text = f"Listo: moví «{appointment.title}» al {format_when(appointment.starts_at)}."
    return (
        {"appointment_id": appointment.pk, "starts_at": appointment.starts_at.isoformat()},
        [
            {
                "tool": "reschedule",
                "args": {"appointment_id": appointment.pk, "new_start": previous.isoformat()},
            }
        ],
        text,
    )


def _apply_plan_visit(args):
    from apps.agenda import planner, services
    from apps.agenda.models import Appointment

    starts_at = parse_when(args["starts_at"])
    appointment = services.create(
        title=args["title"],
        kind=args.get("kind") or Appointment.VISITA,
        starts_at=starts_at,
        duration_min=int(args.get("duration_min") or 60),
        buffer_min=int(args.get("buffer_min") or 0),
        location_name=args.get("location_name") or "",
        address=args.get("address") or "",
        address_source=args.get("address_source") or Appointment.NONE,
        lat=args.get("lat"),
        lng=args.get("lng"),
        travel_min=int(args.get("travel_min") or 0),
        case_id=args.get("case_id") or None,
        client_id=args.get("client_id") or None,
    )
    # The block was shown in the proposal: write it as read, never a second route.
    block = planner.compute_block(
        appointment,
        origin=args.get("origin") or None,
        travel_min=int(args.get("travel_min") or 0),
        summary=args.get("route_summary") or {},
    )
    if block is None:
        text = (
            f"Listo: agendé «{appointment.title}» el {format_when(starts_at)}. "
            "Sin dirección verificada: no hay bloque de traslado."
        )
    else:
        text = (
            f"Listo: agendé «{appointment.title}» el {format_when(starts_at)}. "
            f"Sales a las {_local_clock(block.starts_at)} "
            f"({block.duration_min} min de traslado)."
        )
    return (
        {"appointment_id": appointment.pk},
        [{"tool": "appointment_delete", "args": {"appointment_id": appointment.pk}}],
        text,
    )


def _local_clock(moment):
    return timezone.localtime(moment).strftime("%H:%M")


def _apply_deadline_create(args):
    from apps.agenda.models import Deadline

    # Deadline.save() computes due_date from the term with the applicable calendar union.
    deadline = Deadline.objects.create(
        case_id=args["case_id"],
        title=args["title"],
        kind=args.get("kind") or Deadline.PROCESAL,
        notified_on=date.fromisoformat(args["notified_on"]),
        term_value=int(args["term_value"]),
        term_unit=args["term_unit"],
    )
    text = f"Listo: apunté el plazo «{deadline.title}» para el {format_day(deadline.due_date)} · calculado, verifica."
    return (
        {"deadline_id": deadline.pk},
        [{"tool": "deadline_delete", "args": {"deadline_id": deadline.pk}}],
        text,
    )


def _apply_deadline_delete(args):
    from apps.agenda.models import Deadline

    Deadline.objects.filter(pk=args["deadline_id"]).delete()
    return {"deleted": args["deadline_id"]}, [], "Quité el plazo que había apuntado."


APPLIERS = {
    "appointment_create": _apply_appointment_create,
    "appointment_delete": _apply_appointment_delete,
    "reschedule": _apply_reschedule,
    "plan_visit": _apply_plan_visit,
    "deadline_create": _apply_deadline_create,
    "deadline_delete": _apply_deadline_delete,
}

WEEKDAYS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def parse_when(value):
    """A model-supplied ISO datetime, read in the instance's own timezone."""
    if isinstance(value, datetime):
        moment = value
    else:
        moment = parse_datetime(str(value))
        if moment is None:
            try:
                moment = datetime.fromisoformat(str(value))
            except ValueError as exc:
                raise ProposalError(f"no entiendo la fecha «{value}»") from exc
    return timezone.make_aware(moment) if timezone.is_naive(moment) else moment


def format_when(moment):
    local = timezone.localtime(moment)
    return f"{WEEKDAYS[local.weekday()]} {local.day} {MONTHS[local.month - 1]}, {local:%H:%M}"


def format_day(day):
    return f"{WEEKDAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]} {day.year}"


def _locked(thread, proposal_id):
    return (
        Proposal.objects.select_for_update()
        .filter(thread=thread, pk=proposal_id)
        .first()
    )


def _close(proposal, status):
    proposal.status = status
    proposal.save(update_fields=["status", "updated_at"])


def _reply(ok, text, proposal=None, duplicate=False):
    return {
        "ok": ok,
        "text": text,
        "proposal_id": proposal.pk if proposal else None,
        "status": proposal.status if proposal else None,
        "duplicate": duplicate,
    }
