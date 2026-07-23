# Back-Date / Edit a Completion's Timestamp

**Status: proposed.** Design for [issue #143](https://github.com/prestomation/ha-home-keeper/issues/143).
Not yet implemented — this document is the plan to hand to an implementation PR.

Today, marking a task **Done** always stamps `completed_at = now`. There is no panel
affordance to say "I actually did this last Tuesday" — and for a **floating** task
(next-due measured from the completion), that silently shifts the whole cadence
forward by however many days late the entry was logged. Today's only fixes are the
`home_keeper.complete_task` service's `completed_at` field, or delete-then-re-add
from the history UI — neither is discoverable to a normal user.

This closes the gap with two panel affordances backed almost entirely by the existing
engine:

1. **Completion dialog:** an optional **Completed at** date/time field (defaults to
   now) when logging a *new* completion.
2. **History list (task detail):** a "move date" affordance on each completion row,
   next to the existing edit-metadata / trash buttons, to correct an *already
   recorded* completion's timestamp.

It builds directly on the completion-history and per-completion-metadata surfaces
already shipped (`docs/COMPLETION_HISTORY_PLAN.md`, `docs/PER_COMPLETION_METADATA_PLAN.md`)
— same history list, same dialog family, same service/websocket/event conventions.

---

## 1. What already exists (and what's actually missing)

Already present:

- **`complete_task` already supports back-dating.** Both `recurrence.apply_completion`
  (`recurrence.py:261`) and the `complete_task` **service** (`COMPLETE_TASK_SCHEMA`,
  `__init__.py:198`, `vol.Optional("completed_at"): cv.datetime`) already accept an
  explicit timestamp; `store.complete_task` (`store.py:946`) qualifies a naive value
  with HA's timezone the same way `models._coerce_seed` does.
- **`update_completion` intentionally never moves `ts`.** It edits a completion's
  metadata (note/cost/photo/who) in place (`recurrence.py:414`, `store.py:1012`,
  `home_keeper.update_completion` service, `home_keeper/update_completion` websocket
  command) — by design, so amending a log entry can't accidentally rewind or re-arm a
  task's schedule.
- **`remove_completion`'s re-derive logic is the template for a move.** Undoing a
  completion (`recurrence.py:378`, `store.delete_completion`, `store.py:1049`)
  re-derives `last_completed` as the max of the *remaining* history and recomputes
  `next_due` per recurrence type (floating rewinds to the prior completion; fixed
  stays schedule-driven; triggered/sensor untouched; one-off re-arms only if history
  is now empty). Moving a completion needs the exact same re-derive step, because the
  moved entry isn't necessarily the new latest.
- **The date/time selector conversion already exists.** `forms.ts` (`isoToHaDateTime`
  / `haDateTimeToIso`, lines 71-85) already bridges HA's local `ha-form` `datetime`
  selector and the ISO strings Home Keeper persists — used today for a fixed task's
  `anchor`, a one-off's `due`, and the `last_completed` seed field.

Gaps to close:

1. **No `recurrence.move_completion`.** Re-timestamping an existing entry (as opposed
   to editing its metadata, or removing it) doesn't exist as a pure function.
2. **`ws_complete_task` drops `completed_at` on the floor.** Unlike the service, the
   *websocket* command's schema only has `task_id`/`note`/`cost`/`photo`/`who`
   (`websocket_api.py:227-236`) — so even though the backend already supports
   back-dating, the panel has no wire path to it yet. This must be fixed as part of
   part 1, not assumed away.
3. **No panel UI for either affordance** — the completion dialog has no date field,
   and the history row has no "move date" action.

---

## 2. Key decisions (already made)

- **Ship both affordances in one PR.** The dialog's "Completed at" field (pure UI,
  no new backend beyond the `ws_complete_task` fix) and the history row's "move date"
  action (needs the new `move_completion` plumbing) are one coherent feature from the
  issue's point of view; splitting them would leave the more valuable half (fixing a
  past mistake) out of the first ship.
- **Reuse `task_uncompleted` + `task_completed` events for a move — no new event
  type.** A move is modeled as "undo, then redo at the new time," so it fires the two
  events that already exist for exactly those transitions. This means no additions to
  `const.py`'s event catalog, `events.py`, `docs/EVENTS.md`, or `device_trigger.py` —
  existing automations that already react to completions/uncompletions see the move
  for free, with less new surface to document and test than a dedicated
  `..._completion_moved` event would need.
- **`move_completion` operates on live tasks only**, matching `update_completion`'s
  restriction — an appliance's *archived* task history (from a deleted task) is not
  user-editable here, consistent with how metadata edits are already scoped.

---

## 3. Design

### `recurrence.move_completion(task, old_ts, new_ts, *, now)`

New pure function, alongside `apply_completion` / `remove_completion` /
`update_completion` (`recurrence.py:261-450`):

- Locate the entry at `old_ts` (raise `ValueError` if missing — mirrors
  `update_completion`'s missing-`ts` behavior, which `store.py` already knows how to
  translate into `TaskValidationError`).
- Remove it, preserving its metadata (note/cost/photo/who).
- Re-insert at `new_ts`, colliding with an existing entry there the same way
  `apply_completion` already dedups same-instant completions (replace, not
  duplicate) — the qualification of a naive `new_ts` against `now`'s tzinfo mirrors
  `apply_completion`'s existing comment (`recurrence.py:288-294`).
- Re-derive `last_completed` (max of the resulting history, or `None`) and `next_due`
  per recurrence type **exactly like `remove_completion`** — not `apply_completion`'s
  "trust the given timestamp" shortcut, since the moved entry isn't necessarily the
  new latest.

### `store.move_completion(task_id, old_ts, new_ts)`

New store method alongside `update_completion` / `delete_completion`
(`store.py:1012-1067`): guards with `_reject_synced_problem` (a synced problem
task's history isn't user-editable, same as the other two), calls
`recurrence.move_completion`, persists, and fires `EVENT_TASK_UNCOMPLETED` then
`EVENT_TASK_COMPLETED` (per the reuse-events decision) via the existing
`events.task_event_data` / `events.completion_event_data` builders — no new builder
needed.

### Service + websocket command

- New `home_keeper.move_completion` service (`task_id`, `old_ts`, `new_completed_at`),
  following `update_completion`'s schema/handler/registration pattern exactly
  (`__init__.py`: `MOVE_COMPLETION_SCHEMA` near `UPDATE_COMPLETION_SCHEMA`;
  `handle_move_completion` near `handle_update_completion`; registered and added to
  the `_SERVICES` teardown tuple). Reuses the existing `task_not_found` /
  `invalid_task` translation keys — no new `strings.json` exception entry.
- New `home_keeper/move_completion` websocket command, following `ws_update_completion`
  exactly (`websocket_api.py:259-289`), taking `task_id` / `old_ts` / `new_ts` as
  plain strings (the websocket layer's existing convention — `new_ts` arrives as an
  ISO string built client-side by `haDateTimeToIso`, not `cv.datetime`).
- **Fix `ws_complete_task`** to accept and forward an optional `completed_at` string
  (parsed to a `datetime`), closing gap #2 above — required for part 1 of the
  feature to have any effect.
- `api.ts`: extend `completeTask` with an optional `completedAt`; add
  `moveCompletion(hass, taskId, oldTs, newTs)` mirroring `deleteCompletion`.

### Panel UI (`panel.ts`)

- **Completion dialog** (`_renderCompletionDialog`, currently ~3710-3806): add a
  `completedAt` field (via `selDateTime()` + `isoToHaDateTime`/`haDateTimeToIso`) to
  the `ha-form` schema, **only when logging a new completion** (`c.ts == null`) —
  never in the existing edit-metadata mode, which must keep not touching the
  timestamp. Wire through `_submitCompletion` → `api.completeTask`.
- **History row** (`_historyGroup`, currently ~4637-4685): add a third icon button
  next to the existing edit-metadata / delete buttons, gated the same way as the
  edit button (live, non-archived tasks only). Wire it to a new small dialog (state,
  open/close/submit, and render function, modeled on the existing
  `_openCompletionEdit` family but distinct from it — reusing the metadata-edit
  dialog would blur `update_completion` vs `move_completion` semantics) that collects
  one new date/time and calls `api.moveCompletion`.
- New i18n keys for the move-date button/dialog, added to every locale file
  (translation-parity is enforced by an existing test).

---

## 4. Files touched

- `custom_components/home_keeper/recurrence.py` — `move_completion`
- `custom_components/home_keeper/store.py` — `move_completion`
- `custom_components/home_keeper/__init__.py` — schema, handler, registration, teardown list
- `custom_components/home_keeper/services.yaml`, `strings.json` — service docs/i18n
- `custom_components/home_keeper/websocket_api.py` — `ws_move_completion` + the
  `ws_complete_task` `completed_at` fix
- `frontend/src/api.ts` — `moveCompletion`, `completeTask` extension
- `frontend/src/panel.ts` — completion dialog date field, history row move-date
  action + dialog
- `frontend/src/i18n/*` — new strings
- `tests/unit/` — new `move_completion` pure-function tests (per-recurrence-type
  coverage mirroring `remove_completion`'s existing tests), extend
  `test_completion_metadata.py` if metadata-preservation fits there better
- `tests/integration/test_lifecycle.py` — service-level test asserting both events fire
- `frontend/test/completion.test.js` — API payload-shape tests for `moveCompletion`
  and the `completeTask` `completed_at` extension

---

## 5. Testing strategy

- **Unit (pytest):** floating/fixed/triggered/sensor/one-off re-derive behavior for
  `move_completion` (mirroring `remove_completion`'s per-type branches), metadata
  preservation across the move, dedup-collapse onto an existing `new_ts`, and
  `ValueError` on an unknown `old_ts`.
- **Integration (Docker HA):** a `move_completion` service call fires
  `task_uncompleted` then `task_completed` and leaves `next_due`/history correctly
  re-derived.
- **Frontend (vitest):** `moveCompletion`'s payload shape; `completeTask` sending
  (and omitting) `completed_at`.
- **Manual E2E (Playwright / `ci/e2e-up.sh`):** back-date a new completion via the
  dialog and confirm `next_due` reflects it; move an existing history row's date and
  confirm the row + `next_due` update; watch Developer Tools → Events for the
  uncompleted/completed pair on a move.

---

## 6. Recommended first step

Ship the two affordances together as designed — the `ws_complete_task` fix is a
prerequisite one-liner, `move_completion` is a small, well-precedented addition
alongside `remove_completion`, and the panel changes reuse dialog/history patterns
already in place from the completion-history and per-completion-metadata features.
Per the "every data action is a service" / "fire an event per state change"
conventions (`AGENTS.md`), the service, websocket command, and event reuse should
land together with the pure-function tests before the panel UI is wired up, so the
frontend work has a fully working backend to call from the start.
