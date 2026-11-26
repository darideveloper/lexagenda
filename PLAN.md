# lexagenda — v0.1 plan

Personal assistant for a lawyer, run over WhatsApp. Agenda, deadlines, travel time,
client files. Sold per despacho at ~$50/mo, deployed one instance per client.

- Status: v0.1 design, decisions closed (26 Nov 2026), not yet implemented
- Jurisdiction: México
- Working name: `lexagenda` (rename freely, nothing depends on it)
- Author of decisions: product owner (Dari) + this plan

---

## 1. Product

### 1.1 One-liner

A WhatsApp assistant that tells the lawyer what his day really costs — travel included —
so appointments stop being lost to bad time estimates, and a deadline never slips unseen.

### 1.2 The problem, stated precisely

The lawyer's calendar is a list of intentions with no physics. A visit at 11:00 in another
colonia is stored as "11:00", not as "leave at 10:05, 45 min drive, 15 min buffer". Halfway
through the day the plan is already impossible, and the response is to move the whole
afternoon. Deadlines live on paper, in Excel, or nowhere. Clients call to ask for status.
And when he is already on the road, nobody can answer the only question that matters:
*"¿llego?"*

The product is therefore **not** a calendar and **not** a chatbot. It is **agenda realism**,
delivered as a conversation:

1. every commitment carries its real duration (travel + buffer + the task itself);
2. the day is simulated in advance, and its impossibility is announced the night before;
3. rescheduling is one confirmed sentence away, with the knock-on effects shown;
4. deadlines are tracked with correct business-day arithmetic, and always presented as
   computed-not-authoritative.

### 1.3 What v0.1 is

- One despacho, one lawyer, one instance.
- A WhatsApp **conversation** with the assistant (dedicated number). No menus, no commands.
  The lawyer writes as he would to a competent secretary, and gets answers in the same register.
- A deterministic 08:00 nudge: today's commitments, departure times, conflicts, deadlines < 7 days.
  The facts come from templates; the phrasing invites a reply.
- Conversational queries over the lawyer's own data: agenda, case summary, deadlines, documents,
  *"¿me da tiempo?"*, *"¿qué tengo el jueves?"*.
- Confirm-gated writes: reschedule, create visit + travel block, file a document, send a client
  update. The assistant proposes; the lawyer answers in words; the system commits exactly what
  was shown.
- Client updates drafted by the assistant, sent **only** after the text has been displayed and
  confirmed, from the lawyer's own number.
- Voice notes from the lawyer transcribed into case notes.
- Client files stored and full-text searchable.
- Read-mostly web dashboard (public, login + 2FA): clients, cases, files, pending work.

### 1.4 What v0.1 is explicitly not

- No client-facing bot. Clients never message the assistant.
- No numbered menus or command grammar (`1`/`2`/`3` as a protocol). One reply vocabulary:
  plain Spanish.
- No automatic procedural deadline engine (32 state codes, jurisdictional rules). Only
  business-day arithmetic + seeded official calendars + manual entry.
- No Google Calendar API, no OAuth verification, no Drive.
- No semantic/vector search over documents.
- No multi-tenant shared database. One instance per paying client.
- No TTS (no voice replies from the assistant).
- No billing, no invoicing, no time tracking.
- No n8n in the runtime (see §3.4).
- No multi-stop route optimisation, no return-trip modelling.

### 1.5 Acceptance criteria for v0.1 (whole)

1. The lawyer answers the 08:00 nudge within 2 h on at least 4 of 5 consecutive working days.
2. Zero wrongly-created or wrongly-moved appointments (any error is caught by the proposal).
3. A forwarded PDF is findable by its content within one message.
4. A voice note becomes a case note with a usable transcript.
5. One client update is sent, from the lawyer's number, after the text was shown and confirmed.
6. The lawyer never has to open the dashboard to get value — but it's there and accurate.

Since the pilot lawyer is "available but not committed" (see §13), acceptance is measured by
demo + 5-day trial, not by signed adoption.

---

## 2. Decisions (locked)

| # | Area | Decision | Why |
|---|---|---|---|
| D1 | Tenancy | One instance per despacho, own DB/volume, deployed on Coolify | At $50/mo, shared tenancy is both unnecessary and indefensible for legal confidentiality |
| D2 | Source of truth | Django owns everything; Google Calendar is a one-way mirror | Two-way sync is where these products die |
| D3 | Calendar transport | `.ics` email invites + tokenized read-only ICS feed. **No Calendar API** | Personal @gmail + OAuth "testing" mode expires refresh tokens every 7 days; publishing requires Google verification |
| D4 | WhatsApp | Two sessions: **control** on a dedicated assistant number (read-write, webhook), **delivery** on the lawyer's own number as a write-only companion device. `DELIVERY_MODE=auto\|draft` can turn every send into a draft without a redeploy | Clients must see the lawyer's number; its session is never *read* by the app |
| D5 | Channel provider | gowa (go-whatsapp-web-multidevice), unofficial, pinned tag | Owner rejected Cloud API; two-session design minimises ban risk |
| D6 | Brain | `apps/assistant/agent.py` + `envelope.py` inside Django, tool registry, max 4 steps | State, proposals, audit and data live in one DB and one transaction |
| D7 | Writes | A write tool never mutates. It stores a **proposal envelope** (steps + rendered summary + exact outbound text). The lawyer answers in words; the model may only call `confirm(proposal_id)`, which executes the stored payload in plain Python | An LLM must not be able to act alone, nor to invent what it confirms |
| D8 | Model | **OpenRouter**, OpenAI-compatible, US-hosted, model chosen by env (`LLM_MODEL` + `LLM_FALLBACK_MODEL`). Processing disclosed as *encargado* in the aviso and the contract | One adapter, swap models without code; the lawyer knows where his data goes |
| D9 | Automation | Three management commands on timers: `brief`, `work`, `sweep`. No Celery, no Redis | One worker, a DB-backed job table, at this scale |
| D10 | n8n | Not in v0.1. Returns as a connector shelf (HMAC webhooks) when a second integration earns it | Would otherwise idle as a container + a second credential store |
| D11 | Language/market | **México, Hidalgo**: `America/Mexico_City`, es-MX, business days Mon–Fri minus federal + federal judicial (OAJ) + Hidalgo calendars | One hardcoded assumption, so it must be right |
| D12 | Deadline authority | Every computed date is labelled "calculado — verifica" | A wrong deadline that looks official is worse than none |
| D13 | Files | Store on volume + Postgres full-text search (`spanish`) | 2 days, no embedding pipeline, answers the real questions |
| D14 | Dashboard | Public, login + TOTP 2FA, read-mostly | Chosen by owner; used for review, not daily operation |
| D15 | Resale | One codebase, `config.yaml` + flags. Never a fork per client | 10 forks = 10 unpatched codebases |
| D16 | Voice | Inbound STT only (faster-whisper, CPU, `small`) | Zero confirmed demand for TTS; adds latency and a voice persona problem |
| D17 | Day origin | One `BaseLocation` per instance (office), editable, used as the start of every simulated day | A departure time needs an origin; asking every morning is friction |
| D18 | Retention | Structured records for the life of the instance; raw provider payloads and unfiled media purged at 90 days | The chat is the evidence trail; the duplicated copies are not |
| D19 | Address | Places Text Search once, one candidate card; Maps link as fallback; never a silent pin | A wrong colonia is the failure mode the whole feature exists to prevent |
| D20 | 2FA loss | Owner reset from the ops console, audited, lawyer notified, disclosed in the contract | Fastest recovery; the disclosure is what keeps it honest |

---

## 3. Architecture

### 3.1 Topology

```
                  ┌──────────────────────────────┐
 WhatsApp ───────▶│ gowa  (container, /data)     │
 (assistant no.)  │ device A: read-write         │──webhook──┐
                  │ device B: lawyer's number    │◀──send────┤ (no app processing;
                  │   (still persisted on disk)  │           │  filtered by device)
                  └──────────────────────────────┘           │
                                                             ▼
┌─────────────────────────────── Django (public, 2FA) ───────────────────────────────┐
│ channel.views.gowa_webhook                                                        │
│   1. verify HMAC (X-Hub-Signature-256) + dedupe by message_id                     │
│   2. filter: device A only, sender must be the lawyer's JID, else drop            │
│   3. persist Message + Job(kind=inbound)                                          │
│   4. return 200 immediately                                                       │
│                                                                                   │
│ manage.py work  (timer, every minute)                                             │
│   claim Job with select_for_update(skip_locked)                                   │
│   media? → stt.transcribe(ogg/opus) → text                                        │
│   assistant.agent.run(thread, text)                                                │
│     loop ≤ 4: llm(tools) → tool_call → TOOLS[name].fn(thread, **args) → audit      │
│     reads read; writes only build Proposals; confirm(id) commits a stored payload  │
│   persist reply → channel.send(reply, device=A) → Message.replied_at              │
│                                                                                   │
│ manage.py brief   (08:00, 20:00)   template facts, no LLM, no menu                │
│ manage.py sweep   (every 5 min)    expire proposals, mark missed, purge raw       │
└────────────────────────────────────────────────────────────────────────────────────┘
        │ outbound HTTPS                          │ outbound HTTPS
        ▼                                         ▼
  LLM API (OpenRouter, US)              Google Routes + Places
  SMTP (for .ics invites)               healthchecks ping (dead-man)
```

Four structural rules that do most of the safety and reliability work:

- **The nudge never calls the model for facts.** Cron renders a template from queries.
  Free, deterministic, and it cannot hallucinate a departure time. The model only enters
  when the lawyer replies.
- **The model never supplies a commit payload.** `confirm(proposal_id)` executes a payload
  the system built and displayed. Changing the plan requires a new proposal.
- **The webhook never does work.** It persists and returns; STT and the agent run in `work`,
  so gowa's 10 s window is never at risk and a retry cannot duplicate a conversation.
- **The session that touches client data is never read.** Device B's events are dropped by
  device id before any DB write — and its traffic is still stored by gowa, which is in the
  threat model (§15), not pretended away.

### 3.2 Why the brain is co-located, not a separate service

The brain needs four things that are all state: the conversation thread, the open proposal,
the audit log, and an idempotency key per inbound message. All four are rows in the same
database as the clients. A separate agent service buys nothing at this size and costs a
network hop, a second deploy, duplicated models and two auth stories.

The escape hatch is the tool signature: `fn(thread, **args) -> JSON`. When the agent someday
needs its own box (multi-tenant SaaS, GPU inference), `tools.py` lifts out unchanged.

This is also the answer to "an n8n agent node": the pattern is the same (LLM + tools + memory),
but the state, the proposal and the audit stay in one transaction instead of two systems.

### 3.3 Module layout

```
lexagenda/
├── manage.py
├── config/                 settings/{base,dev,prod}.py, urls.py, asgi.py
│   └── calendars/          federal.yaml, oaj.yaml, hidalgo.yaml, custom.yaml
├── apps/
│   ├── core/               Client, Case, Note, BaseLocation, admin, dashboard views
│   ├── agenda/             Appointment, TravelBlock, Deadline, business-day math
│   ├── docs/               Document, InboundMedia, extraction, FTS, purge
│   ├── assistant/          agent.py, envelope.py, tools.py, models.py, views.py,
│   │                       brief.py, worker.py
│   ├── channel/            gowa client, webhook, send, device filter, rate limits
│   └── integrations/       maps.py, ics.py, llm.py, stt.py, mail.py
├── templates/              dashboard + email + briefing templates
├── media/                  documents/<case_id>/..., inbound/...
├── PLAN.md
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

### 3.4 Where n8n would slot in later

Every tool is `fn(thread, **args)`. A connector backed by n8n is one function that POSTs to
`https://n8n/webhook/<tool>` with an HMAC header. Swapping implementations never touches the
agent. Reintroduce n8n when the integration list is ≥ 3 third-party services (Gmail triage,
Drive, DocuSign) or when the lawyer wants to edit a flow without a deploy.

---

## 4. Domain model

All models carry `created_at`, `updated_at`. Money and durations as integers. Phone numbers
stored E.164. Nothing stores a JID without a visible label.

### core.BaseLocation

| field | type | notes |
|---|---|---|
| label | CharField(80) | "Oficina", "Casa" |
| address | TextField | free text passed to Routes |
| lat / lng | Decimal | resolved once, cached |
| is_default | Boolean | exactly one row true |

The day simulation starts here. Its `address` is the first `origin` of every day; the brief
says "Sal de Oficina a las 08:45".

### core.Client

| field | type | notes |
|---|---|---|
| name | CharField(160) | display name |
| phone | CharField(24) | E.164, unique per instance |
| jid | CharField(64) | WhatsApp JID; resolved on creation, confirmed with the lawyer |
| email | EmailField, blank | |
| notes | TextField, blank | |
| is_active | Boolean | soft delete only; never hard-delete a client |

### core.Case

| field | type | notes |
|---|---|---|
| client | FK Client | |
| reference | CharField(64) | expediente / internal number, unique |
| title | CharField(200) | |
| court | CharField(160), blank | juzgado |
| status | enum | `open`, `paused`, `closed` |
| opened_on | DateField | |
| closed_on | DateField, null | |

### core.Note

| field | type | notes |
|---|---|---|
| case | FK Case | |
| client | FK Client, null | when the note is about the person, not the file |
| body | TextField | markdown-free plain text |
| source | enum | `voice`, `text`, `whatsapp` |
| media | FK InboundMedia, null | the audio it came from |
| transcript_model | CharField(64), blank | which STT model, for a later re-run |

Case notes are what S3 promises, what `/cases/<id>` shows as a timeline, and what
`case_summary` returns. Voice notes are `source=voice` with the transcript in `body`.

### agenda.Appointment

| field | type | notes |
|---|---|---|
| case | FK Case, null | nullable: personal blocks exist |
| client | FK Client, null | denormalised for quick reads and client-facing copy |
| kind | enum | `visita`, `audiencia`, `juzgado`, `reunion`, `tramite`, `personal` |
| title | CharField(200) | |
| starts_at | DateTimeField (tz-aware) | |
| duration_min | PositiveInt | the task itself, from `kind` defaults |
| location_name | CharField(200), blank | human label |
| address | TextField, blank | free text passed to Routes |
| address_source | enum | `places`, `link`, `manual`, `none` |
| lat / lng | Decimal, null | cached resolved point |
| travel_min | PositiveInt, null | computed by the planner |
| buffer_min | PositiveInt | default per `kind` |
| status | enum | `planned`, `done`, `cancelled` |
| ics_uid | UUID | stable across edits — required for correct calendar updates |
| ics_sequence | PositiveInt | incremented on create, move, cancel, and address change only |

`moved` is not a status: a moved appointment is `planned` at a new time. The previous value
lives in the undo record, not in the row.

### agenda.TravelBlock

Derived, but persisted so the lawyer can see and move it. `appointment` FK, `starts_at`,
`duration_min`, `route_summary` (JSON: distance, duration_in_traffic, steps summary),
`origin`/`destination` strings, `computed_at`. Regenerated whenever the appointment moves,
the address changes, or the brief runs. Origin is the previous stop, or `BaseLocation` for
the first stop of the day. Return trips are out of scope.

### agenda.Deadline

| field | type | notes |
|---|---|---|
| case | FK Case | |
| title | CharField(200) | "Contestación demanda laboral" |
| kind | enum | `procesal`, `administrativo`, `interno` |
| notified_on | DateField, null | fecha de notificación |
| term_value | PositiveInt, null | e.g. 20 |
| term_unit | enum | `dias_habiles`, `dias_naturales`, `meses` |
| due_date | DateField | computed if term fields present, else manual |
| computed | Boolean | drives the "calculado" label |
| calendar_overrides | JSON | e.g. `["federal"]` for an administrative matter |
| basis | TextField, blank | "art. X LFT" free text |
| reminder_days | JSON | `[7,3,1]` |
| status | enum | `open`, `done`, `missed` |
| verified_by | FK User, null | who confirmed the date |
| verified_at | DateTimeField, null | when |
| verified_with_calendar | CharField(32), blank | calendar version at verification |

### docs.InboundMedia

| field | type | notes |
|---|---|---|
| wamid | CharField(64), unique | the message it arrived with |
| path | CharField(255) | `media/inbound/<yyyy>/<mm>/<sha256>.<ext>` |
| mime | CharField(80) | |
| filename | CharField(200), blank | |
| size | PositiveInt | bytes |
| sha256 | CharField(64) | content address |
| purged_at | DateTimeField, null | set by `sweep` at 90 days if unfiled |

This is the record `file_document(media_id)` points at, and the reason "the last file I sent"
can be resolved tomorrow. Unfiled rows are purged at 90 days; filed ones survive as a `Document`.

### docs.Document

`case`, `client`, `filename`, `mime`, `size`, `sha256`, `extracted_text`, `no_text_layer`,
`search_vector` (trigger-maintained `tsvector`, `spanish`), `source` (`dashboard|whatsapp`),
`media` FK (null after purge), `is_active`.

Storage is content-addressed, so two Document rows can share one blob. Deletion is therefore
refcounted: a blob is removed only when no active Document and no InboundMedia references it.

### assistant.Thread / Message

- `Thread`: `channel` (`control`), `jid`, `last_activity_at`. One per lawyer (v0.1).
- `Message`: `thread`, `role` (`user|assistant|system|tool`), `text`, `media` FK,
  `media_kind`, `wamid` (unique, idempotency), `raw` (JSON, purged at 90 days),
  `tokens_in/out`, `replied_at`.

`replied_at` is what makes the reply exactly-once: a retry that finds the row already
replied does nothing, and a crash between persist and send is retried instead of lost.

### assistant.Proposal

The heart of D7. Formerly `PendingAction`.

| field | type | notes |
|---|---|---|
| thread | FK Thread | |
| steps | JSON | ordered `[{tool, args}]`, already validated |
| summary | TextField | exactly what the lawyer saw |
| outbound_text | TextField, blank | exact client text, committed as stored bytes |
| source | enum | `chat`, `brief` |
| status | enum | `proposed`, `committed`, `cancelled`, `superseded`, `expired`, `failed`, `undone` |
| expires_at | DateTimeField | min(appointment start, now + 12 h) |
| committed_at | DateTimeField, null | |
| result | JSON | what the commit produced |
| undo_of | FK Proposal, null | set on the compensating proposal |

One `proposed` row per thread at a time: a new proposal marks the old one `superseded` and
says so in one line.

### assistant.Job

| field | type | notes |
|---|---|---|
| kind | enum | `inbound`, `brief_send`, `purge` |
| payload | JSON | `{message_id}` or the rendered text |
| status | enum | `queued`, `running`, `done`, `failed` |
| attempts | PositiveInt | capped at 3 |
| run_after | DateTimeField | backoff |
| locked_at | DateTimeField, null | claim timestamp |
| error | TextField, blank | last failure |

### assistant.AuditLog

`thread`, `tool`, `args` (JSON), `result` (JSON), `model`, `latency_ms`, `ok`,
`raw_words` (the lawyer's exact sentence, for a commit), `created_at`. One row per tool call,
whether it read, proposed, committed or undid.

Indexes that matter: `Message.wamid` unique, `Proposal(thread, status, expires_at)`,
`Job(status, run_after)`, `Document.search_vector` GIN, `Appointment(starts_at)`,
`Deadline(due_date, status)`.

---

## 5. Agent design

### 5.1 The loop

```python
def run(thread, user_text, *, trigger="chat"):
    msgs = [system_prompt(thread)] + thread.recent(20) + [user_msg(user_text)]
    for step in range(4):
        resp = llm.chat(msgs, tools=TOOLS.schemas())
        if not resp.tool_calls:
            return resp.text
        for call in resp.tool_calls:
            tool = TOOLS[call.name]
            result = tool.fn(thread, **call.args)          # reads read; writes propose
            audit(thread, call, result)
            msgs += [resp.as_message(), tool_message(call.id, result)]
    return "No he podido terminar con esto, lo reviso yo."
```

No framework. No LangChain. `llm.py` is one OpenAI-compatible client pointed at
`https://openrouter.ai/api/v1`, so the model is an env var, not a refactor.

The loop never mutates. `confirm`, `cancel` and `undo` are tools like any other, but their
only argument is a proposal id and their body is plain Python over a stored payload.

### 5.2 Tool registry

Reads — flat schemas, unlimited growth, no confirmation:

| tool | args | behaviour |
|---|---|---|
| `agenda_today` | — | appointments + travel blocks + conflicts |
| `agenda_range` | `start`, `end` | same, for arbitrary range |
| `day_simulation` | `date` | the §8.2 loop: departures, lateness, first three conflicts |
| `route_estimate` | `from`, `to`, `at` | one leg, traffic-aware, cached |
| `find_free_slot` | `duration`, `after`, `before` | the first slots that actually fit |
| `case_search` | `query` | clients/cases by name or reference |
| `case_summary` | `case_id` | client, status, last notes, next dates, doc count |
| `case_notes` | `case_id`, `limit=5` | recent notes |
| `document_search` | `query`, `case_id?` | FTS over extracted text, returns snippets |
| `deadline_list` | `days=30` | upcoming deadlines with `computed` flag |

Writes — capped at seven, each builds a `Proposal`, none mutates:

| tool | args | proposes |
|---|---|---|
| `appointment_create` | `kind`, `when`, `duration_min`, `address?`, `title` | a new appointment + travel block |
| `reschedule` | `appointment_id`, `new_start` | the move + knock-on effects |
| `plan_visit` | `case_id?`, `when`, `duration_min?`, `address` | address → card → route → block |
| `deadline_create` | `case_id`, `title`, `notified_on`, `term_value`, `term_unit` | computed date + disclaimer |
| `client_update` | `client_id` | a draft whose exact text is in the envelope |
| `file_document` | `case_id`, `media_id?` | filing the last inbound file |
| `note_add` | `case_id`, `body` | a case note, voice or text |

Commit tools: `confirm(proposal_id)`, `cancel(proposal_id)`, `undo(proposal_id)` — never
counted against the write cap, never carrying data.

If an eighth write is proposed, it must replace one.

### 5.3 The proposal (the critical path)

1. A write tool **never mutates**. It validates args, builds `steps`, renders `summary` and,
   for a client message, `outbound_text`, then inserts `Proposal(status=proposed,
   expires_at=min(appointment.start, now+12h))`. The old open proposal becomes `superseded`.
   The tool returns the summary — the exact Spanish the lawyer will see.
2. The lawyer answers in words. The model sees the open proposal in its prompt and may call
   `confirm(id)`, `cancel(id)` or a new write tool. `confirm` takes **no other arguments**:
   pydantic rejects extra fields, and the commit reads the payload from the row.
3. Commit runs in `transaction.atomic()` with `select_for_update()` on the row, applies each
   step in order, sends `outbound_text` **as stored** (never re-rendered), and writes
   `AuditLog.raw_words`. Duplicate confirmation replies "ya estaba hecho".
4. A question about the proposal ("¿por qué?") never commits: it is answered, and the
   proposal stays open until it expires or is superseded.
5. Expiry is enforced twice: `sweep` every five minutes, and a lazy check at commit time.
6. `undo(id)` builds the compensating proposal and commits it immediately — the lawyer asked
   for it explicitly. It covers calendar, deadline and document effects; a sent client
   message cannot be unsent, so undo offers a correction message instead.

### 5.4 Prompt contract

- System prompt states: role, the lawyer's real data model, today's date in
  `America/Mexico_City`, the base location, the open proposal if one exists, and the rule
  *"you cannot act; you can only propose, and confirm only what was shown"*.
- Spanish register (`usted`), brevity (`WhatsApp`, no markdown tables), direct answers.
- Hard rules: never invent an address, a deadline date, a client, or a time. Times in a
  proposal come from a tool result.
- Tool results are compact JSON with IDs included so the model can chain.
- No raw document text in the prompt beyond retrieved snippets (≤ 3 × 400 chars).
- If the model returns no tool call for an action-shaped request — defined as *an open
  proposal exists*, or *the sentence contains a known action verb* — the answer ends with an
  offer, never an action.

### 5.5 Guardrails (each is a test)

| guard | test |
|---|---|
| Only the lawyer's JID is processed | post webhook as another number → 200, no thread write |
| Device B is never processed | post a device-B event → 200, no thread write |
| Duplicate wamid ignored | same payload twice → one reply, `replied_at` set |
| Write never executes without confirm | call a write tool → DB unchanged, Proposal exists |
| Model cannot inject a payload | call `confirm` with extra args → rejected; stored payload applied |
| Client text is what was shown | model rephrases after proposing → the stored bytes are sent |
| A question does not commit | "¿por qué lo mueves?" → proposal still `proposed` |
| Double confirm commits once | confirm twice → one Appointment, one "ya estaba hecho" |
| Expired proposal cannot commit | freeze time +13 h → confirm → rejected politely |
| Undo restores the prior state | commit then undo → appointment back, audit shows both |
| Tool loop capped | force 4 tool calls → graceful failure message |
| Job retry bounded | poison payload → 3 attempts → failed + alert |
| Rate cap on client sends | 21 messages in an hour → 21st refused with explanation |

### 5.6 Model routing (OpenRouter, cheap first)

`LLM_MODEL` starts cheap (a DeepSeek flash-class model — look the exact id up in the catalogue
at implementation time, ids move). `LLM_FALLBACK_MODEL` is a stronger model, used in exactly
three cases:

1. an open proposal exists and the primary returned no tool call,
2. the primary's tool arguments fail pydantic validation twice,
3. the primary returns malformed JSON or an unknown tool name.

OpenRouter also supports server-side fallback (`models: [...]`, `provider.allow_fallbacks`),
but the app-level fallback is what protects correctness, and it keeps the failure visible in
the audit log instead of hidden in the gateway. `AuditLog.model` records which model actually
answered.

Cheap models fail in one specific way that matters here: they drop or mangle tool arguments.
Mitigations — flat schemas, pydantic validation with one retry, and a commit path that never
depends on model-supplied data. The test that matters: 20 canned Spanish requests must route
to the right tool with valid arguments, on the cheap model, before S2 ships. A second set of
20 must produce the right `confirm`/`cancel`/`nothing` decision on an open proposal.

Add `HTTP-Referer` and `X-Title` headers (OpenRouter attribution); cost is cents at this
volume, so the constraint is reliability, not spend.

---

## 6. Channel: WhatsApp

### 6.1 Sessions

| | A — control | B — delivery |
|---|---|---|
| Number | dedicated eSIM (assistant) | lawyer's own number |
| gowa role | primary | companion device (linked from the phone) |
| Webhook | processed | **dropped by device id** |
| Traffic | lawyer ⇄ assistant | assistant → clients only |
| Failure mode | bot silent, dead-man alert fires | sends become drafts via `DELIVERY_MODE` |

Pairing happens once, from the lawyer's phone (Dispositivos vinculados → Vincular dispositivo).
The assistant number also needs a primary device of its own (a spare phone or a second
WhatsApp install) to issue the pairing code. Session state lives in gowa's volume; losing it
means re-pairing, not data loss. If the lawyer's phone is offline for ~14 days, WhatsApp
unlinks the devices and session B must be paired again — the sweep warns at day 10.

### 6.2 Webhook contract

`POST /webhooks/gowa`, header `X-Hub-Signature-256` (this is what gowa sends; gowa's default
secret is literally `secret`, so `WEBHOOK_SECRET` is mandatory).

Normalised input: `device_id`, `message_id` (wamid), `from_jid`, `timestamp`, `type`
(`text|audio|image|document`), `text`, `media_id`, `mime`, `filename`.

Responsibilities, in order: verify signature → drop non-device-A → dedupe by `wamid` →
check `from_jid` against `LAWYER_JID` → persist Message + InboundMedia + Job → return 200.
The worker then transcribes, runs the agent and sends. Always 200, even on internal error,
because a non-200 makes gowa retry and duplicate the conversation.

`WHATSAPP_WEBHOOK_EVENTS` includes `message` and, optionally, `message.ack`; acks are a
secondary trial signal only.

### 6.3 Outbound rules (delivery session)

- Target must be an existing `client.jid` in the DB. No number outside the book, ever.
- Per-message confirmation of the text that was displayed, always. `outbound_text` is sent
  byte-for-byte; a re-render is a bug.
- `DELIVERY_MODE`: `auto` (send on confirmation) or `draft` (confirmation turns the message
  into a draft the lawyer forwards). The flag is per instance and takes effect on the next send.
- Caps: 20 client messages/hour, 60/day, 2 s inter-message delay.
- Never identical text to two clients in a row (the assistant writes each one), no links by
  default, no attachments unless the lawyer attached them.
- Every send logged with the rendered text, so a complaint can be answered.
- No broadcast, no groups, no status, never to a JID not already in a chat.

These caps are not politeness — they are the difference between a companion device and a
spam account, which is what gets numbers banned.

### 6.4 Media

Inbound: gowa media download → `media/inbound/<yyyy>/<mm>/<sha256>.<ext>` → `InboundMedia`
row, max 25 MB. Audio: ogg/opus → faster-whisper in the worker, no ffmpeg conversion needed.
Images: stored, not OCR'd in v0.1 (a photo of a document is filed, not indexed).
Documents: pdf/docx/xlsx/txt → text extraction → indexed. Unfiled media is purged at 90 days.

---

## 7. Calendar

### 7.1 Why `.ics` and not the API

Personal @gmail with an OAuth app in "Testing" gets refresh tokens that expire in 7 days;
publishing the app with the Calendar scope requires Google verification (privacy policy, demo
video, review). Neither is acceptable for a $50/mo product with a one-week setup.

`.ics` solves it with zero credentials:

- **Invites.** On create/reschedule/cancel, Django emails an iCalendar `REQUEST` to the lawyer.
  Stable `UID` = `appointment.ics_uid`, `SEQUENCE` increments on every real change,
  `STATUS:CANCELLED` on cancel. Correct semantics mean reschedules *update* the event instead
  of duplicating it. Client recipients are out of scope for v0.1.
- **Feed.** `GET /calendar/<ICS_TOKEN>.ics` is a read-only snapshot: appointments, travel
  blocks and deadlines as all-day events. The lawyer subscribes once ("Desde URL"). Google
  refreshes subscribed calendars on its own schedule (hours), so the feed is the *view*, and
  the invite is the *instant* signal.

### 7.2 Event shapes

| object | calendar object | notes |
|---|---|---|
| Appointment | timed event, `LOCATION` = address, `DESCRIPTION` = client + case ref | `TRANSP:OPAQUE` |
| TravelBlock | timed event titled `Traslado → <location>` | `TRANSP:TRANSPARENT`, so it doesn't look busy |
| Deadline | all-day event, `VALARM` at 7/3/1 days | description carries "calculado — verifica" |

### 7.3 Travel blocks

For each visit with coordinates, one block ending 5 min before the appointment, starting at
`appointment.starts_at - buffer_min - travel_min`. Origin is the previous stop of the day, or
`BaseLocation` for the first. Blocks are recomputed when the appointment moves, when the
address changes, or when the 08:00 brief runs (traffic changes). Return trips are not modelled.

---

## 8. Briefing and the day simulation

### 8.1 `manage.py brief --kind=morning|evening`

Pure template rendering. No LLM, no menu. Runs at 08:00 and 20:00 `America/Mexico_City`.

**Morning (08:00)**

```
Buenos días, Dari. Hoy tienes 3 compromisos.

09:30  Visita — García / despacho demandado
       Sal de Oficina a las 08:45 (38 min de traslado + 7 de margen)

11:00  Audiencia — Juzgado 4° de lo Laboral
       Traslado desde la anterior: 22 min
13:00  Junta con Peralta (sin dirección)

Plazos próximos
• 26 nov — Contestación (García) · calculado, verifica
• 02 dic — Ofrecimiento de pruebas (Peralta) · calculado, verifica

Ojo: entre la audiencia y la junta hay 41 min y necesitas 55.
```

No "responde 1". The lawyer answers in words — "no creo que llegue", "muévela", "¿por qué?" —
and the agent takes it from there: `day_simulation`, then `find_free_slot`, then a proposal.

**Evening (20:00)** — tomorrow preview, same simulation, plus "mañana no cabe" and a reminder
of open proposals.

### 8.2 Conflict detection (deliberately simple)

Sequential simulation, no constraint solver:

```
t = day start at BaseLocation
for appt in day.ordered:
    travel = route(prev, appt).duration_in_traffic   # prev = last stop or BaseLocation
    ready = t + travel + appt.buffer_min
    if ready + appt.duration_min > appt.starts_at:  → late_by = ...
    if late_by > 0: record conflict(late_by, cause)
    t = max(appt.starts_at, ready) + appt.duration_min
```

- One `computeRoutes` call per leg (traffic-aware, Pro SKU), cached 30 min per leg and
  departure slot. A single matrix call cannot carry different departure times, so it is not used.
- Conflicts are reported as *the first three*, each with a concrete fix.
- The fix is deterministic: the next free slot of that appointment's duration after the
  blocking block, rounded to 5 min, never before the conflict clears, max three alternatives.
- Never silently rewrite the day. Proposals only.
- If an appointment has no coordinates, travel = 0 and the brief says "sin dirección" once.

### 8.3 Deadline reminders

- 7/3/1 days before, included in the morning brief.
- Missed (`due_date < today`, `status=open`) → escalated to the top of the brief, in bold,
  and repeated every day until `done`. `sweep` is what sets `missed`.

---

## 9. Deadlines (México)

### 9.1 Arithmetic

`business_days_between(start, n, calendar)` adds `n` working days, skipping Sat/Sun and the
holidays of the applicable calendar(s), with two rules that are not optional in Mexican practice:

- **The count starts the day after the notification takes effect.** Day 1 = the next hábil
  day after `notified_on`, never `notified_on` itself.
- **Prórroga:** if the last day is inhábil, the term moves to the next business day.
  `meses` uses calendar months with the same end-of-month and prórroga rules.

Calendars, all as data (`config/calendars/*.yaml`), never as code. Each entry carries
`source:` (the official URL) and `verified_on:`:

- `federal` — Mexican federal holidays from the DOF, including the in-lieu Mondays.
- `oaj` — the yearly *días inhábiles* of the **Órgano de Administración Judicial**
  (`oaj.gob.mx`, formerly the CJF, extinguished by the 2024 reform). Includes the
  "inhábil pero laborable" days (5 feb, 20 nov), which are inhábil for terms even though the
  offices open.
- `hidalgo` — the Poder Judicial del Estado de Hidalgo calendar, currently Circular 01/2026
  (`pjhidalgo.gob.mx/.../Circulares/2026/1_2026.pdf`): 2 feb, 16 mar, 2–3 abr, 1 may,
  16 sep, 2 nov, 16 nov, plus vacations 16–31 jul and 17 dic–8 ene 2027. Seeded by hand from
  the PDF — its OCR is unreliable. One-off decrees during the year (e.g. Circular 03/2026
  declaring 18 Aug inhábil) go in `custom`.
- `custom` — free dates per instance (local closures, suspension days).

Applicable calendar per deadline = `federal ∪ oaj ∪ hidalgo`, overridable per deadline for
administrative matters (federal only) or natural-day terms. `dias_naturales` ignores calendars
except for the prórroga on the last day.

A January ritual refreshes all three from their published sources and bumps a
`CALENDAR_VERSION`; a deadline verified against an older version is flagged
"calendario actualizado — re-verifica".

### 9.2 The disclaimer is load-bearing

Every computed date is rendered as:

> 26 nov 2026 · calculado (20 días hábiles desde notificación 30 oct) · **verifica**

Stored `computed=True` and shown in both WhatsApp and dashboard. The dashboard has a
one-click "marcar como verificado" that sets `verified_by`, `verified_at` and
`verified_with_calendar` — the date keeps its provenance instead of losing it. A bug in the
holiday table must never become a missed filing presented as authoritative.

### 9.3 Out of scope

Automatic rule resolution from the type of proceeding (civil/mercantil/laboral/penal/amparo),
32 state procedural codes, suspension/interruption of terms, notifications with a specific
hour. Manual entry with a calculator is the v0.1 answer.

---

## 10. Files and search

- Storage: `media/documents/<case_id>/<sha256[:2]>/<sha256>.<ext>` — content-addressed, so
  duplicates collapse and renames don't matter.
- Extraction: `pypdf` (PDF text layer), `python-docx`, `openpyxl` (first sheet, first 200 rows),
  plain text. A scanned PDF with no text layer is accepted and flagged `no_text_layer=True`
  (keeps the promise honest: no OCR in v0.1).
- Search: Postgres `tsvector` maintained by a trigger on insert/update, `config='spanish'`,
  GIN index. Snippets via `ts_headline`. Case/client name matches boost via `pg_trgm`.
- Query surface: `document_search` tool (WhatsApp) and a search box in the dashboard.
- No embeddings, no chunking, no vector store. `ponytail:` marker in code: upgrade path is
  pgvector + chunking if the lawyer ever asks "¿hay algo sobre la cláusula suelo?" and FTS fails.
- Limits: 25 MB per file, 500 MB per instance soft cap, with a dashboard warning at 80%.
- Deletion: soft delete on `Document`; the blob goes only when no active document and no
  `InboundMedia` row references it.
- Retention: `raw` provider payloads and unfiled `InboundMedia` rows are purged at 90 days by
  `sweep`; message text, audit rows and filed documents persist for the life of the instance.

---

## 11. Dashboard

Django templates + HTMX, no SPA. Public, TLS, login + TOTP (`django-otp`), no signup, session
8 h, `is_staff` for the ops console. **Login ships in S1**: no page is reachable before it.

Read-mostly pages:

| page | shows | editable |
|---|---|---|
| `/` | today's agenda with computed departure times, conflicts, next deadlines | no |
| `/clients/` `/clients/<id>` | client data, cases, last notes | phone/email/notes |
| `/cases/<id>` | case, appointments, deadlines, documents, notes timeline | status, notes |
| `/documents/` | search + list + upload | upload |
| `/agenda/` | week view with travel blocks | nothing (WhatsApp only) |
| `/plazos/` | deadlines, `computed` badge, "verificar" action | mark done / verify |

Ops console (staff only): raw messages, audit log, proposals, failed jobs, re-run extraction,
download logs, and the **2FA reset** action (audited, emails the lawyer).

Deliberately absent: appointment editing (WhatsApp is the input; undo is a chat tool), client
creation (from WhatsApp or admin), settings UI (config file + env).

---

## 12. Slices

### S1 — channel, briefing, plazos, ETA (≈2 weeks)

Build: Django skeleton, models, auth + TOTP, gowa container + device A pairing, webhook →
`Job` → `work` worker, STT, `BaseLocation`, Routes/Places clients, ICS feed + invites,
`brief` nudge + timer, `sweep`, calendar seeds + deadline arithmetic, read tools
(`agenda_today`, `agenda_range`, `day_simulation`, `route_estimate`, `find_free_slot`,
`case_search`, `case_summary`, `deadline_list`), minimal dashboard behind login.

**Done when**
- [ ] "hola" from the assistant number replies in < 5 s
- [ ] 40 s voice note → usable Spanish transcript
- [ ] 08:00 nudge arrives with a departure time per visit from the base location
- [ ] an intentionally impossible day is flagged, and "¿llego a la de 12:30?" gets a real answer
- [ ] ICS feed subscribed in the lawyer's Google Calendar shows the same appointments
- [ ] an `.ics` invite lands as one event; resending updates it, never duplicates
- [ ] replaying the same webhook twice produces one reply
- [ ] a message from any other number is dropped and logged
- [ ] a device-B event never reaches the database
- [ ] computed deadline matches a hand calculation for 10 fixtures (incl. a Hidalgo vacation)

### S2 — the conversation and the writes (≈1.5 weeks)

Build: `Proposal` + `confirm`/`cancel`/`undo`, expiry in `sweep`, `reschedule`,
`appointment_create`, `plan_visit` (Places card → link fallback → route → travel block),
`deadline_create`, `note_add`.

**Done when**
- [ ] "mueve la cita de las 17:00 al jueves" shows the collision; "sí" commits; "no" cancels
- [ ] "¿por qué la moviste?" answers without committing anything
- [ ] no reply before expiry → expired, nothing changed, the next proposal supersedes cleanly
- [ ] "sí" twice → one appointment, one "ya estaba hecho"
- [ ] `plan_visit` with "frente al Soriana" asks once, offers a link, never pins a wrong colonia
- [ ] travel block appears 5 min before the buffer, and moves when the appointment moves
- [ ] "deshaz lo último" restores the previous state within 24 h

### S3 — notes, voice, files, client updates (≈1.5 weeks)

Build: `file_document` (forward → file under case), extraction + FTS, `document_search`,
voice-note → `Note` + `case_notes`, `client_update` + delivery session B + caps +
`DELIVERY_MODE`, dashboard documents page, 90-day purge.

**Done when**
- [ ] forwarded PDF is filed under the right case and found by a phrase inside it
- [ ] scanned PDF is accepted and clearly marked "sin texto"
- [ ] a post-visit voice note becomes a note on the case, visible in the dashboard
- [ ] client update: drafted → text shown → confirmed → sent from the lawyer's number → logged
- [ ] with `DELIVERY_MODE=draft`, the same flow produces a draft instead of a send
- [ ] sending to an unknown number is refused
- [ ] the 21st client message in an hour is refused with an explanation

### Dashboard polish (≈4 days, parallel)

Clients/cases/documents/plazos pages, ops console, 2FA reset.

---

## 13. Pilot

The lawyer is available but not committed. That changes the order of operations:

1. **15-min interview before S1** — five questions, in their words:
   describe yesterday hour by hour · where do plazos live and what happened the last time one
   nearly slipped · how do you decide when to leave for a visit · how do clients ask for
   updates today · what would you delete from your week.
2. Build S1, demo in week 1 with *their* data seeded (5 clients, 3 cases, a week of
   appointments).
3. 5-day trial. One 10-min debrief, three questions: what did you ignore, what was wrong,
   what did you do manually anyway.
4. S2 only after the nudge survives the trial. If it doesn't, the problem is the framing,
   not the code — stop and re-interview.

Success metrics, all from stored data: answered the nudge within 2 h (≥4 of 5 days),
proposals accepted vs rejected, manual reschedules found in the debrief, days with a flagged
conflict, client updates sent. `message.ack` is a secondary signal, never the gate.

---

## 14. Deployment

### Containers (per despacho)

| service | image | notes |
|---|---|---|
| `web` | built from repo | gunicorn, 2 workers × 2 threads, `media` volume |
| `db` | postgres:16 | own DB per instance, no shared cluster |
| `gowa` | gowa image, pinned tag | `data` volume, **not** exposed publicly |

No Redis, no Celery. Three timers inside `web` (container cron or Coolify scheduled tasks):
`work` every minute, `sweep` every 5 minutes, `brief` at 08:00 and 20:00.
Each successful run pings `HEALTHCHECK_URL`; a missing ping for one cycle emails the owner.

### Instance config (`config.yaml`)

Secrets live in env; human-edited per-instance settings live in `config.yaml`, mounted into
`web` and read at boot (D15):

```yaml
name: "Despacho García"
delivery_mode: auto          # auto | draft
kinds:                       # default duration + buffer per kind
  visita:   {duration: 60, buffer: 15}
  audiencia:{duration: 90, buffer: 30}
  juzgado:  {duration: 60, buffer: 20}
  reunion:  {duration: 45, buffer: 10}
  tramite:  {duration: 30, buffer: 15}
caps: {hourly: 20, daily: 60, delay_seconds: 2}
reminders: [7, 3, 1]
```

### Env

```
DJANGO_SECRET_KEY=      DJANGO_DEBUG=0        DJANGO_ALLOWED_HOSTS=
DATABASE_URL=           TZ=America/Mexico_City
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=            LLM_MODEL=            LLM_FALLBACK_MODEL=
LLM_REFERER=            LLM_TITLE=lexagenda
GOWA_URL=http://gowa:3000       GOWA_BASIC_AUTH=
GOWA_DEVICE_A=          GOWA_DEVICE_B=        GOWA_DEVICE_B_FILTER=1
WEBHOOK_SECRET=         LAWYER_JID=          ASSISTANT_NUMBER=
GOOGLE_MAPS_API_KEY=    ROUTES_DAILY_CAP=200  ICS_TOKEN=
EMAIL_HOST= EMAIL_HOST_USER= EMAIL_HOST_PASSWORD= EMAIL_FROM=
EMAIL_FROM_CLIENT=      HEALTHCHECK_URL=
```

Two senders, on purpose: `EMAIL_FROM` is the system sender on the owner's domain for invites
and internal notices; `EMAIL_FROM_CLIENT` is the lawyer's own address (with `Reply-To`) for
the rare client-facing email. Most client communication moves to WhatsApp by design.

`DELIVERY_MODE`, the caps and the per-kind durations live in `config.yaml`, not in env: they
are per-despacho settings a human may edit, while env holds only secrets and infrastructure.
Changing `delivery_mode` takes effect on the next send, with no redeploy.

### Network posture

- Public: Django only (Traefik + TLS + HSTS). 2FA on every login.
- Internal only: `gowa` and `db`. gowa's port must be unreachable from the internet — verify
  from outside, not from the VPS. A reachable gowa is a "send as the lawyer" API with no 2FA.
- Outbound only: LLM, Routes/Places, SMTP, healthchecks.

### Backups

Nightly: `pg_dump -Fc` + `media/` tarball → Backblaze B2, `age`-encrypted, 30-day retention,
weekly full kept 6 months. The `age` private key is held by the owner offline, never in the
repo or the VPS. One restore drill before the pilot starts, timed and documented.
A legal product without a tested restore is a liability spreadsheet.

---

## 15. Security and privacy

| threat | control |
|---|---|
| Someone else texts the bot | `from_jid` must equal `LAWYER_JID`; everything else dropped before any processing |
| Delivery traffic reaches the app | device id filter before any DB write; gowa's `data` volume is encrypted at rest and its access documented |
| Forged webhook | HMAC-SHA256 in `X-Hub-Signature-256`, constant-time compare, non-default secret |
| gowa exposed | not published in Coolify; verified from an external host |
| Prompt injection from a document | document text enters the prompt only as untrusted snippet, never as instructions; writes still require a human confirmation of a displayed payload |
| Leak of client data to the LLM | tool results only, ≤ 3 snippets × 400 chars, no full files, no attachments; US processing disclosed as *encargado* |
| Phone numbers in logs | redacted in application logs, kept in DB only |
| Lost laptop / stolen session | 2FA, 8 h sessions, logout-all, no "remember me"; ten recovery codes |
| Lost TOTP device | owner reset in the ops console, audited, lawyer emailed, disclosed in the contract |
| Deletion mistakes | soft delete on Client/Case/Document; hard delete only via a management command |
| Cross-client leak | one database per instance; no code path reads another instance |

Retention: structured records for the life of the instance. Raw provider payloads and unfiled
media are purged at 90 days. On cancellation: encrypted export (`manage.py export --all`)
handed to the lawyer, then deletion after 30 days. Both go in the contract, not just the code.

The contract also carries three disclosures that are product decisions, not fine print: the
LLM provider processes case data in the US as *encargado*; the owner can reset 2FA; the
WhatsApp channel is unofficial and a number may be restricted.

---

## 16. Costs (per instance / month)

| item | estimate |
|---|---|
| VPS share (3 containers) | 4–6 € |
| LLM API (OpenRouter) | 1–4 € depending on model |
| Routes API | 0–10 € — traffic-aware is the **Pro** SKU (5,000 free elements/mo, then $10/1,000); one call per leg |
| Places API | 0–2 € — Essentials, 10,000 free/mo |
| Backblaze B2 | ~1 € |
| eSIM for the assistant number | ~5 € |
| **total COGS** | **~15 €** → ~70% margin at $50 |

Guardrail: `ROUTES_DAILY_CAP` in settings, enforced in `maps.py`; exceeding it degrades the
brief to "sin cálculo de traslado" instead of spending.

---

## 17. Risks

| risk | likelihood | impact | mitigation | fallback |
|---|---|---|---|---|
| Delivery session restricted | low–med | lawyer's own number at stake | warm-up, existing-contacts-only, caps, per-message confirm, no links, `DELIVERY_MODE=draft` | he forwards drafts manually |
| Control number banned | low | bot unreachable | warm-up, single-contact number, no outbound campaigns | re-register, re-pair |
| Address resolution wrong | med | lawyer goes to the wrong place | location card + explicit ✅ + link fallback | ask for a Maps link |
| Deadline arithmetic wrong | med | malpractice perception | official calendars + `verified_with_calendar` + 10 fixtures | manual date entry |
| Calendar source changes / OCR errors | med | wrong dates | hand-seeded, `source` + `verified_on`, January refresh, re-verify flag | freeze last year's list, lawyer edits `custom` |
| Google updates ICS behaviour | low | stale feed view | invites remain the instant channel; dashboard always accurate | weekly `.ics` zip export |
| Lawyer doesn't adopt | med–high | no revenue | nudge first, 15-min interview, 5-day trial gate | pivot demo to files/plazos |
| gowa breaking change | med | channel down | pinned image tag, no auto-update, healthcheck | pin older tag |
| Linked device unlinked (phone offline ~14 d) | low | session B silent | sweep warns at day 10 | re-pair from the phone |

---

## 18. Prerequisites (owner actions, start now)

1. **eSIM / second number**, plus a **primary device** to hold it (spare phone or a second
   WhatsApp install). Register it and use it normally for ~1 week before the bot touches it.
2. **Google Cloud project** with billing + **Routes API** and **Places API (New)** enabled;
   key restricted to those APIs, server-side only.
3. **OpenRouter API key**; pick a cheap primary model and a stronger fallback from the
   catalogue and put both in env.
4. **The lawyer's phone, once** — to link the companion device for delivery.
5. **Coolify app** + Postgres + volume + domain; TOTP app installed for 2FA.
6. **SMTP credentials on the owner's own domain** (SPF/DKIM configured) for `.ics` invites.
7. **healthchecks.io** project (or self-hosted) for the dead-man pings.
8. **Test**: send one `.ics` invite to the lawyer's personal @gmail and confirm it lands.

---

## 19. Open questions

Resolved in this revision: conversational confirmation · base location · client onboarding ·
LLM provider and disclosure · address resolution · operator alerts · Hidalgo/OAJ calendar
sources · 2FA recovery · undo surface · trial metrics · retention · delivery number · client
email default (lawyer only) · caps (20/h, 60/d, 2 s) · envelope expiry (12 h, capped at the
appointment) · `moved` removed from the status enum.

Still open:

1. Project name — `lexagenda` is a placeholder.
2. Dashboard domain.
3. The two model ids, once you see the catalogue.
4. Who is the lawyer, and when is the 15-min interview.
5. `usted` confirmed as the register (default in this plan).

---

## 20. v0.2 backlog (not now)

Multi-stop route optimisation across a whole day · return-trip modelling · multiple base
locations · OCR for photographed documents · client portal over WhatsApp (intake + status) ·
Gmail triage · Google Drive as external storage · n8n connector shelf · pdf generation
(status reports, invoices) · time tracking · second user (secretary) with a restricted role ·
pgvector semantic search · TTS replies · per-client instance provisioning automation
(Coolify API) · white-label branding.
