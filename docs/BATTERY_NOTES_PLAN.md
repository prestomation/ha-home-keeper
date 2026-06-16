# Plan: `home-keeper-battery-notes` glue + Home Keeper `triggered` task type

**Status:** Plan / design. Part A (Home Keeper `triggered` type) is being implemented
in this repo; Part B (the glue integration) in `ha-home-keeper-battery-notes`.

## Goal

When a battery goes low/dead, a task is automatically marked **due** in Home Keeper;
when the battery is replaced, the task records the replacement (preserving cadence
history) and goes **dormant** again until the next time it's low. Driven by the
[Battery Notes](https://codechimp.org/HA-Battery-Notes/) integration. Long term this
could live inside Battery Notes; for now it's a separate glue integration
(`home_keeper_battery_notes`) plus one additive feature in Home Keeper.

## Feasibility — confirmed against existing interfaces on both sides

This needs **no new APIs** on the Battery Notes side, and on the Home Keeper side a
new recurrence type plus one new owner-facing service (`trigger_task`).

**Battery Notes provides:**

| We need | Battery Notes provides |
|---|---|
| Detect battery went low | `battery_notes_battery_threshold` event → `battery_low: true` (+ `device_id`, `device_name`, `battery_level`) |
| Detect battery replaced | `battery_notes_battery_replaced` event (`device_id`, `battery_type`, `battery_quantity`) — fired by button or `set_battery_replaced` |
| Detect level recovered | `battery_notes_battery_threshold` → `battery_low: false` |
| Push "replaced" from our side | `battery_notes.set_battery_replaced` service |
| Reconcile after restart | the battery-low `binary_sensor` (device_class `battery`) on each Battery Notes device |

> **External-contract caveat.** The event names and payload field names above are
> Battery Notes' surface, not ours. They are *assumed* and must be re-verified against
> a pinned Battery Notes release before/while building Part B (see Part B testing). If
> Battery Notes changes them, the glue breaks — so Part B pins a Battery Notes version
> and asserts the shapes in an integration test.

**Home Keeper provides** (`docs/INTEGRATING.md`): `add_task` (with `device_id`,
`source`, `managed_by`, returns `task_id`), `update_task`, `delete_task`,
`complete_task`, **`trigger_task`** (new — arm a dormant condition-driven task), the
`home_keeper_task_completed` event, and `list_tasks` for reconciliation.

## The conceptual mismatch (and how Model B resolves it)

Home Keeper is a *recurring*-task engine: every task today has `interval >= 1` and a
floating/fixed schedule (`recurrence.compute_next_due` raises `ValueError` on any
other `recurrence_type`). A battery task is **condition-driven**: it should read as
"due" only while Battery Notes reports the battery low, and otherwise sit quietly.

The naïve design (create a task on low, **delete** it on replace) was rejected because
it (a) throws away the completion history — the single most valuable thing about
tracking batteries ("you replace this every ~13 months") — and (b) floods the to-do
list and the Overdue filter with a permanently-overdue entry per battery.

**Model B — a persistent task with an armed/active state.** One long-lived `triggered`
task per battery, created once and *not* deleted on clear. It has two states, encoded
in the field the engine already keys on:

- **dormant / armed** = `next_due: None`. `recurrence.is_overdue` and `is_due_soon`
  already `return False` on `None`, and the calendar already skips `next_due: None`, so
  a dormant task is invisible to every time surface for free. `todo.py` is taught to
  skip dormant triggered tasks (today it would show them as undated items).
- **active / due** = `next_due: <trigger time>` (now at trigger). Due-now everywhere.

This single decision resolves three problems at once:

- **History is preserved on the task itself.** Every clear goes through `complete_task`,
  so `task.completions` accumulates every replacement and the existing completion-history
  UI shows full cadence — with **no** dependence on the device being a Home Keeper asset,
  and **no** durable-log migration.
- **No flood.** Dormant batteries aren't "due", so the to-do list / Overdue filter only
  ever show batteries that need action *right now*. Healthy ones sit dormant and out of
  sight (but still browsable — see UX).
- **Stable identity.** One persistent task per device → one stable `task_id`, keyed by
  `source.device_id` for reconciliation.

## Decisions (agreed)

- **Model B (persistent armed/active)**, not ephemeral create/delete.
- **Every clear records a completion** (`complete_task`) so history is uniform across
  all three clear paths. Clearing a triggered task sets it dormant (`next_due = None`)
  rather than advancing a schedule or deleting it.
- **Two-way sync:** completing the task in Home Keeper calls
  `battery_notes.set_battery_replaced`, so the two surfaces behave as one button.
- **Idempotent in the live path, not only at startup:** the low/replaced handlers
  look the task up by `source` before acting (no duplicate tasks if Battery Notes
  re-fires).
- **Add the `triggered` task type + `trigger_task` service to Home Keeper now** so the
  model is honest and reusable by any condition-driven source (leak → "mop up",
  filter → "replace", etc.).

## UX walkthrough

Battery Notes attaches its sensors to the *existing* HA device; Home Keeper attaches a
task to that same `device_id`, so the "Replace battery" task, its mark-done button, the
HK overdue binary_sensor, and the Battery Notes sensors all live on **one device page**
(the identifier-merge mechanism in `docs/DESIGN.md`).

1. First time a battery drops low → `battery_notes_battery_threshold {battery_low: true,
   device_id}`. Glue finds no existing task for the device → `add_task` (created
   **active**: due-now). Task appears in `todo.home_keeper_tasks`, on the device page
   (due-now), with a "Managed by Battery Notes" chip.
2. You replace the battery — any surface clears it (records a completion, then dormant):
   - **Check it off in Home Keeper** → Home Keeper records the completion and (because
     it's `triggered`) sets the task dormant; fires `home_keeper_task_completed`
     (origin=None) → glue calls `set_battery_replaced` (no re-complete → no loop).
   - **Press Battery Notes' "Battery Replaced" button** → `battery_notes_battery_replaced`
     → glue calls `complete_task(origin="…")` → history recorded, task dormant; glue
     ignores the echoed event by `origin`.
   - **Device just reports a healthy level** → `battery_notes_battery_threshold
     {battery_low: false}` → glue `complete_task(origin="…")` → dormant.
3. Next time the battery is low → glue finds the existing (dormant) task →
   `trigger_task(task_id)` → active/due again. No new task, history intact.

All paths are idempotent — triggering an active task or completing a dormant one is a
no-op-ish refresh, never a loop or a duplicate.

## Part A — Home Keeper: the `triggered` recurrence type

A `triggered` task has **no schedule**. An owner integration arms it
(`trigger_task` / created active) when a condition becomes true and clears it
(`complete_task`) when the condition resolves; while armed it is "due now".

**Semantics**
- `recurrence_type == "triggered"`; no `interval`/`unit`/`freq`/`anchor` required or stored.
- `next_due` is the state: `None` = dormant (invisible to todo/calendar/overdue/due-soon),
  a timestamp = active/due-now (via existing `is_overdue`, `now >= next_due`).
- **Created active**: `compute_next_due("triggered") → now`, so `add_task` yields a due
  task (the condition that prompted creation is already true).
- `apply_completion("triggered")` records history (and `last_completed`) but **does not
  advance** — it sets `next_due = None` (dormant). This is the asymmetry that makes a
  completion *clear* a condition-driven task instead of rescheduling it.
- `trigger_task(task_id)` re-arms a dormant task: `next_due = now`. Idempotent;
  rejects non-triggered tasks.
- **Omitted from the calendar** entirely (even when active — nothing to project).
- Not user-creatable in the panel; rendered read-only ("Monitored", "due now" when
  active, "Managed by" chip, no recurrence editor).

**File-by-file** (line refs are guidance, verify on edit)

| File | Change |
|---|---|
| `const.py` | `REC_TRIGGERED = "triggered"`; add to `RECURRENCE_TYPES`. **Do not** touch the `SIGNAL_TASK_CONTRIBUTION` note (`:89-93`) — that's the *contribution-API* deferral, a different feature. |
| `recurrence.py` | `compute_next_due`: `triggered` → `now`. `apply_completion`: `triggered` branch records history, sets `next_due = None`. (`is_overdue`/`is_due_soon` already handle `None`.) |
| `models.py` | `normalize_fields`: `triggered` branch that skips interval/unit/freq/anchor (the current `else` assumes fixed and would demand `freq`/`anchor` — this is a required guard, not just additive). `build_task`/`merge_update` fall through cleanly once normalize handles it. |
| `store.py` | `trigger_task(task_id)` method (sets `next_due = now`, rejects non-triggered, persists). |
| `calendar.py` | Skip `triggered` tasks in both `event` (`_next_start`) and `_collect_events`. |
| `todo.py` | Skip a `triggered` task whose `next_due is None` (dormant), so only armed ones appear. |
| `__init__.py` + `services.yaml` | `trigger_task` service (light path: refresh, no entry reload). Allow `recurrence_type: triggered` in the select; document interval/etc. as N/A. |
| `websocket_api.py` | Accept/echo `triggered`; the panel renders it read-only and never offers it in the create form. (No new websocket command needed — owners use the service.) |
| `testing.py` (the fake) | **No change needed** — it delegates to `models.build_task`/`recurrence.apply_completion` and uses an `ALLOW_EXTRA` schema, so it supports `triggered` once the model does. Add a `trigger_task` shim to the fake so glue tests can re-arm. |
| frontend | `types.ts` adds `'triggered'`; `utils.ts recurrenceSummary` returns a "Monitored" summary; `panel.ts` renders triggered read-only, buckets it under a **Monitored** status group, hides dormant ones from the default list, omits it from the create form. |
| tests | Unit (models/recurrence: created-active, completion→dormant, trigger re-arms, calendar/todo visibility) + integration (add→active→complete→dormant→trigger round-trip; calendar omits; delete works). Frontend vitest for the summary + bucketing. |
| `docs/INTEGRATING.md`, `docs/DESIGN.md`, `CHANGELOG.md` | New "Condition-driven (triggered) tasks" section + `trigger_task`. |

## Part B — The `home_keeper_battery_notes` glue integration

Standalone config-entry integration (HA domain `home_keeper_battery_notes`; the repo
is `ha-home-keeper-battery-notes`), `after_dependencies: [battery_notes, home_keeper]`,
every cross-call guarded by `has_service`. The glue is **stateless**: it persists no
`device→task_id` map (foreign device_ids can change); it re-derives everything from
`list_tasks` (matched by `source`) ∩ Battery Notes' registry entities, so it self-heals.

### Repo scaffolding (the repo is currently empty — this is real scope)

```
custom_components/home_keeper_battery_notes/
  __init__.py        # setup_entry: wire event listeners + started-reconcile, store unsubs;
                     #   unload_entry: unsub (+ proactively delete our tasks on clean removal)
  manifest.json      # domain home_keeper_battery_notes, version, config_flow: true,
                     #   after_dependencies: [battery_notes, home_keeper], iot_class: calculated,
                     #   requirements: [], codeowners, integration_type: service
  config_flow.py     # single instance; options: name template, two-way on/off (default on),
                     #   clear-on-recovery on/off (default on)
  const.py           # DOMAIN, SOURCE_NS, ORIGIN, Battery Notes event/field names, managed_by builder
  logic.py           # PURE: (battery_notes state + HK task list) -> desired actions
                     #   (mirrors home_keeper/reconcile.py purity for unit-testability)
  wiring.py          # HA-facing: event subscriptions, service calls, started-reconcile
  strings.json + translations/en.json
hacs.json
requirements-test.txt     # home-keeper @ git+…; a pinned battery_notes ref; pytest-homeassistant-custom-component
tests/  unit (pure logic) + integration-fake (HK testing fake) + integration-docker (all three real)
ci/ + .github/workflows/  # lint, test, hacs validate — borrowed from ha-home-keeper
README.md   (LICENSE already present)
```

### Event wiring (all idempotent, all `has_service`-guarded)

- `battery_notes_battery_threshold` → `battery_low: true` ⇒ look up the device's task in
  `list_tasks` by `source`; **create active** if absent, else `trigger_task`.
- `battery_notes_battery_threshold` → `battery_low: false` ⇒ `complete_task(origin=ORIGIN)`
  (records history, goes dormant). No-op if already dormant/absent.
- `battery_notes_battery_replaced` ⇒ `complete_task(origin=ORIGIN)` (idempotent).
- `home_keeper_task_completed` (ours, `origin != ORIGIN`) ⇒ two-way: call
  `battery_notes.set_battery_replaced(device_id)` only — **do not** re-complete or
  re-trigger (loop guard, INTEGRATING.md §4). The HK side already went dormant.

### `add_task` payload

```
recurrence_type: "triggered"
name: "Replace battery: {device_name}"      # name template configurable
notes: "{battery_quantity}× {battery_type}"  # + battery_level if available
device_id: {the device}
source: {"home_keeper_battery_notes": {"device_id": ...}}
managed_by: {integration: "home_keeper_battery_notes", display_name: "Battery Notes",
             icon: "mdi:battery-alert", config_entry_id,
             deletion_protected: true,
             completion_prompt: "Mark battery as replaced?",
             locked_fields: ["name", "device_id"]}
```

### Matching Battery Notes' entities (no brittle string-matching)

Reconcile by the **entity registry**, not by `entity_id` suffixes: filter
`entry.platform == "battery_notes"` and select the battery-low `binary_sensor` by
`device_class == battery`. (Confirm Battery Notes' actual `unique_id` scheme during
Part B so the match is exact.) `on` with a dormant/absent task ⇒ arm/create; `off`
with an armed task ⇒ complete (dormant). Cross-check via `list_tasks` `source` match to
dedupe.

### Startup ordering (event-driven, no retry/backoff)

`after_dependencies` only orders setup; it does **not** guarantee Battery Notes'
entities/services exist when the glue sets up. So: don't reconcile at
`async_setup_entry` time — run reconcile on `EVENT_HOMEASSISTANT_STARTED` (or
immediately if `hass.is_running`), by which point both integrations are up. `has_service`
guards cover Home-Keeper-absent. The live `threshold`/`replaced` listeners are
self-healing; reconcile is just the catch-up for signals missed while the glue was down.

### Lifecycle / cleanup

- `async_unload_entry`: unsubscribe listeners; on **clean removal** also `delete_task`
  the tasks we own (proactive). Orphan detection (`deletion_protected` +
  `config_entry_id`) is the safety net for crashes/uninstalls where we can't.

### Loop trace (two-way, safe)

Check off in HK → HK records completion + goes dormant → fires `home_keeper_task_completed`
(origin=None) → glue calls `set_battery_replaced` only → the `battery_notes_battery_replaced`
that fires back → glue `complete_task(origin=ORIGIN)` → task already dormant → no-op; the
echoed completion event carries `origin=ORIGIN` → glue ignores it.

### Testing

- **Unit:** the pure `logic.py` (each branch: create/arm/complete/no-op) over plain inputs.
- **Integration (HK fake):** `home_keeper.testing.async_setup_fake_home_keeper` + a small
  Battery Notes event emitter; assert the glue arms/clears and doesn't loop.
- **Integration (docker, end-to-end):** borrow `ha-home-keeper/tests/integration/
  docker-compose.yml`; mount **all three** custom_components (home_keeper, battery_notes,
  home_keeper_battery_notes), pin both upstreams to known refs, fire real Battery Notes
  events / call its services, and assert Home Keeper state via `list_tasks`. This is the
  contract test that guards the external-event caveat above.

## Sequencing

1. **Part A** in this repo — the `triggered` type + `trigger_task` service, useful to any
   condition-driven source.
2. **Part B** in `ha-home-keeper-battery-notes`, built once `triggered` lands so it can
   test against Home Keeper's real fake and (in the docker tier) the real integration.

## Open items

- Confirm Battery Notes' exact event field names and battery-low `unique_id`/`device_class`
  against a pinned release (Part B blocker).
- Multi-battery devices collapse to one per-device task (Battery Notes' threshold event is
  per-device) — acceptable for v1; revisit if needed.
- Panel rendering of `triggered`/"Monitored" tasks (the largest frontend slice).
- If a battery *device* is removed entirely, its task is deleted and its on-task history
  goes with it unless the device is also a Home Keeper asset — acceptable edge for v1.
</content>
</invoke>
