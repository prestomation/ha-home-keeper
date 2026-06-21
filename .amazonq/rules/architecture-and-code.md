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
  keys: `id, name, notes, recurrence_type, interval, unit|freq, anchor, due,
  device_id, area_id, labels[], enabled, last_completed, next_due, completions[],
  created`.
- **Recurrence types** (`const.REC_*`): `floating` (measured from last completion),
  `fixed` (anchored calendar schedule via `freq`+`anchor`), `one-off` (do-once: a
  user-scheduled `due` date; `compute_next_due` returns `due`, `apply_completion`
  sets `next_due=None` permanently, and `remove_completion` re-arms to `due` only
  when the final completion is undone), and `triggered` (condition-driven, no
  schedule — owned by another integration). `one-off` and `triggered` both carry
  **no cadence fields** (`normalize_fields` returns early for each); a completed
  one-off and a dormant triggered task both have `next_due=None`, so they fall out of
  every time surface (to-do/calendar/sensors/transitions) for free. Keep the
  recurrence math in pure `recurrence.py` with an explicit `now`.
- `labels[]` are **Home Assistant label-registry ids** (the same registry as device/
  area/entity labels), normalized in `models.normalize_labels` (de-duped, blank-
  stripped). `merge_update` only rewrites `labels` when the caller sends the key, so a
  rename never stamps a phantom `labels: []` (which would surface as a spurious
  `labels` in `changed_fields`). Pre-existing tasks may lack the key — treat absent as
  empty. Don't garbage-collect ids whose HA label was deleted: a stale id simply stops
  matching, which is harmless.
- The dashboard card filters on labels by **union resolution** (`card-filter.taskLabelIds`):
  a task matches if the label is on the task itself, its attached device, or its
  effective area (`taskAreaId`). This is what lets a card be scoped to a "subject"
  (dog/car/kid) that isn't an HA area or device — keep this transitive rule intact when
  touching card filtering, and keep `card-filter.ts` pure/DOM-free.
- All task mutations go through `HomeKeeperStore`; entities and the panel read via
  the `HomeKeeperCoordinator` and never mutate storage directly.
- **Per-completion metadata.** A `completions[]` entry is `{ ts }` plus any of the
  optional keys `note` / `cost` (number, ≥0) / `photo` (an HA **image-upload id**, never
  bytes) / `who` (a **`person` entity id** — persons are first-class and stable; not an
  HA user). Clean inputs through `models.normalize_completion_metadata` (drops empty
  keys, coerces/validates `cost`); `recurrence.apply_completion(..., metadata=)` merges
  them and `recurrence.update_completion` amends a past entry **without** touching
  `ts`/`last_completed`/`next_due` (editing the log must never rewind or re-arm a task).
  `ts` is the completion's identity for delete/edit/archive.
- **Capture mode is per task, enforcement is list-driven.** `completion_detail`
  (`none`/`optional`/`required`) is the user-facing capture mode; the fields a
  `required` task makes mandatory live in `completion_required_fields` (subset of the
  metadata keys, normalized by `models.normalize_completion_required_fields`). Always
  gate a required completion by reading that **list**, never a hard-coded field, so a
  future per-field "which are required" editor needs only to populate the list — no
  storage migration. Both fields are additive (`.get()` with `none`/`[]` defaults); no
  `STORAGE_VERSION` bump.
- **Capture mode is a panel-only prompt, not a chokepoint constraint.** `store.complete_task`
  records whatever metadata it's given and **never rejects** a completion for missing
  required fields, and the `complete_task` service/websocket fields are all optional. The
  `optional`/`required` gate lives in the panel completion dialog (the card defers a
  `required` task to the panel). This is intentional: every non-panel surface (the native
  `todo` checkbox, the device `button`, automations/voice via the service) funnels through
  the same chokepoint and can't show a dialog, so enforcing there would make a `required`
  task uncompletable from those surfaces. Keep enforcement where a dialog can be shown; do
  not add hard required-field validation to the store/service.

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

## Events are the observation surface — fire one for every state change
- **Every observable state change fires a documented `home_keeper_<noun>_<verb>` bus
  event**, built by a **pure function in `events.py`** (no HA imports) so the test fake
  (`testing.py`) and integrators test against the exact shipped payload — it can't
  drift. Fire at the **`store.py` mutation chokepoint**, not in a service handler, so
  every surface (panel, service, websocket, contributing integration) is observed
  uniformly. *Every* path that mutates the task/asset map counts — including the
  non-CRUD ones (`reconcile_part_tasks`, `detach_tasks_from_device`, `delete_asset`'s
  cascade), which must fire their own create/update/delete events.
- **Edge-triggered transitions live in a pure module + the coordinator.** Time-based
  events (`overdue`/`due_soon`) are detected by `transitions.detect_transitions` (pure,
  unit-tested with an injected `now`) and fired from `coordinator._async_update_data`;
  stock crossings (`low`/`out`/`restocked`) come from `assets.stock_transition`. Fire
  **once per crossing** (keyed on `next_due` / threshold), never every refresh, and
  **baseline silently on startup** (the coordinator gates firing until setup completes)
  so a restart never replays a transition storm.
- **Keep the catalog in sync.** A new event is not done until it's in
  [`docs/EVENTS.md`](../../docs/EVENTS.md) (the canonical catalog: when it fires,
  payload, semantics) and, if device-facing, exposed as a `device_trigger.py` trigger
  with `strings.json` `device_automation` labels at full translation parity. Events are
  *observations* of changes that already flow through services/store methods, so they
  need **no** new service.

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
- **Problem-sensor sync.** When the `sync_problem_sensors` option is on, every
  `binary_sensor` with `device_class: problem` is mirrored as a **triggered** task by
  the pure `problem_tasks.reconcile_problem_tasks` (wrapped by
  `store.reconcile_problem_sensor_tasks`), driven by the HA-aware `problem_sync.py`
  (registry enumeration + a state listener; **skip Home Keeper's own
  `platform == DOMAIN` entities** so our overdue sensors can't feed back in). Tag
  `source={"problem_sensor":{entity_id}}` + a `managed_by` block with
  `completion_blocked: True` so the reconciler owns it and every surface hides *Done*.
  These tasks are **externally-owned / un-completable**: arm on problem, auto-clear when
  the sensor returns to OK, and **never** let a user complete/trigger/uncomplete them —
  `store` rejects those unless the call carries `origin=ORIGIN_PROBLEM_SENSOR_SYNC`. The
  options flow (`config_flow.HomeKeeperOptionsFlow`) carries the toggle + entity/area/
  label exclusions; an options change reloads the entry. Reuse `models.build_task` +
  the existing per-task entities — do NOT build a parallel "problem sensor". A synced
  task that's created/removed reloads the entry (per-task entities); arm/clear is a
  plain coordinator refresh.
- **Options have three editing surfaces that share `options.py`.** Config-entry
  `options` are edited from the **options flow**, the **`home_keeper.set_options`
  service**, AND the panel's **Settings tab** (via `home_keeper/get_options` +
  `home_keeper/set_options` websocket commands). Key list / defaults / normalization
  live in `options.py` (`current_options`, `async_set_options`) so they can't drift;
  every writer goes through `async_update_entry`, which fires the update listener and
  reloads. Per the services rule, the panel ws command is a UI optimization — the
  `set_options` service is the canonical write path. The Settings tab is a top-level
  panel view (`_view === 'settings'`, deep-linked `/home-keeper/settings`) that
  autosaves each `ha-form` change; build its schema from the same selectors in
  `forms.ts` (`settingsSchema`). Options so far: the problem-sensor sync toggle +
  exclusions, and `one_off_retention_days` (int; `0` = keep forever) which the
  **coordinator's periodic refresh** uses to auto-delete completed one-offs
  (`recurrence.one_off_expired` collects expired ids; `_purge_expired_one_offs` deletes
  via `store.delete_task`). Put a new option's default/coercion in `options.py` and add
  it to all three surfaces (flow schema, `SET_OPTIONS_SCHEMA`, Settings `settingsSchema`)
  with `strings.json`/`services.yaml` parity.
  - **The service / ws write path `await`s the reload so the change takes effect
    immediately.** `async_set_options` updates the entry and then awaits
    `async_reload` itself (flagging the entry via `caller_is_reloading` so the update
    listener doesn't fire a second, overlapping reload), so by the time the call
    returns the problem-sensor sync has reconciled for the new exclusions. The fire-
    and-forget update-listener reload (kept for the options *flow*, which updates the
    entry directly) raced the panel's read and left excluded sensors' synced tasks
    lingering. Correspondingly, the panel's `_saveOptions` re-`_reload()`s its cached
    tasks after the save (without re-rendering the form being edited) so the Tasks tab
    reflects the exclusion right away.
- **Relationships.** `parent_asset_id` (virtual only) → native `via_device`
  (provision parents-first via `_ancestor_depth`; reject cycles with
  `assets.would_create_cycle`). `related_device_ids` is panel-only (foreign devices
  can't be reparented). Do NOT set `entry_type=service` on appliance devices (they're
  physical); DO set `configuration_url`. Validate `area_id` at the HA boundary
  (`devices.area_exists`), never in the pure model. See `IDEAS.md` / `docs/DESIGN.md`.

## Exceptions are localized (exception-translations)
- Every user-facing exception raised from a service handler or entity
  (`ServiceValidationError`, `HomeAssistantError`) MUST be constructed with
  `translation_domain=DOMAIN` + a `translation_key` (plus `translation_placeholders`)
  — never a bare f-string. Define the key under `exceptions` in `strings.json`. A
  pure-AST drift-guard (`tests/unit/test_exception_translations.py`) fails the build
  on a bare-string raise or a key missing from `strings.json`.
- Exception message text is currently **English-first across all 16 locales** and
  translated incrementally; `test_translations_parity.py` skips the
  untranslated-leak check for `exceptions.*` (via `_PENDING_TRANSLATION_PREFIXES`)
  while still enforcing key + placeholder parity. Translating a locale's exception
  strings just makes them stop matching English — no test change needed.

## Deferred: cross-integration contribution API
- The stable interface for other integrations (e.g. Battery Notes) to contribute
  tasks is intentionally **not implemented yet**. Only documented hook points
  exist (`const.SIGNAL_TASK_CONTRIBUTION`). Do not build it without an explicit
  decision; see `IDEAS.md` / `docs/DESIGN.md`.
