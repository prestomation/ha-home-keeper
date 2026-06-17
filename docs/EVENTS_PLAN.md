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

> **Back-compatible by construction.** The two existing event names and their payload
> fields are frozen — this plan only **adds** events and **adds** fields to existing
> payloads. No automation built today breaks.

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
  "device_id": "…",          // resolved registry device id, or null
  "area_id": "…",            // null if none
  "recurrence_type": "floating|fixed|triggered",
  "next_due": "…ISO… | null",
  "enabled": true,
  "source": { … } | null,    // opaque, echoed verbatim (as today)
  "managed_by": { … } | null // well-known ownership block (as today)
}
```

- `task_completed` keeps its **exact current fields** (`task_id, name, source, managed_by,
  completed_at, origin`) and *adds* the spine fields — additive only.
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
detect_transitions(prev: dict[str, str], tasks, now) -> (events: list, next_state: dict)
```

The coordinator holds the small `prev` state map (task_id → the `next_due` value already
announced) and fires what `detect_transitions` returns. Firing stays in the HA layer; the
edge logic stays pure.

### Decision B — Edge-triggering and idempotency (don't spam)

Every transition event fires **once per crossing**, never on every 5-minute tick:

- **Overdue / due-soon:** announce a task at most once per `next_due` value. Completing or
  rescheduling advances `next_due`, which re-arms the next announcement naturally. The
  state is keyed on `next_due`, so a task that is *still* overdue next cycle does **not**
  refire.
- **Restart semantics (recommended): baseline silently on first refresh.** On the first
  coordinator run after startup, seed the `prev` map from current state **without firing**,
  so HA restarting doesn't replay an "overdue" storm for tasks that were already overdue.
  Events then fire only for transitions observed *while HA is running*. The overdue
  binary_sensor still reflects the steady state regardless, so nothing is lost — this only
  governs the one-shot *event*. (Alternative: persist a per-task `overdue_announced` marker
  in the store for cross-restart firing — rejected for v1 as storage churn for little gain;
  noted as a future option.)
- **Stock:** out-of-stock and restocked are edge-triggered exactly like the existing
  low-stock crossing — extend the pure `assets.py` helpers to return a richer **transition
  descriptor** (`none | low | out | restocked`) instead of today's bare `crossed_low`
  boolean, then `store.py` maps that to the right event. One chokepoint, three events, no
  double-firing (a single decrement that goes low *and* to zero fires the most specific:
  `out_of_stock`).

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
`event_trigger` with the event type and a `device_id` filter on the payload — so the device
trigger is a thin, well-tested wrapper over the same bus event. Trigger labels live in
`strings.json` under `device_automation`, with **translation parity** across all 16 locales
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
2. **`events.py`** — add a pure builder per event; reuse the spine. Extend
   `completion_event_data` *additively* with the spine fields (keep existing keys).
3. **`assets.py`** — change `consume_part_stock` / `adjust_part_stock` to return a
   transition descriptor (`none|low|out|restocked`) instead of a bare boolean; pure, fully
   unit-tested across boundary values (`stock == reorder_at`, `0`, recovery).
4. **`store.py`** — fire events at the chokepoints: `add_task`/`update_task`/`delete_task`/
   `trigger_task`/`delete_completion`, `add_asset`/`update_asset`/`delete_asset`, and map
   the stock descriptor in `_emit_low_stock`'s sibling(s). `update_task` fires only when
   `merged != existing`, with `changed_fields` computed from the diff.
5. **`testing.py`** — extend the fake to expose the new events via the same builders, so
   integrators can test reactions (mirrors the existing `fire_user_completion`).
6. **Tests** — unit (`events.py` builders, `assets.py` transitions), integration (each
   mutation fires exactly one event with the right payload; no double-fire on a single
   decrement that goes low-and-zero).

### Phase 2 — Time-based transitions (overdue / due-soon)

1. **`transitions.py`** (new, pure) — `detect_transitions(prev, tasks, now)` returning the
   events to fire and the next state map; `DUE_SOON_WINDOW` constant (default 24 h).
2. **`coordinator.py`** — hold the `prev` map, baseline-on-first-refresh (Decision B), call
   the detector each refresh, fire results on the bus. Fire on the **immediate** post-mutation
   refresh too, so completing a task that re-arms a triggered one is observed promptly.
3. **Tests** — unit: crossing fires once, still-overdue doesn't refire, completion re-arms,
   startup baselines silently, DST/timezone-aware `now` (deterministic, injected `now`).

### Phase 3 — Automation-UI device triggers

1. **`device_trigger.py`** (new) — `async_get_triggers` (task vs appliance device subsets),
   `async_attach_trigger` delegating to `event_trigger` with a `device_id` data filter,
   `TRIGGER_SCHEMA`, and `async_get_trigger_capabilities` where useful.
2. **`strings.json` + `translations/*.json`** — `device_automation.trigger_type` labels,
   parity across all locales (enforced by the parity test).
3. **`manifest.json`** — no change (device triggers need no extra dependency).
4. **Tests** — `async_get_triggers` returns the right set per device kind;
   `async_attach_trigger` fires the action when the matching bus event is emitted; a
   non-matching `device_id` does not.

### Phase 4 — Documentation (the deliverable's whole point)

1. **`docs/EVENTS.md`** (new) — the canonical catalog: every event, exactly when it fires,
   a payload table, the **edge-trigger / idempotency / restart semantics**, and copy-paste
   automation examples (both device-trigger and raw `platform: event` YAML). This is the
   "documented well" core.
2. **`docs/INTEGRATING.md`** — extend §3's event references and the at-a-glance table to
   list the new events; cross-link `EVENTS.md` as the full catalog.
3. **`README.md`** — expand the events/automation section with **use cases** (overdue →
   notify; out-of-stock → shopping list; task created → log) and a couple of example
   automations, per the "document new major features in README" rule.
4. **`CHANGELOG.md`** — an **Added** entry under the next beta describing the new events and
   the device-trigger UI, with one automation example.
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
