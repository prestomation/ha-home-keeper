---
title: Architecture
summary: How Home Keeper splits into a pure core and Home Assistant glue, and how it sets up.
implements:
  - custom_components/home_keeper/__init__.py
  - custom_components/home_keeper/const.py
  - custom_components/home_keeper/panel.py
  - custom_components/home_keeper/config_flow.py
  - custom_components/home_keeper/options.py
  - custom_components/home_keeper/diagnostics.py
  - custom_components/home_keeper/manifest.json
related: [recurrence, store, coordinator-entities, events-api, frontend, companions-presets]
source_hash: 2288aab94721
---

# Architecture

Home Keeper is a Home Assistant integration that tracks home maintenance and chores.
Administrators manage tasks and appliances in a sidebar panel. All household members use
the tasks through native entities, such as the to-do list and the calendar.

## Goals

- **G1. Testable core.** The rules for schedules, tasks, assets and options run without
  Home Assistant, so the fast unit tier and the mutation gate can check them.
- **G2. Native usage.** Daily use goes through native entities. The panel is for
  administration only.
- **G3. One privilege line.** Administration is admin-only on every path. Usage is open.
- **G4. Services first.** Each data action is a `home_keeper.*` service, so automations,
  scripts, voice and other integrations can do what the panel does.
- **G5. Safe reloads.** A reload keeps services, the panel and saved options intact.

## Non-goals

- Administration in the dashboard card. The card is a usage surface ([frontend](frontend.md)).
- More than 1 config entry. `config_flow.HomeKeeperConfigFlow` sets a fixed unique id.
- Settings for a companion integration ([companions-presets](companions-presets.md)).

## Design

### Module map

| Layer | Modules | Rule |
|---|---|---|
| Pure core | `recurrence.py`, `models.py`, `assets.py`, `events.py`, `transitions.py`, `profiles.py`, `notifications.py`, `transfer.py`, `reconcile.py`, `sensor_tasks.py`, `problem_tasks.py`, `shopping.py`, `todo_items.py`, `task_photos.py`, `const.py`, the catalogs | No `homeassistant` import. Time and zone come in as arguments. |
| Boundary | `options.py`, `coordinator.py`, `device_compat.py`, `notifier.py`, `card.py`, `sensor_watcher.py`, `tag_listener.py`, `photo_thumbs.py` | Home Assistant imports only under `TYPE_CHECKING`. |
| Glue | `__init__.py`, `store.py`, `devices.py`, `websocket_api.py`, `panel.py`, `config_flow.py`, `diagnostics.py`, `manuals.py`, `companions.py`, the sync modules | Talks to Home Assistant and calls into the core. |
| Platforms | `todo.py`, `calendar.py`, `button.py`, `sensor.py`, `binary_sensor.py`, `number.py` | `const.PLATFORMS` lists them. |

The mutation allowlist (`only_mutate` in `pyproject.toml`) is drawn from the first 2 rows.
`api_surface.py` declares each surface that an integrator sees ([events-api](events-api.md)).

### Administration, usage and privilege

`panel.async_register_panel` registers a `custom` panel at `/home-keeper` with
`require_admin=True`. It serves only `frontend/dist/`, because Home Assistant serves
static paths before authentication. `panel.cache_token` hashes the bundle into its URL.
A non-admin uses tasks from the to-do list, the calendar, the per-task entities and the
card ([SECURITY.md](../SECURITY.md)).

A websocket command and its service twin are the same operation. An admin-only operation
has `@websocket_api.require_admin` on the command, and its service handler calls the
local `_verify_admin`, which raises the bare `Unauthorized`. A call with no
`context.user_id` comes from an automation or from the core and is trusted.
The gate covers appliance edits, asset documents, part files and stock, declarative
companion edits, the orphan and archive deletes, `set_options`, the appliance report,
and data export and import. Other task writes, task photos included, are open. Appliance reads
are open, but a non-admin gets `assets.card_projection`, the fields that the card shows.

### Setup

`async_setup` calls `_register_services` 1 time for each Home Assistant run, so services
stay through reloads. A handler raises `integration_not_loaded` when no entry is loaded.
Each websocket command calls the same store method as its service twin.
`async_setup_entry` then runs these steps in order:

1. Load the backend strings in the executor. Load `HomeKeeperStore` and repair split
   device ids (`devices.async_heal_split_device_ids`).
2. Create `HomeKeeperCoordinator`, refresh it, and store it as `entry.runtime_data`.
3. Reconcile asset devices, part tasks, buy tasks, problem sensors and declarative
   companions, so the tasks exist before the platforms read them.
4. Register the panel, the card, the file HTTP views and the websocket commands, and remove
   stale task photo folders. Forward `const.PLATFORMS` and prune devices with no entities.
5. Ask companions to register again. Add the options and language listeners, which reload.
6. Start the sensor watcher. Start the list syncs when the Home Assistant start is done.
7. Enable transition events, start the 5-minute clock, refresh 1 more time, and set the
   companion registry live after start.

A failure in the repair or the prune is logged and does not stop setup.

### Unload and remove

`async_unload_entry` unloads the platforms and discards edge state for a disabled entry. It
closes the store so that a pass from before the unload cannot write over a new store.
It removes the panel only for a disabled entry, because a reload with no panel sends an
open page to the default dashboard. `async_remove_entry` removes the panel, the card
resource, the storage document and the uploaded files.

### Config entry and options

The config flow is 1 confirmation step with no data. `options.py` defines every option key
and default (`options.ALL_OPTIONS`). The options flow, the `set_options` service and the
panel Settings tab edit them.

- The service and the panel send a partial update to `options.async_set_options`. It
  merges, refuses a save that strands a notification (`options.ProfileInUseError`),
  writes, and waits for the reload. A flag stops the update listener from a 2nd reload.
- Home Assistant stores an options flow result as the whole options object. The form
  shows only `options.FLOW_OPTIONS`, so the flow returns `options.merge_flow_input`: a
  cleared form key resets, and a key outside the form keeps its value.

### Diagnostics

`diagnostics.py` dumps the tasks and assets for the entry or for 1 device. It removes the
keys in `diagnostics.TO_REDACT`, because users attach dumps to public issues.

### Design doc index

| Doc | Subject |
|---|---|
| [recurrence](recurrence.md) | Recurrence types and the next-due calculation |
| [store](store.md) | The storage document and the mutation chokepoint |
| [coordinator-entities](coordinator-entities.md) | The coordinator, the platforms and device links |
| [appliances](appliances.md) | Assets, virtual devices, parts and stock |
| [completions](completions.md) | Completion, skip and snooze records |
| [documents-photos](documents-photos.md) | Appliance documents, completion photos and signed URLs |
| [task-photos](task-photos.md) | Photos on a task, thumbnails and the cover |
| [sensor-tasks](sensor-tasks.md) | Tasks driven by sensors, meters and problem sensors |
| [companions-presets](companions-presets.md) | Companion discovery and declarative presets |
| [profiles-notifications](profiles-notifications.md) | Profiles and notifications |
| [sync](sync.md) | Shopping-list and to-do list syncs |
| [events-api](events-api.md) | Events, device triggers and the API surface model |
| [transfer](transfer.md) | Import and export |
| [frontend](frontend.md) | The panel and the dashboard card |

## Trade-offs

- **A sidebar panel** over **a dashboard card for administration**: management is a
  full-page activity with forms and pickers, and native cards already do usage well.
- **Services registered in `async_setup`** over **per-entry services**: a call during a
  reload gets a clear error, not "action not found".
- **A reload on each options change** over **live updates in each consumer**: 1 setup
  path applies every option, at the cost of a short reload.

## One-way doors

- The domain `home_keeper`, the panel path `/home-keeper`, and the option keys in
  `entry.options` (`const.OPTION_*`). Automations call `home_keeper.set_options` by key.
- The service names and fields. The API surface model lists them
  ([INTEGRATING.md](../INTEGRATING.md)).
