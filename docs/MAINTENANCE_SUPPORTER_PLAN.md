# Plan: detect **Maintenance Supporter** and import its tasks into Home Keeper

**Status:** Plan / design. No code yet. Target repo: `ha-home-keeper` (this repo).
Upstream: [`iluebbe/maintenance_supporter`](https://github.com/iluebbe/maintenance_supporter)
(HA domain `maintenance_supporter`, default branch `master`).

## Goal

When a user has **Maintenance Supporter** installed, Home Keeper should:

1. **Detect** it (a loaded `maintenance_supporter` config entry) and surface it in the
   panel's **Settings → Companions** section as an *importable* upstream — alongside the
   existing self-registered (push) and catalog-suggested (pull) rows.
2. **Import** its maintenance tasks into Home Keeper on demand: one click in the panel
   (and an equivalent `home_keeper.*` service) reads Maintenance Supporter's per-task
   data and creates equivalent Home Keeper tasks, attached to the same devices/areas,
   with completion history seeded.

This is a **one-shot import** (copy-in), **not** a live two-way sync glue. That
distinction is deliberate — see "Import, not sync" below.

## Why this is different from the Battery Notes / companion-catalog pattern

The existing catalog (`companions_catalog.py`) detects a popular upstream and **suggests
installing a separate *glue* integration** (e.g. `home_keeper_battery_notes`) that then
keeps the two in live sync. Maintenance Supporter is different:

- It is a **complete maintenance manager in its own right** — it already owns the task
  *configuration* (schedules, intervals, history). There is nothing to keep in sync;
  the user is **migrating** to (or consolidating in) Home Keeper.
- There is **no glue integration to install** and we don't want to write one. The action
  the user wants is **"bring my existing tasks over"**, not "install a bridge."

So we add a **third companion path — _importable_** — that reuses the Companions UI but
offers an **Import tasks** action instead of an **Install** link.

## Loose coupling: how Home Keeper reads Maintenance Supporter's data

Home Keeper must not `import` Maintenance Supporter's Python, depend on it, or reach into
its private `Store` (`.storage/maintenance_supporter.{entry_id}`). Following the same
event-bus/no-hard-dependency philosophy as `docs/INTEGRATING.md`, **we read its public
Home Assistant surface: entity states + the entity/device registries.**

Maintenance Supporter exposes **one sensor entity per task** (confirmed in its
`sensor.py`):

- `unique_id`: `maintenance_supporter_{object_slug}_{task_id}`
- `state`: status string (`ok` / `due_soon` / `overdue` / `triggered`)
- `extra_state_attributes` carry everything we need to reconstruct the schedule:
  `maintenance_type`, `schedule_type`, `interval_days`, `interval_unit`,
  `interval_anchor`, `due_date`, `warning_days`, `last_performed`, `next_due`,
  `days_until_due`, `parent_object`, `times_performed`, `total_cost`,
  `average_duration`, `notes`, `documentation_url`, and trigger-specific keys
  (`trigger_type`, `trigger_active`, …).

It also exposes **six aggregate "summary" sensors** (`overdue`, `due_soon`, `triggered`,
`needs_attention`, `ok`, `total_tasks`, unique-id-prefixed with its `GLOBAL_UNIQUE_ID`).
These must be **excluded** — only per-task sensors get imported.

**Read algorithm (HA-facing wrapper):**

1. `entity_registry.async_entries_for_config_entry()` for each loaded
   `maintenance_supporter` config entry (or filter the registry by
   `entry.platform == "maintenance_supporter"`), keep `domain == "sensor"`.
2. Drop the summary sensors (unique_id starts with the global prefix / lacks a
   `{object}_{task}` shape). Keep one per task.
3. For each task sensor, read `hass.states.get(entity_id).attributes` for the schedule
   fields and `registry_entry.device_id` for the device. Resolve `area_id` from the
   device (or the object's area). The `task_id` is parsed from the `unique_id`.

> **External-contract caveat (must re-verify against a pinned release).** The attribute
> key names, `unique_id` scheme, and summary-sensor prefix above are *Maintenance
> Supporter's* surface, not ours — assumed from reading its `master` source. Pin a known
> Maintenance Supporter version, assert these shapes in an integration test, and treat a
> shape change as a breaking upstream change (same posture as the Battery Notes plan's
> caveat). If an attribute is missing on a given task, that task is reported as
> **skipped (unmappable)** rather than guessed.

> **Alternative considered & rejected:** calling its `export.py` / legacy
> `export_maintenance_data` WebSocket handler. It produces a richer
> `{version, objects:[{tasks:[…]}]}` document, but a server-side component can't cleanly
> invoke another integration's *WebSocket* command, and there is no `export_data`
> *service* to call. States + registries are the idiomatic, stable, loosely-coupled read.

## Mapping Maintenance Supporter → Home Keeper tasks

Home Keeper already has every recurrence type we need (`const.py`):
`REC_FLOATING`, `REC_FIXED`, `REC_ONE_OFF`, `REC_TRIGGERED`, `REC_SENSOR`.

| MS `schedule_type` | → Home Keeper | Mapping notes |
|---|---|---|
| time-based (`interval_days` + `interval_unit`) | **`floating`** `interval` + `unit` | Convert MS `interval_days`/`interval_unit` to HK `interval`+`unit` (`days`/`weeks`/`months`/`years`). Seed `last_completed` from `last_performed` so the first `next_due` matches. |
| calendar recurrence (`schedule`/anchor) | **`fixed`** `freq` + `interval` + `anchor` | Map the MS recurrence to `DAILY`/`WEEKLY`/`MONTHLY` + `interval`; `anchor` from `interval_anchor` (carries time-of-day). |
| one-time (`due_date`) | **`one_off`** | Home Keeper already models a one-off due date — direct mapping, no fudge. |
| sensor/trigger-based (`trigger_config`) | **`sensor`** if it maps to HK's `usage`/`threshold` shape; else **`triggered`** | Threshold/runtime triggers → `sensor` mapping (`entity_id`, `mode`, `comparison`/`target`). Compound/counter/state-change triggers HK can't express → import as **`triggered`** (armed iff MS state is `triggered`/`overdue`) and report it as a downgrade. |
| manual | **`triggered`** (dormant) | No schedule; user arms/completes manually. |

Common fields for every imported task:

- `name` ← MS task name (optionally prefixed with the parent object, e.g.
  `"{object}: {task}"`, configurable).
- `notes` ← MS `notes` (+ `documentation_url` appended).
- `device_id` ← the MS task sensor's `device_id` (registry). `area_id` ← resolved from
  the device/object. Omit if unresolved (graceful, per INTEGRATING.md).
- `last_completed` ← MS `last_performed` (seed) so cadence continues seamlessly.
- **Completion history** ← MS `history` is **not** on the sensor attributes; v1 seeds
  only `last_completed`. (Full history import is a follow-up — see Open items.)
- `source` ← `{"maintenance_supporter": {"task_id": …, "entry_id": …}}` — opaque
  provenance and the **idempotency key**.
- `managed_by` ← **not set.** Imported tasks are fully Home-Keeper-owned and
  user-editable; that's the point of an import vs. a managed sync. (Contrast the Battery
  Notes glue, which *does* set `managed_by` because it keeps owning the task.)

### Import, not sync (explicit non-goals for v1)

- We **do not** delete, modify, or write back to Maintenance Supporter. Both lists exist
  independently after import; the user can disable/remove Maintenance Supporter at their
  leisure.
- We **do not** subscribe to Maintenance Supporter events for ongoing updates. (No live
  two-way sync.)
- **Re-running** the import is safe and **idempotent**: tasks whose
  `source.maintenance_supporter.task_id` already exists in Home Keeper are **skipped**,
  so a second run only brings over tasks added since. The service returns
  `created` / `skipped` / `unmappable` counts.

## Detection & UX (Settings → Companions)

Add a third status to the companion model: **`importable`** (next to `connected` /
`suggested`). An importable row renders with an **Import tasks** button and a count
(`N tasks ready to import`, `M already imported`). It's dismissible like a suggestion
(reuses `OPTION_DISMISSED_COMPANIONS`), and a dismissed importable never nags again but
the action stays available.

Flow: detect loaded `maintenance_supporter` entry → row appears → user clicks **Import
tasks** → confirmation dialog (counts, and a note that this copies tasks one-way) →
runs the import service → toast with `created/skipped/unmappable` results → the new tasks
appear in the task list (each firing the normal `home_keeper_task_created` event).

## Service-first (project convention)

Per `AGENTS.md` / `.amazonq/rules/` — **every data action ships as a `home_keeper.*`
service first**, and the panel's websocket command merely delegates to it.

- **Service** `home_keeper.import_maintenance_supporter` (with `services.yaml` entry and
  `strings.json` localization parity). Options: `entry_id` (optional — default all loaded
  MS entries), `name_prefix_object` (bool), `dry_run` (bool — report what *would* import
  without creating). `return_response=True` yields `{created, skipped, unmappable,
  details: [...]}`.
- **Websocket** `home_keeper/import_maintenance_supporter` for the panel button →
  delegates to the same store/import method. (Never a substitute for the service.)

## Architecture (keep the pure core pure)

- New module **`importers/maintenance_supporter.py`** split into:
  - a **pure** mapper `map_ms_task(attrs, *, device_id, area_id, …) -> add_task payload | None`
    (no HA imports) — unit-testable in isolation like `recurrence.py`/`models.py`;
  - a thin **HA-facing** reader that walks the registry/states and calls the store.
- A small **`importers/__init__.py` registry** so future importers (other maintenance
  managers) plug in the same way, and the Companions catalog can list them generically.

## File-by-file (guidance; verify symbols on edit)

| File | Change |
|---|---|
| `const.py` | `STATUS_IMPORTABLE = "importable"`; `EVENT_COMPANION_IMPORTABLE` (optional, see Events); a `maintenance_supporter` domain const. |
| `companions_catalog.py` | Add an **importer** entry type (`upstream_domain`, `import_action`, copy/icon/install-not-applicable) and a `_importable_from_catalog()` row builder; extend `build_companion_list()` to emit `importable` rows when the upstream is installed and there's no glue to install. |
| `companions.py` | Detect importable upstreams in `reconcile()`; (optionally) edge-fire `home_keeper_companion_importable`. Reads stay pure/event-free. |
| `importers/maintenance_supporter.py` *(new)* | Pure mapper + HA-facing reader (registry/states → `add_task` payloads), with the summary-sensor exclusion and per-`schedule_type` mapping table above. |
| `importers/__init__.py` *(new)* | Importer registry (name, upstream domain, reader callable). |
| `store.py` | `import_tasks(payloads)` path that dedupes by `source.maintenance_supporter.task_id` (reuse the existing `source`-match logic), calls `add_task` per new task, returns counts. |
| `__init__.py` + `services.yaml` + `strings.json` | `import_maintenance_supporter` service (light path: no entry reload beyond the normal task-create refresh) + localized strings + `exceptions` parity for unmappable/no-entry errors. |
| `websocket_api.py` | `home_keeper/import_maintenance_supporter` command delegating to the store method (mirrors `ws_get_companions`); `get_companions` already returns the new `importable` rows for free. |
| `events.py` / `docs/EVENTS.md` | If we add `home_keeper_companion_importable`, build it with the pure builder and document it. (Imported tasks already fire `home_keeper_task_created`, so no per-task event work.) |
| `frontend/src/panel.ts`, `types.ts`, `utils.ts` | Render the `importable` companion row + **Import tasks** button + confirmation dialog (counts, one-way note) + result toast. Add the status to the companion type. |
| `tests/unit` | Pure mapper tests: one per `schedule_type` (floating/fixed/one_off/sensor/triggered/manual), `last_performed` seeding, summary-sensor exclusion, unmappable downgrade, idempotent dedupe. |
| `tests/integration` | Docker: mount **both** custom_components (home_keeper + a pinned maintenance_supporter), seed a couple of MS tasks (via its config flow or a fixture entry), call `home_keeper.import_maintenance_supporter`, assert HK `list_tasks` reflects the mapping + dedupe on re-run. This is the contract test that guards the external-contract caveat. |
| `tests/e2e` + `docs/images/` | **UI gate:** Playwright capture of the Companions section showing the importable row and the import dialog/result. Add a capture step to `screenshots.capture.ts`. |
| `README.md` | New feature section (use case: migrate/consolidate Maintenance Supporter tasks; how to use) **with screenshot(s)** — same capture, committed under `docs/images/`, relative path. |
| `CHANGELOG.md` | User-facing entry (Added: detect Maintenance Supporter and import its tasks). |
| `.amazonq/rules/` | Record the new **importable** companion path / importer-registry convention so it's picked up automatically. |

## Hard gates (from AGENTS.md) this work must satisfy

- **UI screenshots are mandatory** — the Companions change touches
  `frontend/src/`, so the PR body MUST embed current Playwright screenshots
  (committed under `docs/images/`, HTML `<img>` with a SHA-pinned
  `raw.githubusercontent.com` URL). Not reviewable/mergeable without them.
- **Service-first + localization parity** (`services.yaml` + `strings.json`).
- **README documents the new feature** in the same change, with a screenshot.
- **Run tests locally before pushing**; request an **Amazon Q (`/q review …`)** pass
  after pushing, tuned for correctness (schedule-mapping edge cases, DST/timezone in
  anchors, idempotency) and HA best practices.

## Open items / decisions to confirm

1. **Completion-history import.** Sensor attributes expose `last_performed` and
   `times_performed` but not the full `history` list. v1 seeds `last_completed` only.
   Importing full history would require a richer read (its export document) — defer.
2. **Sensor/trigger fidelity.** Which MS `trigger_type`s map cleanly to HK's `sensor`
   `usage`/`threshold` modes vs. fall back to `triggered`. Enumerate against the pinned
   release and decide the downgrade reporting wording.
3. **Object → device identity.** Confirm every MS task sensor has a `device_id` in the
   registry (objects appear to be HA devices). If some don't, those import device-less.
4. **Pin the Maintenance Supporter version** for the contract test and document it.
5. **Re-import semantics** beyond dedupe: should a changed MS schedule update the existing
   HK task, or stay one-shot (create-only)? v1 is create-only (skip existing); a future
   `update_existing` flag could reconcile. Confirm desired default.
6. Whether to fire a dedicated `home_keeper_companion_importable` event or reuse the
   suggested-row treatment (no event).

## Sequencing

1. Pure mapper + unit tests (`importers/maintenance_supporter.py`) — no HA needed.
2. Service + websocket + store import path + integration (docker) contract test.
3. Detection in the Companions catalog (`importable` status).
4. Panel UI (row + dialog + toast) → e2e screenshots → README/CHANGELOG/docs → Q review.
