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

## Errors, validation & security
- Service handlers raise `ServiceValidationError` for user-facing errors.
  Websocket commands return structured errors via `connection.send_error`.
- Escape all user-provided content before injecting it into `innerHTML` in the
  panel frontend (`escapeHTML`).

## Planned: asset metadata decoupled from device creation
When the appliance/asset-metadata feature is built:
- Keep two concerns separate: (1) an **asset-metadata layer** keyed by `device_id`
  that can attach to ANY device — virtual or from another integration — and
  (2) optional **virtual-device provision** for hardware no integration provides.
  Do not couple metadata to device creation; it must work on existing devices too.
- Reuse HA-native primitives first — device `manufacturer`/`model`/`serial_number`/
  `area` and **labels** (2023.7+); the custom layer owns only the gap (dates,
  warranty, cost, vendor, manual link, consumable part numbers, photo, notes).
- Make temporal/automatable fields real **entities** (`date`/`timestamp` sensors,
  e.g. warranty expiry); keep purely descriptive fields as stored metadata.
- Attach metadata only to devices that currently exist
  (`device_registry.async_get` first, reject `None` — no shadow registry). Store
  the device `identifiers`/`connections` alongside `device_id` for reconciliation,
  and clean up all metadata/entities/virtual devices on integration removal.
  See `IDEAS.md` / `docs/DESIGN.md`.

## Deferred: cross-integration contribution API
- The stable interface for other integrations (e.g. Battery Notes) to contribute
  tasks is intentionally **not implemented yet**. Only documented hook points
  exist (`const.SIGNAL_TASK_CONTRIBUTION`). Do not build it without an explicit
  decision; see `IDEAS.md` / `docs/DESIGN.md`.
