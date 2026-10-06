---
title: Task model and recurrence
summary: Builds and validates the task dict and computes when each task is due next.
implements:
  - custom_components/home_keeper/recurrence.py
  - custom_components/home_keeper/models.py
  - custom_components/home_keeper/frontend/src/defer.ts
  - custom_components/home_keeper/frontend/src/defer-dialogs.ts
  - custom_components/home_keeper/frontend/src/panel-defer.ts
  - custom_components/home_keeper/frontend/src/rrule.ts
  - custom_components/home_keeper/frontend/src/panel-rule.ts
max_lines: 193
exception: 6 recurrence types plus the RRULE engine and moved dates of a fixed schedule
related: [store, completions, sensor-tasks, appliances, events-api, transfer, frontend]
source_hash: c90239d0b3da
---

# Task model and recurrence

A task is a plain JSON dict. `models.py` builds, validates and merges it. `recurrence.py`
calculates `next_due` from the task and an explicit `now`. The 5 frontend modules give the
panel and the dashboard card the Snooze, Skip and Due today actions and the schedule form.

## Goals

- **G1. One task shape.** Creation and edit share 1 validation, so every path stores the
  same keys for a recurrence type.
- **G2. Six recurrence types.** Each type in `const.RECURRENCE_TYPES` has 1 rule for
  `next_due` on creation, completion, skip and undo.
- **G3. Local wall time.** A schedule keeps the time of day that the user set, across a
  daylight-saving change and after a reload from storage.
- **G4. Defer without loss.** Snooze, skip and due today move the due date and never change
  the completion log or lose a fixed occurrence.
- **G5. Pure core.** Both Python modules import only the standard library, `dateutil.rrule`
  and `const.py`, and take time and zone as arguments, so unit tests and mutmut run without
  Home Assistant.

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
| `fixed` | `rrule`, `anchor`, `moved_occurrences` | next schedule date | next schedule date |
| `one-off` | `due` | `due` (default `now`) | `None` (dormant) |
| `triggered` | none | `now` (armed) | `None` (dormant) |
| `sensor` | `sensor` block | `None` (dormant) | `None` (dormant) |
| `use` | none | `None` | `None` (always) |

`models.infer_recurrence_type` picks a type when a creation call names none: `interval` or
`unit` gives `floating`, `rrule`, `freq` or `anchor` gives `fixed`, and a bare name gives
`one-off`. A `last_completed` seed goes through `recurrence.apply_completion` first.

`models.merge_update` runs `normalize_fields` on the stored task plus the update:

- Fields in `managed_by.locked_fields` are removed from the update first.
- A type change reads `due` and `sensor` only from the update, and removes each key in
  `_TYPE_SCHEDULE_KEYS` that the new type does not use.
- `next_due` is calculated again only if a recurrence field changed its value.
  `models._same_schedule_value` compares `due` and `anchor` as instants to the second, and
  seasons as month-day pairs. Thus a rename keeps a snooze and keeps a finished one-off done.
- A legacy `freq` or `interval` edit changes the stored rule (`models._rule_after_legacy_edit`).
  A new rule or anchor removes each move whose `from` is not a date of the new schedule.
- Labels, card links, chips, `external_id`, the tag and `snooze_hours` change only if sent.

### Fixed schedules

`rrule` is an RFC 5545 RRULE body, and `anchor` is its DTSTART and gives the time of day.
`recurrence.normalize_rule` is the 1 validator. It removes an `RRULE:` prefix, needs a FREQ
in `const.RULE_FREQS`, and refuses `const.RULE_FORBIDDEN_PARTS` (COUNT, UNTIL, DTSTART and
the sub-daily parts). It also refuses a rule over `MAX_RULE_LENGTH` or with no date in 20
years. `recurrence.legacy_rule` converts `freq` and `interval`: `models.normalize_fields`
uses it on input, and `models.migrate_legacy_fixed_schedule` uses it on store load.

`dateutil.rrule` expands the rule on naive local wall time. `recurrence.effective_rule`
first writes out each day that dateutil takes from DTSTART. A plain monthly rule on the
29th to 31st becomes "that day or the last day of a shorter month". A yearly rule on
February 29 falls on February 28 in other years. `recurrence._fast_forward_start` moves
the start by whole periods near the probe, so an old anchor costs few steps.
`recurrence._on_schedule` tells if a moment is a schedule date, and so not a snooze. It
probes 3 hours early, which is more than a daylight-saving shift.

### Moved dates

`moved_occurrences` holds `{from, to}` pairs, at most `MAX_MOVED_OCCURRENCES`. The engine
removes each `from` and adds each `to`. `recurrence.move_occurrence` takes the date on the
rule or the current `to`, and a move to its own date undoes the move. It refuses a `to` in
the past or on a date that the schedule has. `next_due` changes only if it is the moved
date or the new date is earlier, so a snooze stays. `recurrence.prune_moves` removes the
moves that are fully past. `recurrence.upcoming_occurrences` lists the next dates as
`{start, moved_from}` rows. `store.add_task` and `store.update_task` refuse
`moved_occurrences`, so every move goes through these checks and fires its event.

### Schedule form

The task form never holds a second copy of the rule. Repeats, Every and the day buttons are
views of `rrule`. `rrule.parseSimple` reads a rule into the controls, and `rrule.buildSimple`
and `rrule.toggleDay` write the controls back. If `rrule.parseSimple` gives `null`, the
controls are disabled and `rrule.resetToSimple` gives Reset to simple. `panel-rule.ts`
writes the rule on each change and repaints each view in place, so the rule box keeps focus.
The card form uses `forms.reconcileRuleEdit`. A line under the form shows the next dates
from `home_keeper/upcoming_occurrences`. The task page shows them in an Upcoming block,
with Move and Undo on each date (`panel-detail.ts`).

### How `next_due` is calculated

`recurrence.compute_next_due` derives a date from the task state alone. Floating adds the
interval to `last_completed`; with no completion it is `now`, and a missed task stays overdue.
Fixed returns the first schedule date after `now`. Triggered and sensor return `now`, which
arms them: the owner calls `trigger_task`, and the watcher arms a sensor task. One-off returns
`due`. Use raises `ValueError`, because nothing arms a use task and each caller skips it.
`recurrence.add_months` clamps the day (Jan 31 + 1 month is Feb 28) for a floating task.

### Time zones

Every datetime is aware. The caller passes `now` from Home Assistant, so tests fix the clock.
A stored ISO string keeps only a UTC offset, not a zone. `recurrence._regrid` and
`recurrence._local` move the anchor and `last_completed` into the zone of `now` before any
arithmetic. A naive input gets the configured zone with `replace(tzinfo=...)`.

### Completion and skip

`recurrence.apply_completion` writes the log entry and moves `next_due`. A completion older
than the latest one only fills in the log. For a fixed task,
`recurrence._advance_fixed_schedule` moves past `max(now, next_due)`. Done before the time of
day clears today's occurrence, and an overdue task jumps over all missed occurrences in
1 step. The entry keeps `prior_due`, so `recurrence.remove_completion` can restore it. A
floating entry keeps it only after a snooze, a due today or a moved date.

`recurrence.skip_occurrence` writes to `skips`, never to `completions`, and does not change
`last_completed`. A floating task becomes due 1 interval from `now`. A fixed task moves as it
does on completion. Every other type becomes dormant. `recurrence.remove_skip` re-arms a
one-off at `due` only when it has no completion and no other skip.

### Snooze and due today

Both call `recurrence.defer`, which sets `next_due` and records no log entry. On a fixed task
it stores the schedule date in `deferred_from`. A later completion moves past that date, and
so the user loses no occurrence between the old date and the new date.
`recurrence.snooze_from` counts a snooze from the due date if that is later than `now`, so a
snooze never makes a task due earlier. The store rejects both on a dormant task.

In the frontend, `defer.deferVerbs` decides which actions to show. All need a `next_due`.
Skip also needs a task that is not `completion_blocked`, and due today a task that is not
overdue. Each action has an option switch. `defer.snoozeTarget` repeats the `snooze_from`
rule. `defer-dialogs.ts` holds the menu and both dialogs for the panel and the card, and
`panel-defer.ts` binds them to the panel. On a fixed task, the Snooze dialog also has
"A later date", which moves 1 of the next schedule dates with `move_occurrence`.

### Dormant, disabled and one-off

A task with `next_due` set to `None` is dormant. `recurrence.is_overdue` and
`recurrence.is_due_soon` return false for it, and a surface that lists tasks must skip it.
`enabled: false` keeps `next_due` but removes the task from the to-do list, the calendar,
the per-task entities and the transition events. The coordinator deletes a finished one-off
(`recurrence.one_off_completed`) after the retention option (`recurrence.one_off_expired`).

### Seasons

`active_season` is 1 or more `{"start": "MM-DD", "end": "MM-DD"}` windows. A window can wrap
the year end. `recurrence._clamp_season` moves a date outside the season to the next season
start. A fixed task uses `recurrence.next_in_season_occurrence`, which the calendar uses too.

## Trade-offs

- **`next_due` as stored state** over **a date derived on each read**: snooze, skip and
  deferral need memory that the log does not hold, so only undo derives again.
- **Never completed means due now** over **due 1 interval later**: a seed date opts out.
- **Skips in their own list** over **a flag on a completion**: no reader must filter.
- **Moves in their own list** over **EXDATE and RDATE in the rule**: the form edits the rule
  text only, and a rule change keeps each move that still fits.
- **Re-home into the zone of `now`** over **storing a zone name**: ISO text holds no zone,
  and every caller has the configured zone.

## One-way doors

- Stored keys: the `recurrence_type` values, `interval`, `unit`, `rrule`, `anchor`,
  `moved_occurrences` (`from`, `to`), `due`, `next_due`, `last_completed`, `enabled`,
  `active_season`, `snooze_hours`, `skips`, and the internal `prior_due` and `deferred_from`.
- Services that set them: `add_task` and `update_task` (which also take the legacy `freq`),
  `snooze_task`, `skip_task`, `set_due_today`, `move_occurrence` and `trigger_task`.
  See [INTEGRATING](../INTEGRATING.md).
