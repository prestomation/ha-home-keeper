# Minor-bugs fix plan (follow-up to the 2026-07 code review)

The in-depth code review (`REVIEW_FIX_PLAN.md`, PR #124) shipped every
critical, security, and major fix, plus several minors. This plan covers the
**remaining unchecked minor bugs**: **N1, N2, N5, N6, N8, N9, N10, N12, N13**.

Each item below is grounded in the current code (file:line references verified
against `main` at the time of writing). Items are grouped so related changes
land together, ordered by risk/independence. Every group is its own
commit/PR-slice, ticks its box in `REVIEW_FIX_PLAN.md`, and follows the repo
gates (tests locally, mypy, frontend build, CHANGELOG for user-facing fixes,
screenshots for panel-UI changes).

## Gate reminders that apply to this batch

- **Panel-UI gate (N8, N13):** these edit
  `custom_components/home_keeper/frontend/src/*.ts`, so the PR **must** embed
  current Playwright screenshots of the affected surface (task list buckets,
  confirm dialog) under `docs/images/`, per AGENTS.md. No new user-facing
  *feature* is added, so no video-walkthrough edit and no beta bump are required
  — these are bug fixes.
- **User-facing vs developer-only:** N1, N2, N5, N6, N8, N10 are user-facing →
  add `## [Unreleased]` (or the current top beta) CHANGELOG entries. N9, N12
  (dead-param, caps), N13 (leaks) are largely internal but N9/N12 change service
  docs the user sees — give N9 a short CHANGELOG note. When in doubt, add an
  entry.
- **Regression tests first.** Pure-logic bugs (N2, N6, N12 date/cap) get unit
  tests in `tests/unit`. Store/coordinator bugs (N1, N5, N10) get integration
  or store-level tests. Frontend bugs (N8, N13) get vitest tests where the logic
  is pure (bucketing, relative-day), plus a manual/e2e check for the DOM leaks.
- **No new services or events** are introduced here, so no `services.yaml`/
  `EVENTS.md` additions beyond N9's parity work.

---

## Group A — Notification & scheduling correctness (backend)

### N1. Notification "Mark done" must no-op on a stale tap
- **Where:** `notifier.py`, `_handle` coroutine in `async_setup_notifications`,
  completion branch at `notifier.py:301-304`.
- **Problem:** The handler calls `coord.store.complete_task(task_id, ...)`
  unconditionally. `complete_task` (`store.py:785`) always runs
  `recurrence.apply_completion` and advances the schedule. A stale notification
  still sitting on a second device — tapped after the task was already completed
  elsewhere — double-advances: a recurring task jumps two intervals, a snoozed
  task loses its snooze, a one-off/triggered/sensor task that already went
  dormant gets re-processed. The only current guard
  (`try/except (KeyError, TaskValidationError)`) catches a deleted task, not a
  no-longer-due one.
- **Fix:** Before completing, fetch the task and gate on whether it is actually
  armed/overdue.
  1. Add `recurrence` to the module imports (it is not currently imported).
  2. In the `ACTION_COMPLETE` branch, fetch `task = coord.store.get_task(task_id)`
     (accessor already used at `__init__.py:552`); treat a missing task as a
     silent no-op (mirror the existing `return`).
  3. Gate the completion on `recurrence.is_overdue(task, now=dt_util.utcnow())`
     (`recurrence.py:453`: `next_due is not None and now >= next_due`). This is
     `False` for a just-completed recurring task (next_due moved to the future),
     a snoozed task (future next_due), and any dormant one-off/triggered/sensor
     task (next_due is None) — exactly the stale-tap cases — and `True` only for
     a genuinely-overdue task.
  4. Scope the guard to the complete branch only. Snooze/skip share this handler
     (`notifier.py:305-317`); leave them unless we decide they need the same
     protection (they are idempotent-ish but worth a follow-up note).
- **Test:** integration/store test — complete a recurring task, then invoke the
  notification action a second time with the stale `task_id`; assert
  `last_completed`/`next_due` unchanged and no second completion appended.
- **User-facing:** yes → CHANGELOG "Fixed".

### N2. Usage-meter zero-blip: debounce meter-reset re-baseline
- **Where:** `sensor_tasks.py`, `evaluate_usage`, reset detection at
  `sensor_tasks.py:113-116`.
- **Problem:** `evaluate_usage` is a **pure** function whose only inputs are
  `task, reading, now`. Any single reading below the stored baseline immediately
  returns `ACTION_REBASELINE` with `baseline=reading`. A momentary sensor blip to
  0 (or any transient dip) is indistinguishable from a real meter reset, so one
  spurious low reading re-anchors the baseline and discards accumulated usage.
- **Fix — carry edge state across ticks (mirror `evaluate_threshold`):**
  `evaluate_threshold` (`sensor_tasks.py:123-163`) already models carried caller
  state: it takes `condition_met_prev`/`crossed_at` in and echoes the next edge
  state out in its decision dict, with the coordinator's `SensorTaskWatcher`
  holding that state across ticks (seeded at `coordinator.py:110-113`, applied in
  `SensorTaskWatcher.async_evaluate`, `coordinator.py:154`). Apply the same
  shape to `evaluate_usage`:
  1. Add a carried in-param (e.g. `reset_candidate: float | None = None`) and a
     matching key in the returned decision dict.
  2. On a below-baseline reading: if the prior tick already saw a below-baseline
     reading (`reset_candidate is not None`), fire `ACTION_REBASELINE`; otherwise
     return `action: None` and record `reset_candidate=reading`. Clear the
     candidate on any at-or-above-baseline reading.
  3. Extend `SensorTaskWatcher.async_evaluate` (`coordinator.py:154`) to persist
     and feed back the new field, exactly as it does for threshold edge state.
- **Test:** unit test in `tests/unit` — one low reading returns `action: None`
  with a candidate set; a second consecutive low reading returns
  `ACTION_REBASELINE`; a low-then-recovered pair does **not** rebaseline.
- **User-facing:** yes → CHANGELOG "Fixed".
- **Caveat:** confirm the watcher persists the candidate in memory only (not to
  the store) so a restart safely re-evaluates from the current reading.

---

## Group B — Coordinator lifecycle (backend)

### N5. Purged one-off tasks leave orphaned entities
- **Where:** `coordinator.py`, `_purge_expired_one_offs` at
  `coordinator.py:190-212` (called from `_async_update_data`,
  `coordinator.py:150`).
- **Problem:** The purge loop calls `self.store.delete_task(tid)` directly.
  `store.delete_task` (`store.py:390`) only mutates the store and fires the
  event — it never touches the entity registry. Entity cleanup happens by
  **reloading the config entry**, which the service delete path does explicitly
  (`handle_delete_task`, `__init__.py:575`, gated on the M14 predicate
  `task_has_entities`, `coordinator.py:80`). The purge path never reloads, so a
  device-attached + enabled one-off that expires on retention leaves stale
  button/sensor/binary_sensor entities in the registry.
- **Fix:**
  1. In the purge loop, keep the task dict (currently discarded — only `tid` is
     kept at `coordinator.py:203-207`) and record whether any purged task
     satisfied `task_has_entities`.
  2. After the loop, if any did, trigger an entry reload.
  3. **Reload safely from inside the update cycle.** `_purge_expired_one_offs`
     runs at the top of `_async_update_data` (`coordinator.py:150`) — the
     coordinator's own refresh. Awaiting `async_reload` inline tears down and
     recreates *this* coordinator mid-refresh. Defer it instead:
     `self.hass.async_create_task(self.hass.config_entries.async_reload(self.entry.entry_id))`
     so the current refresh completes first. (The service handlers await inline
     because they run outside the update loop; the coordinator must not.)
- **Test:** integration test — create an enabled device-attached one-off with a
  short retention, advance time so it purges, assert the per-task entities are
  removed (registry empty for that task) after the deferred reload.
- **User-facing:** yes (stale entities) → CHANGELOG "Fixed".

---

## Group C — Calendar window semantics (backend)

### N6. Fixed occurrences active during their window; overlap-start queries
- **Where:** `calendar.py` — `_next_start` fixed branch at
  `calendar.py:91-97`, and `_collect_events` fixed/floating branches at
  `calendar.py:119-131`. `EVENT_DURATION = timedelta(hours=1)` (`calendar.py:25`).
- **Problem (a):** `next_fixed_occurrence` (`recurrence.py:159`) returns the
  smallest occurrence **strictly greater than `after`**. So the instant a fixed
  occurrence's start crosses `now`, `_next_start` jumps to the *next* occurrence
  and the in-progress one (whose `start + EVENT_DURATION` window still covers
  `now`) is treated as past. The **floating** branch just below
  (`calendar.py:98-103`) deliberately keeps an occurrence active during its
  window (`if due and due + EVENT_DURATION > now: return due`) — the fixed branch
  is inconsistent.
- **Problem (b):** `async_get_events` window filtering uses a half-open
  `[start, end)` on the occurrence **start**: `expand_fixed_occurrences`
  (`recurrence.py:191`) yields only `start_date <= occ < end_date`, and the
  floating branch checks `start_date <= due < end_date` (`calendar.py:130`). An
  occurrence that *started* just before the window but still overlaps its start
  is excluded.
- **Fix:**
  - (a) Query from `now - EVENT_DURATION` in the fixed branch:
    `next_fixed_occurrence(anchor, freq, interval, after=now - EVENT_DURATION)`.
    (`start > now - EVENT_DURATION` ⇔ `start + EVENT_DURATION > now`, matching
    floating semantics.)
  - (b) Fixed query: expand from `start_date - EVENT_DURATION`. Floating query:
    change the lower bound to include overlap —
    `due < end_date and due + EVENT_DURATION > start_date`.
- **Test:** unit tests in `tests/unit` (calendar logic is thin over
  `recurrence`) — an occurrence whose window straddles `now` is returned as the
  active event; a `get_events` window whose start falls inside an occurrence's
  window includes that occurrence.
- **User-facing:** yes (calendar entity behavior) → CHANGELOG "Fixed".

---

## Group D — Documents I/O (backend)

### N10. Stream document GETs; write blob before persisting metadata
- **Where:** `manuals.py` — `HomeKeeperDocumentView.get` at `manuals.py:151-172`,
  `post` upload tail at `manuals.py:237-262`.
- **Problem (a):** GET buffers the whole file via
  `async_read_document(...)` (up to `MAX_DOCUMENT_BYTES` ≈ 25 MB) into memory
  before responding (`manuals.py:162,168`).
- **Problem (b):** The upload persists store metadata and fires
  `home_keeper_asset_updated` (`manuals.py:238`, event at `:259-261`) **before**
  the blob is written to disk (`async_save_document` at `:252`). In that gap a
  GET 404s and the event advertises a document with no backing file.
- **Fix:**
  - (a) Resolve the on-disk path (`documents.document_path(root, asset_id,
    document_id, filename)`, `documents.py:106`) and return
    `web.FileResponse(path, headers={CONTENT_DISPOSITION: disposition})` so
    aiohttp streams from disk and sets content-type. Drop the buffering
    `async_read_document` call; keep the NOT_FOUND handling for a missing file.
  - (b) Reorder: write the blob first, then persist metadata; on metadata
    failure delete the just-written file. Because `add_asset_document`
    (`manuals.py:238`) assigns `entry["id"]`, either (i) reserve/generate the id
    up front and pass it to both `async_save_document` and the store, or
    (ii) write to a temp name and rename to the store-assigned id after metadata
    succeeds. Prefer (i) if the store supports a caller-supplied id; otherwise
    (ii). Keep the existing OSError rollback semantics but inverted.
- **Test:** integration test — upload a document, assert the on-disk blob exists
  the instant the event fires (no 404 window); GET returns a streamed
  `FileResponse` (assert `Content-Disposition` and body). A metadata-failure
  path leaves no orphaned blob.
- **User-facing:** partially (perf/robustness) → CHANGELOG "Fixed".
- **Caveat:** verify `web.FileResponse` respects the auth/permission checks the
  current handler performs before responding — keep those checks ahead of the
  response.

---

## Group E — Feature-module minors (backend)

### N12. Four small correctness/hygiene fixes
1. **`last_replaced` uses naive `date.today()`** — `assets.py:437-441`
   (`_normalize_part`). Thread the injected clock down the call chain
   `build_asset`/`merge_update` (which already have `now`, `assets.py:612,636`)
   → `normalize_fields` (`:568`) → `_normalize_parts` (`:445`) →
   `_normalize_part` (`:395`), and compare against `now.date()` instead of
   `date.today()`. Add a `now`/`today` param with a sensible default only at the
   internal helpers; require it from the public entry points.
2. **Document cap enforced before merge** — `assets.py:212-215`
   (`_normalize_documents`) caps the *incoming* payload, but `_merge_documents`
   (`assets.py:278-290`) later prepends stored `file` documents to incoming
   `link`s, so the merged list can exceed `_MAX_DOCUMENTS`. Enforce the cap on
   the **merged** result — after `merge_update` assembles
   `fields["documents"]` (`assets.py:668-671`), raise
   `AssetValidationError` if `len > _MAX_DOCUMENTS`. (`append_document`,
   `assets.py:303`, already caps the merged total correctly — mirror it.)
3. **Companion registry unbounded** — `companions.py:68-79`
   (`REGISTER_COMPANION_SCHEMA`) uses `cv.string` with no length limits and
   `register` (`companions.py:102-121`) stores the descriptor verbatim with no
   count cap. Any client (via `EVENT_REGISTER_COMPANIONS`) can register unbounded
   domains and arbitrarily large strings. Add `vol.Length` bounds to the schema
   fields (`name`, `description`, `icon`, `docs_url`, and the `capabilities`
   list) and a count guard at the top of `register`: reject a *new* domain once
   `len(self._registered) >= MAX_COMPANIONS` (define `MAX_COMPANIONS` in
   `const.py`); updates to an existing domain remain allowed.
4. **Dead `declared_type` param** — `documents.py:59-61` (`validate_upload`).
   The param is never referenced (type is sniffed from bytes,
   `documents.py:75`). Drop it → `def validate_upload(filename: str, data: bytes)`;
   update the caller `manuals.py:233` and remove the now-unused `declared_type`
   local in `post` (`manuals.py:192,219`).
- **Test:** unit tests — future `last_replaced` rejected against injected `now`
  (deterministic, no wall clock); merged documents over cap rejected; oversized
  companion field / over-count registration rejected. The `declared_type` drop
  is covered by existing upload tests compiling/passing.
- **User-facing:** mostly internal; the companion cap and `last_replaced` fix
  are minor "Fixed" CHANGELOG notes.
- **Note:** #3 tightens a public service contract (`register_companion`). Pick
  generous limits (e.g. name ≤ 100, description ≤ 500, ≤ 50 companions) so no
  legitimate integration is rejected; document them in `services.yaml`/
  `strings.json` alongside N9.

---

## Group F — Service/string parity (backend)

### N9. `strings.json` ↔ `services.yaml` parity
- **Scope (verified against current files):**
  - **Two services entirely missing from `strings.json`:** `register_companion`
    (`services.yaml:895`, incl. 7 fields: `domain`, `name`, `icon`,
    `description`, `config_entry_id`, `docs_url`, `capabilities`) and
    `list_companions` (`services.yaml:948`).
  - **Missing field strings on existing services:**
    - `add_task` / `update_task` → `labels`, `card_links`, `task_chips`,
      `source` (fields at `services.yaml:109-147` / `235-266`).
    - `complete_task` → `origin`, `note`, `cost`, `photo`, `who`
      (`services.yaml:301-335`).
    - `update_completion` → `note`, `cost`, `photo`, `who`
      (`services.yaml:355-379`).
    - `set_options` → `dismissed_companions` (`services.yaml:885-893`).
  - **Schema-only fields (defined in voluptuous but absent from `services.yaml`
    *and* `strings.json`):** `completion_detail`, `completion_required_fields`
    (`ADD_TASK_SCHEMA`/`UPDATE_TASK_SCHEMA`, `__init__.py:117,118,142,143`),
    `managed_by` (`__init__.py:122`), snooze/skip `origin`
    (`SNOOZE_TASK_SCHEMA`/`SKIP_TASK_SCHEMA`, `__init__.py:164,170`).
- **Fix:**
  1. Add the two missing services (name + description + all fields) to
     `strings.json` → `services`.
  2. Add the missing field strings listed above to their services.
  3. For the four schema-only fields, first add them to `services.yaml` (so they
     have UI docs), then add matching strings. `managed_by` is
     integration-internal — consider marking it `advanced`/omitting from the UI
     rather than exposing it; decide per field. Snooze/skip `origin` should
     mirror `complete_task.origin`.
  4. **Propagate to all 16 locales.** `en.json` mirrors `strings.json`; the
     other 15 (`ca, cs, da, de, es, fi, fr, it, nb, nl, pl, pt-BR, ru, sv,
     zh-Hans`) carry the same `services` key structure. Add the new keys with
     English fallback text where a translation isn't available (HA convention),
     matching how prior parity fixes (M4/M8) handled the 16-locale spread.
- **Test:** there is likely an existing parity/hassfest check — run
  `pytest tests/unit` and hassfest locally; if a `strings.json`↔`services.yaml`
  parity test doesn't already exist, add a small unit test asserting every
  `services.yaml` service+field has a `strings.json` entry (guards future drift).
- **User-facing:** yes (service docs) → short CHANGELOG note.
- **Caveat:** this is the largest mechanical diff (16 locale files). Keep it in
  its own commit/PR-slice so review is tractable. Do the schema-only-field
  decision (#3) explicitly — don't silently expose `managed_by`.

---

## Group G — Frontend (panel UI — screenshots required)

### N8. Status-bucket drift across panel / card-filter / card / utils
`card-filter.ts` `statusBucket` (`card-filter.ts:87-97`) is the reference. Align
the others to kill the drift class (R5 later folds these onto one shared
function; N8 is the tactical fix).

1. **Panel `_statusBucket` (`panel.ts:1489-1506`):**
   - Add the **NaN guard** the reference has (`card-filter.ts:92`): after
     `const due = new Date(task.next_due).getTime();` (`panel.ts:1502`) insert
     `if (Number.isNaN(due)) return 'none';`. Today a malformed `next_due`
     silently falls through to `'later'`.
   - Bucket **dormant sensor tasks as `monitored`.** The panel only checks
     `recurrence_type === 'triggered'` at `panel.ts:1496`; a dormant `sensor`
     task (no `next_due`) falls to `'none'`. `utils.ts dueLabel` already treats
     both `triggered` and `sensor` dormant tasks as monitored — match it:
     `if ((task.recurrence_type === 'triggered' || task.recurrence_type === 'sensor') && !task.next_due) return 'monitored';`.
     Apply the same broadening in `card-filter.ts:89` for consistency (the note
     calls out the panel, but the two must not re-diverge).
2. **Card Done button (`card.ts:785-802`):** `dormant`
   (`card.ts:788`) only covers `triggered`. A completed one-off
   (`recurrence_type === 'one-off' && !next_due && last_completed`) still renders
   a Done button. Broaden the hide condition:
   `const completedOneOff = task.recurrence_type === 'one-off' && !task.next_due && !!task.last_completed;`
   then `const done = (dormant || completedOneOff) ? '' : \`<ha-icon-button …>\`;`.
   (Panel already carves these into a `completed` bucket, `panel.ts:1499`.)
3. **`utils.ts` relative-day (`utils.ts:129-135`):** `Math.round(diffMs /
   86_400_000)` measures rolling 24-hour periods, not calendar days — at 20:00 a
   task due 08:00 tomorrow is 12h away and reads inconsistently as "today"/
   "tomorrow". Compute from calendar midnights:
   ```ts
   const startOfDay = (d: Date) => { const x = new Date(d); x.setHours(0,0,0,0); return x.getTime(); };
   const days = Math.round((startOfDay(due) - startOfDay(now)) / 86_400_000);
   ```
   Mirrors card-filter's `endOfToday` calendar-day approach.
- **Test:** vitest unit tests for `statusBucket` (NaN → none, dormant sensor →
  monitored) and `dueLabel` (time-of-day boundary cases). Run
  `npm test` and `npm run build` in `frontend/`.
- **Screenshots:** capture the task-list buckets (panel) and card via the
  Playwright harness → `docs/images/`, embed in the PR body (SHA-pinned
  `<img>`). This is the panel-UI gate.
- **User-facing:** yes → CHANGELOG "Fixed".

### N13. Frontend leaks / races
1. **Panel has no `disconnectedCallback`** (`panel.ts`; only
   `connectedCallback` at `:748`). On unmount-while-dialog-open the confirm scrim
   appended to `document.body` (`panel.ts:1083`) and the document `keydown`
   listener (`panel.ts:1044`) leak. Add a `disconnectedCallback` that removes the
   scrim (`this._confirmScrim`) and the keydown listener. This requires hoisting
   the `onKey` closure (`panel.ts:1038`) to an instance field so it can be
   removed. (Optionally clear the debounce timers in `_persistTimers`,
   `panel.ts:668`.)
2. **`_openConfirmDialog` (`panel.ts:995-998`)** calls
   `_renderConfirmDeleteDialog` which always appends a **new** scrim without
   removing a prior one — a second open (or a stale scrim) orphans the earlier
   scrim + its listener. Remove any previous scrim first:
   `if (this._confirmScrim) { this._confirmScrim.remove(); this._confirmScrim = null; }`.
3. **Duplicate initial load (`panel.ts:683,831,875`).** Both `set hass`
   (`:683`) and `_init` (`:831`) trigger the first `_refresh` under the same
   `!this._loaded` gate, and `_loaded` is only set `true` *after* `_reload`'s
   awaited `Promise.all` resolves (`:864`) — so both can pass the check and run
   two concurrent full loads. Add an in-flight guard mirroring the card's
   `_refreshing`: a `_loading` boolean checked/set at the top of `_refresh`,
   cleared in `finally`.
4. **Card `_subscribe` disconnect-mid-flight race (`card.ts:391-409`).** During
   the `await conn.subscribeEvents(...)` (`card.ts:402`), `this._unsub` is still
   `undefined`, so a `disconnectedCallback` (`card.ts:334`) firing mid-await
   finds nothing to unsubscribe; the promise then resolves and assigns
   `this._unsub` on a detached element — a permanent leak. Add a `_disconnected`
   flag (set in `disconnectedCallback`, reset in `connectedCallback`); after the
   await, `if (this._disconnected) { unsub(); return; }` before storing it.
5. **Card editor profile refetch (`card.ts:901-911`).** The `this._profiles.length`
   guard (`card.ts:908`) already prevents per-hass-churn refetch in the normal
   case. Residual edge: a legitimate **empty** profile result keeps
   `_profiles.length === 0`, so every `set hass` re-hits the API. Track an
   attempted flag (`_profilesLoaded`) instead of relying on array length so an
   empty result also suppresses refetches.
- **Test:** mostly DOM-lifecycle — add vitest coverage where feasible (the
  in-flight/attempted guards are unit-testable); verify the scrim-leak fix
  manually / via e2e (open confirm dialog, navigate away, assert no orphaned
  `.hk-…scrim` in `document.body`). Run `npm test` + `npm run build`.
- **Screenshots:** N13 is mostly non-visual, but it edits panel/card source, so
  include a confirm-dialog screenshot to satisfy the panel-UI gate (the dialog
  is the surface most affected).
- **User-facing:** stability → CHANGELOG "Fixed" (brief).

---

## Suggested sequencing

Independent, low-risk, no-UI backend fixes first; the large parity diff and the
UI batch last so screenshots are captured once against a settled UI:

1. **Group E (N12)** — smallest, pure-logic, no cross-cutting risk.
2. **Group A (N1, N2)** — notification + sensor correctness.
3. **Group B (N5)** — coordinator reload (test the deferred-reload carefully).
4. **Group C (N6)** — calendar windows.
5. **Group D (N10)** — documents streaming + ordering.
6. **Group F (N9)** — service/string parity (large mechanical, own slice).
7. **Group G (N8, N13)** — frontend, with Playwright screenshots in the PR body.

Each slice: run the relevant tests + `mypy custom_components/home_keeper` (and
`npm test`/`npm run build` for Group G) locally before pushing, tick the box in
`REVIEW_FIX_PLAN.md`, and add the CHANGELOG entry. After the last slice, do the
`REVIEW_FIX_PLAN.md` wrap-up (W1/W2): full suite green, screenshots embedded,
request a Cue review, and delete both plan files.
