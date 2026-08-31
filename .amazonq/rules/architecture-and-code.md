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

## Privilege model: administration is admin-only, usage is not
The split above is also the **security boundary** (user-facing writeup:
`docs/SECURITY.md`). HA reserves Settings, Developer tools and every `config/*`
command for admins; Home Keeper follows that rather than inventing a weaker line.
- The panel is registered `require_admin=True`. Anything reachable only from the
  panel is administration.
- **Admin-only operations: gate BOTH halves.** A websocket command and its
  `home_keeper.*` service twin are the same operation over the same authenticated
  connection, so `@websocket_api.require_admin` on the command without a check in
  the service handler is not a gate — `call_service` walks straight through it.
  Service handlers call the local `_verify_admin(call)` helper in `__init__.py`,
  which raises HA's `Unauthorized`. Currently gated: appliance CRUD (create /
  update / delete / archive / restore, documents, part files, part stock),
  `set_options`, `export_inventory`.
- A call with **no** `context.user_id` (internal / automation-triggered) is
  trusted, matching HA core.
- **`Unauthorized` is the one exception to the localized-exception rule.** It is an
  auth failure, not bad input; core raises it bare and the websocket/REST layers map
  it to `unauthorized`/401. Do not dress it up as a `ServiceValidationError`.
- **Usage stays open**: tasks (read, create, complete, snooze, skip), profiles,
  companions, and the dashboard card's reads.
- **Reads that return appliance data must project for non-admins.** The card needs
  appliance data, so `get_assets` / `list_assets` are not admin-only; instead a
  non-admin gets `assets.card_projection(...)` — a **whitelist** of the fields the
  card renders (documents, `link`-type metadata, part id/name/url). Costs, serials,
  warranty dates and free-text custom fields stay admin-only, so a new field is
  private until someone publishes it deliberately. A mutating command that echoes
  the full asset back is admin-gated instead (that is why appliance CRUD is on the
  list above).
- **Notify targets are allowlisted where they're stored**, not only in the picker:
  `notifications.split_targets` keeps `mobile_app_*` and `persistent_notification`
  and drops the rest, so Home Keeper can't be made to relay text through an admin's
  SMTP/chat integration. A rejected `target:` override on `home_keeper.notify` fails
  the call (`notify_invalid_target`); a rejected stored target is dropped with a
  warning.
- **Only built assets are published as a static path.** HA serves static paths
  pre-auth, so `panel.py` mounts `frontend/dist/` (rollup's output), never the
  source tree.

## Panel navigation & high-fidelity deep linking
- The panel's navigation state is **high-fidelity deep-linked**: every navigable
  destination maps to a URL under the panel prefix (`/home-keeper`). Current
  scheme: `/tasks` (default), `/appliances`, `/tasks/<id>`, `/appliances/<id>`
  (asset detail lives under the `appliances` segment), `/appliances/<id>/<tab>`
  for an appliance's sub-tabs (`ASSET_TABS` in `utils.ts`), and
  `/settings/<section>` for a Settings section (`SETTINGS_SECTIONS`). Forms are
  ephemeral overlays and are intentionally **not** deep-linked.
- **A route may render differently at different widths, but only CSS may decide
  which.** `/settings/<section>` is one section beside a rail on a desktop and a
  section on its own with a back arrow on a phone. The panel renders all of it —
  rail, section index, and every section — puts the named section on the layout as
  `data-section` and marks its card `.hk-sec-current`, and the media query picks.
  Nothing in `_render()` or `_hydrate()` reads the viewport, so the rule below
  about viewport-agnostic rendering still holds.
- **A new URL segment must keep the old URLs working.** The sub-tab segment is
  optional and an unrecognised value falls back to the default tab, because
  `/appliances/<id>` is already written into every registered appliance device's
  `configuration_url`. `buildPath` leaves the *default* tab out of the URL, so the
  canonical link to an appliance stays the short one.
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
- **Opening a form is not a navigation.** The edit drawer opens beside the page it
  was pressed on — the list, or that object's own detail page — and the location does
  not move (`_openEdit` / `_openEditAsset`, gated by `_editsThisPage`). Edit used to
  navigate to the owning list, which threw away the schedule, notes and history that
  the values being edited come from. Only a *cross-view* edit still navigates, because
  a form mounts on its own view: the task form on `tasks`, the appliance form on
  `appliances`. That one goes through `_navigate` plus `_pendingEdit`, since
  `_applyLocation` clears ephemeral forms on the way.
- **The drawer belongs to every page of its view, so mount it before any page-specific
  wiring returns.** `_hydrate` returns early for a task detail ("a page of its own"),
  so `_mountDrawerForm` runs above that return — mounted after it, Edit on a task page
  opens an empty drawer.
- **A form beside a detail page must not dim it.** The dimming that marks the edited
  row on a list is keyed off `.hk-wrap:not([data-detail])`: on a detail page the page
  *is* the subject of the form, so it stays at full contrast. Where a third column
  would not fit (an appliance, read beside its list), the list steps aside above
  1150px rather than everything shrinking.

## Pure, HA-free core
- `recurrence.py` and `models.py` MUST NOT import anything from `homeassistant`.
  They are pure Python so they can be unit-tested without the HA test harness.
  Inject HA-specifics (the current time, the configured timezone) from the
  callers instead of importing them here.
- Keep the recurrence engine deterministic: functions take an explicit `now`
  rather than calling a clock internally.
- `options.py` sits on the boundary: it takes a `ConfigEntry` and a `HomeAssistant`,
  but only ever reads attributes off them, so those two imports live under
  `if TYPE_CHECKING:` and the module is runtime-pure. That is what lets the fast unit
  tier assert on the option merge rules every write path shares. Keep it that way —
  reach for `hass.<something>` at import time and `tests/unit/test_options.py` stops
  running without the HA harness.
- `device_compat.py` sits on the same boundary for the same reason: it only ever calls
  methods on a `DeviceRegistry` it is handed, so its `homeassistant` import is
  `TYPE_CHECKING`-only and `tests/unit/test_device_compat.py` can drive both registry
  shapes with plain fakes. Both modules are in the mutmut `only_mutate` allowlist.

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
  schedule — owned by another integration), and `sensor` (due-state derived from a
  bound numeric entity — see below). `one-off`, `triggered`, and `sensor` all carry
  **no cadence fields** (`normalize_fields` returns early for each); a completed
  one-off and a dormant triggered/sensor task all have `next_due=None`, and every
  time surface (to-do/calendar/sensors/transitions) must drop them. Only the surfaces
  that *compare* `next_due` get that free (`is_overdue` is `False` for `None`);
  a surface that **lists** tasks needs an explicit dormancy skip, so add one when you
  build a new one — the to-do list shipped without one for `one-off`, and a finished
  do-once task sat there undated forever (#221). Keep the recurrence math in pure
  `recurrence.py` with an explicit `now`.
- **Sensor-based tasks** (`REC_SENSOR`) bind a task to a numeric entity via a
  `task["sensor"]` block (`models.normalize_sensor`: `entity_id`, `mode`, and the
  mode's fields — `target` for `usage`, `comparison`+`value`+optional `for_seconds`
  for `threshold`, optional `attribute`). Like `triggered`, `next_due` is the state
  (`None` dormant / timestamp armed) and the task is **user-created** — so, unlike the
  problem-sensor sync, there is **no auto-creation/reconcile and no entry reload**. The
  arming math is a **pure evaluator** (`sensor_tasks.py`: `evaluate_usage` /
  `evaluate_threshold`, plus `compare`/`parse_reading`) and the **HA-aware watcher**
  (`sensor_watcher.py`) only *evaluates* existing sensor tasks: it subscribes to the
  bound entities, reads live values, and applies decisions through the store
  (`trigger_task` to arm — now accepts `REC_SENSOR` — and `set_sensor_baseline` for a
  usage meter; completion clears + re-baselines via `store.complete_task`). Threshold
  edge state (was-true / crossed-at) lives in the watcher's memory and is **baselined
  on startup** (`async_baseline`) so a restart never replays a spurious arm — the same
  discipline as `transitions.py`. The coordinator's periodic tick calls
  `sensor_watcher.async_evaluate(refresh=False)` before transition detection.
- **The `sensor` block is the extension point for new recurrence dimensions.** When a
  usage task needs to be due on something *other* than its meter, add a key to
  `task["sensor"]` and a branch to the pure evaluator — don't reach for the top-level
  `interval`/`unit`/`freq` fields, which `normalize_fields` deliberately skips for
  `REC_SENSOR`. The shipped example is the **time backstop** (`also_every` +
  `combinator`): "every 300 h *or* every 6 months, whichever comes first". Two rules
  that generalize to whatever comes next:
  - **Anchor a time dimension to `last_completed`, falling back to `created`** — never
    to the meter baseline. A meter reset (a replaced controller, a rolled-over counter)
    is bookkeeping, not a service, and must not move the calendar.
  - **A dimension that doesn't need the live reading must still be evaluated without
    one.** The watcher skips a task whose bound entity is unavailable; a usage task
    carrying `also_every` is exempt, because an idle or unplugged machine is exactly
    the one whose annual service you most want to hear about.
- **A usage meter's `baseline` is *the reading on its latest completion*.** That one
  sentence settles every question about it. It is why `store._reset_usage_baseline`
  takes the reading resolved for the history entry rather than re-reading the sensor
  (the log and the anchor are then the same number by construction, back-dating
  included); why `store.update_completion` re-anchors when you correct the `reading`
  on the *latest* completion — and only then, and only in `usage` mode; and why
  `delete_completion` / `move_completion` leave it alone, because neither changes a
  reading. The re-anchor is the documented exception to "amending the log never
  re-arms a task": if the last oil change really was 10,000 miles ago, the task really
  is due, and the alternative is a history row saying 45,000 beside a progress bar
  counting from 48,000. It fires no extra event — `EVENT_TASK_COMPLETION_UPDATED`
  carries `meter_baseline` instead.
- **A user may set `baseline` at creation; the watcher only fills a gap.** `sensor.
  baseline` has always been accepted by `normalize_sensor`, and the panel now offers it
  as **Starting reading** so a machine already partway through an interval doesn't
  start a full one late. `sensor_watcher.async_baseline` and `evaluate_usage` stamp a
  baseline only when there isn't one, so an explicit anchor survives. A baseline
  *above* the live reading is deliberately not rejected — `evaluate_usage`'s debounced
  meter-reset re-anchors it, which is right for a counter about to be zeroed — so the
  form warns in `sensorHintText` rather than the backend refusing. Teaching the
  evaluator to respect a "user-set" baseline would need provenance on the field and
  would leave a task permanently stuck after a genuine reset.
- **Completion fields split into requirable and captured.** `COMPLETION_METADATA_FIELDS`
  (note/cost/photo/who) is what a user types, and doubles as the allowlist for a task's
  `completion_required_fields`. `COMPLETION_CAPTURED_FIELDS` (`reading`) is what Home
  Keeper fills in. Keep a captured field out of the metadata list: marking one required
  would gate completion on something nobody was asked for, and on a task with no sensor
  it could never arrive at all — an uncompletable task, from the panel, with no error
  explaining why. `COMPLETION_ENTRY_FIELDS` is the union and is what you iterate when
  lifting/echoing/persisting an entry; four separate literals used to duplicate it
  (`sensor.py`, `websocket_api._ws_metadata`, `__init__._COMPLETION_METADATA_KEYS`, the
  unit test) and every one of them silently skipped a new field. `reading` is recorded
  for the **numeric** sensor modes only — the single gate is `models.task_records_reading`
  / `utils.taskRecordsReading`, so widening it is one line on each side.
- **Glue integrations own their default intervals, but never lock them.** A companion
  that pushes maintenance tasks (see `docs/GLUE_INTEGRATIONS.md`) should set a sourced
  default and leave `sensor` out of `managed_by.locked_fields`, so the panel's edit form
  can retune it — `merge_update` preserves the accumulated `baseline` when only `target`
  changes. Reserve `completion_blocked` for read-only mirrors (firmware, problem
  sensors); a task a human physically performs must stay completable.
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
  disabled tasks, and both also skip **dormant** ones (`next_due is None` on a
  `one-off`/`triggered`/`sensor`).
- Attach to an existing device by reusing that device's `DeviceInfo`
  `identifiers`/`connections` (Battery-Notes-style identifier merge) — never
  create a duplicate device for someone else's hardware.
- On `update_task`, reload the config entry only when the entity-set identity
  changes (`coordinator.entity_set_key`, i.e. `device_id` or `enabled`);
  otherwise call `coordinator.async_request_refresh()`. `add_task`/`delete_task`
  reload (entities appear/disappear).
- **Owner vs guest on the device page.** The device-info block and `configuration_url`
  belong to whoever owns the device record, so enrich **only our own virtual asset
  devices** (`kind == "virtual"`); on a *foreign* device a task is attached to, add our
  per-task entities but never overwrite the owning integration's metadata/Visit link.
  `manufacturer`/`model`/`serial_number` are first-class asset text fields
  (`assets._TEXT_FIELDS`) synced into `DeviceInfo` by `devices._reconcile_virtual`
  (serial guarded by `_supports_kwarg`). A virtual device's `configuration_url`
  deep-links to **that appliance's** panel page
  (`homeassistant://home-keeper/appliances/<asset_id>`), not the panel root — **no**
  `navigate/` segment (the device page renders `homeassistant://X` as `/X`; a
  `navigate/...` URL becomes a dead `/navigate/...` link that bounces to the dashboard).
- **Per-part stock entities** (virtual appliances only): a `number` (spare count, edits
  delegate to `store.adjust_part_stock`) for each `assets.part_tracks_stock` part, and a
  `PROBLEM` `binary_sensor` (`assets.part_is_low`) for each `assets.part_has_reorder`
  part. Both enumerate via `coordinator.virtual_asset_parts(predicate)` and prune stale
  registry entries by unique-id shape (mirroring the asset-date-sensor cleanup).
- **Read the device registry through `device_compat.py`, never `DeviceRegistry`
  directly.** Home Assistant 2026.9 made `async_get` answer with a `ChildDeviceEntry`
  (a separate class with no `connections`/`manufacturer`/`model`) as well as a
  `DeviceEntry`, and turned `DeviceRegistry.devices` from an id-keyed mapping into a
  collection of entries — so iterating it yields ids on one core and entries on the
  next. `lint.yml` type-checks against *stable* HA, where `ChildDeviceEntry` has no
  name, so the codebase keeps annotating registry devices as `dr.DeviceEntry` and
  confines the approximation to that one module: `resolve_device` for a lookup by id,
  `all_devices` to enumerate, `device_connections` for the one attribute a child
  lacks. A child device is a valid attach target (HA links entities to either kind) —
  don't filter them out. Reading any other `DeviceEntry`-only attribute off a resolved
  device needs a helper there too, not a bare attribute access.
- `diagnostics.py` provides **both** config-entry and **per-device**
  (`async_get_device_diagnostics`) downloads; the per-device one scopes to the device's
  appliance + its tasks. A device-level *action* was deliberately **not** added (the
  per-task mark-done button + `adjust_part_stock` service cover it without the
  which-task/which-part ambiguity).

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
- **Every `*_id` service field accepts a name as well as an id, id first.** The ids are
  `uuid4`s (`models.build_task`, `assets.build_asset`) that appear in no UI a person
  reads, so an id-only field makes the whole service surface unusable by hand. This
  follows Home Assistant core: `todo.update_item`'s single `item` field is labelled
  "Item name or UID" and resolved by `_find_by_uid_or_summary`. Keep it **one field**
  — never a `task_name` sibling beside `task_id` — and never rename the existing key,
  which integrators and published automations already pass.
  `resolve.py` holds the resolution (pure, HA-free, on the mutmut allowlist): exact id,
  then exact name, then a trimmed/case-folded name, with parts and documents scoped to
  their already-resolved asset. `__init__.py`'s `_task_ref`/`_asset_ref`/`_part_ref`/
  `_document_ref` wrap it for the handlers.
  **Ambiguity raises; it does not guess.** This is the one deliberate departure from
  core, which takes the first name match: Home Keeper's names are not unique by design
  (`docs/INTEGRATING.md` tells contributors to expect collisions) and the services
  reached this way include `delete_task` and `delete_asset`. A name matching several
  objects raises `<kind>_ambiguous` naming every candidate id. A name matching *nothing*
  is passed through untouched so the handler's existing not-found error quotes what the
  user actually typed.
  The panel shows each object's id with a copy button (`panel.ts` `_idRow`), which is
  what makes the id form reachable when a name is ambiguous. Websocket commands stay
  id-only: the panel holds full objects and never types a name.
- Read-only/report actions use `SupportsResponse.ONLY`; data mutations reload the
  entry or refresh the coordinator exactly as the equivalent CRUD service does.
- **Uploaded document blobs are the one non-service mutation surface.** Asset documents
  (`manuals.py`) can be a link *or* an uploaded file; a binary can't ride a YAML service
  or the websocket, so file uploads go through the integration's single
  `HomeAssistantView` (`HomeKeeperDocumentView`, auth-gated, `POST` multipart / `GET`
  served from disk). Even so the **metadata still funnels through the store**: the view
  calls `store.add_asset_document`, so the `home_keeper_asset_updated` event still fires
  and the service-first rule holds for the link side (`add_asset_document` /
  `update_asset_document` / `remove_asset_document` services). Editing is the same
  upload-only split: `update_asset_document` renames any document and changes a **link's**
  URL, but a **file** is rename-only (its blob/filename/type are immutable — replace it by
  removing and re-uploading). Blobs live under the **config dir**
  (`home_keeper/documents/<asset_id>/…`, one dir per asset → asset-delete is a single
  `rmtree`), not in `.storage`. The browser opens a file via a short-lived
  `async_sign_path` URL minted by the `sign_document_url` websocket command. Keep the
  pure, HA-free validation (magic-byte sniff, allowlist, size cap, filename sanitization,
  path-traversal guard) in `documents.py` so it stays unit-testable without an HA runtime.
  **File documents are upload-only:** the generic `build_asset` / `merge_update` write
  controls only `link` documents and always carries the stored `file` documents through
  (`_merge_documents`), so a plain `add_asset`/`update_asset` can neither inject a
  blob-less phantom file nor orphan a blob by omitting one — file blobs are removed only
  by `remove_asset_document` / `delete_asset`. A **document mutation must NOT call
  `devices.async_apply_asset_change`**: documents touch no device/entity/task, so the
  full entry reload that metadata/parts need is pure waste here — the `store` save +
  `home_keeper_asset_updated` event is the whole job. The per-asset list is capped
  (`_MAX_DOCUMENTS`).
- **Frontend: documents are a discriminated union; display/open goes through one
  helper.** `AssetDocument` in `types.ts` is `AssetLinkDocument | AssetFileDocument`
  (discriminated on `kind`), so touching a kind-specific field (`url` vs
  `filename`/`size`) without first narrowing `kind` is a **compile error** — a missed
  kind can't slip through. Every surface that lists or opens a document (the panel and
  the dashboard card) consumes the shared `documents.ts` helpers
  (`isDisplayableDocument` / `documentLabel` / `documentIcon` / `openDocument`, plus
  `assertNever` for exhaustiveness) rather than re-deriving the link-vs-file branch.
  Add a new kind, or change how files open, in `documents.ts` once and both surfaces
  follow. Don't hand-roll `doc.kind === 'file' ? … : …` at call sites.
- **A file is opened by a native `<a href>` tap — never by a JS `window.open` after an
  `await`.** The iOS companion app's WKWebView blocks a `window.open` issued once the
  user gesture has been consumed by an async round-trip, so a "sign the URL on click"
  handler silently does nothing there (issue #164, after the same bug on the card).
  Every surface therefore **pre-mints** the signed URL — `SignedUrlCache` in
  `documents.ts`, shared by the panel and the card — and renders a real anchor whose
  `href` is already set (or gets set by the panel's `_signFiles` chokepoint, keyed by
  the `data-sign` cache key on the anchor) before the user can reach it. A link
  document just uses its own URL; both kinds get `target="_blank"`
  `rel="noopener noreferrer"`. `openDocument` / `openPartFile` remain **only** as the
  fallback for the window before the first sign lands, and stand down as soon as the
  anchor has an href (otherwise a click both navigates *and* opens a second tab).
  The affordances this preserves are the point: hover/cursor, long-press "open in new
  tab", middle-click, and keyboard activation are all things a `role="button"` anchor
  with no `href` throws away. New openable-file surface? Pre-sign it, and make its tap
  target at least 44px (WCAG 2.5.5) — these live on phones.
- **A part's single attached file is a smaller sibling of the document pattern
  above, not a second implementation of it.** A part has exactly one optional file
  slot (`file_name`/`file_content_type`/`file_size` — no list, no link kind, since a
  link is already the part's own `url` field), keyed by the **part's own id** instead
  of a minted document id and served by a second, much shorter
  `HomeAssistantView` (`HomeKeeperPartFileView`). It reuses `documents.py`'s pure
  validation and `manuals.py`'s on-disk I/O helpers as-is (they're already generic
  over an opaque id) and lives under the **same per-asset directory**, so an
  asset-delete `rmtree` cleans up part files for free — no separate cleanup path.
  The same upload-only isolation applies: `_normalize_part` never reads `file_*` from
  input, and `_merge_parts` unconditionally restores them from the stored part, so
  only `set_part_file`/`clear_part_file` (called from the view/store, never from a
  generic write) can change them. Removal is a service (`remove_part_file`) like
  `remove_asset_document`; upload stays HTTP-only, same reasoning (no binary bytes in
  a service call).

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
- **Keep the catalog in sync.** A new event is not done until it has an `EventSpec` in
  `api_surface.py` (name, payload shape, per-event extras, and the one-line "fires
  when" the reference renders) and, if device-facing, a `device_trigger.py` trigger
  with `strings.json` `device_automation` labels at full translation parity.
  [`docs/EVENTS.md`](../../docs/EVENTS.md) keeps only what a table can't say: when
  each event fires in context, edge-triggering, what a restart replays, worked
  automations. Events are *observations* of changes that already flow through
  services/store methods, so they need **no** new service.

## The integrator-facing surface is modelled, and the reference is generated
- **`api_surface.py` is the single index of every surface an integrator can touch** —
  services, events and their payloads, device triggers, entity platforms and
  attributes, config-entry options, plus the internal websocket commands and HTTP
  views. A new one is not done until it has a spec there;
  `tests/unit/test_api_surface.py` parses the component's own source and fails
  otherwise, and `tests/integration/test_api_surface.py` checks the running system.
- **The runtime consumes the model.** `__init__.async_unload_entry` iterates
  `SERVICE_NAMES`; `device_trigger.py` builds `TASK_TRIGGERS`/`ASSET_TRIGGERS` from
  `triggers_for()`. Never restate a modelled list as a second literal beside it —
  that is exactly how `set_task_meter` shipped registered on setup and missing from
  the teardown tuple, still callable against an unloaded integration.
- **The model declares names and structure only.** Every string Home Assistant already
  localizes — service and field labels, trigger labels, entity names, option labels,
  error messages — is resolved at generation time from `services.yaml` /
  `strings.json`, so the reference and the Home Assistant UI cannot describe the same
  action differently. Never put a user-facing sentence in `api_surface.py`. The one
  exception is `EventSpec.summary`: a bus event has no Home Assistant string source.
- **The reference is generated, never written.** `ci/generate_api_docs.py` renders
  `website/developer/api.md` from the model plus those two files, and `npm run sync`
  runs it after `sync-docs.mjs` (which clears that directory). The page is gitignored
  with the rest of the generated tree, so it can't go stale in git — which also means
  a canonical doc links to it by its published URL, not a relative path.
  `sync-docs.mjs` pulls those URLs back to site-relative routes so a PR preview links
  within itself.
- **`SURFACE_KINDS` lists the surfaces we don't offer too**, each with a status and a
  one-sentence reason. A list of what exists can't tell you what was forgotten. Adding
  a new kind of surface means adding a row there first.

## Errors, validation & security
- Service handlers raise `ServiceValidationError` for user-facing errors.
  Websocket commands return structured errors via `connection.send_error`.
- Escape all user-provided content before injecting it into `innerHTML` in the
  panel frontend (`escapeHTML`).
- **User free text that should render rich goes through `markdown.ts`, never raw
  `innerHTML`.** `markdownBlock()` emits an `<ha-markdown>` carrying the *escaped*
  source in `data-md`; `wireMarkdown()` moves it onto the element's `content`
  property after insertion (it's a property, not an attribute), and must run in
  every render pass's wiring step. Everything else still goes through `escapeHTML`.
  See "Markdown notes" below.

## Markdown notes (implemented)
Every notes field — task, appliance, part, and per-completion — renders as Markdown.
- **Render with HA's own `ha-markdown`; never bundle a parser.** It parses with
  `marked` (GFM) and sanitizes with DOMPurify *in a Web Worker*, retargets off-host
  anchors, and brings theme-aware styles. Hand-rolling that means maintaining
  sanitizer-adjacent code; bundling `marked`+DOMPurify means ~70 KB and two
  supply-chain deps in a frontend that ships **zero** JS runtime dependencies. The
  frontend Rollup config deliberately has no `node-resolve` plugin — keep it that way.
- **`ha-markdown` is lazily loaded** and absent from HA's eager entrypoints.
  `ensureMarkdown()` registers it by asking `window.loadCardHelpers()` to build a
  markdown card (the chunk that defines `hui-markdown-card` also defines
  `ha-markdown`). `window.loadCardHelpers` itself comes from the Lovelace chunk, so a
  cold deep-link straight to `/home-keeper` may not have it — `markdownBlock` then
  falls back to escaped text with `white-space: pre-wrap`, and `_ensureMarkdown()`
  retries on later renders so the panel upgrades once a dashboard has been visited.
  **Never assume the element is registered; always keep the fallback path working.**
- **Authoring**: a detail page's Notes card has an inline editor (`_noteEdit` /
  `_saveNote` / `_notesCardBody`) and every notes field in a form gets a live
  `createPreview()`. Previews are **debounced** (each render round-trips through the
  worker) and driven from the form's existing `value-changed` handler — update in
  place, never re-render, or the field loses focus mid-word (same technique as
  `_updateSensorHint`). The preview stays hidden until `looksLikeMarkdown()` is true:
  echoing plain prose back at the author is noise.
- **Storage is Markdown source, not HTML.** The raw text is what `todo`/`calendar`
  item descriptions and the services/events hand out; only the panel renders it.
- Appliance `notes` lives in `assets._PROSE_FIELDS`, deliberately **separate** from
  `_TEXT_FIELDS` — the latter documents "these sync into the device registry"
  (`manufacturer`/`model`/`serial_number`), and notes must never leak into the
  device card.

### A failed action reports itself where the user is looking
An action's failure must surface **inline, next to the control that triggered it**, and
also via `_toast(...)` (HA's `hass-notification` snackbar, which is viewport-fixed and
so can't scroll out of sight). A single form-level error banner is **not** sufficient on
a long form: the appliance editor's banner sits below the documents, metadata, parts and
related-devices sections, which is why upload failures read as "nothing happened"
(issue #159). Scope the inline error to the control with a key (`document`,
`part:<id>`), scroll it into view via a one-shot flag set at failure time — never by
checking "an error exists" during render, since `mergeAsset` clears the error on every
keystroke — and clear a stale error when the next attempt succeeds.

### Uploads stream to disk — never buffer a whole file in memory
`manuals._parse_upload` spools each multipart file part to a temp file under
`<documents root>/.incoming/`, flushing at most `_FLUSH_BYTES` at a time, then moves it
into place with an atomic same-filesystem rename. Peak memory is therefore independent
of `MAX_DOCUMENT_BYTES` — the reason that ceiling can be 100 MB at all. Consequences to
preserve: validation works from `(header, size)` via `documents.validate_upload_stream`
(only `SNIFF_BYTES` are ever kept); the caller **owns the temp file** and must always
finish with `async_discard_upload` (a no-op after the move); downloads use
`web.FileResponse`, never a full read; and setup calls `async_cleanup_temp_uploads` so a
restart mid-upload can't strand a partial file. Don't reintroduce a `bytes`-returning
read/write on this path.

### Backend constants the panel needs live in `frontend/src/limits.ts`
TypeScript can't import a Python constant, so a limit the panel must enforce
client-side (e.g. `MAX_DOCUMENT_BYTES`, checked before uploading so an oversized file
fails instantly instead of after a long transfer) is mirrored in
`frontend/src/limits.ts` and drift-guarded by a pytest test
(`tests/unit/test_upload_limit_parity.py`). The backend stays the authority — the
client check is a fast path, never the enforcement.

### The panel's visual language is a token block, never literal colour
- `STYLES` opens with a `:host` block of `--hk-*` tokens (accent/danger/warn/ok,
  surface/page/line/ink, radii, `--hk-tap`). **Every rule reads a token; no rule
  hard-codes a colour.** Each token resolves to a Home Assistant theme variable, or
  to a `color-mix()` off one for the tints HA does not publish (a 12% mix over the
  *surface* darkens with the surface, so it reads correctly in a dark theme too).
  A design comp is drawn in one palette; pasting its hexes breaks dark mode and
  every custom theme.
- **One primary action per surface, and every button states its weight.** The
  vocabulary lives in `utils.ts` as `BtnWeight` + `btnAttrs()` / `setBtnWeight()`:
  `primary` (no attributes — HA's own default), `secondary` (`appearance="filled"`),
  `tertiary` (`appearance="plain" variant="neutral"`), `danger`
  (`appearance="plain" variant="danger"`) and `danger-primary` (`variant="danger"`).
  **Never write `ha-button` attributes by hand**, and never re-introduce `raised` or
  `destructive`: `ha-button` extends Web Awesome's `Button`, whose observed attributes
  are `appearance`, `variant` and `size` only. Neither Material attribute is read, so
  a button carrying one renders at the default accent fill exactly as a bare one does
  — which is how twelve `raised` buttons, plus every bare one, silently converged on a
  single weight (#262). `--mdc-theme-primary` is dead for the same reason.
  - Because `primary` is spelled as the *absence* of attributes, "given the primary
    weight" and "nobody thought about this button" are otherwise the same markup. The
    helpers stamp `data-hk-weight`, which is what makes the difference legible, what
    the tonal ink rule selects on, and what `tests/e2e/tests/button-weights.spec.ts`
    walks.
  - **Cancel is always `tertiary`.** A destructive action takes the weight of the
    *surface's* purpose, not of the thing it destroys: `danger` where it sits among
    other actions, `danger-primary` only on a surface whose whole job is the deletion
    (the confirm scrim, and nowhere else).
  - `tertiary` is `neutral` rather than brand on purpose — `appearance="plain"` alone
    paints the label in the accent colour at 3.26:1 on a card.
- Two shared primitives carry the system: `.hk-eyebrow` (uppercase micro-label
  above a group) and `.hk-indent` (a rule down the left of fields that exist only
  because of a choice above them). Reuse them rather than restating the rules.

### Responsive: viewport media queries, sticky over fixed
- Breakpoints are **viewport `@media` queries**, so `_render()` stays
  viewport-agnostic and nothing depends on JS breakpoint state. **Never put
  `container-type` on `:host`** — it makes the host a containing block for every
  fixed descendant, which would anchor the phone tab bar to the bottom of the
  content instead of the screen.
- Prefer `position: sticky` for panes that stay put while the page scrolls (the
  edit drawer, the appliance master pane, the Settings rail). Sticky is positioned
  by its own scroll container, so it survives whatever transformed or contained
  ancestor HA wraps a custom panel in — the same reason the confirm scrim is
  appended to `document.body` rather than positioned from inside the shadow root.
  `fixed` is for genuine viewport overlays (the phone tab bar, the bottom sheet).
- Breakpoints in use: **1150px** (drawer becomes a bottom sheet), **1000px**
  (Settings rail becomes an index, appliance master pane steps aside), **700px**
  (phone: bottom tab bar, floating Add, wrapped filter chips, stacked rows). The
  first two are 1150/1000 rather than the 900 they shipped with — see the sidebar
  note below, which is what moved them.
- **Never dim a container to recede it if a child must stay bright.** `opacity`
  creates a stacking context, so an opaque child of a faded parent is still faded.
  Fade the elements individually (see the drawer's treatment of the edited row).
- **A media query measures the viewport; the panel gets the viewport minus Home
  Assistant's ~256px sidebar.** Any breakpoint about *our* available width has to be
  ~250px larger than the width being reasoned about. The drawer and the appliance
  master pane both shipped with a 900px threshold that let a 400px drawer sit beside
  a 320px list at a 1000px window, breaking task names one character per line; they
  are 1150px and 1000px for this reason.
- **Recede is not disable.** Dimming the list behind the drawer is presentation;
  `pointer-events: none` on it takes away marking another task done, which the inline
  form it replaced never did. Where the drawer genuinely covers the list (the phone
  sheet) the content gets `inert` instead — which removes it from the tab order too,
  something `pointer-events` never did.

### Contrast and affordance are measured, not eyeballed
- **Colour pairs are checked against rendered pixels, in both themes.** Sample the
  computed colours through the shadow root and compute the ratio; the light and dark
  failures are rarely the same ones. `--hk-accent-fg` on `--hk-accent` is 3.26:1 —
  Home Assistant's own filled-button pairing, and not good enough for a 12px label,
  so selected states use the soft/ink pair plus an edge.
- **The `*-ink` tokens mix ~58% hue into `--primary-text-color`, not 78%.** At 78%
  the mix barely moves off the hue in light mode, and stays red-on-red in dark. When
  adding a semantic colour, pair a `*-soft` container with a `*-ink` label — never a
  literal `#fff` over a mid-tone fill (that pairing measured 1.88–1.96:1).
- **Enclosure means pressable.** A bordered status pill beside a borderless tonal
  button reads as the pill being the control. Status chips carry no outline; the
  row's action carries the ring.
- **Reach into a Home Assistant component through its `part`, not its colour custom
  properties.** `ha-button` reads only fill tokens, so the label colour is only
  reachable as `::part(base)`. HA's tonal label on its own tonal fill measures
  2.85:1, so every tonal button restates it from `--hk-accent-ink` — keyed off
  `[data-hk-weight="secondary"]` rather than a class, so a button cannot opt out of
  the fix by being written somewhere new.
- **When a semantic colour needs a label, add the `*-ink` to match the `*-soft`.**
  The `ok` family shipped with a container and no ink, which is why the "Connected"
  chip was still white-on-mid-tone at 3.30:1 after #261 fixed its neighbours.

### Accessibility contracts the panel has to keep
- **`_render()` destroys the focused element, so `_render()` restores focus.**
  Every control carries a stable `data-*` attribute; `_focusKey()` records one before
  the rebuild and `_restoreFocus()` finds its replacement after. Without it every
  activation drops a keyboard user at the top of the document.
- **Focus a Home Assistant element through `_focus()`, never `el.focus()` directly.**
  Its `focus()` dereferences a shadow root that may not exist yet immediately after an
  `innerHTML` assignment, and the throw propagates out of `_render()` and skips
  everything after it.
- **State conveyed by colour needs a text equivalent.** The rail's dots carry
  `role="img"` plus a label; the selected filter chip carries `aria-pressed`.
- **Don't declare a widget role you have not implemented.** The appliance sub-tabs
  and the phone tab bar are navigation between URLs, so they are buttons with
  `aria-current="page"` — a `role="tab"` with no tabpanel, roving tabindex or arrow
  keys is worse than no role at all.
- `tests/e2e/tests/a11y.spec.ts` pins all of the above. The rest of the suite runs at
  desktop width with a mouse and noticed none of it.

### One `ha-form` per section — and seed each with only its own fields
- `ha-form` renders its own rows and exposes no slot between them, so **a heading
  between two fields is only reachable by splitting the schema.** The task form
  (`taskSchemaSections`) and the problem-sensor settings card
  (`problemSyncToggleSchema` + `problemSyncExclusionsSchema`) do this; in both
  cases the *flat* schema builder is kept as the concatenation, with a unit test
  asserting the two can never drift. `_renderAssetForm` has done this since before
  the convention existed.
- **Seed each section with `pickFormData(data, section.fields)`, never the whole
  form.** `ha-form` emits its entire `data` object on every change, so a section
  seeded with everything re-asserts a stale snapshot of every other section each
  time it changes — typing a name and then changing the recurrence put the name
  back to what it was before the first keystroke, and the save created nothing.
- Because each event now carries only one section's fields, **a change handler
  must check a field is present before reading it** (`'interval' in value`).
  An unguarded read sees `undefined` for fields in other sections; the cadence
  interval is coerced with `Number(...) || 1`, so it silently became 1.
- Keep the wrapper's id (`hk-task-form`) on a `<div>` around the section forms, so
  every `#hk-task-form <selector>` descendant lookup still resolves. Tests that
  dispatch `value-changed` must address the *section that owns the field* — an
  event dispatched at the wrapper reaches no listener and passes vacuously.

### Don't build on lazily-loaded HA components
Only use an HA custom element that is registered on a *custom panel's* page. Several
(`ha-progress-bar`, `ha-progress-ring`) exist in HA's frontend but only inside
lazy-loaded chunks, so they never upgrade for us and would render as invisible empty
elements; `REQUIRED_COMPONENTS` only *waits* for a registration, it can't cause one.
Verify with `customElements.get('<tag>')` on `/home-keeper` in the e2e container before
depending on one, and otherwise build the element from plain DOM plus theme CSS
variables (`var(--primary-color)`, `var(--divider-color)`) — see the upload progress
bar (`.hk-upload`).

**The same element has now broken us three times, always the same way: an API we were
still using stopped being read, and nothing failed.** #144 took `ha-dialog`'s action
buttons (only a `footer` slot survived), #262 took its title (`heading` is ignored; the
title comes from a `headerTitle` slot) and, in the same release, every `raised` and
`destructive` on `ha-button`. A string that is still correct, still translated and
still asserted by anything reading the attribute is not evidence it reaches the screen.

- **Both `ha-dialog`s are built by `panel.ts`'s `_makeDialog`.** Do not hand-roll a
  third — the first two were duplicated side by side and each break had to be fixed
  twice. It sets the title *both* ways: a current frontend renders the slotted span
  and ignores the attribute, an older one renders the attribute and drops the span,
  because a light-DOM child whose slot name matches no slot is not rendered at all.
  Neither can show it twice, so this needs no feature detection.
- **Assert on rendered pixels, not on markup, whenever HA owns the rendering.** Read
  the computed style off the element's `part`, the way
  `tests/e2e/tests/button-weights.spec.ts` does. An attribute assertion would have
  passed throughout both of the above.
- **Probe the real element before designing against it.** `observedAttributes` on the
  constructor is the authoritative answer to "does it still read this?", and a
  throwaway spec in the e2e container gets it in a minute.

### Frontend registrations outlive the config entry — never tear one down on unload
The sidebar panel and the card's Lovelace resource are registered against the *HA
run*, not the entry: both name a static module URL that
`async_register_static_paths` serves until restart, and setup re-registers each one
identically. An ordinary unload is almost always the first half of a **reload**, and
reloads are routine here — saving options, a synced problem sensor appearing, a
purged one-off, a language change. Dropping the registration in
`async_unload_entry` therefore deletes it for as long as setup takes, on a schedule
the user never asked for.

For the panel that is user-visible damage, not churn: HA's `partial-panel-resolver`
answers `home-keeper` disappearing out of `hass.panels` by navigating to the default
panel, so a reload throws anyone reading the panel back to their dashboard. It reads
as random because it is a race with the frontend's `get_panels` refetch — a fast
reload usually wins, a slow one never does (#247). Tear both down in
`async_remove_entry` instead, plus the panel when `entry.disabled_by` is set (HA
sets it *before* unloading, and a disabled entry is the one unload that isn't coming
back). Services are different: re-registering them is invisible, so they still go on
the last loaded entry's unload.

### A dashboard asset ships as a Lovelace resource, not just an extra module URL
`frontend.add_extra_js_url` reaches the browser exactly one way: `IndexView` renders an
inline `import("<url>")` per extra module into the app-shell HTML — a response with no
`Cache-Control` and no ETag, which HA's own service worker then serves
`StaleWhileRevalidate` out of a 24h `file-cache`. A shell cached before the integration
was installed replays forever with no import, and the custom element is never defined
(#228). It reads as permanent rather than flaky because HA already recovers from a
*late* definition (`customElements.whenDefined(tag)` → `ll-rebuild`), so a stuck error
card proves the module never executed. `frontend/subscribe_extra_js` does not save you:
it pushes only *changes* to already-connected clients, never the initial set.

Register the bundle **additionally** as a Lovelace resource
(`hass.data[LOVELACE_DATA].resources`), which the frontend fetches over the websocket on
every dashboard load — the reason HACS cards were immune on the identical shell, and the
only method HA's own docs describe for loading a custom card. Keep `add_extra_js_url`
too: it is the only path when Lovelace is in yaml resource mode, and double delivery is
inert because both name the same URL and `card-index.ts` guards its `define` and its
`customCards` push. Reconcile idempotently — match on the URL *path* so a rebuilt
bundle's new `?v=` token updates the row instead of adding one (`card_resource.py` is
the pure planner; `card.py` does the talking). `ResourceStorageCollection` loads lazily,
so call `async_get_info()` before reading `async_items()` or every start looks like a
fresh install. Write `res_type`, read `type` — the collection renames the key on the way
in. Skip `ResourceYAMLCollection` (it has no create/update/delete, and rewriting a
user's YAML is out of bounds), delete only in `async_remove_entry` (never on unload,
which also runs on every reload), and never let a failure break entry setup. Reading
Lovelace internals means `lovelace` in `after_dependencies` — hassfest's dependency
check runs for custom integrations and `lovelace` is not in its allow-list.

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
  - **The generated name is localized to the instance language at write time.** The
    task name (`"Replace {part} ({asset})"`) is server-side *global* data — one value
    shared by the to-do item, calendar event, notifications, device-page entity names,
    and every API consumer — so it can't be re-rendered per viewer the way the panel's
    static UI is. Instead `store.reconcile_part_tasks` resolves the template + the
    unnamed-appliance fallback word from `hass.config.language` (the household's
    primary language) via `const.resolve_wear_task_naming` and passes them into the
    **pure** reconciler (which stays HA-free, defaulting to English). Translations live
    in `const.WEAR_TASK_NAME_TEMPLATES` / `APPLIANCE_FALLBACK_NAMES` (16 languages,
    guarded by `tests/unit/test_wear_task_naming.py`). A language change is picked up
    as ordinary **name drift** — the `__init__` `EVENT_CORE_CONFIG_UPDATE` listener
    reloads the entry, reconcile recomputes the name in the new language, and the
    existing `before.get("name") != name` branch rewrites it (and recreates the
    per-task entities under the new name). Consequence, by design: a mixed-language
    household sees one language (the instance's) on these names everywhere, including
    the panel — the tradeoff for translating every surface, not just the panel.
- **Manual consumable links.** A user can link *any* task (e.g. a sensor task) to a
  consumable via `store.set_task_consumable` (the `home_keeper.set_task_consumable`
  service + `home_keeper/set_task_consumable` websocket command). It reuses the same
  `source={"part":{asset_id,part_id}}` shape — so completing it consumes a spare at the
  existing `_stamp_part_replacement` chokepoint (which keys only on the part source, not
  recurrence type) — but adds a **`manual: true`** discriminator inside the part dict.
  `reconcile.is_manual_part_link` reads it, and `reconcile_part_tasks` **skips** manual
  links entirely: it must never update or orphan-delete them (they have no wear cadence,
  so the reconciler would otherwise delete them as orphans). The flag needs **no storage
  migration** — existing reconciler-derived tasks lack it and stay owned. Setting a link
  is rejected on a reconciler-derived part task (already bound) and a synced problem
  sensor. The panel's `sourceOwned` gate treats `part.manual` as user-owned, so a linked
  task stays editable/deletable. The panel's **Linked consumable** picker is **scoped to
  the appliance the task is attached to** (its `device_id` / related devices) — you link
  a task to its own appliance's consumable, not an unrelated one — and re-scopes (clearing
  a now-out-of-scope link) when the attached device changes.
- **Spare quantities are decimal, and a whole one stays an `int`.** `stock`,
  `reorder_at`, `restock_quantity`, `consume_quantity` and the `adjust_part_stock`
  `delta` are all floats: a part can be measured in millilitres or in thirds of a
  bottle, not just in whole spares. Every write goes through `assets._round_stock`,
  which rounds to `_STOCK_DECIMALS` (3) and **collapses a whole result back to `int`** —
  so 0.1 taken ten times reaches exactly zero instead of a 1.4e-17 remainder that reads
  as "still in stock", and the ordinary count-the-filters case keeps round-tripping as
  `3`, not `3.0`, through storage, the panel and every event payload. Validation rejects
  NaN/inf explicitly (they pass every bound comparison). `stock_unit` (free-form, ≤16
  chars, purely presentational — Home Keeper never converts units) rides in the stock
  event payload as `unit` and on the part's `number`/`binary_sensor`, and the panel
  renders every quantity through `utils.formatQuantity`. The two per-completion amounts
  have a **read-side floor**: `assets.part_consume_quantity` /
  `part_restock_quantity` return 1 for unset, junk, zero or negative — records written
  before the fields existed must keep consuming exactly one, and a completion must
  never fail because a stored field is malformed. Because that floor makes zero and
  unset indistinguishable, the writers refuse to store a zero that would lie about it:
  `consume_quantity` **rejects** it (the field is new, so nothing can already hold
  one), while `restock_quantity` **folds it to `None`** (it predates the validator and
  its service schema accepted zero, so raising would make an untouched part
  unsaveable). Prefer that asymmetry to a stored value the code ignores.
- **Auto-buy tasks.** A part can opt in (`create_buy_task`, needs a `reorder_at`
  threshold) to a system-managed shopping reminder. The pure
  `reconcile.reconcile_buy_tasks` (wrapped by `store.reconcile_buy_tasks`) is
  **level-triggered**: a one-off `"Buy {part}"` task exists exactly while the part
  `part_wants_buy_task` **and** `part_is_low`, tagged `source={"buy":{asset_id,part_id}}`
  (a third **reserved** source namespace — `add_task` rejects it, `delete_task` blocks
  it, `delete_asset` drops it, `_purge_expired_one_offs` skips it). Idempotency is
  **per low episode**: `existing_by_key` counts a buy task whether open *or completed*,
  so completing it doesn't respawn one while still low; it's orphan-removed once the
  part restocks above the threshold (or opts out). Name localized like wear tasks
  (`const.BUY_TASK_NAME_TEMPLATES` / `resolve_buy_task_naming`). Completing the reminder
  bumps stock by `restock_quantity` at a **new** `store._stamp_buy_restock` chokepoint
  (buy tasks aren't a `part` source, so `_stamp_part_replacement`'s consume branch
  skips them — no double-mutation). Because it's level-triggered, do **not** hook it
  into the sync `_emit_stock_event`; instead every stock/completion surface calls
  `coordinator.async_settle_buy_tasks`, which reconciles and — iff a buy task that owns
  device entities was created/removed — schedules a **deferred** entry reload (guarded
  like `problem_sync._reload_scheduled`), else a plain refresh. Asset-CRUD and setup
  call `store.reconcile_buy_tasks` directly (they already reload / run pre-forward).
- **Shopping-list mirror.** A buy reminder can also be put on an *existing* HA to-do
  list — the `shopping_list_entity` option, one list for the whole integration, `""`
  off. Same split as the problem-sensor sync: pure `shopping.py` (the diff engine +
  `normalize_target`, in `only_mutate`) and HA-aware `shopping_sync.py` (reads the list
  over `todo.get_items`, applies with `todo.add_item`/`update_item`/`remove_item`).
  The questions both to-do syncs ask a list — how an item is addressed in a service
  call, whether it is ticked off, which live item a tracked entry points at, whether
  an open line already says this — are facts about a to-do list rather than about
  either sync, so they live once in the pure `todo_items.py` (`item_identity`,
  `item_is_open`, `resolve_tracked`, `find_open`, plus the two `STATUS_*` values;
  also in `only_mutate`). What differs between the syncs — what a *vanished* line
  means, what a key is, when a line is wanted at all — stays in each planner.
  Rules that hold it together:
  - **Two-way.** A line ticked off on the external list completes the reminder with
    `origin=ORIGIN_SHOPPING_LIST` (authorizes nothing, like `ORIGIN_SENSOR_RECOVER`),
    which restocks the part and retires the reminder. A **completed item is never
    touched** — an unbought reminder's line is *removed*, a bought one is *ticked off*.
  - **Bookkeeping is persisted, keyed by part**, in the storage doc's `shopping_items`
    (additive, no version bump, alongside `problem_notes`), because the moment the
    mirror most needs to know which line is ours is *after* the reminder is deleted.
    Written by `store.async_set_shopping_items`, which fires **no** event and skips an
    unchanged write — internal state, same reasoning as `set_sensor_baseline(silent=True)`.
  - **A failed call is retried, never compensated.** `plan_sync` returns the bookkeeping
    as it reads *once every op succeeded*, and every op carries its `key` so the driver
    can put an entry back when a call raises. Dropping an entry for a remove that never
    happened orphans that line forever.
  - **An unreadable list is not an empty one.** A list absent from `items_by_entity`
    (unavailable, service raised) has nothing planned for it and keeps its tracking; only
    a list that answered is acted on.
  - **`needs_pass` gates the read.** The settle chokepoint fires on every completion and
    stock nudge; most concern no mirrored part, so a pure "has anything drifted" check
    from the two maps decides whether any `todo` service is called at all. The surfaces
    watching the *shopper's* side (the target's state listener, the coordinator's
    periodic `async_schedule_sweep`) force a full pass, since that side is invisible
    from Home Keeper's state.
  - `coordinator.async_settle_buy_tasks` runs the mirror on **both sides** of the
    reconcile and **before** the deferred reload is scheduled: before, so a
    just-completed reminder still exists to tick its line off; after, for whatever the
    reconcile created or retired.
  - Never mirror onto our own to-do list (`own_todo_entity_ids`, the registry-resolved
    generalization of `problem_sync`'s `platform == DOMAIN` guard); it is a loop, and
    ours declares only `UPDATE_TODO_ITEM`. The picker excludes it in both the options
    flow and the panel (`ws_get_options` returns `own_todo_entities`).
  - Every `todo.*` call is best-effort (the `notifier.py` precedent) and `async_sync`
    swallows what reaches it: a pass runs off the back of a completion or a stock
    adjustment and must never be the thing that fails.
- **To-do list sync.** Profile-filtered tasks kept in step with
  *external* `todo.*` lists. **A sync is a profile** — there is no sync record and
  no sync id: a profile carries a `sync` block
  (`{entity_id, two_way, vanish_as_completed}`, normalized by
  `profiles.normalize_sync`) naming the one list it syncs onto, so the config rides
  on the existing panel-managed `profiles` option (**not** in `FLOW_OPTIONS`).
  Clearing `sync.entity_id` is both the off switch and the delete, and one list per
  profile is the cap — a household wanting two lists writes two profiles, which it
  needed anyway to say what goes on each. Same split as the shopping-list sync: pure
  `todo_list.py` (the diff engine, in `only_mutate`, matching items through the
  shared `todo_items.py`) and HA-aware
  `todo_list_sync.py`. It inherits the shopping-list sync's rules verbatim —
  retry-not-compensate, an unreadable list is not an empty one, `needs_pass` gates the
  read, never sync onto our own to-do entity, every `todo.*` call best-effort — plus
  its own. **Both drivers subclass `TodoSyncDriver` (`todo_sync_driver.py`)**, which
  owns the HA-facing machinery they run identically: the re-entrancy guard and pass
  budget in `async_sync` (`_sync_once` is the abstract hook), `_read_lists`,
  `_call`/`_supports`, `_warn_once`, and `_async_stop`/`_handle_state_change`.
  Everything it logs is a `ClassVar[str]` knob (and `_logger`, so a message still
  reads as coming from its own module). Deliberately **not** shared: each planner's
  `plan_sync` semantics, target resolution, `_apply` (only the to-do sync writes
  `due_date`/`description`, capability-gated by `_capabilities`), the listener sets
  (one target vs many plus `_TASK_EVENTS`), the sweep guards, and what an inbound
  tick does. `problem_sync.py` is **not** a subclass — it drives the entity registry,
  not a to-do list. Add a shared method only when both bodies are already identical
  bar a log string:
  - **The profile is both filter and timing.** A sync shows exactly what
    `profiles.matches_filter` selects for that profile (status `overdue` = when due,
    `due_soon` = the 3-day window, `all` = everything scheduled). The driver enriches
    tasks with effective labels first (`notifier.effective_filter_tasks`), so a sync
    agrees with the panel/card. A profile cannot fail to resolve itself, so there is no
    "misconfigured sync" state to hold — don't reintroduce one. Auto-buy reminders
    are excluded: the shopping-list sync owns them, and two syncs must not fight over
    one line.
  - **Bookkeeping is keyed per profile** (`sync_key(profile_id, task_id)`) in the
    storage doc's `todo_list_items`, so two profiles can hold the same task on two
    lists; one `claimed` set spans all of them so they never share one line. Entries
    snapshot the task's `last_completed` at bind time — a live value strictly newer is
    the pure "completed inside Home Keeper since it was synced" detector (an undo therefore
    reads as content drift, never as a tick).
  - **A completed item is never touched, and recurrence adds a fresh one.** Completing
    a task ticks its item off and drops the entry; the next due cycle adds a new item
    beside the old record.
  - **A profile saved before `sync` existed reads back switched off.** `normalize_sync`
    rebuilds the block from a fixed key set and `options.current_options` re-normalizes
    on every read, so that is the whole migration.
  - **Vanish semantics deliberately diverge from the shopping-list sync.** With `two_way`
    and `vanish_as_completed` on, a tracked open item that disappeared completes the
    task — required for providers (Todoist) whose `todo` entity drops completed items —
    but only when the entry captured a `uid` (an add that never confirmably landed is
    re-added, never completed). Otherwise a vanish means deleted → recreate (strict
    self-healing). With `two_way` off the inbound direction is inert and a ticked item
    freezes its entry so phase 2 doesn't re-add against the user's wishes.
  - **Content is capability-gated in the planner**, not the driver: due dates
    (`SET_DUE_DATE_ON_ITEM`, written date-only like our own `todo.py`) and
    descriptions (`SET_DESCRIPTION_ON_ITEM`, carrying the task's notes) are neither
    emitted nor diffed for a list that can't hold them, or every pass would re-plan
    the same update forever.
  - Inbound completions use `origin=ORIGIN_TODO_SYNC` (authorizes nothing);
    `require_tag_scan` tasks reject it by design — the driver warns once and drops the
    entry so a fresh open item reappears, honest feedback that the tick "didn't take".
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
  plain coordinator refresh. **`notes` is the one user-editable field** on a synced
  task (it's not in `managed_by.locked_fields`, and `update_task` isn't gated by the
  synced-task guard) — it's where the user records what to remember next time the
  problem fires. Notes are **durable, keyed by the sensor `entity_id`** in
  `store._problem_notes` (persisted in the storage doc alongside `tasks`/`assets`):
  `update_task` mirrors a synced task's note there, and `reconcile_problem_tasks`
  re-hydrates it onto a freshly built mirror (`notes_by_entity`), so a note outlives
  the task being deleted and recreated (sync toggled, sensor excluded) and reappears
  the next time the same problem fires.
  - **A synced task is an ordinary member of a Profile, and Snooze is the one verb it
    accepts.** `profiles.matches_filter` and its TS twin `card-filter.profileMatches`
    used to drop these outright, so no Profile ever saw one — in the panel, on the card,
    or in a notification (#248). An armed mirror is real overdue work and belongs in the
    filter. Keep a rule like that **out of the filter**: the two matchers are pinned to
    each other by `tests/fixtures/profile_filter_cases.json` and must keep selecting the
    same tasks for the panel, the card and the server.
  - **`snooze_task` is deliberately not gated by `_reject_synced_problem`; `complete_task`
    and `skip_task` still are.** Splitting the guard that way is the point: complete and
    skip both assert the problem is dealt with, which only the originating integration
    can decide, while snooze defers the reminder and leaves the problem standing. It
    also survives the sync — `reconcile_problem_tasks` reads armed as
    `next_due is not None`, so a snoozed mirror stays armed while its sensor is bad and
    still auto-clears when the sensor returns to OK. This is what lets these tasks ride
    in a *walk* notification, which advances only on a successful action:
    `notifications.actions_for` drops complete/skip for a `completion_blocked` task
    (keyed on that marker, the same one every surface uses to hide *Done*, not on the
    `problem_sensor` source) and offers Snooze **even when the notification's own button
    set omits it**, so a walk can never park on one forever. Never offer a button the
    store will refuse: `notifier` swallows the rejection, so it reads as a dead button.
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
  via `store.delete_task`), `shopping_list_entity` (a `todo.*` entity id; `""` =
  off) driving the shopping-list mirror. The to-do list sync has no option of its own —
  its config is the `sync` block inside each profile. Put a new option's default in
  `options.py`'s `_empty_options` **and** its coercion in `_normalize` — both, or the
  key is invisible to every reader and dropped by every writer — then add it to all
  three surfaces (flow schema *and* `FLOW_OPTIONS`, `SET_OPTIONS_SCHEMA`, Settings
  `settingsSchema`) with `strings.json`/`services.yaml` parity. `tests/unit/test_options.py`
  fails the build if a `const.OPTION_*` misses either half.
  - **The options *flow* merges; it never replaces.** Home Assistant stores whatever
    an options flow returns from `async_create_entry` as `entry.options` **verbatim**
    — the whole object, not a patch. The Configure dialog renders only
    `options.FLOW_OPTIONS`; `profiles` (to-do list sync included),
    `notifications` and `dismissed_companions` are
    panel-only, so returning `user_input` deleted every one of them on each save, and
    notifications then stopped firing with nothing on screen to say why (`notifier`
    reads a missing key back as `[]`). `async_step_init` returns
    `options.merge_flow_input(entry, user_input)`, which starts from `current_options`,
    resets any `FLOW_OPTIONS` key the submission *omits* — that absence is how clearing
    the `shopping_list_entity` picker turns the mirror off, and it's the one field with
    no voluptuous `default` for exactly that reason — routes everything through
    `_normalize`, and touches nothing else. Guarded at three levels:
    `tests/unit/test_options.py` (every `const.OPTION_*` reaches `_empty_options` and
    `_normalize`; `strings.json`'s labels match `FLOW_OPTIONS`),
    `tests/unit/test_config_flow.py` (the form's schema keys equal `FLOW_OPTIONS`, and
    the shopping picker still has no `default`), and
    `tests/integration/test_options_flow.py` (a real save over HA's flow API leaves the
    panel-only keys byte-identical — the framework contract no mock can see).
  - **A single-value picker needs a clear-coercion on the panel side.** `ha-form`'s
    entity selector emits `undefined` when cleared, and JSON drops it — so the key
    never reaches `_normalize`'s `if key in updates` merge and "turn it off" silently
    doesn't stick. `_settingsCard` takes an optional `coerce` for exactly this. The
    existing multi-select options emit `[]` and never hit it, which is why the trap
    went unnoticed until the first scalar picker.
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
  physical); DO set `configuration_url` (an `appliances/<asset_id>` deep link — see
  "Entities & devices"). Validate `area_id` at the HA boundary (`devices.area_exists`),
  never in the pure model. See `IDEAS.md` / `docs/DESIGN.md`.
- **Archiving is a visibility flag, not a device/entity teardown.** `archived_at`
  (an ISO timestamp, `None` when active) is a **backend-managed** field on the asset
  dict — like `created`/`identifiers` — so it's set only by `store.archive_asset`/
  `restore_asset`, never through `_ASSET_FIELDS`/`normalize_fields`/`merge_update`
  (the generic `add_asset`/`update_asset` field set). It gets its own dedicated
  service + websocket-command pair and its own events
  (`home_keeper_asset_archived`/`_restored`), exactly like `delete_asset` is
  dedicated rather than routed through `update_asset` — archiving is a distinct
  lifecycle action, not a field edit. Archiving does **not** remove the device
  registry entry, its entities, or affect attached tasks — those keep running so
  history stays intact; the panel just filters archived assets out of the default
  Appliances list (an `active`/`archived` toggle, mirroring the task filter
  segment). `delete_asset` remains available on an archived asset for permanent
  removal.

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

## Notification payload text is localized (notifications.py)
- Actionable mobile notifications are delivered straight to the mobile app, outside
  HA's own frontend translation loading — so unlike exceptions (which the frontend
  resolves lazily via `translation_key` when it renders them), the button labels,
  titles, and body text must be resolved **eagerly, in Python, at send time**. These
  strings do **not** live in `strings.json`/`translations/<lang>.json` — hassfest
  validates that tree against a fixed set of categories (`config`, `services`,
  `entity`, …) and rejects an unrecognized top-level key (`extra keys not allowed`),
  confirmed the hard way in CI. Instead they're bundled as flat dotted-key
  `notification_strings/<lang>.json` files (one per locale, mirroring
  `frontend/src/locales/*.json`'s convention for the panel — flat `"key.category":
  "..."` entries, not nested objects), with their own parity test
  (`test_notification_strings_parity.py`) rather than `strings.json`'s. Every such
  string is defined there; `notifications.py`'s private `_t`/`_tn` helpers read the
  files directly (no HA import — the module stays pure) and interpolate `{token}`
  placeholders. All the builder functions (`build_notification`, `build_digest`,
  `build_all_clear`, `_action_button`, `_overdue_phrase`) take a `lang` keyword
  (default `"en"`, so callers/tests that omit it keep working); `notifier.py` is the
  only caller that passes a real value, `hass.config.language`.
- Pluralized strings (`overdue`, `digest_title`, …) are stored as `<key>.one`,
  `<key>.few`, `<key>.many`, `<key>.other` — always all four regardless of whether a
  given locale's grammar uses them (identical `other` filler for `few`/`many` in an
  English-shaped locale is fine — it's simply never selected) — this keeps every
  locale's key set identical, which `test_locale_key_parity` requires. The category
  is picked by `_tn` via `Babel`'s CLDR plural rules (`Locale(lang).plural_form(n)`),
  the backend counterpart to `frontend/src/i18n.ts`'s browser-native
  `Intl.PluralRules`. Babel is the
  integration's **first Python runtime dependency** (`manifest.json` `requirements`),
  a deliberate exception to "ship none" — getting Polish/Russian/Czech plural
  categories right by hand is exactly the kind of thing not worth re-deriving.

## Eagerly-resolved backend text (backend_i18n.py, backend_strings/)
- `translation_key` (above) is **lazy** — the frontend resolves it to text only when
  it renders an error, in the viewer's own language. Two surfaces need the *final
  string* immediately, server-side, because nothing downstream localizes it later:
  the websocket API's `connection.send_error(id, code, message)` (`websocket_api.py`)
  and the document-upload HTTP views' `self.json_message(message, status)`
  (`manuals.py`) — both display `message` verbatim to the user. Route these through
  `backend_i18n.resolve_exception(hass.config.language, key, **placeholders)` (reads
  the *same* `exceptions` category in `strings.json`/`translations/<lang>.json` —
  reuse an existing key where the concept matches, e.g. `task_not_found`,
  `invalid_task`) rather than a literal string. `websocket_api.py`'s `_err`/
  `_not_loaded` helpers do this for every command; never call
  `connection.send_error`/`json_message` with a bare string — a pure-AST drift-guard
  (`tests/unit/test_backend_error_surface_translations.py`, mirroring
  `test_exception_translations.py`) fails the build on one.
- A handful of backend-generated strings that aren't exceptions at all — the
  problem-sensor sync's `completion_prompt`, a companion catalog suggestion's
  `description`, the inventory CSV column headers — have no home in `strings.json`
  either (hassfest rejects an unrecognized top-level category there). These use
  `backend_i18n.resolve_string(lang, key, **params)` against a separate flat
  dotted-key bundle, `backend_strings/<lang>.json` (16 locales, own parity test
  `tests/unit/test_backend_strings_parity.py`), the same convention
  `frontend/src/locales/*.json` uses for the panel. A pure module that needs one of
  these (`problem_tasks.py`, `inventory.py`, `companions_catalog.py` are all
  HA-import-free) takes `lang: str = "en"` as a plain parameter rather than reading
  `hass` itself — the HA-aware caller (`store.py`, `websocket_api.py`,
  `companions.py`) threads `hass.config.language` in, the same pattern
  `store.reconcile_part_tasks` already established for wear-part task names.
- **Warm the tables in the executor before anything asks for a string.**
  `backend_i18n` has no HA import by design, so it cannot dispatch its own reads the
  way `notifier.py` does (#150) — and its `functools.cache` only helps *after* the
  first read, which lands on whichever loop-bound caller gets there first (the
  problem-sensor reconcile during setup, a websocket error reply, a CSV export). HA's
  blocking-call detector logs every one of those as `Detected blocking call to
  read_text ... inside the event loop` (#247). `async_setup_entry` runs
  `backend_i18n.preload` through `hass.async_add_executor_job` before it touches the
  store, so every later `resolve_*` is a cache hit; `preload` always warms English
  alongside the requested language, because that is the fallback both resolvers
  reach for. Add a table to this module and you add it to `preload` —
  `tests/unit/test_backend_i18n_preload.py` checks *every* cached table, and
  `tests/integration/test_event_loop_blocking.py` reads HA's own log back to catch
  anything the unit lane can't see.

## Companion discovery (implemented)
- Home Keeper surfaces integrations that work with it in the panel's **Settings →
  Companions** section. Two paths feed one registry — keep them separate:
  - **Push / self-registration.** A Home-Keeper-aware integration announces itself via
    the `home_keeper.register_companion` service (Pawsistant, the Battery Notes glue).
    Home Keeper stores the descriptor **verbatim** and never imports the companion —
    same opacity rule as `source`. The registry is in-memory on `hass.data`
    (`DATA_COMPANIONS`), best-effort, rebuilt on restart as companions re-announce.
  - **Pull / catalog detection.** A tiny curated catalog (`companions_catalog.py`,
    pure) maps a *popular* upstream (e.g. `battery_notes`) to the glue that bridges it,
    so Home Keeper can **suggest** the glue when the upstream is installed but the glue
    isn't. Keep the catalog short and high-signal; the merge logic is pure and
    unit-tested (`tests/unit/test_companions.py`).
- The merge (`companions_catalog.build_companion_list`) is HA-free and pure; the
  HA-facing registry + event firing live in `companions.py`. Detection is computed
  on demand (no background poller) by scanning `hass.config_entries`.
- Re-announce handshake: Home Keeper fires `home_keeper_register_companions` at setup
  (and on reload); companions both register at their own setup *and* listen for that
  ping, so discovery works regardless of startup order.
- New events (`home_keeper_companion_connected` / `_suggested`) are edge-triggered and
  deduped per domain in the registry; documented in `docs/EVENTS.md`.
- The "Configure" action **deep-links by domain to the companion's integration page**
  (`/config/integrations/integration/<domain>`) — the same helper as the "Edit in X"
  managed-task link (`panel._navigateToIntegration`). There's no stable public API to
  pop an options *dialog* directly from a custom panel, so the integration page (where
  Configure is one click away) is the deep link; the descriptor still carries
  `config_entry_id` for future use. Home Keeper does **not** reimplement a companion's
  settings — ownership stays with the companion. Don't add inline companion settings
  without an explicit decision.
- The two new services (`register_companion`, `list_companions`) are
  developer/automation-facing; their English names live in `services.yaml` (no
  `strings.json`/16-locale parity entries, unlike user-facing UI strings). The panel
  Companions strings ARE user-facing and are localized in the frontend `locales/`.

## Integration-provided task chips (`task_chips`)
- A task may carry an optional `task_chips` list — an array of `{label, icon?, url?}`
  objects set **exclusively by the integration that owns the task** (not user-editable
  in the panel). The field is normalized in `models.normalize_task_chips` and carried
  through `build_task` / `merge_update`. Validated constraints: `label` is a non-empty
  string; `icon` (if present) must start with `"mdi:"`; `url` (if present) must be an
  `http://` or `https://` URL. Empty-label entries are silently dropped.
- Chips are rendered in **both** the panel task list and the dashboard card (using
  `<ha-assist-chip>`), alongside the managed-by chip, area chip, and label chips. A
  chip with a `url` is wrapped in `<a class="hk-task-chip-link">` (`display: contents`
  makes the anchor transparent to flexbox layout while preserving native link behavior).
  They are intentionally **not** shown in the panel task-edit form — the owning
  integration controls them, not the user.
- `task_chips` is distinct from `card_links` (which resolves appliance document links
  at render time from the asset library, is user-configurable in the panel, and is
  card-only). Use `task_chips` when an integration needs to surface direct metadata
  alongside the task on all UI surfaces; use `card_links` when the task is attached to
  an appliance and you want to link its manuals/documents.
- A third, distinct mechanism: `task.source.part = {asset_id, part_id[, manual]}`
  links a task to a specific **part** (an auto-generated wear-item task, or a
  manually-linked consumable via `set_task_consumable`) — this is not a chip list,
  just a pointer resolved at render time. The panel's task-detail "Consumable link"
  row (`_consumableLinkLabel`) and the dashboard card's task row
  (`_resolvePartLink`) both resolve it against the loaded asset library and render
  the part's name as a clickable link **when the part has a `url`** (falling back to
  plain text in the panel; the card shows no chip at all when there's no link, since
  its docs row is specifically for openable links). Both call sites duplicate the
  `asset_id`/`part_id` lookup rather than sharing a helper because they live in
  different files (`panel.ts` vs `card.ts`) with no existing shared "resolve a task's
  part" module — if a third surface needs this, extract one then.
- See `docs/INTEGRATING.md` "Attaching metadata chips to a task (`task_chips`)" for
  the full external-integrator API, schema, and example service calls.

## Deferred: cross-integration contribution API
- The stable interface for other integrations (e.g. Battery Notes) to contribute
  tasks via a dedicated upsert/reconcile service is intentionally **not implemented
  yet** — contributors use the existing `add_task` + event contract (and now
  `register_companion` for discovery). Only the documented hook point
  `const.SIGNAL_TASK_CONTRIBUTION` remains reserved. Do not build the fuller
  contribution service without an explicit decision; see `IDEAS.md` / `docs/DESIGN.md`.
