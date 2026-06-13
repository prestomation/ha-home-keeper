# Home Keeper — Design

## Goal

Track home maintenance and chores in Home Assistant, modeled deeply enough to live
*on* the devices they concern (Battery-Notes-style), with administration separated
from everyday usage.

## Recurrence model

Two kinds, both implemented in the pure `recurrence.py` engine (no HA imports, takes
an explicit `now`):

| Type | Semantics | `next_due` after completion |
|------|-----------|-----------------------------|
| **floating** | measured from last completion (`interval` × days/weeks/months) | `completed_at + interval` — the clock resets |
| **fixed** | anchored calendar schedule (`FREQ` DAILY/WEEKLY/MONTHLY × `interval` from an `anchor` datetime) | the next scheduled occurrence after `now` — schedule-driven, not completion-driven |

Month arithmetic clamps to month length (Jan 31 + 1mo → Feb 28/29). A missed
floating task stays overdue rather than rolling forward on its own.

## Components

- `store.py` — single JSON document (`.storage/home_keeper`); all mutations funnel
  through it.
- `coordinator.py` — `DataUpdateCoordinator` exposing the task map; refreshed after
  each mutation, plus a 5-minute tick so time-based "overdue" stays current.
  `device_info_for_task` reuses an existing device's identifiers when a task is
  attached (so entities merge onto that device page), else a self-owned device.
- Entities (usage surfaces):
  - `todo.py` — one to-do list; completing an item advances recurrence.
  - `calendar.py` — upcoming occurrences (floating = next due; fixed = expanded).
  - `button.py` / `sensor.py` / `binary_sensor.py` — per-task, **only for
    device-attached tasks**; mark-done / next-due / overdue.
- `panel.py` + `frontend/` — the admin sidebar panel (a custom HA panel registered
  via `frontend.async_register_built_in_panel` with a `_panel_custom` config block).
- `websocket_api.py` + services in `__init__.py` — CRUD + complete; the panel uses
  websocket commands, automations use services.

## Why a panel (not a Lovelace card) for admin

Management is a full-screen, app-like activity (lists, forms, device pickers) that
shouldn't compete for space on a dashboard. Usage — *what's due, mark it done* — is
exactly what HA's native to-do/calendar cards and the mobile app already do well, so
we lean on those instead of a bespoke card.

## Device attachment

A task may reference a device-registry `device_id` (chosen in the panel). Its per-
task entities set `DeviceInfo(identifiers=<that device's identifiers>)`, which makes
HA merge them onto the existing device's page — no new device created. This is the
same identifier-merge mechanism Battery Notes uses, and it works regardless of which
integration owns the device.

## Deferred: cross-integration contribution API

The end goal is for other integrations (e.g. Battery Notes) to contribute tasks
*without Home Keeper knowing about them*. Planned mechanism:

- a dispatcher signal `home_keeper_task_contribution` (constant reserved in
  `const.py`) and/or a `home_keeper.contribute_task` service;
- contributed tasks carry a `source` so they can be reconciled/removed when the
  contributor goes away.

Not built in this prototype — only the hook points and this note exist. See
[../IDEAS.md](../IDEAS.md).

## Appliances & asset metadata

Support for dumb appliances and richer asset records, built as two intentionally
**decoupled** layers. An **asset** is a JSON dict (`assets.py`, pure — no HA imports)
managed from the panel's **Appliances** tab and the `*_asset` services/websocket
commands; all mutations funnel through `HomeKeeperStore` alongside tasks in the same
`.storage/home_keeper` document (the `assets` key is additive — no migration).

- **Asset-metadata layer** — keyed by an `id`, with a `device_id` anchor that can
  point at *any* device. `kind == "existing"` attaches metadata to a device another
  integration owns (we never mutate that device); `kind == "virtual"` is one we
  provision. Reuses HA-native fields first (device `manufacturer`/`model`/
  `serial_number`/area) and owns only the gap: manufacture/purchase/install dates,
  warranty expiry + provider, cost, vendor, manual link, consumable part numbers,
  notes. Each set **date** field becomes a `date` sensor
  (`HomeKeeperAssetDateSensor`) merged onto the device page via
  `coordinator.device_info_for_device_id`, so e.g. warranty expiry is automatable.
- **Virtual-device provision** — `devices.async_reconcile_assets()` registers a real
  registry device with `async_get_or_create(config_entry_id=..., identifiers={...})`,
  idempotently on setup and after each asset mutation, writes the assigned
  `device.id` back to the asset, and prunes orphan asset devices. The identifier is
  prefixed `(home_keeper, asset_<id>)` so it never collides with the per-task
  self-owned device `(home_keeper, <task_id>)`. Multiple tasks (and, later, Battery
  Notes batteries) thus share one appliance device page.

Lifecycle: metadata is never coupled to device creation; existing-device assets
recover a re-created device from a stored `identifiers`/`connections` snapshot.
Virtual devices are config-entry-owned, so HA removes them on integration removal,
and `async_remove_entry` drops the stored document. Deleting an asset removes its
virtual device and detaches its tasks (they become standalone). Remaining open
questions (labels for category/type, photo storage, contribution-API interplay) in
[../IDEAS.md](../IDEAS.md).
