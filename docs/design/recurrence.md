---
title: Task model and recurrence
summary: Builds and validates the task dict and computes when each task is due next.
implements:
  - custom_components/home_keeper/recurrence.py
  - custom_components/home_keeper/models.py
  - custom_components/home_keeper/frontend/src/defer.ts
  - custom_components/home_keeper/frontend/src/defer-dialogs.ts
  - custom_components/home_keeper/frontend/src/panel-defer.ts
related: [store, completions, sensor-tasks, appliances, events-api, transfer, frontend]
source_hash: d67a00e10d69
---

# Task model and recurrence

A task is a plain JSON dict. `models.py` builds, validates and merges it. `recurrence.py`
calculates `next_due` from the task and an explicit `now`. The 3 frontend modules give the
panel and the dashboard card the Snooze, Skip and Due today actions.

## Goals

- **G1. One task shape.** Creation and edit share 1 validation, so every path stores the
  same keys for a recurrence type.
- **G2. Six recurrence types.** Each type in `const.RECURRENCE_TYPES` has 1 rule for
  `next_due` on creation, completion, skip and undo.
- **G3. Local wall time.** A schedule keeps the time of day that the user set, across a
  daylight-saving change and after a reload from storage.
- **G4. Defer without loss.** Snooze, skip and due today move the due date and never change
  the completion log or lose a fixed occurrence.
- **G5. Pure core.** Both Python modules import only the standard library and `const.py`,
  and take time and zone as arguments, so unit tests and mutmut run without Home Assistant.

## Non-goals

- Arming a sensor or use task from a reading lives in `sensor-tasks`.
- The completion log lives in `completions`; storage and events in `store` and `events-api`.

## Design

### Task dict

`models.build_task` gives `id` (a UUID), `created`, `name`, `notes`, `recurrence_type`,
`device_id`, `area_id`, `enabled`, `last_completed`, `next_due`, `completions`, `skips`,
`active_season`, `snooze_hours`, provenance (`source`, `managed_by`) and display fields.
`models.normalize_fields` adds only the schedule keys of the type:

| Type | Schedule keys | Created as | After completion |
|---|---|---|---|
| `floating` | `interval`, `unit` | due `now` | `completed_at` + interval |
| `fixed` | `interval`, `freq`, `anchor` | next grid occurrence | next grid occurrence |
| `one-off` | `due` | `due` (default `now`) | `None` (dormant) |
| `triggered` | none | `now` (armed) | `None` (dormant) |
| `sensor` | `sensor` block | `None` (dormant) | `None` (dormant) |
| `use` | none | `None` | `None` (always) |

`models.infer_recurrence_type` picks a type when a creation call names none: `interval` or
`unit` gives `floating`, `freq` or `anchor` gives `fixed`, and a bare name gives `one-off`.
A `last_completed` seed goes through `recurrence.apply_completion` as the first log entry.

`models.merge_update` runs `normalize_fields` on the stored task plus the update:

- Fields in `managed_by.locked_fields` are removed from the update first.
- A type change reads `due` and `sensor` only from the update, and removes each key in
  `_TYPE_SCHEDULE_KEYS` that the new type does not use.
- `next_due` is calculated again only if a recurrence field changed its value
  (`models._same_schedule_value`), so a rename keeps a snooze and a finished one-off done.
- Labels, card links, chips, `external_id`, the tag and `snooze_hours` change only if sent.

### How `next_due` is calculated

`recurrence.compute_next_due` derives a date from the task state alone. Floating adds the
interval to `last_completed`; with no completion it is `now`, and a missed task stays overdue.
Fixed returns the first grid occurrence after `now`. Triggered and sensor return `now`, which
arms them: the owner calls `trigger_task`, and the watcher arms a sensor task. One-off returns
`due`. Use raises `ValueError`, because nothing arms a use task and each caller skips it.

`recurrence.add_months` clamps the day (Jan 31 + 1 month is Feb 28). `recurrence._fast_forward`
jumps near the target, so an old anchor costs few steps; a monthly grid first steps to day 28.

In the `set_time` due time mode the store passes `due_time` to each call.
`recurrence._floating_due` adds the interval, clamps to the season, and `snap_to_due_time` sets
that time on the date. A due `now` does not snap, and a floating snooze rounds up. Each entry
load runs `snap_future_floating`, which moves each future floating date to the set time.

### Time zones

Every datetime is aware, and the caller passes `now`. A stored ISO string keeps only a UTC
offset, so `recurrence._regrid` and `recurrence._local` move the anchor and `last_completed`
into the zone of `now` before any arithmetic: 10:00 stays 10:00 after a daylight-saving
change. A naive input gets the configured zone with `replace(tzinfo=...)`.

### Completion and skip

`recurrence.apply_completion` writes the log entry and moves `next_due`. A completion older
than the latest one only fills in the log. For a fixed task, `_advance_fixed_schedule` moves
past `max(now, next_due)`: Done before the time of day clears today's occurrence, and an
overdue task skips all missed ones in 1 step. The entry keeps `prior_due` for
`remove_completion`; a floating entry only after a snooze, a due today or a moved date.

`recurrence.skip_occurrence` writes to `skips`, never to `completions`, and does not change
`last_completed`. A floating task becomes due 1 interval from `now`. A fixed task moves as it
does on completion. Every other type becomes dormant. `recurrence.remove_skip` re-arms a
one-off at `due` only when it has no completion and no other skip.

### Snooze and due today

Both call `recurrence.defer`, which sets `next_due` and records no log entry. On a fixed task it
keeps the grid occurrence in `deferred_from`, so a later completion loses none.
`recurrence.snooze_from` counts a snooze from the due date when that is later than `now`. The
store rejects both on a dormant task.

In the frontend, `defer.deferVerbs` decides which actions to show: all need a `next_due`, Skip
a task that is not `completion_blocked`, Due today one that is not overdue, and each has an
option switch. The details item opens the completion dialog on a one-tap task.
`defer.snoozeTarget` repeats `snooze_from` and the set-time round-up, and refuses a custom
date that is not later. `defer-dialogs.ts` holds the menu and both dialogs for the panel and
the card; `panel-defer.ts` binds them to the panel host.

### Dormant, disabled and one-off

A task with `next_due` set to `None` is dormant. `recurrence.is_overdue` and
`recurrence.is_due_soon` return false for it, and a surface that lists tasks skips it.
`enabled: false` keeps `next_due` but removes the task from the to-do list, the calendar, the
per-task entities and the transition events. `recurrence.one_off_expired` adds the retention
option to `one_off_completed`, and the coordinator deletes an expired task.

### Seasons

`active_season` is 1 or more `{"start": "MM-DD", "end": "MM-DD"}` windows. A window can wrap
the year end. `recurrence._clamp_season` moves a date outside the season to the next season
start. For a fixed task it uses `recurrence.next_in_season_occurrence`, so the result stays on
the grid and agrees with the calendar.

## Trade-offs

- **`next_due` as stored state** over **a date derived on each read**: snooze, skip and
  deferral need memory that the log does not hold, so only undo derives again.
- **Never completed means due now** over **due 1 interval later**: a seed date opts out.
- **Skips in their own list** over **a flag on a completion**: no reader must filter.
- **Re-home into the zone of `now`** over **storing a zone name**: ISO text holds no zone,
  and every caller has the configured zone.

## One-way doors

- Stored keys: the `recurrence_type` values, `interval`, `unit`, `freq`, `anchor`, `due`,
  `next_due`, `last_completed`, `enabled`, `active_season`, `snooze_hours`, `skips`, and
  the internal `prior_due` (completion entry) and `deferred_from` (task).
- Services that set them: `add_task`, `update_task`, `snooze_task` (`hours` or `until`),
  `skip_task`, `set_due_today`, `trigger_task`. See [INTEGRATING](../INTEGRATING.md).
- Options: `due_time_mode` (`completion`, `set_time`) and `due_time` (`HH:MM`).
