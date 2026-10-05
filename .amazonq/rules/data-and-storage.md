---
title: Data and storage rules
summary: Rules for the task and appliance data, sensor tasks, completions, syncs and the import and export document.
---

# Data and storage rules

The store is in [store](../../docs/design/store.md), the task model in
[recurrence](../../docs/design/recurrence.md), and the appliance model in
[appliances](../../docs/design/appliances.md).

## Tasks

- Tasks are plain JSON dicts in storage, never model objects. The key list is in the
  recurrence design doc. Treat an absent additive key as its empty default.
- Keep recurrence math in the pure `recurrence.py`, with an explicit `now`.
- `one-off`, `triggered` and `sensor` tasks have no cadence fields. A completed one-off
  and a dormant triggered or sensor task have `next_due=None`. Every time surface drops them.
- `labels[]` are Home Assistant label-registry ids. `merge_update` writes `labels` only
  when the caller sends the key. Do not remove the id of a deleted label.
- A `source` dict is merged, never replaced. Each namespace has 1 owner. Home Keeper owns
  `part`, `buy` and `declarative_companion`. A writer changes only its own key, and an
  unlink pops only that key.
- `task_chips` is set only by the integration that owns the task, and the task form does
  not show it. `card_links` is the user's link from a card task to appliance documents.
- **A fixed schedule is an RFC 5545 RRULE.** `rrule` holds the body only, with no `RRULE:`
  prefix and no DTSTART. `anchor` is the DTSTART. Validate a rule only with
  `recurrence.normalize_rule`, so the service, the import and the panel refuse the same rules.
- **Store the rule, never the legacy pair.** Services and old exports still accept `freq`
  and `interval`, and `models.normalize_fields` converts them on the way in. The store
  converts the stored tasks 1 time on load. No task stores both.
- **A moved date goes in `moved_occurrences`**, never as EXDATE or RDATE in the rule text.
  Each entry is `{from, to}`, and `from` is always the date on the rule. The task form does
  not write the list.
- **A move is a usage action, as a snooze is.** Do not gate `move_occurrence` to admins.
- **A glue integration sets a default interval but never locks it.** Leave `sensor` out of
  `managed_by.locked_fields`. Use `completion_blocked` only for a read-only mirror.

## Sensor tasks

Details are in [sensor-tasks](../../docs/design/sensor-tasks.md).

- The arming math is pure (`sensor_tasks.py`). `sensor_watcher.py` only reads entities
  and applies decisions through the store.
- **Edge state is baselined at startup**, so a restart never arms a task. Tasks that a
  declarative companion has just made are marked new
  (`sensor_watcher.async_mark_tasks_new`) on the path that reloads, and the baseline
  consumes the mark.
- **A hold measures unbroken truth.** An indeterminate reading decides nothing and ends a
  pending hold. Route a missing reading through the evaluator. Do not skip the task.
- Carried edge state is stamped with `sensor_tasks.condition_fingerprint`. A changed
  condition retires it.
- **A new recurrence dimension goes in the `sensor` block** with a branch in the pure
  evaluator, never in `interval`, `unit` or `rrule`. Anchor a time dimension to
  `last_completed`, then `created`, never to the meter baseline. A dimension that does not
  need the reading is evaluated also when the entity is unavailable.
- **A usage meter's `baseline` is the reading on its latest completion.** Correcting that
  reading re-anchors it. Deleting or moving a completion does not. The watcher fills a
  baseline only when there is none, so a user-set start survives.
- The reconciler owns every key of a managed `sensor` block except `baseline`.

## Declarative companions

Details are in [companions-presets](../../docs/design/companions-presets.md).

- A disabled declarative companion pauses its tasks. It never deletes them.
- Every registry event goes through the reconcile debouncer. A spec change starts its own
  pass, and its service waits for the pass and the reload before it answers.
- A declarative companion owns the notes only when it has a notes template. Re-render the
  notes at the arm transition, before `trigger_task`.
- Template labels are added and removed only on a spec save. The reconcile pass never
  writes labels on a task that exists.

## Completions

Details are in [completions](../../docs/design/completions.md).

- A completion is `{ ts }` plus optional `note`, `cost`, `photo` (a URL) and `who` (a
  `person` entity id). `ts` is its identity. Clean input with
  `models.normalize_completion_metadata`.
- **Editing the log never rewinds or re-arms a task**, except the usage baseline rule above.
- `COMPLETION_METADATA_FIELDS` is what a user types and what a task can require.
  `COMPLETION_CAPTURED_FIELDS` is what Home Keeper fills in. Never make a captured field
  requirable. Iterate `COMPLETION_ENTRY_FIELDS` when you copy an entry.
- **Required fields are a panel prompt, not a store rule.** `store.complete_task` never
  rejects a completion for a missing field, because the `todo` checkbox, the button and
  automations cannot show a dialog. Read the required fields from
  `completion_required_fields`, never from a fixed field.
- **`completion_blocked` decides who can press Done**, on every surface.
  `clear_on_recover` sets it for a declarative companion's task.

## Appliances, parts and stock

- Keep appliance metadata apart from device creation. An `existing` appliance never
  changes its device. Prefer native device fields and keep only the gap in the asset.
- A wear part's task is made by `store.reconcile_part_tasks`. Reuse `models.build_task`
  and the per-task entities. Never build a parallel part sensor.
- Generated task names (wear and buy) are localized to `hass.config.language` when they
  are written. The pure reconciler takes the template as an argument.
- `reconcile_part_tasks` skips a manual consumable link (`source.part.manual`).
- **An integration can own an appliance, never the stock on its parts.** `PART_USER_KEYS`
  stay the user's on every path. A part that the owner drops is removed only if it tracks
  no stock. A new part field goes in `PART_USER_KEYS` or `PART_OWNER_KEYS`.
- **Stock quantities are decimal, and a whole value stays an `int`.** Write through
  `assets._round_stock`, and reject NaN and infinity. The per-completion amounts read as 1
  when unset or bad.
- Buy tasks are level-triggered. Settle them through `coordinator.async_settle_buy_tasks`,
  never from the stock event.
- `archived_at` is set only by `archive_asset` and `restore_asset`. Archiving hides an
  appliance. It does not remove its device, entities or tasks.
- Reject a parent cycle with `assets.would_create_cycle`.

## Syncs

Details are in [sync](../../docs/design/sync.md).

- **A to-do list sync is a profile.** Its `sync` block lives in the profile. There is no
  sync record and no sync id.
- Both list syncs subclass `TodoSyncDriver`. Share a method only when both bodies are the
  same except a log string. `problem_sync.py` is not a subclass.
- **A failed call is retried, never compensated.** Keep the bookkeeping entry when a call raises.
- **An unreadable list is not an empty list.** Plan nothing for it.
- **Never touch a completed item**, and never sync onto Home Keeper's own to-do entity.
- Every `todo.*` call is best-effort. A sync pass must never fail a completion.
- Hold an unconfirmed add until `UNCONFIRMED_GRACE` ends. A list that does not show an item
  yet is not proof that the add failed.
- Problem-sensor mirrors accept snooze only. `complete_task` and `skip_task` reject them
  unless the origin is the sync. Never offer a button that the store will refuse.

## Import and export

Details are in [transfer](../../docs/design/transfer.md).

- **A new persisted field travels, or it says why not.** Export passes every field except
  the `EXCLUDED_*` keys, each with a reason. `tests/unit/test_transfer_roundtrip.py`
  proves that a field round-trips. When it goes red, make the field travel or exclude it.
- A new top-level storage key goes in a document section or in `EXCLUDED_STORE_KEYS`.
  `test_transfer_coverage.py` fails otherwise.
- A nested record list (such as parts) is stripped with its own excluded keys.
- A record's fields are the service's fields. Never restate the field list in `transfer.py`.
- Match records by `id`, then `external_id`, then `name`. An ambiguous match raises.
- Validate everything before anything is written. An unknown field is a named warning, and a
  newer `format` is an error.
