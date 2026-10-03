---
title: Sensor tasks and problem sensors
summary: Tasks that arm from a live entity reading, and tasks that mirror problem binary sensors.
implements:
  - custom_components/home_keeper/sensor_tasks.py
  - custom_components/home_keeper/sensor_watcher.py
  - custom_components/home_keeper/template_context.py
  - custom_components/home_keeper/problem_tasks.py
  - custom_components/home_keeper/problem_sync.py
related: [recurrence, store, coordinator-entities, completions, companions-presets, events-api]
source_hash: pending
---

# Sensor tasks and problem sensors

Two features let Home Assistant entities decide when a task is due. A **sensor task**
(`const.REC_SENSOR`) is bound to 1 entity by a user. A **problem-sensor mirror** is a
`triggered` task for each `binary_sensor` with `device_class: problem`. Each feature
is a pure decision module plus a Home Assistant driver that holds the listeners.

## Goals

- **G1. Due on use, not only on time.** A task comes due when a meter advances by a
  target, when a reading crosses a limit, or when an entity enters a state.
- **G2. No false arms.** A restart, a missing entity or a dropout must not arm a task
  or record a completion that did not occur.
- **G3. Pure decisions.** The arm, clear and re-baseline rules run in unit tests with
  plain dicts and an explicit time.
- **G4. Problems mirror themselves.** A problem sensor that turns on arms its task, and
  the task clears itself when the sensor returns to OK.

## Non-goals

- The watcher does not create or delete sensor tasks. A user, a glue integration or a
  declarative companion makes them (see `companions-presets`).
- A sensor task has no predicted due date. `next_due` is `None` (dormant) or the arm
  time, so the calendar and the due-soon window do not show a dormant one.

## Design

### The binding

`models.normalize_sensor` validates the `sensor` block: `entity_id`, `mode`, an optional
`attribute` to read, and the mode fields. A mode rejects the fields of other modes.

| Mode | Fields | Due when |
| --- | --- | --- |
| `usage` | `target`, `baseline`, `unit`, `also_every`, `combinator` | `reading - baseline >= target`, or the time backstop is due |
| `threshold` | `comparison`, `value` | the numeric comparison becomes true |
| `state` | `state` | the state string equals `state` |
| `availability` | (none) | the entity becomes `unavailable` or `unknown` |
| `template` | `template` (no `attribute`) | the template renders true |

The 4 edge modes also take `for_seconds` (a hold of 1 year at most) and
`clear_on_recover`, which is true by default for `availability` only.

### Usage meters

`sensor_tasks.evaluate_usage` returns `arm`, `rebaseline` or no action. The `baseline`
is the meter reading at the latest completion or skip: `store._reset_usage_baseline`
writes the reading that the history entry records. `store._stamp_meter_start` keeps the
old baseline on the entry, and `sensor_tasks.baseline_after_delete` restores it on undo.

- **First reading.** The first valid reading fills an empty `baseline`; a set one stays.
- **Debounced reset.** 1 reading below the baseline is only a candidate. A second one,
  from a new entity report (`last_reported`), re-anchors the meter.
- **Time backstop.** `also_every` (`interval`, `unit`) counts from
  `sensor_tasks.latest_decision_ts`, or from `created`, in local time
  (`sensor_tasks.backstop_due`). A meter reset does not move it. `combinator` `any`
  arms on the first limit met; `all` needs both.
- **No reading.** A task with `also_every` is evaluated with no reading, so an offline
  machine still comes due on time. A task without it is skipped.

### Edge modes

`threshold`, `state`, `availability` and `template` share `sensor_tasks._evaluate_edge`.
Only the test for "condition met" differs. The watcher carries `condition_met`,
`crossed_at` and `sensor_tasks.condition_fingerprint` for each task.

- A false-to-true change sets `crossed_at`. The task arms when the condition stays true
  for `for_seconds`, and the arm consumes the crossing. An armed task consumes a new
  crossing at once, so a steady true, or a completion while true, does not re-arm.
- A false condition drops the crossing. With `clear_on_recover` it clears an armed task.
- An indeterminate reading (no state, `unavailable`, `unknown`, or no boolean from a
  template) decides no action and ends a pending hold (`sensor_tasks._evaluate_indeterminate`).
- A changed fingerprint (entity, attribute, mode, comparison, value, state, template)
  discards the carried state, so an edited task arms on a condition that is true.

### The watcher

`SensorTaskWatcher` applies the decisions. Setup runs `sensor_watcher.async_baseline` first.

- **Baseline.** Each edge task records its current condition as met with no crossing,
  or `None` if the entity has no state or only a `restored` placeholder. The first
  definite reading after `None` is a baseline too, not a crossing.
- **New tasks.** `sensor_watcher.async_mark_tasks_new` keeps ids in `hass.data`, because
  the companion reload destroys the watcher. The baseline consumes the set and leaves
  their edge unset, so a new task arms on a condition that is true.
- **Triggers.** A state listener evaluates the tasks bound to the changed entity, or a
  template that names it. The 5-minute coordinator tick calls
  `sensor_watcher.async_evaluate` for all tasks. A hold books a point-in-time timer.
  Passes run one at a time; a request during a pass adds one more pass.
- **Apply.** `arm` renders the companion notes again, then calls `store.trigger_task`.
  `rebaseline` calls `store.set_sensor_baseline` with no event. `clear` calls
  `store.complete_task` with `ORIGIN_SENSOR_RECOVER` if the task is still armed.
- **Memory only.** Edge state, reset candidates and timers are not stored. Unload
  cancels them. `store.async_repoint_sensor_entity` follows an entity id rename.

### Templates

`sensor_watcher.render_template_result` renders with strict undefined variables, so a
typo is an error. It accepts a `bool` or the words true/yes/on/enable and
false/no/off/disable; a number is an error. Each error is logged once per task.
`template_context.template_variables` gives `entity_id`, `friendly_name`, `device_id`,
`device_name`, `area_id`, `area_name`, `integration`, `translation_key`, `state` and
`attributes`. `template_context.cached_template` keeps 64 compiled templates.

### Problem-sensor sync

`ProblemSensorSync` runs when the `sync_problem_sensors` option is on. It lists each
enabled problem `binary_sensor` except Home Keeper's own and the exclusions (entity,
device, area, label). `problem_sync._is_problem` gives `True`, `False` or `None`.

`problem_tasks.reconcile_problem_tasks` is the pure diff. It returns the new task map,
ordered ops (`created`, `deleted`, `updated`, `armed`, `cleared`) and a changed flag.
`None` never arms or clears. `cleared` records a completion with the sync origin.
`problem_tasks.build_managed_by` locks the name, type, device and area and sets
`completion_blocked`. `store._reject_synced_problem` refuses complete, skip and trigger
from users; snooze is allowed. `notes` stays editable and is kept by entity id in
`problem_notes`, so a mirror made again gets its note back.
`problem_tasks.rename_problem_entity` moves a mirror to a renamed id. A created or
deleted mirror reloads the entry once; other changes refresh the coordinator.

## Trade-offs

- **Edge state in memory** over **stored edge state**: a restart re-baselines from live
  readings, so an old crossing cannot replay as a false arm.
- **Indeterminate ends the hold** over **keeping the crossing**: time with no reading is
  not time the condition was true.
- **Strict boolean templates** over **truthy results**: a number or a typo cannot arm
  or clear a task.

## One-way doors

- The `sensor` block keys and mode names, in storage and in the task services.
- `source.problem_sensor.entity_id` and the `problem_notes` storage section.
- The completion origins `home_keeper_sensor_recover` and `home_keeper_problem_sensor_sync`.
- The template variable names, which saved templates use.
- `reading` and `meter_start` on completion and skip entries.
