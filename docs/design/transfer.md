---
title: Import and export
summary: Writes the tasks and appliances as one portable YAML document and reads that document back.
implements:
  - custom_components/home_keeper/transfer.py
  - custom_components/home_keeper/transfer_runner.py
related: [store, appliances, completions, recurrence, documents-photos, events-api]
source_hash: 3804045eb4d5
---

# Import and export

The `export_data` and `import_data` services and their websocket twins move tasks and
appliances between installs, spreadsheets and scripts. `transfer.py` is pure: it builds the
document, reads YAML and plans an import with an injected clock. `transfer_runner.py` uses Home
Assistant: registries, device provisioning, executor jobs and the reload. Both are admin-only.

## Goals

- **G1. Symmetry.** An export is a valid import, so 1 exported file is a full example of the
  format for a person or an AI assistant that writes more records.
- **G2. Record equals service payload.** A `tasks` record is an `add_task` payload plus a few
  document-only keys. An `appliances` record is an `add_asset` payload.
- **G3. New fields travel by default.** A new model field travels with no edit here.
- **G4. All or none.** The import checks the whole document first. 1 error writes no record.
- **G5. Exact restore, safe re-run.** A restore keeps the record ids, so entities and
  automations stay valid. A second run of 1 file updates records and makes no copies.

## Non-goals

- Uploaded files. A text document has no room for a binary, so the export counts them.
- Declarative companions, profiles, notifications and options (`EXCLUDED_STORE_KEYS`).
- Records an integration owns. The owner makes them again on the other install.

## Design

### The document

The first line is a `yaml-language-server` comment that names `TRANSFER_SCHEMA_URL`. The
`home_keeper` block holds `format`, `version`, `exported_at` and `skipped`. `transfer.SECTIONS`
names the sections, `appliances` and `tasks`, in the order the import applies them.
`TRANSFER_FORMAT` changes only when the meaning of a key changes; a new key or section is
additive. A higher format, or a format that is not an integer, is an error. The JSON Schema
comes from the service schemas through `ci/generate_schema.py`, and its filename holds the
format number. `transfer._yaml_dialect` builds the dumper (block style, no anchors) and a
loader that keeps the scalars equal to JSON. The loader refuses an alias, which stops an
expansion attack before records exist to count. It reads a bare date as text and has no
constructor for `!!binary`, `!!set` or other types the store file cannot hold. It keeps the
YAML 1.1 booleans, as Home Assistant YAML does. A JSON file is also YAML, so it reads too.
`transfer.parse_document` refuses text over `MAX_IMPORT_BYTES` before it parses. A section
over `MAX_IMPORT_RECORDS` is an error. The panel has the lower `MAX_IMPORT_WS_BYTES` limit.

### Export

`transfer.build_document` exports every stored key that `EXCLUDED_TASK_KEYS`,
`EXCLUDED_ASSET_KEYS` or `EXCLUDED_PART_KEYS` does not name. Each entry is a key and a reason.
`transfer._strip` also drops empty values. Then the exporter adds the document-only keys:
- `id` in its own slot, `area` as the area name, and `archived: true`.
- `appliance` on a task: the `external_id`, else the name, else the appliance id. A shared
  name is not used. A device id is never used, because it is different on each install.
- `history` and `skips`, with `ts` as `completed_at` and `skipped_at`. A `photo` is URL text.
- On an appliance: its `device_id`, link documents only, and each part through `_strip`.
  `carried_uses` is the 1 computed value: `reconcile.counted_uses` states the use count on
  the part, because the derived tasks that hold it do not travel.

`transfer.is_portable_task` and `transfer.is_portable_asset` keep out records with
`managed_by`, appliances with a `source`, and tasks in a reserved reconciler namespace. A
consumable link that the user made is the exception: the task travels and the link stays.
Other `source` namespaces travel, so an integration finds its tasks after a restore.
`home_keeper.skipped` counts the uploaded files in `file_documents` and `task_photos`, and
the `consumable_links`. `transfer_runner.async_export_document` builds the document on the
loop and writes the YAML in the executor, on a deep copy that shares no value with the store.

### Planning an import

`transfer.plan_import` takes the text or the parsed document, copies of the store, the area
names, the device ids and a match mode (`auto` or `none`). It returns an `ImportPlan` of
`PlannedRecord` and `Problem` rows. A problem has a section, an index, a path such as
`tasks[3].history[0].completed_at`, a message and a severity. An `error` blocks the import. A
`warning` is reported and applied. An unknown key or section is a warning, so an older release
reads a newer file and names the data it drops. `transfer._known_task_keys` gets the known
keys from 1 probe task per recurrence type. Appliances are planned first. For each record:
1. `transfer._keyed_records` refuses a key field that is a list or a mapping, and an `id`
   that 2 records state.
2. `transfer._Matcher` matches by `id`, then `external_id`, then name through
   `resolve.match_by_name`. A stated id with no stored record is a create, never a name match.
   2 hits are an error. A stored record that an earlier row claimed is not matched again.
3. An update gives the full merged record (`models.merge_update`, `assets.merge_update`). A
   create gives a built record (`models.build_task`, `assets.build_asset`).
4. `transfer.apply_history` folds `history` and `skips` onto the record (below).
5. `transfer._colliding_external_ids` refuses an `external_id` that 2 records use, unless
   each states a uuid `id`. `transfer._looping_parents` refuses a loop in the new tree.

### References and ids

- **Area.** A stated `area_id` that exists here wins, then `area` by name without case. An
  unknown name stays as text, with a warning.
- **Appliance of a task.** A stated `device_id` that exists here wins. Else `appliance`
  resolves in the document first, then in the store. A planned appliance has no device yet,
  so the task gets a `hk-planned-asset:` placeholder (`transfer.planned_asset_id`).
- **Parent appliance.** `parent_asset_id` resolves the same way, to an asset id. Parent first.
- **Ids.** `transfer._claim_id` keeps a stated id if it is a free uuid, else makes a new uuid.

**History.** `transfer.apply_history` sorts entries by date and replays each completion through
`recurrence.apply_completion`. `recurrence.record_skip` logs a skip and keeps the due date. A
fixed task gets `next_due` from its anchor after the replay, or each entry moves it 1
occurrence on. `transfer._merge_log` merges by `ts` with the stored log and keeps the newest
`MAX_COMPLETION_HISTORY`. A stored task done on or after the last date in the file keeps its
`last_completed` and `next_due`. The replay fires no completion events.

### Applying

`transfer_runner.async_import_document` parses text in the executor and plans on the loop. A
dry run, or a plan with an error, returns the report. Else it:
1. writes the appliances with `store.async_import_records`, then runs
   `devices.async_reconcile_assets` once to give each virtual appliance its device;
2. plans the tasks again with `transfer.replan_tasks` against the store after those saves, so
   a task change in that time is kept; on a new error it keeps the first plan;
3. swaps each placeholder for the device id, or imports the task alone with a warning;
4. writes the tasks, runs the part and buy reconcilers, and reloads the entry once.

`store.async_import_records` saves 1 time per batch and fires 1 created or updated event per
record. `ImportPlan.as_report` gives `ok`, `dry_run`, `counts`, `records` and `problems`.

### The guards

`tests/unit/test_transfer_roundtrip.py` sends a maximal record of each kind through YAML
text onto an empty store and names each key that did not come back. `test_transfer_coverage.py`
fails on a `store._save` key in neither `SECTIONS` nor `EXCLUDED_STORE_KEYS`, an exclusion with
no reason, a service field the import drops, part-schema drift, and a null in an export.

## Trade-offs

- **Excluded-key tables** over **an exported-key list**: a list goes stale as the model grows.
- **Validate all, then write** over **a write per record**: a bad file writes no record. A
  device that fails after the appliances are written gives a warning, not a rollback.
- **Keep a stated uuid** over **new ids**: entities and automations survive a restore.
- **Name match, error on 2 hits** over **id-only match**: hand-written files update by name.
- **Plan on the loop** over **a store snapshot in the executor**: no copy step, but a very
  large document holds the event loop while it plans.

## One-way doors

- The envelope keys `format`, `version`, `exported_at`, `skipped` and its 3 counts.
- The sections `appliances` and `tasks`, the keys `external_id`, `appliance`, `area`,
  `archived`, `carried_uses`, `history[].completed_at` and `skips[].skipped_at`.
- The schema URL, the service fields `include`, `document`, `dry_run` and `match`, the report
  shape, and the problem `path` grammar that scripts read to fix a file.
