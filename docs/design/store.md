---
title: Store
summary: Holds all Home Keeper data in one JSON document and is the one place that changes it.
implements:
  - custom_components/home_keeper/store.py
related: [architecture, coordinator-entities, events-api, transfer, appliances, completions]
source_hash: 05b98a051919
---

# Store

`HomeKeeperStore` wraps the Home Assistant `Store` helper around one JSON document,
`.storage/home_keeper`. It keeps the data in memory as plain dicts and writes the full
document after each change. Every write path goes through it: services, websocket
commands, the reconcilers and the sync modules. It also fires the `home_keeper_*` bus
events, so a change is visible to automations whatever surface caused it.

## Goals

- **G1. One chokepoint.** Each change to tasks, appliances or companion specs goes
  through a store method that validates, writes, saves and fires its event.
- **G2. Durable on return.** When a mutation returns, its save is complete.
- **G3. Safe load.** An older or hand-edited file loads without a failed setup.
- **G4. No stale writes.** A pass that started before an entry unload cannot write old
  data over the file that the reloaded store owns.
- **G5. Exact events.** An event fires once per real change, after the save, with the
  same payload that `events.py` builds for the test fake.

## Non-goals

- Record shape and validation. `models.py` and `assets.py` build and check records;
  the pure passes in `reconcile.py`, `problem_tasks.py` and `declarative_companions.py`
  compute the diffs. The store persists their output.
- Entities. The coordinator reads the store and the platforms read the coordinator.
  The store does not refresh the coordinator or reload the entry.
- Uploaded files (`manuals.py` keeps them on disk) and time-based events (the
  coordinator detects overdue and due soon on its clock).

## Design

### The document

`STORAGE_KEY` is `home_keeper` and `STORAGE_VERSION` is 1. The store sets no minor
version and no migrate function. `HomeKeeperStore._save` writes these top-level keys:

| Key | Contents |
|---|---|
| `tasks` | task id to task dict |
| `assets` | appliance id to appliance dict, with parts, documents and archived history |
| `problem_notes` | problem sensor `entity_id` to the note of its mirror task |
| `shopping_items` | `asset_id:part_id` to the to-do item that mirrors a buy reminder |
| `declarative_companions` | spec id to a declarative companion spec |
| `todo_list_items` | profile and task key to the item on a synced to-do list |

The last 3 maps are bookkeeping kept outside the task, because they matter most after
the task is deleted. `tests/unit/test_transfer_coverage.py` parses `_save` and fails on
a new key that the import/export document neither carries nor excludes.

### Load and migrations

`store.load` reads each section if it is a dict and uses an empty dict if not. A new
section is therefore additive and needs no version bump. Declarative specs go through
`declarative_companions.normalize_declarative_companion` again. A spec that fails is
dropped with a warning, because one lost spec is better than a failed startup.

Then load runs idempotent shims: `assets.migrate_legacy_part_numbers`,
`assets.migrate_documents_from_manual_url`, `_clean_relationship_links` and
`reconcile.adopt_part_tags`. It saves once, only if a shim changed data. A new optional
field needs no shim, because readers use `.get()` with a default.

### The mutation shape

Each public mutation keeps one order. It finds the record or raises `KeyError`, and
runs its guards (`models.TaskValidationError`, `assets.AssetValidationError`) before any
write. Then it changes the in-memory dicts, awaits `_save`, fires its events and returns
the new record.

Events fire after the save, so a listener that reads the store back sees saved state.
`_changed_fields` ignores history and schedule keys, so a reschedule is not an edit, and
an update with no changed field fires no event.

Guards that every surface must meet live here: reserved `source` namespaces in
`add_task`, part-owned names and tags, `_check_deletable`, and the completion origin
gates such as `_reject_scan_required`. Some writes fire no event, because they record
internal state: the 2 sync bookkeeping setters (which also skip an unchanged save),
`set_sensor_baseline` with `silent=True`, and the derived edits of a part reconcile.

### Responsibilities

- **Tasks:** add, update, delete, trigger, snooze, due today, skip, meter baseline. A
  delete calls `_archive_task_history` to keep history on a linked appliance. The set due
  time from `async_apply_due_time` goes to each recurrence call, and a floating snooze
  rounds up to it ([recurrence](recurrence.md)).
- **History:** `complete_task` and the edit, move and delete methods for completions
  and skips. They re-anchor the schedule and meter, and draw or return part stock.
- **Appliances:** CRUD, archive, managed appliances, stock (`_emit_stock_event`), and
  documents and part files through `_mutate_asset`.
- **Task photos:** add, remove and set the cover through `_mutate_task_photos`. `_save`
  removes the photo folder of each task that it dropped ([task-photos](task-photos.md)).
- **Reconcilers:** `reconcile_part_tasks`, `reconcile_buy_tasks`, `settle_use_tasks`,
  `reconcile_problem_sensor_tasks` and `reconcile_declarative_companion_tasks` call a
  pure pass, save once, and fire the lifecycle events the pass implies.
- **Declarative specs:** add, update and delete, then dispatch
  `SIGNAL_DECLARATIVE_SPECS_CHANGED` so the companion sync runs without a reload.
- **Device repair:** `async_repoint_device_ids`, `async_repoint_asset_device_ids`,
  `async_merge_split_duplicates` and `detach_tasks_from_device`.
- **Import:** `async_import_records` writes a validated plan under stated ids with one
  save. It fires one created or updated event per record, not one per completion.

### Saves

Every mutation awaits `Store.async_save`, never `async_delay_save`. A bulk path saves once:
`delete_tasks`, each reconciler pass, `delete_orphaned_tasks`, `async_import_records`.
The `Store` write lock keeps 2 close saves in order.

### Unload, reload and concurrency

`async_unload_entry` calls `store.close`. After that, `_save` raises
`models.StoreClosedError`. A reload builds a new `HomeKeeperStore`, so a pass that still
holds the old store fails at its save and cannot write its old snapshot over the new file.

All methods run on the event loop, and the store holds no lock. Most methods change the
dicts before their first `await`, so 2 calls do not interleave inside a change. Each
save writes the full state, so a later save also carries an earlier change.

### How the coordinator learns of a change

The store does not import the coordinator. The caller of a mutation calls the
coordinator's `async_request_refresh`, or reloads the entry when the per-task entity set
changed (`coordinator.task_has_entities`, `task_entities.entity_set_key`). Reconciler
return values and the tasks that bulk deletes return tell the caller which one to do.

## Trade-offs

- **One document** over a file per section: the data is small and one write keeps the
  sections consistent. Each change costs a full write.
- **Immediate save** over `async_delay_save`: a delayed write still pending at unload
  writes old data over the reloaded file, and the return-means-durable rule breaks.
- **Load shims** over version bumps: an older file always loads, with no migrate
  function to keep for each version.
- **A closed flag that raises** over a lock or a generation check: one boolean stops
  every stale pass, and the failure is loud.
- **Caller-driven refresh** over a store that refreshes: only the caller knows if the
  entity set needs a reload. It also prevents an import cycle.

## One-way doors

- The storage key `home_keeper`, version 1, and the 6 top-level section names. A
  downgrade reads this file, so a rename or a version bump breaks older releases.
- The event payloads the store fires: see [EVENTS.md](../EVENTS.md).
