---
title: Import and export
summary: Writes the tasks, appliances and companion data as 1 document or bundle, and reads it.
implements:
  - custom_components/home_keeper/transfer.py
  - custom_components/home_keeper/transfer_bundle.py
  - custom_components/home_keeper/transfer_runner.py
  - custom_components/home_keeper/transfer_http.py
  - custom_components/home_keeper/frontend/src/transfer-view.ts
related: [store, appliances, completions, recurrence, documents-photos, events-api]
source_hash: fedce1f71f68
---

# Import and export

The `export_data` and `import_data` services and their websocket twins move tasks, appliances
and companion data between installs and scripts. A bundle (a zip file) adds the uploaded files
and the settings. `transfer.py` and `transfer_bundle.py` are pure. `transfer_runner.py` uses
Home Assistant, and `transfer_http.py` has the HTTP views. All are admin-only.

## Goals

- **G1. Symmetry.** An export is a valid import, so 1 exported file is a full example of the
  format for a person or an AI assistant that writes more records.
- **G2. Record equals service payload.** A `tasks` record is an `add_task` payload plus a few
  document-only keys. An `appliances` record is an `add_asset` payload.
- **G3. New fields travel by default.** A new model field travels with no edit here.
- **G4. All or none.** The import checks the whole document first, companion sections
  included. 1 error writes no record.
- **G5. Exact restore, safe re-run.** A restore keeps the record ids, so entities and
  automations stay valid. A second run of 1 file updates records and makes no copies.
- **G6. 1 file for the whole home.** A companion's data and the uploaded files travel with
  Home Keeper's, so a user does 1 export and 1 import.

## Non-goals

- Declarative companions (`EXCLUDED_STORE_KEYS`) and the settings in a YAML export that does
  not ask for them.
- Records an integration owns. The owner makes them again on the other install.
- Deletes. An import is an upsert, and a record that is not in the file stays.

## Design

### The document

The first line is a `yaml-language-server` comment that names `TRANSFER_SCHEMA_URL`. The
`home_keeper` block holds `format`, `version`, `exported_at` and `skipped`. `transfer.SECTIONS`
names `appliances` and `tasks`, in the order the import applies them. `TRANSFER_FORMAT`
changes only when the meaning of a key changes; a new key or section is additive. A higher
format, or one that is not an integer, is an error. `ci/generate_schema.py` makes the JSON
Schema. `transfer._yaml_dialect` keeps the scalars equal to JSON: no alias, a bare date is
text, no `!!binary` or `!!set`. `transfer.parse_document` refuses text over `MAX_IMPORT_BYTES`,
and a section over `MAX_IMPORT_RECORDS` is an error. The websocket has `MAX_IMPORT_WS_BYTES`.

Other top-level keys (`transfer.RESERVED_SECTIONS`):
- `<domain>`: the section of a companion with the `import_export` capability, exactly as its
  `<domain>.export_data` returned it: `{format, version, data, skipped}` (INTEGRATING.md §11).
- `profiles`, `notifications` and `options` (`transfer.SETTINGS_SECTIONS`), from
  `transfer_bundle.settings_sections`. A bundle writes them, a YAML export only on request.
- `files`: a bundle's list of `{kind, appliance|task, id|part, name, path}` entries.

### Export

`transfer.build_document` exports every stored key that `EXCLUDED_TASK_KEYS`,
`EXCLUDED_ASSET_KEYS` or `EXCLUDED_PART_KEYS` does not name, each with a reason, and
`transfer._strip` drops empty values. It adds the document-only keys: `id`, `area` as the area
name, `archived: true`, a task's `appliance` (the `external_id`, else an unshared name, else
the id, never a device id), `history` and `skips`, an appliance's `device_id`, its link
documents and each part. `carried_uses` states a counted wear item's use count
(`reconcile.counted_uses`). `transfer.is_portable_task` and `transfer.is_portable_asset`
keep out records with `managed_by`, appliances with a `source`, and tasks in a reserved
reconciler namespace, except a user's consumable link. `skipped` counts what does not travel.

`transfer.resolve_include` splits `include` into sections, companion domains and `settings`,
and an unknown name raises `unknown_export_section`. The runner calls each ready companion's
`export_data` with the caller's `Context` and a `COMPANION_TRANSFER_TIMEOUT_S` limit.
`skipped.companions` names each other companion: `no_import_export`, `no_service` or `failed`.

### Bundles

`transfer_runner.async_export_bundle` makes a run folder below `IMPORT_EXPORT_SUBDIR`, gives
each companion a `files_dir` in it, and writes `home_keeper.yaml`, the Home Keeper files
(`transfer_bundle.bundled_files`, under `files/home_keeper/`) and `files/<domain>/` into the
zip. A missing file is counted in `skipped.missing_files`, and a companion symlink is
skipped. The service writes `EXPORTS_SUBDIR/home-keeper-<date>.zip` and returns its path.
`transfer_http.HomeKeeperBundleExportView` streams it. A `finally` deletes the run folder.

`transfer_bundle.safe_extract` refuses the whole zip for an absolute name, a `..` part, a symlink,
an encrypted entry or more than `MAX_BUNDLE_ENTRIES` entries, before it writes. It counts the real
bytes it writes and stops above `MAX_BUNDLE_BYTES`. A zip that `zipfile` cannot read is a
`BundleError`. `import_data` takes a bundle by its file name in `EXPORTS_SUBDIR`.
`HomeKeeperImportUploadView` streams an upload to the run folder and stops with a 413 at once when a
zip passes `MAX_BUNDLE_BYTES`, another file `MAX_IMPORT_BYTES`, or a text field
`MAX_UPLOAD_FIELD_BYTES`. It reads only the fields in `_UPLOAD_FIELDS`. The panel uploads a zip
or a YAML file over `MAX_IMPORT_WS_BYTES` (`transfer-view.fileRoute`), refuses a binary file
(`transfer-view.decodeText`) and exports the checked rows (`transfer-view.exportInclude`).

### Planning an import

`transfer.split_document` sorts the keys. A section that no ready companion reads is a
warning. `transfer.plan_import` takes the Home Keeper part, store copies, area names, device
ids and a match mode (`auto` or `none`). It returns an `ImportPlan` of `PlannedRecord` and
`Problem` rows. A problem has a section, an index, a path (`tasks[3].history[0].completed_at`),
a message and a severity: an `error` blocks, a `warning` is applied. Appliances come first:
1. `transfer._keyed_records` refuses a list or a mapping as a key, and an `id` stated twice.
2. `transfer._Matcher` matches by `id`, then `external_id`, then name. 2 hits are an error.
3. An update merges (`models.merge_update`, `assets.merge_update`); a create builds.
4. `transfer.apply_history` folds `history` and `skips` onto the record.
5. `transfer._colliding_external_ids` and `transfer._looping_parents` refuse clashes and loops.

A stated `area_id` or `device_id` that exists wins, else the name. A task's `appliance` resolves in
the document, then in the store; a planned one gets a `hk-planned-asset:` placeholder.
`transfer._claim_id` keeps a free uuid. History replays through `recurrence.apply_completion`.

The settings plan (`transfer_bundle.plan_settings`) runs only with `include_settings`. It upserts
profiles and notifications by id, then name, and a notification follows its profile's kept id. It
warns on a target, a to-do list or a profile filter id (`transfer_bundle.RegistryIds`) that this
install lacks, and leaves out a target off the allowlist and a refused value.
`transfer_bundle.plan_files` maps each file to its record and skips a file that the record has.
`transfer_runner` checks each file's type and size, then dry-runs each `<domain>.import_data`.

### Applying

`transfer.merge_reports` adds each companion report under `sections`, and its problems with
the prefix `<domain>.`. A dry run or an error returns the report. Else the runner:
1. writes the appliances, runs `devices.async_reconcile_assets`, plans the tasks again
   (`transfer.replan_tasks`), swaps each placeholder for the device id, and writes the tasks;
2. plans the files again with the written ids, copies each into place and saves it through
   the store, then runs the part and buy reconcilers and reloads the entry once;
3. applies the settings with `options.async_set_options`;
4. calls each companion's `import_data` for real, in registration order.

A failure after step 1 is a warning or a companion error, never a rollback, with `partial: true`.
The store fires 1 event per record, and the runner `home_keeper_data_exported` and `_imported`.

## Trade-offs

- **Excluded-key tables** over **an exported-key list**: a list goes stale as the model grows.
- **Validate all, then write** over **a write per record**: a bad file writes no record.
- **Keep a stated uuid** over **new ids**: entities and automations survive a restore.
- **Companion sections as is** over **a Home Keeper schema**: each companion owns its format.

## One-way doors

- The envelope keys `format`, `version`, `exported_at`, `skipped`, its counts and
  `skipped.companions`, and the sections `appliances`, `tasks`, `<domain>`, `profiles`,
  `notifications`, `options` and `files`, with the record keys above.
- The schema URL, the fields `include`, `kind`, `document`, `bundle`, `dry_run`, `match`,
  `include_settings`, the report shape with `sections` and `partial`, and the problem paths.
- The bundle layout, the 2 HTTP views, the 2 events and the companion contract (§11).
