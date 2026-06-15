# Home Keeper — architecture & code conventions

These rules describe the conventions Amazon Q must follow when generating or
reviewing code in this repository (the `home_keeper` Home Assistant integration).

## Separation of administration vs. usage
- **Administration** lives in the custom **sidebar panel**
  (`custom_components/home_keeper/frontend/`, a `panel_custom`/`frontend`
  built-in custom panel). Task create/edit/delete, recurrence configuration, and
  device attachment belong here.
- **Usage** (viewing and completing tasks) is surfaced through **native Home
  Assistant entities** — a `todo` list, a `calendar`, and per-task device-page
  `button`/`sensor`/`binary_sensor` entities. Prefer native entities + HA's
  built-in cards over bespoke Lovelace usage cards. Do not put management UI into
  a Lovelace card.

## Panel navigation & high-fidelity deep linking
- The panel's navigation state is **high-fidelity deep-linked**: every navigable
  destination maps to a URL under the panel prefix (`/home-keeper`). Current
  scheme: `/tasks` (default), `/appliances`, `/tasks/<id>`, `/appliances/<id>`
  (asset detail lives under the `appliances` segment). Forms are ephemeral
  overlays and are intentionally **not** deep-linked.
- **The URL is the single source of truth.** HA hands the panel a
  `route = { prefix, path }` for every in-panel URL change, including browser
  Back/Forward. The `set route` setter parses `path` and is the *only* place that
  flips `_view`/`_detail`. Never mutate `_view`/`_detail` directly to navigate —
  that desyncs the URL and breaks Back.
- **Navigate by changing the URL**, via the `_navigate(location, replace?)`
  helper (`history.pushState`/`replaceState` + a bubbling `composed`
  `location-changed` event). HA re-sets `route` in response, which flows back
  through `set route`. Drill-in steps (open a detail) **push**; lateral moves
  (switch tab) and detail-closing/deletes **replace**, so Back never retraces a
  tab toggle or returns to a deleted object — and Back moves within the panel
  instead of ejecting from it.
- Keep route parse/build as **pure functions in `utils.ts`** (`parseRoute`,
  `buildPath`) so they unit-test in isolation and round-trip losslessly. Unknown
  or empty paths fall back to the tasks list; a detail URL whose id no longer
  exists renders the "gone" notice rather than erroring.

## Pure, HA-free core
- `recurrence.py` and `models.py` MUST NOT import anything from `homeassistant`.
  They are pure Python so they can be unit-tested without the HA test harness.
  Inject HA-specifics (the current time, the configured timezone) from the
  callers instead of importing them here.
- Keep the recurrence engine deterministic: functions take an explicit `now`
  rather than calling a clock internally.

## Datetimes & timezones
- All datetimes are timezone-aware. Use `homeassistant.util.dt` (`dt_util`) at the
  HA boundary; the pure modules receive aware datetimes.
- A naive wall-clock value (e.g. the panel's `<input type="datetime-local">`)
  must be qualified with Home Assistant's configured timezone
  (`dt_util.now().tzinfo`) using `datetime.replace(tzinfo=...)` — never shifted
  with `astimezone()`, and never left naive (it would crash recurrence math).

## Task data model
- Tasks are plain JSON-serializable dicts (never model objects in storage), with
  keys: `id, name, notes, recurrence_type, interval, unit|freq, anchor,
  device_id, area_id, enabled, last_completed, next_due, completions[], created`.
- All task mutations go through `HomeKeeperStore`; entities and the panel read via
  the `HomeKeeperCoordinator` and never mutate storage directly.

## Entities & devices
- Entity `unique_id`s are anchored to the task `id` so they survive renames.
- Per-task device-page entities (`button`/`sensor`/`binary_sensor`) are created
  only for **enabled, device-attached** tasks (use
  `coordinator.device_attached_task_ids()`); `todo`/`calendar` likewise skip
  disabled tasks.
- Attach to an existing device by reusing that device's `DeviceInfo`
  `identifiers`/`connections` (Battery-Notes-style identifier merge) — never
  create a duplicate device for someone else's hardware.
- On `update_task`, reload the config entry only when the entity-set identity
  changes (`coordinator.entity_set_key`, i.e. `device_id` or `enabled`);
  otherwise call `coordinator.async_request_refresh()`. `add_task`/`delete_task`
  reload (entities appear/disappear).

## Services are the interoperability surface — expose every action as one
- **Every action that mutates or exports Home Keeper data MUST be exposed as a
  `home_keeper.*` Home Assistant service**, not only as a panel websocket command.
  This is not limited to task/asset CRUD — it includes exports (e.g. the inventory
  export), stock adjustments, and any future operation. Services are what
  automations, scripts, voice assistants, and other integrations build on, so they
  are the contract; a panel **websocket command** is only a UI-latency optimization
  layered on top and is **never a substitute** for the service.
- **New action ⇒ service first.** A new operation lands as a service (handler in
  `__init__.py`, registered in `_register_services` and listed in `_SERVICES` for
  teardown) *and* documented: a `services.yaml` entry plus `strings.json`
  localization with parity across all `translations/<lang>.json` files (the
  translations-parity test enforces this; hassfest requires the `services.yaml` ↔
  `strings.json` pairing). The websocket command, if any, is added alongside and
  delegates to the same `HomeKeeperStore` method — never a divergent code path.
- Read-only/report actions use `SupportsResponse.ONLY`; data mutations reload the
  entry or refresh the coordinator exactly as the equivalent CRUD service does.

## Errors, validation & security
- Service handlers raise `ServiceValidationError` for user-facing errors.
  Websocket commands return structured errors via `connection.send_error`.
- Escape all user-provided content before injecting it into `innerHTML` in the
  panel frontend (`escapeHTML`).

## Assets: metadata decoupled from device creation (implemented)
The appliance/asset feature lives in `assets.py` (pure model — no HA imports, like
`models.py`) and `devices.py` (registry provisioning). Keep the two concerns separate:
- **Asset metadata layer** — an asset is a JSON dict keyed by `id`, carrying a
  `device_id` anchor that can point at ANY device. `kind == "virtual"` (we own the
  device) or `kind == "existing"` (metadata on another integration's device). Don't
  couple metadata to device creation; existing-device assets never mutate the device.
- **Virtual-device provision** — `devices.async_reconcile_assets()` registers a
  registry device via `async_get_or_create(config_entry_id=..., identifiers={...})`,
  idempotently, on setup and after every asset mutation; it writes the assigned
  `device.id` back to the asset and prunes orphan asset devices. The virtual-device
  identifier is prefixed `(DOMAIN, f"{ASSET_IDENTIFIER_PREFIX}_{asset_id}")` so it
  never collides with the per-task self-owned device `(DOMAIN, task_id)`.
- Reuse HA-native primitives first — device `manufacturer`/`model`/`serial_number`/
  `area`; the custom layer owns only the gap (dates, warranty, cost, vendor, manual
  link, consumable part numbers, notes).
- Temporal fields are real **entities**: `HomeKeeperAssetDateSensor` (a `date`
  sensor per set date field) in `sensor.py`, merged onto the asset's device page via
  `coordinator.device_info_for_device_id`. Descriptive fields stay stored metadata.
- Attach to existing devices only when they currently exist (`device_registry`
  lookup; reconcile recovers a re-created device from the stored
  `identifiers`/`connections` snapshot). Virtual devices are config-entry-owned so HA
  removes them on integration removal; `async_remove_entry` drops the stored doc.
  Deleting an asset removes its virtual device and detaches its tasks (standalone).
- **Parts / wear items.** An asset's `parts` list is structured; a `wear` part with a
  `replace_interval` is materialized into a floating task by
  `store.reconcile_part_tasks` (run at setup + after each asset mutation), tagged
  `source={"part":{asset_id,part_id}}` so the reconciler owns it. Reuse
  `models.build_task`/`recurrence.py` + the existing per-task entities — do NOT build
  a parallel "part sensor". A load-time shim migrates the legacy `part_numbers` string
  (no storage-version bump).
- **Relationships.** `parent_asset_id` (virtual only) → native `via_device`
  (provision parents-first via `_ancestor_depth`; reject cycles with
  `assets.would_create_cycle`). `related_device_ids` is panel-only (foreign devices
  can't be reparented). Do NOT set `entry_type=service` on appliance devices (they're
  physical); DO set `configuration_url`. Validate `area_id` at the HA boundary
  (`devices.area_exists`), never in the pure model. See `IDEAS.md` / `docs/DESIGN.md`.

## Deferred: cross-integration contribution API
- The stable interface for other integrations (e.g. Battery Notes) to contribute
  tasks is intentionally **not implemented yet**. Only documented hook points
  exist (`const.SIGNAL_TASK_CONTRIBUTION`). Do not build it without an explicit
  decision; see `IDEAS.md` / `docs/DESIGN.md`.
