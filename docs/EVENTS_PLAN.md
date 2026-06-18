# Comprehensive Events & Automation Hooks

**Status: planned.** This document specifies a full, consistent set of Home Assistant
**bus events** for every meaningful thing that happens in Home Keeper — a task is
created, edited, completed, deleted, becomes overdue or due-soon; a spare part runs low,
runs out, or is restocked; an appliance is added, changed, or removed — plus the
**automation-UI triggers** that let users wire those events up from the visual automation
editor without knowing the raw event names.

Events are the interoperability surface. The existing two events
(`home_keeper_task_completed`, `home_keeper_part_low_stock`) are already the documented
hook other integrations subscribe to (`docs/INTEGRATING.md`); this generalises that one
pattern into a complete, well-documented catalog so **automations and other integrations
can react to the full lifecycle**, not just completion and low-stock.

> **Pre-1.0 — free to normalise.** Home Keeper is still a beta (panel `0.3.0bN`), so this
> plan is **not** bound by back-compatibility. It keeps the existing field names because
> they're already good (changing them would be churn for its own sake), but it is free to
> reshape a payload where that yields a cleaner, uniform spine. The one external consumer
> of the current `home_keeper_task_completed` contract is **Pawsistant** (same owner); any
> breaking change to that payload is made **in lockstep** with Pawsistant and
> `docs/INTEGRATING.md`, and lands as a **breaking** CHANGELOG entry rather than an additive
> one.

---

## 1. What already exists (and what doesn't)

Already present (the pattern to generalise):

- **Two events, fired at the store chokepoint.** `complete_task()` fires
  `home_keeper_task_completed` (`store.py:353`); the low-stock crossing fires
  `home_keeper_part_low_stock` from `_emit_low_stock()` (`store.py:404-408`), reached
  both on wear-part consumption (`_stamp_part_replacement`, `store.py:400`) and manual
  `adjust_part_stock()` (`store.py:427`).
- **Pure payload builders.** `events.py` builds both payloads (`completion_event_data`,
  `low_stock_event_data`) with **no Home Assistant imports**, so the test fake
  (`testing.py`) and integrators test against the exact shipped contract and it can't
  drift. This is the convention every new event must follow.
- **Event-name convention.** `EVENT_* = f"{DOMAIN}_<noun>_<verb>"` in `const.py:38,45`.
- **Edge-triggered stock crossing.** `assets.consume_part_stock()` /
  `assets.adjust_part_stock()` return `True` *only* on the transition into low, so the
  event fires once, never nags (`assets.py`).
- **A 5-minute coordinator refresh** (`coordinator.py:29`) that keeps time-based state
  current — but only *reads* the task map (`_async_update_data`, `coordinator.py:65`); it
  detects no transitions and fires no events.

Gaps to close:

1. **Mutations are invisible.** Creating, editing, deleting, triggering (arming), and
   un-completing a task fire nothing. Asset create/update/delete fire nothing.
2. **Overdue is never announced.** `recurrence.is_overdue()` (`recurrence.py:289`) is a
   stateless, on-demand check used by the overdue binary_sensor; nothing fires when a task
   *crosses* into overdue. There is no "due soon" concept at all.
3. **Stock has only one of three transitions.** Low-stock fires, but **out-of-stock**
   (reaches 0) and **restocked** (recovers above the threshold) do not.
4. **No automation-UI surface.** Users must know the raw event string and hand-write a
   `platform: event` trigger; nothing appears in the visual automation editor or on a
   device page.

---

## 2. The event catalog

Naming stays `home_keeper_<noun>_<verb>`. Every event gets a `const.EVENT_*` constant and
a **pure builder in `events.py`**. Payloads share a common spine so automations can
template uniformly.

### Task lifecycle — fired at the `store.py` mutation chokepoints

| Event | Fires from | When |
|---|---|---|
| `home_keeper_task_created` | `add_task` | a task is created (any source: panel, service, contributing integration) |
| `home_keeper_task_updated` | `update_task` | a task actually changes (no-op merges don't fire); payload carries `changed_fields` |
| `home_keeper_task_deleted` | `delete_task` | a task is removed |
| `home_keeper_task_completed` | `complete_task` | **(exists)** any completion surface |
| `home_keeper_task_uncompleted` | `delete_completion` | a completion is undone (re-derives `next_due`) |
| `home_keeper_task_triggered` | `trigger_task` | a condition-driven task is armed (dormant → due-now) |

> **`add_task`/`delete_task` are not the only mutation paths.** Wear-part maintenance tasks
> are created and removed by `reconcile_part_tasks` (`store.py:303`), which rewrites
> `self._tasks` directly and **bypasses** `add_task`/`delete_task`. It must therefore fire
> `task_created` / `task_deleted` for the tasks it adds/removes (diff `new_tasks` against the
> old map), or that whole class of tasks is silent. Likewise `detach_tasks_from_device`
> (`store.py:196`) clears `device_id` in place — fire `task_updated` with
> `changed_fields: ["device_id"]` (or explicitly document it as a non-event). The "fire at
> the chokepoint" rule means *every* path that mutates the task map, not just the two CRUD
> services.

### Time-based transitions — fired from the coordinator, **edge-triggered**

| Event | When |
|---|---|
| `home_keeper_task_overdue` | a task first crosses `next_due` (now ≥ next_due) while HA is running |
| `home_keeper_task_due_soon` | a task enters the look-ahead window (default 24 h before `next_due`) |

### Stock transitions — fired at the stock chokepoints, **edge-triggered**

| Event | When |
|---|---|
| `home_keeper_part_low_stock` | **(exists)** stock crosses to ≤ `reorder_at` |
| `home_keeper_part_out_of_stock` | stock reaches 0 |
| `home_keeper_part_restocked` | stock recovers back above `reorder_at` |

### Asset lifecycle — fired at the `store.py` asset chokepoints

| Event | Fires from |
|---|---|
| `home_keeper_asset_created` | `add_asset` |
| `home_keeper_asset_updated` | `update_asset` |
| `home_keeper_asset_deleted` | `delete_asset` |

### Payload spine

Task events carry a common core, so one automation template works across all of them:

```jsonc
{
  "task_id": "…",
  "name": "…",
  "device_id": "…",          // the task's stored registry device id, echoed verbatim; null if unset
  "area_id": "…",            // null if none
  "recurrence_type": "floating|fixed|triggered",
  "next_due": "…ISO… | null",
  "enabled": true,
  "source": { … } | null,    // opaque, echoed verbatim (as today)
  "managed_by": { … } | null // well-known ownership block (as today)
}
```

- `task_completed` adopts the common spine and carries its completion-specific extras
  (`completed_at`, `origin`) on top. Concretely, `completion_event_data` (`events.py:14`,
  today only `task_id, name, source, managed_by, completed_at, origin`) gains the missing
  spine fields `device_id, area_id, recurrence_type, next_due, enabled`. The task dict it's
  built from is the *post-completion* task (`store.py:346-355`), so `next_due` is already
  the next occurrence — echo `task.get("next_due")`. (We're no longer *constrained* to
  preserve the exact legacy shape; see the pre-1.0 note above.)
- `task_updated` adds `changed_fields: ["name", "interval", …]`.
- `task_overdue` adds `next_due` and `days_overdue`; `task_due_soon` adds `next_due` and
  `due_in_hours`.
- Stock events reuse the existing `low_stock_event_data` shape (`asset_id, asset_name,
  device_id, part_id, part_name, part_number, vendor, stock, reorder_at`) so all three
  stock events are interchangeable in a template.
- Asset events carry `asset_id, asset_name, device_id` (+ `changed_fields` for update).

---

## 3. Key design decisions

### Decision A — Where transition events are detected (overdue / due-soon)

The coordinator already wakes every 5 min and holds the task map; it is the natural place.
Keep the **detection logic pure and unit-testable** (matching the `recurrence.py` /
`assets.py` convention) in a new `transitions.py` (no HA imports):

```python
# state per task: the next_due we announced for, and which events already fired for it
detect_transitions(prev: dict[str, TaskEdgeState], tasks, now) -> (events, next_state)
```

**Where it runs — the plan's earlier draft glossed this.** `_async_update_data`
(`coordinator.py:65`) today only *reads* the store; it fires nothing. Override it so each
refresh does: read the task map → call `detect_transitions(self._prev, tasks, now)` → fire
the returned events on the bus → store `next_state` as `self._prev` → return the map. Because
this runs on **both** the 5-min interval **and** every post-mutation
`async_request_refresh()` (every service/store mutation already requests a refresh), a
completion that re-arms a triggered task is observed promptly without a second mechanism.
Firing stays in the HA layer; the edge logic in `transitions.py` stays pure.

### Decision B — Edge-triggering and idempotency (don't spam)

Every transition event fires **once per crossing**, never on every 5-minute tick.

- **Per-task edge state — not a bare `next_due` key.** Keying only on the `next_due` *value*
  isn't enough: a task crosses **due-soon first, then overdue** against the *same* `next_due`,
  so the two events need independent "already-fired" flags, and re-firing must reset when
  `next_due` changes. The state per task is therefore:

  ```python
  TaskEdgeState = {"next_due": str | None, "due_soon_fired": bool, "overdue_fired": bool}
  ```

  On each refresh, per task: if its `next_due` differs from the stored one, reset both flags
  (a reschedule/completion re-arms it). Then fire `due_soon` once if now in the window and
  `not due_soon_fired`; fire `overdue` once if `now >= next_due` and `not overdue_fired`;
  set the flags. A task that is *still* overdue next cycle does **not** refire.
- **Skip non-eligible tasks.** `recurrence.is_overdue`/`is_due_soon` (`recurrence.py:289`)
  already return `False` when `next_due is None` — so **dormant triggered tasks** (next_due
  `None`) and tasks with no due date never fire, and arming one (`trigger_task` → a fresh
  `now` timestamp) is a `next_due` change that correctly re-arms a single overdue
  announcement. Additionally **filter `enabled is False`**: a disabled task with a stale past
  `next_due` must not fire. (Re-enabling does not replay missed events — its state is
  baselined as of the next refresh.)
- **Restart semantics (recommended): baseline silently on first refresh.** On the first
  coordinator run after startup, seed the per-task state from current values **without
  firing**, so an HA restart doesn't replay an "overdue" storm for tasks that were already
  overdue. Events then fire only for transitions observed *while HA is running*; the overdue
  binary_sensor still reflects steady state, so nothing is lost — this governs only the
  one-shot *event*. The state is in-memory (no per-tick storage writes). (Alternative:
  persist the per-task markers for cross-restart firing — rejected for v1 as churn for
  little gain; noted as a future option, along with a possible `replay`/clear escape hatch.)
- **Stock — a pure transition function, not a bare boolean.** Today `consume_part_stock` /
  `adjust_part_stock` (`assets.py:314,330`) return only `crossed_low: bool`, which **cannot
  express out-of-stock**. Replace with a pure helper that compares old/new against *both*
  thresholds, with `out` taking precedence over `low`:

  ```python
  def stock_transition(old: int, new: int, reorder_at: int | None) -> str:
      if reorder_at is None:        # untracked part — never fires
          return "none"
      if new == 0 and old > 0:      # most specific; wins over a simultaneous low crossing
          return "out"
      if new <= reorder_at and old > reorder_at:
          return "low"
      if new > reorder_at and old <= reorder_at:
          return "restocked"
      return "none"
  ```

  `store.py` maps `out|low|restocked` to the corresponding event. Events fire **only when the
  part tracks both `stock` and `reorder_at`** (untracked parts return `none`). This also
  closes the gap where a part already at/below threshold drops to zero — the old boolean saw
  "already low" and stayed silent; `stock_transition` fires `out`. Enumerate and update both
  current callers (`_stamp_part_replacement` consume path, `adjust_part_stock`) when changing
  the return type.

### Decision C — Automation-UI surface: device triggers

Per the chosen scope, expose the events in the **visual automation editor** via a
`device_trigger.py` platform (Home Assistant's well-established device-automation API).
This works broadly because nearly everything in Home Keeper already has a registry device:

- **Device-attached tasks** merge onto an existing device page (`coordinator.device_info_for_task`).
- **Standalone tasks** get a self-owned device `(DOMAIN, task_id)`.
- **Appliances** are virtual devices `(DOMAIN, "asset_<id>")`.

`async_get_triggers(hass, device_id)` offers, per device, the relevant subset: *Task
completed / overdue / due-soon* (and created/updated) for task devices; *Low stock /
Out of stock / Restocked* for appliance devices. `async_attach_trigger` delegates to HA's
`event_trigger`, filtering the event payload — **but on the right key**:

- A **self-owned task device** is `(DOMAIN, task_id)`, yet that task's event payload carries
  `device_id: null` (its `device_id` is unset). Filtering by `device_id` would match nothing
  *and* leak every other standalone task's events. So for a self-owned task device, resolve
  the registry device back to its `task_id` (read the `(DOMAIN, …)` identifier) and filter on
  **`event.data.task_id`**.
- A task **attached to an existing device** (or an **asset/appliance** virtual device) is
  shared by potentially several tasks/parts; filter on **`event.data.device_id`**.

So `async_attach_trigger` picks the filter key from the device kind. (This is why the
detector/builders must populate `task_id` on every task event and `device_id` on stock/asset
events.) Trigger labels live in `strings.json` under `device_automation`, with **translation
parity** across all 16 locales
(enforced by `test_translations_parity.py`).

Global, non-device automations (e.g. "*any* part low" → one shopping-list automation)
continue to use a raw `platform: event` trigger, documented with copy-paste YAML in
`docs/EVENTS.md`. (A modern integration-level trigger platform — `triggers.yaml` +
`async_get_triggers` for non-device triggers — is recorded as a **stretch**, not v1.)

### Decision D — Services? Mostly no.

These events are *observations of* state changes that already flow through services /
store methods — they are not new data actions, so they need **no new `home_keeper.*`
service** (the "every action is a service" rule governs *mutations*, which already exist).
The one exception worth weighing: a `home_keeper.list_overdue` / report-style service is
**out of scope** here (the overdue binary_sensors already expose that state). Firing happens
inside existing store methods and the coordinator.

---

## 4. Phased implementation

Each phase is an independently reviewable PR; request a Cue review after each push
(`/q review …`), tailored to that phase (correctness/edge-cases for the transition logic,
HA best-practices for the device triggers).

### Phase 1 — Task & asset lifecycle + stock depletion events (backend, no UI)

1. **`const.py`** — add the `EVENT_*` constants (task created/updated/deleted/uncompleted/
   triggered; part out_of_stock/restocked; asset created/updated/deleted), each with a
   doc-comment like the existing two.
2. **`events.py`** — add a pure builder per event; reuse the spine. Bring
   `completion_event_data` onto the spine too (no longer constrained to the legacy shape —
   if Pawsistant relies on a field, change both repos in lockstep).
3. **`assets.py`** — change `consume_part_stock` / `adjust_part_stock` to return a
   transition descriptor (`none|low|out|restocked`) instead of a bare boolean; pure, fully
   unit-tested across boundary values (`stock == reorder_at`, `0`, recovery).
4. **`store.py`** — fire events at **every** chokepoint that mutates the map, not just the
   CRUD services:
   - `add_task`/`update_task`/`delete_task`/`trigger_task`/`delete_completion`,
     `add_asset`/`update_asset`/`delete_asset`, and the stock descriptor in the
     `_emit_low_stock` sibling(s).
   - **`reconcile_part_tasks`** (`store.py:303`) — diff `new_tasks` vs the old map and fire
     `task_created`/`task_deleted` for the wear-part tasks it adds/removes (else they're
     silent).
   - **`detach_tasks_from_device`** (`store.py:196`) — fire `task_updated`
     (`changed_fields: ["device_id"]`) for each task it clears.
   - `update_task` fires only when `merged != existing`, with `changed_fields` from the diff.
5. **`testing.py`** — extend the fake to fire the new events via the same `events.py`
   builders (so the integrator contract can't drift), adding helpers mirroring
   `fire_user_completion`: at least `fire_task_created(task)`, `fire_task_updated(task,
   changed_fields)`, `fire_task_deleted(task_id)`, and the stock-event helpers. (Time-based
   overdue/due-soon helpers come with Phase 2's `now` injection.)
6. **Tests** — unit (`events.py` builders, `assets.py` `stock_transition` across all
   boundaries: `==reorder_at`, →0, restock-from-0, untracked→`none`), integration (each
   mutation fires exactly one event with the right payload; a single decrement crossing both
   low and zero fires **`out_of_stock` only**; `reconcile_part_tasks` create/remove fire).

### Phase 2 — Time-based transitions (overdue / due-soon)

1. **`transitions.py`** (new, pure) — `detect_transitions(prev, tasks, now)` over the
   `TaskEdgeState` map (Decision B): per-task `due_soon_fired`/`overdue_fired` flags reset on
   `next_due` change, skip `next_due is None` and `enabled is False`; `DUE_SOON_WINDOW`
   constant (default 24 h).
2. **`coordinator.py`** — override `_async_update_data` (Decision A) to read → detect → fire →
   store `self._prev` → return. Baseline-on-first-refresh (no firing on the first run). Runs on
   both the 5-min interval and every post-mutation `async_request_refresh()`, so a completion
   re-arming a triggered task is observed promptly — no second mechanism.
3. **Tests** — unit: due-soon then overdue both fire once for one `next_due`; still-overdue
   doesn't refire; completion/reschedule re-arms; disabled task with stale `next_due` never
   fires; dormant triggered task fires only on arm; startup baselines silently; DST/timezone
   boundary on the due-soon window (deterministic, injected `now`).

### Phase 3 — Automation-UI device triggers

1. **`device_trigger.py`** (new) — `async_get_triggers` (task vs appliance device subsets),
   `async_attach_trigger` delegating to `event_trigger` with the **filter key chosen by
   device kind** (Decision C): `task_id` for self-owned task devices, `device_id` for
   existing-device/asset devices. `TRIGGER_SCHEMA`, and `async_get_trigger_capabilities`
   where useful.
2. **`strings.json` + `translations/*.json`** — `device_automation.trigger_type` labels,
   parity across all locales (enforced by the parity test).
3. **`manifest.json`** — no change (device triggers need no extra dependency).
4. **Tests** — `async_get_triggers` returns the right set per device kind; a **self-owned
   task device** trigger fires for *its* task's event and **not** for another standalone
   task's (the `device_id: null` leak this avoids); an existing-device trigger fires for any
   task on that device; a non-matching device does not fire.

### Phase 4 — Documentation (the deliverable's whole point)

1. **`docs/EVENTS.md`** (new) — the canonical catalog: every event, exactly when it fires,
   a payload table, the **edge-trigger / idempotency / restart semantics**, and copy-paste
   automation examples (both device-trigger and raw `platform: event` YAML). This is the
   "documented well" core.
2. **`docs/INTEGRATING.md`** — extend §3's event references and the at-a-glance table to
   list the new events; cross-link `EVENTS.md` as the full catalog. If the
   `task_completed` payload shape changed, update its field table here and ship the matching
   Pawsistant change in lockstep.
3. **`README.md`** — expand the events/automation section with **use cases** (overdue →
   notify; out-of-stock → shopping list; task created → log) and a couple of example
   automations, per the "document new major features in README" rule.
4. **`CHANGELOG.md`** — an **Added** entry under the next beta for the new events and the
   device-trigger UI, with one automation example. If the `task_completed` payload shape
   changed, add a **Changed/Breaking** note too (and call out the Pawsistant bump).
5. **`.amazonq/rules/architecture-and-code.md`** + **`AGENTS.md`** — record the convention:
   *every observable state change fires a documented bus event built by a pure `events.py`
   function; edge-triggered transitions are detected in `transitions.py`/coordinator; the
   event catalog in `docs/EVENTS.md` is kept in sync in the same change.* (A new convention
   isn't real until it's written into the rules.)

> **Screenshot gate:** this feature touches **no panel UI** (`frontend/src/`), so the hard
> screenshot gate does not apply. Optionally capture the device-trigger picker in HA's
> automation editor for the README — nice-to-have, not gated.

---

## 5. Files touched (by phase)

**Phase 1 (lifecycle + stock):**
- `custom_components/home_keeper/const.py` — `EVENT_*` constants
- `custom_components/home_keeper/events.py` — pure builders (+ additive completion fields)
- `custom_components/home_keeper/assets.py` — stock transition descriptor
- `custom_components/home_keeper/store.py` — fire at mutation/stock chokepoints
- `custom_components/home_keeper/testing.py` — fake exposes new events
- `tests/unit/*`, `tests/integration/*`

**Phase 2 (transitions):**
- `custom_components/home_keeper/transitions.py` — new, pure detector + window const
- `custom_components/home_keeper/coordinator.py` — state, baseline, fire
- `tests/unit/test_transitions.py`

**Phase 3 (device triggers):**
- `custom_components/home_keeper/device_trigger.py` — new
- `custom_components/home_keeper/strings.json` + `translations/*.json`
- `tests/integration/test_device_trigger.py`

**Phase 4 (docs):**
- `docs/EVENTS.md` (new), `docs/INTEGRATING.md`, `README.md`, `CHANGELOG.md`
- `.amazonq/rules/architecture-and-code.md`, `AGENTS.md`

---

## 6. Testing strategy

- **Unit (pytest, pure):** `events.py` builders produce the exact documented payloads;
  `assets.py` stock transitions across all boundaries (low / out / restock / no-op);
  `transitions.py` overdue/due-soon crossing, no-refire, re-arm on completion, silent
  startup baseline — all with an injected, timezone-aware `now` for determinism (incl. a
  DST boundary case).
- **Integration (Docker HA):** each store mutation fires exactly one correctly-shaped
  event; a single decrement to zero fires `out_of_stock` once (not also `low_stock`); the
  device trigger fires its action for the matching `device_id` and not for others.
- **Contract (the fake):** the fake fires the new events via the same `events.py` builders,
  proving the integrator-facing contract can't drift from production.
- **Parity:** `test_translations_parity.py` covers the new device-trigger strings.

Run locally before pushing (per AGENTS.md): `pytest tests/unit -v`, the full unit suite,
and the Docker integration suite — never use CI as the test runner.

---

## 7. Recommended first step

Ship **Phase 1** end-to-end: it generalises the already-proven "fire at the store
chokepoint via a pure `events.py` builder" pattern to the full mutation + stock surface,
needs no new infrastructure, and is immediately useful (task-created / out-of-stock
automations). Phases 2–3 then add the genuinely new machinery (runtime transition
detection, the automation-UI surface) on top, and Phase 4 documents the lot in
`docs/EVENTS.md` as the single catalog automations and integrations build against.
