"""Tools the model may call. `fn(thread, **args)` returns compact JSON (PLAN.md §3.2).

Reads read; writes build a Proposal; only `confirm`/`cancel`/`undo` touch the domain.
"""

from datetime import date, timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.agenda import business_days
from apps.agenda import day as simulation
from apps.agenda import planner
from apps.agenda.models import Appointment, Deadline
from apps.assistant import envelope
from apps.assistant.envelope import ProposalError, format_day, format_when, parse_when, propose
from apps.core.models import Case, Client, jid_for_phone
from apps.docs import filing
from apps.docs import search as docs_search
from apps.docs.models import InboundMedia
from apps.integrations import maps


def agenda_today(thread):
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = Appointment.objects.filter(
        starts_at__gte=start, starts_at__lt=start + timedelta(days=1)
    ).select_related("client")
    return {
        "date": start.date().isoformat(),
        "count": len(rows),
        "appointments": [
            {
                "id": appt.pk,
                "time": timezone.localtime(appt.starts_at).strftime("%H:%M"),
                "kind": appt.kind,
                "title": appt.title,
                "location": appt.location_name or None,
                "client": appt.client.name if appt.client else None,
            }
            for appt in rows
        ],
    }


def case_search(thread, query):
    clients = Client.objects.filter(is_active=True, name__icontains=query).order_by("name")[:5]
    cases = Case.objects.filter(
        Q(reference__icontains=query) | Q(title__icontains=query)
    ).order_by("reference")[:5]
    return {
        "clients": [{"id": client.pk, "name": client.name, "phone": client.phone} for client in clients],
        "cases": [
            {
                "id": case.pk,
                "reference": case.reference,
                "title": case.title,
                "status": case.status,
            }
            for case in cases
        ],
    }


def case_summary(thread, case_id):
    try:
        case = Case.objects.select_related("client").get(pk=case_id)
    except Case.DoesNotExist:
        return {"error": f"no existe el expediente {case_id}"}
    upcoming = case.appointments.filter(
        starts_at__gte=timezone.now(), status=Appointment.PLANNED
    ).first()
    return {
        "case_id": case.pk,
        "reference": case.reference,
        "title": case.title,
        "court": case.court or None,
        "status": case.status,
        "opened_on": case.opened_on.isoformat(),
        "client": {"id": case.client.pk, "name": case.client.name, "phone": case.client.phone},
        "next_appointment": (
            {
                "id": upcoming.pk,
                "starts_at": timezone.localtime(upcoming.starts_at).isoformat(),
                "title": upcoming.title,
            }
            if upcoming
            else None
        ),
        "notes": _note_shapes(case),
    }


def case_notes(thread, case_id, limit=5):
    """The recent notes of one case, the same rows `/cases/<id>` shows as a timeline."""
    try:
        case = Case.objects.get(pk=case_id)
    except Case.DoesNotExist:
        return {"error": f"no existe el expediente {case_id}"}
    notes = _note_shapes(case, limit=max(1, min(int(limit or 5), 20)))
    return {"case_id": case.pk, "reference": case.reference, "count": len(notes), "notes": notes}


def _note_shapes(case, limit=5):
    """One shape for a voice note and a typed note: the transcript is the body (PLAN §5.2)."""
    return [
        {
            "id": note.pk,
            "source": note.source,
            "body": note.body,
            "created_at": timezone.localtime(note.created_at).isoformat(),
            "media_id": note.media_id,
            "transcript_model": note.transcript_model or None,
        }
        for note in case.notes.all()[:limit]
    ]


def document_search(thread, query, case_id=None):
    """FTS over the extracted text, with a snippet; the same query the dashboard runs."""
    rows = docs_search.search(query, case_id=case_id)
    return {
        "count": len(rows),
        "results": [
            {
                "document_id": row["id"],
                "filename": row["filename"],
                "case": f"{row['case_reference']} — {row['case_title']}",
                "snippet": row["snippet"],
                "no_text_layer": row["no_text_layer"],
            }
            for row in rows
        ],
    }


def day_simulation(thread, date=None):
    """The §8.2 walk for one day: departures, lateness, first three conflicts."""
    when = parse_date(date) if date else None
    return simulation.simulate(when)


def find_free_slot(thread, duration, after, before):
    """The first three gaps of `duration` minutes that fit between after and before."""
    start = _moment(after)
    limit = _moment(before)
    if start is None or limit is None:
        return {"error": "after y before deben ser fechas ISO"}
    slots = simulation.find_free_slot(duration, start, limit)
    return {"duration": duration, "slots": [_clock(slot) for slot in slots]}


def llegada(thread, appointment_id, date=None):
    """¿Llego? — the lateness of one stop and up to three slots where it would fit."""
    when = parse_date(date) if date else None
    return simulation.llegada(appointment_id, when)


def _moment(value):
    moment = parse_datetime(value) if value else None
    if moment is not None and timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    return moment


def _clock(moment):
    return timezone.localtime(moment).strftime("%H:%M")


def appointment_create(thread, **args):
    allowed = {"title", "when", "kind", "duration_min", "address", "location_name", "case_id", "client_id"}
    if bad := _reject_extra(args, allowed):
        return bad
    if not args.get("title") or not args.get("when"):
        return {"error": "necesito el título y la hora de la cita"}
    kind = args.get("kind") or Appointment.VISITA
    if kind not in dict(Appointment.KINDS):
        return {"error": f"tipo de cita desconocido: {kind}"}
    duration_min, buffer_min = _kind_defaults(kind)
    if args.get("duration_min"):
        duration_min = int(args["duration_min"])
    try:
        starts_at = parse_when(args["when"])
    except ProposalError as exc:
        return {"error": str(exc)}
    if starts_at <= timezone.now():
        return {"error": "esa hora ya pasó; dime a qué hora la agendo"}

    case = None
    if args.get("case_id"):
        case = Case.objects.filter(pk=args["case_id"]).first()
        if case is None:
            return {"error": f"no existe el expediente {args['case_id']}"}

    location = args.get("location_name") or args.get("address") or ""
    lines = [f"Nueva cita: «{args['title']}»", f"{format_when(starts_at)}, {duration_min} min"]
    if location:
        lines[1] += f" · {location}"
    lines.append("¿La agendo?")
    proposal = propose(
        thread,
        steps=[
            {
                "tool": "appointment_create",
                "args": {
                    "title": args["title"],
                    "kind": kind,
                    "starts_at": starts_at.isoformat(),
                    "duration_min": duration_min,
                    "buffer_min": buffer_min,
                    "location_name": args.get("location_name") or "",
                    "address": args.get("address") or "",
                    "case_id": case.pk if case else None,
                    "client_id": args.get("client_id") or (case.client_id if case else None),
                },
            }
        ],
        summary="\n".join(lines),
        expires_at=starts_at,
    )
    return {"proposal_id": proposal.pk, "summary": proposal.summary}


def reschedule(thread, **args):
    if bad := _reject_extra(args, {"appointment_id", "new_start"}):
        return bad
    appointment = Appointment.objects.filter(pk=args.get("appointment_id")).first()
    if appointment is None:
        return {"error": f"no existe la cita {args.get('appointment_id')}"}
    if appointment.status != Appointment.PLANNED:
        return {"error": f"la cita está {appointment.get_status_display()}"}
    try:
        new_start = parse_when(args.get("new_start"))
    except ProposalError as exc:
        return {"error": str(exc)}
    if new_start <= timezone.now():
        return {"error": "esa hora ya pasó; dime a qué hora la muevo"}

    ends_at = new_start + timedelta(minutes=appointment.duration_min)
    collisions = (
        Appointment.objects.filter(
            status=Appointment.PLANNED,
            starts_at__lt=ends_at,
            starts_at__gte=new_start - timedelta(minutes=appointment.duration_min),
        )
        .exclude(pk=appointment.pk)
        .order_by("starts_at")[:2]
    )
    lines = [
        f"Mueve: «{appointment.title}»",
        f"{format_when(appointment.starts_at)} → {format_when(new_start)}",
    ]
    for other in collisions:
        lines.append(f"No cabe: «{other.title}» ({format_when(other.starts_at)})")
    lines.append("¿La muevo?")
    proposal = propose(
        thread,
        steps=[
            {
                "tool": "reschedule",
                "args": {
                    "appointment_id": appointment.pk,
                    "new_start": new_start.isoformat(),
                },
            }
        ],
        summary="\n".join(lines),
        expires_at=new_start,
    )
    return {"proposal_id": proposal.pk, "summary": proposal.summary}


def plan_visit(thread, **args):
    """A visit as a card: one Places candidate or a Maps link, then its travel block (D19)."""
    if bad := _reject_extra(
        args,
        {"title", "when", "kind", "duration_min", "address", "case_id", "client_id"},
    ):
        return bad
    if not args.get("when"):
        return {"error": "necesito la hora de la visita"}
    kind = args.get("kind") or Appointment.VISITA
    if kind not in dict(Appointment.KINDS):
        return {"error": f"tipo de cita desconocido: {kind}"}
    duration_min, buffer_min = _kind_defaults(kind)
    if args.get("duration_min"):
        duration_min = int(args["duration_min"])
    try:
        starts_at = parse_when(args["when"])
    except ProposalError as exc:
        return {"error": str(exc)}
    if starts_at <= timezone.now():
        return {"error": "esa hora ya pasó; dime a qué hora la agendo"}

    case = None
    if args.get("case_id"):
        case = Case.objects.filter(pk=args["case_id"]).first()
        if case is None:
            return {"error": f"no existe el expediente {args['case_id']}"}
    client = case.client if case else _client(args.get("client_id"))

    card = _card_for(client, args.get("address"))
    if card is None:
        return {"error": "necesito la dirección de la visita"}

    origin, travel_min, route_summary = "", 0, {}
    located = card["lat"] is not None and card["lng"] is not None
    if located:
        origin, travel_min, route_summary = planner.plan_leg(
            card["address"], starts_at, buffer_min
        )

    title = args.get("title") or (f"Visita {client.name}" if client else "Visita")
    lines = [f"Nueva visita: «{title}»", f"{format_when(starts_at)}, {duration_min} min"]
    if located:
        lines.append(f"{card['location_name'] or card['address']} — {card['address']}")
        if travel_min:
            leave = starts_at - timedelta(minutes=buffer_min + travel_min)
            lines.append(
                f"Salida: {_clock(leave)} ({travel_min} min de traslado + {buffer_min} de margen)"
            )
        else:
            lines.append("sin cálculo de traslado")
    else:
        lines.append(f"{card['address']} — sin dirección verificada")
        lines.append(f"Mapa: {card['maps_url']}")
        lines.append("No hay bloque de traslado: mándame la ubicación y lo calculo.")
    lines.append("¿La agendo?")

    proposal = propose(
        thread,
        steps=[
            {
                "tool": "plan_visit",
                "args": {
                    "title": title,
                    "kind": kind,
                    "starts_at": starts_at.isoformat(),
                    "duration_min": duration_min,
                    "buffer_min": buffer_min,
                    "location_name": card["location_name"] or "",
                    "address": card["address"],
                    "address_source": card["address_source"],
                    "lat": card["lat"],
                    "lng": card["lng"],
                    "origin": origin,
                    "travel_min": travel_min,
                    "route_summary": route_summary,
                    "case_id": case.pk if case else None,
                    "client_id": client.pk if client else None,
                },
            }
        ],
        summary="\n".join(lines),
        expires_at=starts_at,
    )
    return {"proposal_id": proposal.pk, "summary": proposal.summary}


def _client(client_id):
    return Client.objects.filter(pk=client_id).first() if client_id else None


def _card_for(client, address):
    """The client's last resolved address first; a Places search only when there is none."""
    wanted = (address or "").strip()
    last = _last_resolved(client)
    if last is not None and (not wanted or _same_place(wanted, last)):
        return {
            "address_source": last.address_source,
            "address": last.address,
            "location_name": last.location_name,
            "lat": str(last.lat),
            "lng": str(last.lng),
            "maps_url": "",
        }
    return maps.resolve(wanted) if wanted else None


def _last_resolved(client):
    if client is None:
        return None
    return (
        Appointment.objects.filter(client=client, lat__isnull=False, lng__isnull=False)
        .order_by("-starts_at")
        .first()
    )


def _same_place(address, appointment):
    wanted = _normalize(address)
    return wanted in {_normalize(appointment.address), _normalize(appointment.location_name)}


def _normalize(text):
    return " ".join(str(text or "").lower().split()).rstrip(".,")


def deadline_create(thread, **args):
    """A computed date from the notification, always labelled calculado — verifica (D12)."""
    if bad := _reject_extra(
        args, {"case_id", "title", "notified_on", "term_value", "term_unit", "kind"}
    ):
        return bad
    case = Case.objects.filter(pk=args.get("case_id")).first()
    if case is None:
        return {"error": f"no existe el expediente {args.get('case_id')}"}
    unit = args.get("term_unit")
    if unit not in business_days.UNITS:
        return {"error": f"unidad de plazo desconocida: {unit}"}
    kind = args.get("kind") or Deadline.PROCESAL
    if kind not in dict(Deadline.KINDS):
        return {"error": f"tipo de plazo desconocido: {kind}"}
    try:
        notified_on = date.fromisoformat(str(args.get("notified_on")))
        term_value = int(args.get("term_value"))
    except (TypeError, ValueError):
        return {"error": "necesito la fecha de notificación y el número de días"}
    if term_value <= 0:
        return {"error": "el plazo debe ser de al menos un día"}

    due = business_days.due_date(notified_on, term_value, unit)
    title = args.get("title") or "plazo"
    summary = "\n".join(
        [
            f"Nuevo plazo: «{title}» ({case.reference})",
            f"Vence el {format_day(due)} · calculado ({term_value} {dict(Deadline.UNITS)[unit]}"
            f" desde notificación {format_day(notified_on)}) · verifica",
            "¿Lo apunto?",
        ]
    )
    proposal = propose(
        thread,
        steps=[
            {
                "tool": "deadline_create",
                "args": {
                    "case_id": case.pk,
                    "title": title,
                    "kind": kind,
                    "notified_on": notified_on.isoformat(),
                    "term_value": term_value,
                    "term_unit": unit,
                },
            }
        ],
        summary=summary,
    )
    return {"proposal_id": proposal.pk, "summary": proposal.summary}


def file_document(thread, **args):
    """Propose filing the last (or a named) inbound file under a case."""
    if bad := _reject_extra(args, {"case_id", "media_id"}):
        return bad
    case = Case.objects.filter(pk=args.get("case_id")).first()
    if case is None:
        return {"error": f"no existe el expediente {args.get('case_id')}"}
    available = InboundMedia.objects.filter(purged_at__isnull=True)
    if args.get("media_id"):
        media = available.filter(pk=args["media_id"]).first()
        if media is None:
            return {"error": f"no existe el archivo {args['media_id']}"}
    else:
        media = available.order_by("-created_at").first()
        if media is None:
            return {"error": "no tengo un archivo reciente para archivar"}
    summary = "\n".join(
        [
            f"Archivar: «{media.filename}»",
            f"En el expediente «{case.reference} — {case.title}»",
            "¿Lo archivo?",
        ]
    )
    proposal = propose(
        thread,
        steps=[
            {"tool": "file_document", "args": {"case_id": case.pk, "media_id": media.pk}}
        ],
        summary=summary,
    )
    return {"proposal_id": proposal.pk, "summary": proposal.summary}


def note_add(thread, **args):
    """A case note as a proposal: the note exists only after the lawyer confirms (§5.2)."""
    if bad := _reject_extra(args, {"case_id", "body"}):
        return bad
    case = Case.objects.filter(pk=args.get("case_id")).first()
    if case is None:
        return {"error": f"no existe el expediente {args.get('case_id')}"}
    body = (args.get("body") or "").strip()
    if not body:
        return {"error": "necesito el texto de la nota"}

    summary = "\n".join(
        [
            f"Nota para «{case.reference} — {case.title}»:",
            body,
            "",
            "¿La guardo?",
        ]
    )
    proposal = propose(
        thread,
        steps=[{"tool": "note_add", "args": {"case_id": case.pk, "body": body}}],
        summary=summary,
    )
    return {"proposal_id": proposal.pk, "summary": proposal.summary}


def client_create(thread, **args):
    """Propose a new client from a typed number: nothing is written until it is confirmed."""
    if bad := _reject_extra(args, {"name", "phone", "wa_name"}):
        return bad
    name = (args.get("name") or "").strip()
    if not name:
        return {"error": "necesito el nombre del cliente"}
    return _propose_client(
        thread,
        name=name,
        phone=(args.get("phone") or "").strip(),
        wa_name=(args.get("wa_name") or "").strip(),
    )


def client_create_from_contact(thread, name, phone):
    """A forwarded contact card lands on the same card as a typed number (PLAN §6.2)."""
    name = " ".join(str(name or "").split())
    if not name:
        return {"error": "la tarjeta no trae nombre; dime cómo se llama"}
    return _propose_client(thread, name=name, phone=phone, wa_name=name)


def _propose_client(thread, *, name, phone, wa_name):
    try:
        jid = jid_for_phone(phone)
    except ValueError:
        return {"error": "ese no es un número de WhatsApp; dime el número con lada"}
    existing = Client.objects.filter(Q(jid=jid) | Q(phone=phone)).first()
    if existing is not None:
        return {"error": f"ya está en la agenda: «{existing.name}»"}

    lines = [f"Nuevo cliente: «{name}»", f"WhatsApp: {phone}"]
    if wa_name:
        lines.append(f"En WhatsApp aparece como «{wa_name}»")
    lines.append("¿Lo doy de alta?")
    proposal = propose(
        thread,
        steps=[
            {
                "tool": "client_create",
                "args": {"name": name, "phone": phone, "jid": jid, "wa_name": wa_name},
            }
        ],
        summary="\n".join(lines),
    )
    return {"proposal_id": proposal.pk, "summary": proposal.summary}


def client_update(thread, **args):
    """Draft one client message: the text shown is the text sent, byte for byte (§6.3)."""
    if bad := _reject_extra(args, {"client_id", "text"}):
        return bad
    client = Client.objects.filter(pk=args.get("client_id"), is_active=True).first()
    if client is None:
        return {"error": f"no existe el cliente {args.get('client_id')}"}
    text = (args.get("text") or "").strip()
    if not text:
        return {"error": "necesito el texto del aviso"}
    if not client.jid:
        return {"error": f"«{client.name}» no tiene WhatsApp en la agenda"}

    summary = "\n".join(
        [f"Aviso para «{client.name}»:", text, "", "Se manda tal cual desde tu número. ¿Lo mando?"]
    )
    proposal = propose(
        thread,
        steps=[{"tool": "client_update", "args": {"client_id": client.pk}}],
        summary=summary,
        outbound_text=text,
    )
    return {"proposal_id": proposal.pk, "summary": proposal.summary}


def _kind_defaults(kind):
    spec = (settings.CONFIG.get("kinds") or {}).get(kind) or {}
    return int(spec.get("duration", 60)), int(spec.get("buffer", 0))


def _reject_extra(args, allowed):
    extra = sorted(set(args) - allowed)
    if extra:
        return {"error": f"no acepto {', '.join(extra)}"}
    return None


def confirm(thread, **args):
    bad = _proposal_id_only(args)
    if bad:
        return bad
    return envelope.confirm(thread, args["proposal_id"])


def cancel(thread, **args):
    bad = _proposal_id_only(args)
    if bad:
        return bad
    return envelope.cancel(thread, args["proposal_id"])


def undo(thread, **args):
    bad = _proposal_id_only(args)
    if bad:
        return bad
    return envelope.undo(thread, args["proposal_id"])


def _proposal_id_only(args):
    """`confirm` takes nothing but the id: the payload lives in the row, not in the model."""
    if set(args) != {"proposal_id"}:
        return {"error": "solo acepto proposal_id; lo que se aplica es lo que ya se mostró"}
    try:
        args["proposal_id"] = int(args["proposal_id"])
    except (TypeError, ValueError):
        return {"error": "proposal_id debe ser un número"}
    return None


TOOLS = {
    "agenda_today": {
        "fn": agenda_today,
        "description": "Los compromisos de hoy, con hora, lugar y cliente.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "case_search": {
        "fn": case_search,
        "description": "Busca clientes y expedientes por nombre, referencia o título.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "case_summary": {
        "fn": case_summary,
        "description": "Resumen de un expediente: cliente, estado y próxima cita.",
        "parameters": {
            "type": "object",
            "properties": {"case_id": {"type": "integer"}},
            "required": ["case_id"],
            "additionalProperties": False,
        },
    },
    "case_notes": {
        "fn": case_notes,
        "description": "Las notas recientes de un expediente: voz y texto tienen la misma forma.",
        "parameters": {
            "type": "object",
            "properties": {
                "case_id": {"type": "integer"},
                "limit": {"type": "integer", "description": "5 por defecto"},
            },
            "required": ["case_id"],
            "additionalProperties": False,
        },
    },
    "document_search": {
        "fn": document_search,
        "description": "Busca una frase en el texto de los documentos archivados; devuelve el fragmento.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "case_id": {"type": "integer"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "day_simulation": {
        "fn": day_simulation,
        "description": "El día simulado: hora de salida de cada cita, traslados y choques.",
        "parameters": {
            "type": "object",
            "properties": {"date": {"type": "string", "description": "YYYY-MM-DD; hoy por defecto"}},
            "additionalProperties": False,
        },
    },
    "find_free_slot": {
        "fn": find_free_slot,
        "description": "Los primeros huecos libres de una duración, entre dos fechas ISO.",
        "parameters": {
            "type": "object",
            "properties": {
                "duration": {"type": "integer"},
                "after": {"type": "string"},
                "before": {"type": "string"},
            },
            "required": ["duration", "after", "before"],
            "additionalProperties": False,
        },
    },
    "llegada": {
        "fn": llegada,
        "description": "¿Llego? Minutos de retraso de una cita y hasta tres horarios donde cabe.",
        "parameters": {
            "type": "object",
            "properties": {
                "appointment_id": {"type": "integer"},
                "date": {"type": "string", "description": "YYYY-MM-DD; hoy por defecto"},
            },
            "required": ["appointment_id"],
            "additionalProperties": False,
        },
    },
    "appointment_create": {
        "fn": appointment_create,
        "description": "Propone una cita nueva; no la agenda hasta que el abogado confirme.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "when": {"type": "string", "description": "ISO 8601 en hora local"},
                "kind": {"type": "string", "enum": [kind for kind, _ in Appointment.KINDS]},
                "duration_min": {"type": "integer"},
                "address": {"type": "string"},
                "location_name": {"type": "string"},
                "case_id": {"type": "integer"},
                "client_id": {"type": "integer"},
            },
            "required": ["title", "when"],
            "additionalProperties": False,
        },
    },
    "reschedule": {
        "fn": reschedule,
        "description": "Propone mover una cita existente; muestra con qué choca.",
        "parameters": {
            "type": "object",
            "properties": {
                "appointment_id": {"type": "integer"},
                "new_start": {"type": "string", "description": "ISO 8601 en hora local"},
            },
            "required": ["appointment_id", "new_start"],
            "additionalProperties": False,
        },
    },
    "plan_visit": {
        "fn": plan_visit,
        "description": (
            "Propone una visita con su ficha de dirección (una de Places o un enlace de Maps) "
            "y su bloque de traslado; no agenda nada hasta que el abogado confirme."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "la dirección tal como la dijo el abogado"},
                "when": {"type": "string", "description": "ISO 8601 en hora local"},
                "title": {"type": "string"},
                "kind": {"type": "string", "enum": [kind for kind, _ in Appointment.KINDS]},
                "duration_min": {"type": "integer"},
                "location_name": {"type": "string"},
                "case_id": {"type": "integer"},
                "client_id": {"type": "integer"},
            },
            "required": ["address", "when"],
            "additionalProperties": False,
        },
    },
    "deadline_create": {
        "fn": deadline_create,
        "description": "Propone un plazo calculado desde la notificación; siempre dice verifica.",
        "parameters": {
            "type": "object",
            "properties": {
                "case_id": {"type": "integer"},
                "title": {"type": "string"},
                "notified_on": {"type": "string", "description": "AAAA-MM-DD"},
                "term_value": {"type": "integer"},
                "term_unit": {"type": "string", "enum": list(business_days.UNITS)},
                "kind": {"type": "string", "enum": [kind for kind, _ in Deadline.KINDS]},
            },
            "required": ["case_id", "title", "notified_on", "term_value", "term_unit"],
            "additionalProperties": False,
        },
    },
    "file_document": {
        "fn": file_document,
        "description": "Propone archivar un archivo recibido en un expediente; no lo archiva hasta confirmar.",
        "parameters": {
            "type": "object",
            "properties": {
                "case_id": {"type": "integer"},
                "media_id": {"type": "integer", "description": "el último archivo si se omite"},
            },
            "required": ["case_id"],
            "additionalProperties": False,
        },
    },
    "note_add": {
        "fn": note_add,
        "description": "Propone una nota en un expediente; no la guarda hasta que el abogado confirme.",
        "parameters": {
            "type": "object",
            "properties": {
                "case_id": {"type": "integer"},
                "body": {"type": "string", "description": "el texto de la nota"},
            },
            "required": ["case_id", "body"],
            "additionalProperties": False,
        },
    },
    "client_create": {
        "fn": client_create,
        "description": "Propone dar de alta un cliente; dice cómo aparece en WhatsApp.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "phone": {"type": "string", "description": "con lada, como lo dictó"},
                "wa_name": {"type": "string", "description": "el nombre que muestra WhatsApp"},
            },
            "required": ["name", "phone"],
            "additionalProperties": False,
        },
    },
    "client_update": {
        "fn": client_update,
        "description": "Propone un aviso para un cliente; el texto se manda tal cual.",
        "parameters": {
            "type": "object",
            "properties": {
                "client_id": {"type": "integer"},
                "text": {"type": "string", "description": "el mensaje exacto, como lo verá el cliente"},
            },
            "required": ["client_id", "text"],
            "additionalProperties": False,
        },
    },
    "confirm": {
        "fn": confirm,
        "description": "Aplica la propuesta abierta que el abogado acaba de aceptar. Solo lleva su id.",
        "parameters": {
            "type": "object",
            "properties": {"proposal_id": {"type": "integer"}},
            "required": ["proposal_id"],
            "additionalProperties": False,
        },
    },
    "cancel": {
        "fn": cancel,
        "description": "Descarta la propuesta abierta sin cambiar nada. Solo lleva su id.",
        "parameters": {
            "type": "object",
            "properties": {"proposal_id": {"type": "integer"}},
            "required": ["proposal_id"],
            "additionalProperties": False,
        },
    },
    "undo": {
        "fn": undo,
        "description": "Deshace una propuesta ya aplicada hace menos de 24 horas. Solo lleva su id.",
        "parameters": {
            "type": "object",
            "properties": {"proposal_id": {"type": "integer"}},
            "required": ["proposal_id"],
            "additionalProperties": False,
        },
    },
}


# `confirm` applies stored steps through this table; the docs app owns its own write.
def _apply_file_document(args, proposal=None):
    """`confirm` hands every applier the proposal; filing only reads its own args."""
    return filing.apply_file_document(args)


envelope.APPLIERS["file_document"] = _apply_file_document


def schemas():
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": tool["description"],
                "parameters": tool["parameters"],
            },
        }
        for name, tool in TOOLS.items()
    ]
