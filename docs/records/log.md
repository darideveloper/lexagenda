# Log

## walking-skeleton — 2026-11-26
Shipped: WhatsApp control channel with eight domain models, TOTP login plus ten recovery codes, an HMAC webhook that drops device B, foreign JIDs, non-text and duplicate wamids and always answers 200, a job worker with `replied_at` and bounded retry, three read tools, and `/admin/` behind `OTPAdminSite`; 52 tests green, surface `local — prod unproven`.

## deadlines — 2026-11-26
Shipped: four official calendars seeded with a source per date, day-after start, prórroga and `meses`, ten hand-computed fixtures, `/plazos/` verify with a stale-version flag, and `sweep` marking overdue deadlines missed; 87 tests green, surface `local — prod unproven`.

## day-simulation — 2026-11-26
Shipped: `BaseLocation` as the day's origin, per-leg traffic-aware routes with a 30-minute cache and daily cap, the sequential day walk with `late_by` and causes, `find_free_slot` and ¿llego?, the morning and evening briefs with no model call, and `seed_demo`; 131 tests green, surface `local — prod unproven`.
