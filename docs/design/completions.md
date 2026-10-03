---
title: Completions
summary: Records each time a task is done, with optional detail, and lets a user correct it.
implements:
  - custom_components/home_keeper/frontend/src/panel-history.ts
  - custom_components/home_keeper/frontend/src/panel-dialogs.ts
  - custom_components/home_keeper/tags.py
  - custom_components/home_keeper/tag_listener.py
related: [recurrence, store, appliances, documents-photos, sensor-tasks, events-api, frontend]
source_hash: pending
---

# Completions

A completion is one dated entry in a task's `completions` list. It records that the work
was done, and it can carry a note, a cost, a photo, the person who did it, and a meter
reading. The panel shows the list as a history log, and a user can edit, re-date or delete
each entry. An NFC/RFID tag scan is one more way to complete a task.

## Goals

- **G1. One-tap Done stays fast.** A task with no detail mode completes in 1 tap with Undo.
- **G2. Optional detail per task.** The task owner picks if Done asks for detail.
- **G3. A correctable log.** A user can fix an entry's detail or date, or delete it, and
  the schedule stays correct.
- **G4. History outlives the task.** A deleted task's completions stay on its appliance.
- **G5. Physical presence.** A tag scan completes the bound tasks, and a task can demand a
  scan as the only way to complete it.

## Non-goals

- The due-date math after a completion. `recurrence.py` owns it (see `recurrence`).
- Persistence, events and the shared gates. `store.py` owns them (see `store`).
- Tag registration and image storage. Home Assistant owns both.

## Design

### Completion record

Each entry is a dict keyed on its ISO `ts`, which is the identity for edit, move, delete
and archive:

| Key | Type | Source |
|---|---|---|
| `ts` | aware ISO datetime | always |
| `note` | Markdown string | user |
| `cost` | float, 0 or more | user |
| `photo` | site-relative or http(s) image URL | `ha-picture-upload` |
| `who` | `person.*` entity id | user |
| `reading` | float | sensor, editable |
| `prior_due`, `meter_start` | internal | store bookkeeping |

`models.normalize_completion_metadata` cleans the user fields. It strips strings, drops
blanks, refuses a negative or non-finite cost, and refuses a photo that is not http(s) or
a site-relative path. That last rule stops a `javascript:` URI from becoming stored XSS;
the panel repeats it with `isSafeImageUrl`. Empty keys are omitted, never stored as null.
`const.COMPLETION_ENTRY_FIELDS` lists every entry field, and the device-page sensor copies
the latest entry's fields into `last_completion_<field>` attributes.

`recurrence._record_entry` appends an entry, replaces a twin at the same `ts`, and keeps
the newest `const.MAX_COMPLETION_HISTORY` (500). The skip log shares it. Undo and edit
thus always find exactly 1 entry for a `ts`.

### Detail modes and required fields

A task has `completion_detail` (`none`, `optional`, `required`) and
`completion_required_fields`. `models.normalize_completion_required_fields` keeps only
members of `const.COMPLETION_METADATA_FIELDS`, empties the list unless the mode is
`required`, and falls back to `["note"]`. The form offers only the mode; the panel reads
the list, so a per-field editor needs no migration. `reading` is never required, because
Home Keeper captures it and a task with no sensor cannot supply it.

### Completion dialog and one-tap Done

`_complete` in `panel.ts` refuses a scan-only task with a toast. For `optional` or
`required` it calls `openCompletionDialog`. Otherwise it calls `api.completeTask`, and the
toast's Undo deletes the new entry by its `ts`. The card has no dialog, so a `required`
task sends the user to the panel.

`renderCompletionDialog` in `panel-dialogs.ts` builds one `ha-form` for both uses. To log
a completion it shows Completed at, note, cost, who (person picker) and, for a numeric
sensor task, the live reading. In edit mode it hides Completed at, because an edit never
moves `ts`. A photo field appears only if the frontend has `ha-picture-upload`. In
`optional` mode a Skip details button completes with no detail. The panel blocks Mark done
while a required field is empty. `guardWrite` stops a double click from logging 2 entries.

Completed at back-dates the entry. `recurrence.apply_completion` logs an entry older than
the latest as backfill: it moves neither `last_completed` nor a floating or fixed `next_due`.

### Editing, moving and deleting an entry

- **Edit.** `store.update_completion` calls `recurrence.update_completion`, which sets or
  clears each field and never touches `ts` or the schedule. A changed `reading` on the
  latest decision of a usage task moves the meter baseline. Event:
  `home_keeper_task_completion_updated`.
- **Move.** `store.move_completion` calls `recurrence.move_completion`, which re-inserts
  the whole entry at the new `ts` and derives `last_completed` once from the final list.
  Only a floating task recomputes `next_due`, and only if the latest entry changed. It
  fires `home_keeper_task_uncompleted` then `home_keeper_task_completed`.
- **Delete.** `store.delete_completion` calls `recurrence.remove_completion`. A fixed task
  gets its `prior_due` back, a one-off re-arms if its log is empty, and stock and the
  meter baseline return. Event: `home_keeper_task_uncompleted` with the removed `ts`.

`panel-history.ts` wires these 3 row buttons. A sync-owned problem-sensor task refuses all 3.

### Archived completions on appliances

When a task is deleted, `store._archive_task_history` asks `assets.find_archiving_asset`
for its appliance: the part-source appliance first, then one that owns or relates to the
task's device. `assets.build_archived_history` snapshots the task name, part id and the
whole completion list, with all detail, into `task_history`. A standalone task's history
is dropped. `completionGroupsFor` merges live and archived groups, newest first. An
archived row has delete only (`store.delete_archived_completion`), because edit and move
work on live tasks.

### NFC tags

A task has `tag_id` and `require_tag_scan`; `models.normalize_tag_id` validates the id,
and a scan-only task without a tag is refused. `tag_listener.async_setup_tag_listener`
subscribes to `tag_scanned` once per Home Assistant run, not per config entry, so a scan
during a reload waits for the coordinator. `tags.tasks_for_tag` returns every enabled task
bound to the tag; one tag can complete several tasks. Each completes through
`store.complete_task` with the tag-scan origin. A refusal on one task is logged at debug
level and the rest continue.

`store._reject_scan_required` applies the gate `tags.completion_allowed`. Its
`tags.SCAN_ALLOWED_ORIGINS` adds sensor recovery and problem-sensor sync to the tag scan.

## Trade-offs

- **Required fields checked in the panel** over a server check: the `complete_task` service
  stays usable by automations that have no person to ask.
- **Photo stored as a URL** over bytes: the single JSON store stays small.
- **Move as uncompleted plus completed events** over a new event type: listeners know both.
- **Origin markers trusted as given** over authentication: the scan gate is household
  accountability, not a security boundary.

## One-way doors

- Entry keys `ts`, `note`, `cost`, `photo`, `who`, `reading` in storage, in the export,
  in event payloads and in `last_completion_*` attributes.
- Task fields `completion_detail`, `completion_required_fields`, `tag_id`,
  `require_tag_scan`.
- Services `complete_task`, `update_completion`, `move_completion`, `delete_completion`,
  `delete_archived_completion`, and the `ts` that identifies an entry in each.
- The appliance `task_history` entry shape: `task_id`, `task_name`, `part_id`,
  `completions`, `archived_at`.
