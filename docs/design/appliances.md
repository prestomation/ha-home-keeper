---
title: Appliances and parts
summary: Appliance records, their devices, and the parts, spares and wear tasks they own.
implements:
  - custom_components/home_keeper/assets.py
  - custom_components/home_keeper/devices.py
  - custom_components/home_keeper/device_compat.py
  - custom_components/home_keeper/reconcile.py
  - custom_components/home_keeper/appliance_report.py
  - custom_components/home_keeper/frontend/src/panel-asset-editors.ts
  - custom_components/home_keeper/frontend/src/panel-asset-form.ts
related: [store, coordinator-entities, completions, documents-photos, transfer, events-api]
source_hash: b7cd2fb3d0e8
---

# Appliances and parts

An appliance ("asset" in code) is a JSON record about a physical thing: make, model, cost,
documents, metadata and parts. It owns a virtual device or points at a device of another
integration. Wear parts generate maintenance tasks, and the part counts the spare stock.

## Goals

- **G1. Metadata without a device.** An appliance keeps its data with or without a device.
- **G2. One device page per thing.** Tasks, part entities and tracked dates meet on one
  device page. Home Keeper never edits a device that it does not own.
- **G3. Survive registry churn.** A re-created or split device does not strand an appliance.
- **G4. Parts drive tasks.** Only the reconciler creates, updates and deletes wear tasks.
- **G5. Count uses with no counter.** A use count comes from a completion log.
- **G6. Stock is the household's.** No owner, sync or edit path deletes a spare count.

## Non-goals

- Linking task entities to a device (`coordinator-entities`), file storage
  (`documents-photos`), backup (`transfer`), completions (`completions`), events
  (`events-api`).

## Design

### The record

`assets.build_asset` and `assets.merge_update` validate through `assets.normalize_fields`
and raise `AssetValidationError`. `assets.py` has no Home Assistant imports.

- `kind` is `virtual` (Home Keeper owns a device) or `existing` (metadata on another
  device). `kind` and the virtual identifier never change.
- `manufacturer`, `model`, `serial_number` are first-class; `notes` is Markdown; `cost`
  feeds the report. `metadata` is a list of `{id, type, label, value}` (`text`, `link`,
  `date`). A `date` entry with `track: true` becomes a `date` sensor.
- `parent_asset_id` (virtual only) nests a device through `via_device`, and
  `assets.would_create_cycle` rejects a loop. `related_device_ids` is panel-only.
- `managed_by` and `source` are create-only. An update with `managed_by: null` hands the
  appliance back to the user. `task_history` keeps completions of deleted tasks.
- `assets.card_projection` is the allowlist of fields a non-admin dashboard card reads.

### Virtual and existing devices

`devices.async_reconcile_assets` runs at setup and after each change, parents first.

- **Virtual.** `devices._reconcile_virtual` registers `(home_keeper, asset_<id>)`, apart
  from task devices keyed on the bare task id. It syncs name, make, model, parent and a
  `configuration_url` to the appliance page, and writes the device id back. The serial
  number stays off the device, because any signed-in user can list devices.
- **Existing.** `devices._reconcile_existing` refreshes an `identifiers`/`connections`
  snapshot. If the id is gone, `devices._resolve_by_snapshot` finds the device that the
  owner made again, and `store.async_repoint_device_ids` moves the tasks.
- **Prune.** An `asset_` device with no appliance is removed. A delete removes the virtual
  device, detaches its tasks, drops derived and buy tasks, and unlinks manual links.

### The per-entry device split

Home Assistant 2026.8 made device identifiers unique per config entry, so a copied foreign
identifier forks a nameless device. The chosen model links entities to a foreign device
through the entity's `device_entry`, and owns a device only for a virtual appliance.
2 setup steps repair data from the merge model:

- `devices.async_detach_legacy_merged_devices` removes our entry from a foreign device that
  has another entry, so the split has nothing of ours to divide.
- `devices.async_heal_split_device_ids` maps each stale id to a live device. A stale id
  still resolves to a composite, so `devices._split_successor` takes its split that is not
  ours, or an appliance snapshot match. Tasks, appliances and options share 1 mapping.
  `store.async_merge_split_duplicates` merges contributor tasks that the split duplicated.

`device_compat.py` holds every registry read and each call whose shape changed between
releases, such as `device_compat.resolve_device` and `device_compat.find_devices`. A child
device is a valid target. Its imports are `TYPE_CHECKING`-only, so tests use plain fakes.

### Parts and spares

A part is `consumable` or `wear` (`assets._normalize_part`). Stock is decimal;
`assets._round_stock` keeps a whole value an `int`. `assets.consume_part_stock` and
`assets.adjust_part_stock` return a transition (`low`, `out`, `restocked`) for the store to
fire. `reconcile.reconcile_buy_tasks` keeps a "Buy" task while an opted-in part is low.

`assets.PART_USER_KEYS` (stock) and `assets.PART_OWNER_KEYS` split every part key. On a
managed appliance the user edits only stock. The owner writes the rest through
`assets.apply_managed_parts`, and a part it drops stays if the part tracks stock.

### Wear tasks and counted wear

`reconcile.reconcile_part_tasks` is pure. It keys tasks by `(asset_id, part_id, role)` from
`source.part`, deletes orphans, and writes the rest with localized names from the store. A
`manual: true` link (`reconcile.is_manual_part_link`) is outside its scope.

- **Time wear:** 1 `floating` task anchored to `last_replaced`. A completion stamps
  `last_replaced` and consumes stock (`store._stamp_part_replacement`).
- **Counted wear** (`replace_unit: "uses"`, `assets.part_counts_uses`): a `use` task whose
  `next_due` is always `None`, and a dormant `triggered` replacement task. A use completion
  records only a completion (`reconcile.is_use_task` gates the stamp).

`reconcile.uses_since_replacement` counts use completions after `reconcile.cycle_start`,
the last completion or skip of the replacement task. `reconcile.counted_uses` adds an
imported `carried_uses` until the first cycle starts. `reconcile.settle_use_tasks` picks
replacement tasks at the target or past the `replace_also_every` backstop, and
`store.settle_use_tasks` arms them. `reconcile.trim_use_completions` keeps
`assets.use_retention_cap` entries and never trims the live count.

### Appliance report and panel

`appliance_report.build_report` gives 1 row per appliance plus totals: cost, spares value
(unit cost times stock) and a grand total. `appliance_report.report_to_csv` localizes the
headers and escapes formula-like cells. The `export_appliance_report` service is admin-only.

`panel-asset-form.ts` renders the drawer, fills empty make, model and serial from a picked
device, and hides locked fields. The editors in `panel-asset-editors.ts` change
`_assetEdit.asset` in place for the save to read. A wear part previews the tasks it makes.

## Trade-offs

- **Entity linking on a foreign device** over **always owning a device**: our entities stay
  on the real device page with no duplicate. Device triggers and per-device diagnostics come
  from config entries, so a linked foreign device offers neither. Virtual devices keep both.
- **Count from the completion log** over **a stored counter**: no reset path can drift, and
  each use keeps its note and photo. The cost is a retention rule and a target cap
  (`MAX_USE_TARGET`, 250), so the 500-entry completion cap never cuts the live count.
- **2 tasks per counted part** over **1**: a use and a renewal are different events, and
  the replacement task keeps the renewal history.
- **Task names in the instance language** over **per-viewer names**: one stored name.

## One-way doors

- Appliance: `kind`, `(home_keeper, asset_<id>)`, `metadata`, `parts`, `managed_by`,
  `source`, `task_history`.
- Part: `type`, `replace_interval`, `replace_unit` (with `uses`), `replace_also_every`,
  `action`, `use_noun`, `use_task_name`, `carried_uses`, the stock fields.
- Task: `recurrence_type: "use"`, `source.part` with `role` (absent is `replace`) and
  `manual`, and `source.buy`. The `export_appliance_report` response keys.
