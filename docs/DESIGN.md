# Home Keeper — Design

## Goal

Track home maintenance and chores in Home Assistant, modeled deeply enough to live
*on* the devices they concern (Battery-Notes-style), with administration separated
from everyday usage.

## Recurrence model

Three kinds, all implemented in the pure `recurrence.py` engine (no HA imports, takes
an explicit `now`):

| Type | Semantics | `next_due` after completion |
|------|-----------|-----------------------------|
| **floating** | measured from last completion (`interval` × days/weeks/months) | `completed_at + interval` — the clock resets |
| **fixed** | anchored calendar schedule (`FREQ` DAILY/WEEKLY/MONTHLY × `interval` from an `anchor` datetime) | the next scheduled occurrence after `now` — schedule-driven, not completion-driven |
| **triggered** | condition-driven, *no schedule*. An owning integration arms it (`trigger_task`, or by creating it) when a condition becomes true and clears it (`complete_task`) when it resolves. `next_due` is its state: a timestamp = armed/due-now, `None` = dormant (invisible to to-do/calendar/overdue). | `None` (dormant) — completing *clears* the condition rather than rescheduling, while still recording the completion so cadence accumulates |

Month arithmetic clamps to month length (Jan 31 + 1mo → Feb 28/29). A missed
floating task stays overdue rather than rolling forward on its own. The `triggered`
type is the first-class home for condition-driven sources (Battery Notes batteries,
leak sensors, filter pressure) — see [INTEGRATING.md](INTEGRATING.md) §7 and
[BATTERY_NOTES_PLAN.md](BATTERY_NOTES_PLAN.md).

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
  provision. Only the fields that wire into HA stay structured — `manufacturer`/`model`
  (the device card), `cost` (the inventory value rollup), `icon`, `area`. Manuals,
  warranties and receipts live in a **`documents`** list (each a `link` URL or an
  uploaded `file` served from disk via the document HTTP view).
  Everything else is a free-form **`metadata`** list: ordered `{id, type, label, value}`
  entries where `type` is `text`, `link`, or `date`. A `date` entry with `track: true`
  becomes a `date` sensor (`HomeKeeperAssetDateSensor`, named from its label) merged
  onto the device page via `coordinator.device_info_for_device_id`, so e.g. a tracked
  warranty-expiry date is automatable; untracked dates are display-only.
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
virtual device and detaches its tasks (they become standalone).

### Parts / wear items

An asset carries a structured `parts` list (`assets._normalize_parts`); a legacy
`part_numbers` string is folded into a single consumable part by a load-time shim
(`assets.migrate_legacy_part_numbers`, no storage-version bump). A `wear` part with a
`replace_interval`/`replace_unit` is materialized into a floating **task** by
`store.reconcile_part_tasks` (run at setup and after every asset mutation): the task
is tagged `source = {"part": {asset_id, part_id}}` so the reconciler exclusively owns
it (create/update/remove), reuses `models.build_task`/`recurrence.py`, and lands the
normal per-task entities on the appliance device. Completing such a task stamps the
part's `last_replaced`. This is the first internal use of the task `source` field
that the deferred cross-integration contribution API will generalize.

### Relationships: subdevices & related devices

`parent_asset_id` (virtual assets only) makes one appliance a **subdevice** of
another via HA's native `via_device`: `devices._reconcile_virtual` passes the parent's
identifier (`asset_<parentid>`) on create and syncs `via_device_id` on update, with
assets provisioned **parents-first** (`_ancestor_depth`) and cycles rejected in the
store (`assets.would_create_cycle`). `related_device_ids` loosely associates arbitrary
registry devices (including foreign ones HA won't let us reparent) — stored and shown
only in the panel.

### Smaller HA integration points

`area_id` is validated at the HA boundary (`devices.area_exists`) for both tasks and
assets; virtual devices set `configuration_url` (a `homeassistant://` deep
link straight to that appliance's panel page — see "Device page enrichment" below) —
but **not** `entry_type=service`, which would wrongly mark a physical appliance as a
non-physical service entry. An optional mdi `icon` rides on the asset (applied to its
metadata sensors, since HA devices have no icon field), and `diagnostics.py` exposes a
tasks/assets snapshot (config-entry-wide **and** per-device). Remaining open items
(labels for category/type, photo storage, a live device-registry listener,
contribution-API interplay) are in [../IDEAS.md](../IDEAS.md).

## Device page enrichment

The HA **device page** is a framework-fixed layout: an integration can't inject custom
cards/HTML, only contribute entities, device-registry metadata, a diagnostics download,
and the "Visit" link. Home Keeper leans into exactly those hooks so a maintenance
appliance's device page is a useful summary *and* a one-click jump into the panel for
the rich stuff (manuals, full inventory, history) that has no native rendering.

**Owner vs guest.** The enrichment differs by who owns the device record, because the
device-info block and `configuration_url` belong to whoever owns the device:

- **Owned** — a Home Keeper *virtual* asset device (identifier `asset_<id>`). Home
  Keeper controls the whole record, so it goes maximalist (see below).
- **Guest** — a task merged onto a *foreign* device (`device_id` on a task/existing-kind
  asset). Home Keeper is a polite guest: it adds its per-task entities (next-due,
  overdue, mark-done) and tracked-date sensors but never overwrites the foreign
  integration's device-info block or "Visit" link, and does **not** add per-part stock
  entities there. So guest pages are not materially enriched beyond what already
  existed — by design.

**On an owned (virtual asset) device page Home Keeper contributes:**

- **Identity in the device-info block.** `manufacturer` / `model` already synced;
  `serial_number` is now a first-class asset field (`assets._TEXT_FIELDS`) synced into
  `DeviceInfo.serial_number` by `devices._reconcile_virtual` (guarded by
  `_supports_kwarg` for older HA). `sw_version`/`hw_version` are intentionally left out
  — a maintenance appliance rarely has firmware, and a first-class field with no source
  would just be clutter. Serial stays editable in the panel's appliance form next to
  make/model (the legacy "Serial number" *metadata seed* remains for anyone already
  using it; the first-class field is what feeds the registry).
- **A precise "Visit" deep link.** `configuration_url` is
  `homeassistant://home-keeper/appliances/<asset_id>` (was the panel root) so the device
  page lands directly on that appliance's panel detail — where its documents
  (manuals/warranties/receipts) and full parts inventory render as real links/lists.
  (The device page renders a `homeassistant://X` config URL as the in-app path `/X` —
  there is **no** `navigate/` action segment on the web frontend, so a `navigate/...`
  URL renders as a dead `/navigate/...` link and bounces to the default dashboard.
  Caveat: the **companion mobile app** has historically used the `homeassistant://navigate/<path>`
  deep-link form, so the two clients may disagree on the right value; the web/desktop
  frontend is the supported surface here, and the bare-path form is verified there.)
  This is the bridge for the data that *can't* live on the device page: entity
  attributes are never linkified or markdown-rendered there, so links and lists belong
  in the panel, reached in one click.
- **Per-part spare-stock entities.** For each stock-tracked part (`assets.part_tracks_stock`)
  the `number` platform (`number.py`) adds a "<part> spares" control: its value is the
  on-hand count and editing it delegates to `store.adjust_part_stock` (the same service
  path, so the edge-triggered stock events still fire). For each part that also carries a
  reorder threshold (`assets.part_has_reorder`) the `binary_sensor` platform adds a
  "<part> low stock" `PROBLEM` sensor (`is_on = assets.part_is_low`) — making the
  *state* visible on the page, complementing the existing `part_*` device triggers that
  only surface the *transition*. Both key on the asset device and are pruned from the
  entity registry when their part/stock-tracking goes away (mirroring the asset-date
  sensor cleanup).

**Why not device actions.** A device-level "mark task done" / "restock" action was
considered and skipped: a device with several tasks (or parts) makes the target
ambiguous, and the mark-done **button entity** already exposes that action per task in a
non-ambiguous way (and is automatable). The `part_*` device triggers + the
`adjust_part_stock` service cover the automation side without that ambiguity.
