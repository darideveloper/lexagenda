# Log

## walking-skeleton — 2026-11-26
Shipped: WhatsApp control channel with eight domain models, TOTP login plus ten recovery codes, an HMAC webhook that drops device B, foreign JIDs, non-text and duplicate wamids and always answers 200, a job worker with `replied_at` and bounded retry, three read tools, and `/admin/` behind `OTPAdminSite`; 52 tests green, surface `local — prod unproven`.

## deadlines — 2026-11-26
Shipped: four official calendars seeded with a source per date, day-after start, prórroga and `meses`, ten hand-computed fixtures, `/plazos/` verify with a stale-version flag, and `sweep` marking overdue deadlines missed; 87 tests green, surface `local — prod unproven`.

## day-simulation — 2026-11-26
Shipped: `BaseLocation` as the day's origin, per-leg traffic-aware routes with a 30-minute cache and daily cap, the sequential day walk with `late_by` and causes, `find_free_slot` and ¿llego?, the morning and evening briefs with no model call, and `seed_demo`; 131 tests green, surface `local — prod unproven`.

## proposals — 2026-11-26
Shipped: the proposal envelope (one open, supersede, 12-hour expiry), id-only confirm/cancel/undo under a row lock with `raw_words`, `reschedule`, `appointment_create` and `deadline_create` on the real calendars, and the fallback router with 20+20 canaries; 183 tests green, surface `local — prod unproven`.

## dashboard — 2026-11-26
Shipped: clients and cases pages behind TOTP with a whitelisted edit surface, the staff ops console (messages, audit, proposals, jobs, retry, audited 2FA reset), and dead-man pings from `work`, `sweep` and `brief`; 212 tests green, surface `local — prod unproven`.

## files-search — 2026-11-26
Shipped: content-addressed `Document`/`InboundMedia`, a 25 MB ingest cap, pdf/docx/xlsx/txt extraction with "sin texto", Spanish FTS with `pg_trgm` and a GIN-backed snippet query shared by `document_search` and `/documents/`, and a 90-day purge with refcounted blob release; 291 tests green, surface `local — prod unproven`.

## plan-visit — 2026-11-26
Shipped: one Places card or a Maps link (never a guessed pin), address reuse from the client's last resolved visit, `plan_visit` proposals that spend no second route, travel blocks from `starts_at - buffer - travel` to `starts_at - buffer`, and recompute on move and brief; 323 tests green, surface `local — prod unproven`.

## ics — 2026-11-26
Shipped: stable UID and one SEQUENCE service that bumps only on create, move, cancel or re-address, lawyer-only REQUEST/CANCEL invites, a tokenized read-only feed with 404/noindex, per-request rotation, byte-wise token compare, and undo that cancels the visit and clears its travel block; 326 tests green, surface `local — prod unproven`.
