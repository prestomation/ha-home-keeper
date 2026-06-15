# Task Completion History & Appliance History

**Status: implemented.** Click a **task** to see every time it was completed; click an
**appliance** to see the history of *all* maintenance done on it (across every related
task). This is the "when did I last do X / when was this serviced" view.

## Implemented behaviour (this PR)

- **Task history dialog** — every task card has a history (clock) button and a clickable
  body; opening it lists all completion dates newest-first with a count and average
  cadence (`≈ every N days`). The card meta also shows the completion count.
- **Appliance history dialog** — every appliance card opens an aggregated, grouped
  timeline of all related tasks' completions (part-derived, device-attached, or
  related-device), newest activity first.
- **Reference-counting retention** — when a task that belongs to an appliance is deleted,
  its completion history is *archived onto that appliance* (shown with a **REMOVED TASK**
  badge) so the appliance's maintenance record survives the task. A standalone task's
  history is dropped with it, and deleting an appliance drops its archive too (the
  archive is a field on the asset record). This is exactly the reference-counting model:
  history lives on while *something* still references it.
- **Larger cap** — `MAX_COMPLETION_HISTORY` raised from 50 → 500 so long-lived tasks keep
  years of cadence.

The rest of this document is the original design rationale, kept for context.

---

The feature is staged so the most valuable, lowest-risk slice (showing history that the
backend *already records*) ships first.

---

## 1. What already exists (and what doesn't)

The recording half of this feature is already built. The gap is purely **surfacing**
it and, for longevity, **durability**.

Already present:

- **Per-task completion log.** Every completion appends `{ "ts": <iso> }` to
  `task["completions"]` in `recurrence.apply_completion()`
  (`custom_components/home_keeper/recurrence.py:216`). `last_completed` is also stamped.
- **Single completion chokepoint.** Every surface (to-do list, device mark-done button,
  `complete_task` service, websocket command) funnels through
  `HomeKeeperStore.complete_task()` (`store.py:247`), so history is recorded uniformly.
- **Appliance ↔ task link for part-derived tasks.** A wear part with a replacement
  interval auto-creates a task tagged `task["source"] = {"part": {"asset_id", "part_id"}}`.
  On completion, `_stamp_part_replacement()` (`store.py:282`) writes the part's
  `last_replaced` date.
- **The data already reaches the frontend.** `Task.completions` is already in the
  TypeScript type (`frontend/src/types.ts:19`) and is returned by `getTasks()`. The
  panel already has **Tasks** and **Appliances** tabs (`frontend/src/panel.ts`).

Gaps to close:

1. **No UI** to view a task's completion list or an appliance's aggregated history.
2. **History is capped at 50** (`MAX_COMPLETION_HISTORY`, `const.py:22`) and **lives on
   the task** — so it is silently truncated on long-lived tasks and **lost when a task is
   deleted** (e.g. an appliance or its wear part is removed). "All the history in the
   past" wants durability the current array doesn't guarantee.
3. **"Tasks related to an appliance" is not formally defined.** Only part-derived tasks
   carry `source.asset_id`; tasks a user manually attached to the appliance's device are
   not associated.

---

## 2. Key design decisions

### Decision A — Reuse `task.completions`, or add a durable history log?

| | Reuse `task.completions` | Durable append-only log |
|---|---|---|
| Effort | Tiny (data already there) | Moderate (new store + migration) |
| Survives task deletion | ❌ | ✅ |
| Unbounded history | ❌ (cap 50) | ✅ |
| Per-entry metadata (origin, note) | ❌ | ✅ |

**Recommendation: stage it.** Phase 1 reuses the existing array (and raises/relaxes the
cap) to ship the UI immediately against real data. Phase 3 adds a durable log for
longevity and deleted-task history. Most users never hit the cap (50 completions of a
quarterly task is ~12 years), so Phase 1 alone is genuinely useful.

### Decision B — What counts as "a task related to an appliance"?

Define `tasks_for_asset(asset, tasks)` as the **union** of:

1. **Part-derived tasks** — `task.source.part.asset_id == asset.id` (the strong link).
2. **Device-attached tasks** — `asset.device_id` is set and `task.device_id == asset.device_id`.
3. **Related-device tasks** — `task.device_id ∈ asset.related_device_ids`.

This captures both auto-generated part maintenance and tasks the user hand-attached to
the appliance's device. Implemented once in the backend (`assets.py`) and reused by the
websocket command; the frontend can also derive it client-side in Phase 1.

### Decision C — Where does the UI live?

- **Task history:** a **detail dialog** opened by clicking a task row (or a dedicated
  history icon-button on the card). Avoids cluttering the list.
- **Appliance history:** extend the existing **Appliances** tab — clicking an appliance
  opens its detail view showing parts (with `last_replaced`) **plus a merged, reverse-chronological
  timeline** of every related task's completions.

This reuses the existing two-tab panel; no new top-level navigation.

---

## 3. Phased implementation

### Phase 1 — Surface existing history (frontend-only, ships first)

No backend changes; `completions` is already on every `Task` in the panel.

1. **Shared formatting helpers** in `frontend/src/utils.ts`:
   - `sortedCompletions(task): string[]` — parse + sort `ts` descending.
   - `completionStats(task)` — count, most-recent, and average interval between
     completions (useful "you do this every ~Nd" insight).
   - Localized date formatting reusing existing i18n (`frontend/src/i18n.ts`).
2. **Task history dialog** (`panel.ts`): new `_openHistory(task)` rendering a list of
   completion dates (newest first), the count, and average cadence. Use HA-native
   `ha-dialog` / `ha-card` (consistent with the existing edit dialog).
3. **Entry points:** a history icon-button on each task card; clicking an appliance's
   related-task entry opens the same dialog.
4. **Appliance detail timeline:** in the Appliances tab, compute related tasks
   client-side (Decision B) and render a merged timeline. Each entry: date, task name,
   and (for part tasks) the part. Sort all completions across tasks descending.
5. **i18n:** add keys to all locale files; `test_translations_parity.py` enforces parity.
6. **Frontend tests** (vitest): `sortedCompletions`, `completionStats`, and
   `tasks_for_asset` equivalence helper.

**Outcome:** clicking a task or appliance shows full recorded history. Limitations:
capped at 50, lost on deletion — addressed next.

### Phase 2 — Clean backend API + relax the cap

1. **Raise/relax `MAX_COMPLETION_HISTORY`** (`const.py:22`). Either bump substantially
   (e.g. 500) or make it generous; keep a cap to bound storage. Pure constant change,
   already exercised by `recurrence` tests.
2. **`tasks_for_asset()` helper** in `assets.py` (Decision B), unit-tested.
3. **Websocket commands** (`websocket_api.py`):
   - `home_keeper/get_task_history` → `{ task_id, completions[] }`.
   - `home_keeper/get_asset_history` → related tasks + merged completions for an asset.
   Frontend `api.ts` gains `getTaskHistory` / `getAssetHistory`; the panel switches from
   client-side derivation to these (single source of truth, ready for Phase 3).

### Phase 3 — Durable, deletion-proof history log (optional, longevity)

> Note: the shipped implementation took the lighter-weight path below instead of a
> separate top-level log: a deleted task's history is archived onto the appliance it
> belonged to (a `task_history` field on the asset). This is additive (no
> `STORAGE_VERSION` bump) and gives reference-counting retention — appliance deletion
> drops the archive with it. The separate-log design here remains an option if
> cross-appliance or fully task-independent history is ever needed.

Decouple recorded history from the live task object.

1. **New persisted collection** in `store.py`: `history` — an append-only list of
   entries `{ id, task_id, asset_id?, part_id?, task_name, completed_at, recorded_at,
   origin }`. Persisted in the same `Store` document under a new `history` key.
2. **Write on completion:** `complete_task()` appends a history entry (alongside the
   existing `apply_completion`). `task_name`/`asset_id` are snapshotted so history reads
   correctly even after the task or appliance is deleted.
3. **Bump `STORAGE_VERSION`** (`const.py:21`) and add a one-time migration in
   `store.load()` that seeds `history` from existing `task.completions` arrays.
4. **Retention:** keep history entries when their task is deleted (that is the whole
   point); optionally prune entries older than a configurable horizon.
5. **Repoint the websocket commands** at the durable log; appliance history can now
   include completions of tasks that no longer exist.

---

## 4. Files touched (by phase)

**Phase 1 (frontend):**
- `frontend/src/utils.ts` — formatting/stats/relation helpers
- `frontend/src/panel.ts` — history dialog + appliance timeline
- `frontend/src/i18n.ts` + locale JSON — strings
- `frontend/test/*` — vitest coverage

**Phase 2 (backend API + cap):**
- `custom_components/home_keeper/const.py` — `MAX_COMPLETION_HISTORY`
- `custom_components/home_keeper/assets.py` — `tasks_for_asset()`
- `custom_components/home_keeper/websocket_api.py` — two history commands
- `frontend/src/api.ts`, `panel.ts` — consume the commands
- `tests/unit/test_assets.py`, `tests/integration/*` — coverage

**Phase 3 (durable log):**
- `custom_components/home_keeper/store.py` — `history` collection, append, migration
- `custom_components/home_keeper/const.py` — `STORAGE_VERSION` bump
- `custom_components/home_keeper/events.py` — (optional) reuse for entry shape
- `tests/unit/*` — migration + append tests

---

## 5. Testing strategy

- **Unit (pytest):** `tasks_for_asset` membership across the three link types; history
  append + cap behavior; Phase 3 migration seeds from `completions`; deletion retains log.
- **Frontend (vitest):** `sortedCompletions`, `completionStats` cadence math, relation
  helper parity with backend.
- **Integration (Docker HA):** websocket `get_task_history` / `get_asset_history`
  round-trips; complete a task and confirm it appears in both views.

---

## 6. Recommended first step

Ship **Phase 1** end-to-end: it is frontend-only, needs no migration, and immediately
answers "when did I do this before?" against data the system has been recording all
along. Phases 2–3 then harden the cap and durability without changing the UX the user
already sees.
