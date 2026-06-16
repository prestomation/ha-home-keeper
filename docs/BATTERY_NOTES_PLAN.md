# Plan: `home-keeper-battery-notes` glue + Home Keeper `triggered` task type

**Status:** Plan / design discussion. No code written yet.

## Goal

When a battery goes low/dead, a task is automatically created in Home Keeper; when
the battery is replaced, the task is cleared. Driven by the
[Battery Notes](https://codechimp.org/HA-Battery-Notes/) integration. Long term this
could live inside Battery Notes; for now it's a separate glue integration
(`home-keeper-battery-notes`) plus one additive change to Home Keeper.

## Feasibility — confirmed against existing interfaces on both sides

This needs **no new APIs** on either side beyond a new Home Keeper recurrence type.

**Battery Notes provides:**

| We need | Battery Notes provides |
|---|---|
| Detect battery went low | `battery_notes_battery_threshold` event → `battery_low: true` (+ `device_id`, `device_name`, `battery_level`) |
| Detect battery replaced | `battery_notes_battery_replaced` event (`device_id`, `battery_type`, `battery_quantity`) — fired by button or `set_battery_replaced` |
| Detect level recovered | `battery_notes_battery_threshold` → `battery_low: false` |
| Push "replaced" from our side | `battery_notes.set_battery_replaced` service |
| Reconcile after restart | `binary_sensor.{device}_battery_plus_low` state + `sensor.{device}_battery_last_replaced` |

**Home Keeper provides** (`docs/INTEGRATING.md`): `add_task` (with `device_id`,
`source`, `managed_by`, returns `task_id`), `delete_task`, `complete_task`, the
`home_keeper_task_completed` event, and `list_tasks` for reconciliation.

## The conceptual mismatch

Home Keeper is a *recurring*-task engine: every task today has `interval >= 1` and a
floating/fixed schedule (`recurrence.py` raises on any other `recurrence_type`). A
battery task is **condition-driven**: it exists because Battery Notes reports the
battery low, and should vanish when Battery Notes reports it healthy — not advance to
"next month." `const.py:89-93` already reserves this exact Battery Notes use case as
deferred work.

## Decisions (agreed)

- **Two-way sync:** completing the task in Home Keeper calls
  `battery_notes.set_battery_replaced`, so the two surfaces behave as one button.
- **Clear on both signals, idempotently:** an explicit replaced event *or* a level
  recovery both delete the task; deleting a gone task is a no-op.
- **Add the `triggered` task type to Home Keeper now** (rather than faking a
  recurrence) so the model is honest.

## UX walkthrough

Battery Notes attaches its sensors to the *existing* HA device; Home Keeper can attach
a task to that same `device_id`. So the "Replace battery" task, its mark-done button,
and the battery sensors all live on **one device page**.

1. Battery drops low → `battery_notes_battery_threshold {battery_low: true, device_id}`.
2. Glue calls `home_keeper.add_task` (payload below). Task appears in
   `todo.home_keeper_tasks`, on the device page (overdue/due-now), with a
   "Managed by Battery Notes" chip.
3. You replace the battery — any surface clears the task and updates "last replaced":
   - **Check it off in Home Keeper** → `home_keeper_task_completed` (origin=None) → glue
     calls `set_battery_replaced` *and* `delete_task`.
   - **Press Battery Notes' "Battery Replaced" button** → `battery_notes_battery_replaced`
     → glue `delete_task`s the device's task.
   - **Device just reports a healthy level** → `battery_notes_battery_threshold
     {battery_low: false}` → glue `delete_task`s it.
   All three are idempotent — no loops, no double counting.

## Part A — Home Keeper: the `triggered` recurrence type

A `triggered` task has **no schedule**. An owner integration creates it when a
condition becomes true and deletes it when the condition clears. It is "due now" the
whole time it exists.

**Semantics**
- `next_due` = trigger time (now at creation); never advances → always overdue/due-now
  via existing `is_overdue` (`now >= next_due`). No special-casing in
  todo/sensor/binary_sensor surfaces.
- No `interval`/`unit`/`freq`/`anchor` required or stored.
- `apply_completion` records history and fires `home_keeper_task_completed` (so two-way
  sync works) but does **not** reschedule.
- **Omitted from the calendar** (nothing to project).
- Not user-creatable in the panel; rendered read-only ("due now", "Managed by" chip,
  no recurrence editor).

**File-by-file**

| File | Change |
|---|---|
| `const.py` | `REC_TRIGGERED = "triggered"`; add to `RECURRENCE_TYPES`; retire the deferred note at `:89-93` |
| `models.py` | `normalize_fields`: branch for `triggered` — skip interval/unit/freq/anchor. `build_task`: `next_due` falls out as now. `merge_update`: no recurrence keys to recompute |
| `recurrence.py` | `compute_next_due`: `triggered` → now (sticky due-now). `apply_completion`: `triggered` branch records history, leaves `next_due` untouched |
| `calendar.py` | Skip `triggered` tasks in expansion + next-event |
| `services.yaml` | Allow `recurrence_type: triggered`; document interval/etc. as N/A |
| `websocket_api.py` + panel JS | Accept/display triggered; render read-only; don't offer it in the create form |
| `testing.py` (the fake) | Allow a triggered task with no interval so glue tests pass |
| tests | Unit (models/recurrence) + integration (todo shows due-now, calendar omits, completion fires-but-doesn't-advance, delete works) |
| `docs/INTEGRATING.md`, `CHANGELOG.md` | New "Condition-driven (triggered) tasks" section |

## Part B — The `home-keeper-battery-notes` glue integration

Mirrors the Pawsistant pattern: standalone config-entry integration,
`after_dependencies: [battery_notes, home_keeper]`, every cross-call guarded by
`has_service`.

**Event wiring**
- `battery_notes_battery_threshold` → `battery_low: true` ⇒ create task; `false` ⇒ clear.
- `battery_notes_battery_replaced` ⇒ clear (idempotent).
- `home_keeper_task_completed` (ours, `origin != us`) ⇒ two-way: call
  `battery_notes.set_battery_replaced(device_id)`, then `delete_task` — *without*
  re-completing (loop guard, INTEGRATING.md §4).

**`add_task` payload**
```
recurrence_type: "triggered"
name: "Replace battery: {device_name}"
notes: "{battery_quantity}× {battery_type}"
device_id: {the device}
source: {"home_keeper_battery_notes": {"device_id": ...}}
managed_by: {integration, display_name: "Battery Notes",
             icon: "mdi:battery-alert", config_entry_id,
             deletion_protected: true,
             completion_prompt: "Mark battery as replaced?",
             locked_fields: ["name", "device_id"]}
```

**Loop trace (two-way, safe):** check off in HK → completion event →
`set_battery_replaced` + `delete_task`; the replaced event that fires back → clear →
task already gone → no-op.

**Reconciliation on startup** (self-heals restarts & already-low-on-install):
enumerate Battery Notes' `binary_sensor.*_battery_plus_low` (entity registry, platform
`battery_notes`); `on` with no task ⇒ create; `off` with a stale task ⇒ delete.
Cross-check via `list_tasks` source match to dedupe.

**Config flow:** single instance; options for name template, two-way on/off
(default on), clear-on-recovery on/off (default on).

## Sequencing

1. **Part A** in this repo (`claude/charming-fermi-dinemb`) — in scope, useful to any
   condition-driven source (leak → "mop up", appliance "replace filter", etc.).
2. **Part B** in its own repo (like Pawsistant), built once `triggered` lands so it can
   test against Home Keeper's real fake.

## Open items

- Final home for the glue integration (separate repo recommended).
- Panel rendering of `triggered` tasks (largest soft spot — frontend work + tests).
