---
title: Architecture rules
summary: The admin and usage split, the privilege gate, the pure core, entities, options and localized text.
---

# Architecture rules

How the integration is built is in [docs/design/architecture.md](../../docs/design/architecture.md).
This file gives the rules for code that changes it.

## Administration and usage

- **Administration lives in the panel.** Task and appliance create, edit and delete,
  recurrence settings and device links belong there. Never put management UI in a card.
- **Usage goes through native entities**: the `todo` list, the `calendar`, and the
  per-task `button`, `sensor` and `binary_sensor` entities. Prefer them and Home
  Assistant's own cards to a custom usage card.
- All task mutations go through `HomeKeeperStore`. Entities and the panel read through
  `HomeKeeperCoordinator` and never write storage.

## Privilege model

The admin and usage split is also the security boundary ([SECURITY.md](../../docs/SECURITY.md)).

- The panel is registered with `require_admin=True`. A command that only the panel uses
  is administration.
- **Gate both halves of an admin-only operation.** Put `@websocket_api.require_admin` on
  the websocket command, and call `_verify_admin(call)` in its service handler. A gate on
  the command alone is no gate: `call_service` goes around it. The list of gated
  operations is in the architecture design doc. Add a new admin operation to that list.
- A call with no `context.user_id` comes from an automation or the core and is trusted.
- Raise the bare `Unauthorized`. It is the 1 exception to localized exceptions, and the
  websocket and REST layers map it to `unauthorized` and 401.
- Usage stays open: task reads, create, edit, delete, complete, snooze and skip, task
  photos, profiles, companions, and the card's reads.
- **An appliance read projects for a non-admin.** A non-admin gets
  `assets.card_projection`, a whitelist of the fields that the card shows. A new field is
  private until someone adds it to the whitelist. A mutation that echoes the whole asset
  is admin-gated.
- **Allowlist notify targets where they are stored.** `notifications.split_targets` keeps
  `mobile_app_*` and `persistent_notification` and drops the rest. A rejected `target:`
  on `home_keeper.notify` fails the call.
- Serve only built assets (`frontend/dist/`) as a static path. Home Assistant serves
  static paths before authentication.

### How to decide

Use this list for each new service, websocket command, HTTP method and event. Write the
result in the plan's Security section ([pr-workflow.md](pr-workflow.md)).

- **Open: a task and its data.** A field, file or list on a task follows the task. A user
  who can create a task can also edit it, delete it and add its photos.
- **Open: a read that the card or a native entity needs.**
- **Admin-only: appliances and parts.** They own Home Assistant devices, and they hold
  costs and serial numbers.
- **Admin-only: settings, profiles and notification delivery**, and each operation that
  can send text to a place the caller cannot reach.
- **Admin-only: bulk and whole-store operations**: the orphan delete, import, export and
  the appliance report.
- **Admin-only: each operation that shows what Home Assistant hides from a user**, such
  as a template preview or an entity registry list.
- **A reply never leaks.** A reply holds only data that the caller can already read. If
  the reply would leak, project it or gate the operation.
- **An upload always needs a real user.** A signed URL never writes.
- **If no rule fits, ask the maintainer.** Write the answer in the plan, then add the rule
  here.

## Pure core

- The pure modules never import `homeassistant`. The module map in the design doc lists
  them. Pass in the time and the time zone from the caller.
- Recurrence functions take an explicit `now`. They never read a clock.
- `options.py` and `device_compat.py` import HA only under `TYPE_CHECKING`, so their unit
  tests run without the HA harness. Keep it that way.
- All datetimes are timezone-aware. Use `homeassistant.util.dt` at the HA boundary.
- **Qualify a naive wall-clock value** (from `<input type="datetime-local">`) with
  `dt_util.now().tzinfo` through `replace(tzinfo=...)`. Never shift it with `astimezone()`
  and never leave it naive.

## Entities and devices

How the entities work is in [coordinator-entities](../../docs/design/coordinator-entities.md).

- Entity `unique_id`s are anchored to the task `id`, so they survive a rename.
- Per-task device entities exist only for **enabled, device-attached** tasks
  (`coordinator.device_attached_task_ids()`). `todo` and `calendar` skip disabled and
  **dormant** tasks (`next_due is None`).
- **A surface that lists tasks needs an explicit dormancy skip.** Only a surface that
  compares `next_due` gets it for free.
- **Link an entity to a device through `device_entry`.** Never create a second device for
  hardware that another integration owns, and never copy its identifiers.
- **On a foreign device, add entities only.** Never write its metadata or its
  `configuration_url`. Enrich only Home Keeper's own virtual appliance devices.
- A virtual device's `configuration_url` is `homeassistant://home-keeper/appliances/<id>`,
  with no `navigate/` segment. Do not set `entry_type=service` on an appliance device.
- On `update_task`, reload the entry only when `task_entities.entity_set_key` changes.
  Otherwise refresh the coordinator. `add_task` and `delete_task` of a task with
  entities reload.
- **Read the device registry only through `device_compat.py`.** HA 2026.9 can answer with a
  `ChildDeviceEntry`, and `DeviceRegistry.devices` changed shape. A child device is a valid
  link target. Add a helper there for each new attribute that you read.
- Validate `area_id` at the HA boundary (`devices.area_exists`), never in the pure model.

## Options

- `options.py` owns every option key, default and coercion. Add a new option to
  `_empty_options` **and** `_normalize`, then to all 3 surfaces: the flow schema and
  `FLOW_OPTIONS`, `SET_OPTIONS_SCHEMA`, and `settingsSchema` in `forms.ts`, with
  `strings.json` and `services.yaml` parity. `tests/unit/test_options.py` fails on a gap.
- **The options flow merges. It never replaces.** Return
  `options.merge_flow_input(entry, user_input)` from `async_create_entry`, never
  `user_input`. HA stores the result as the whole options object, so a raw return deletes
  every panel-only key (profiles, notifications, dismissed companions).
- The `set_options` service is the canonical write path. It awaits the reload, so the
  change is in effect when the call returns.
- A single-value picker in the panel needs a clear coercion: `ha-form` emits `undefined`
  on clear, and JSON drops it.

## Localized text

- **Every user-facing exception is localized.** Construct `ServiceValidationError` and
  `HomeAssistantError` with `translation_domain=DOMAIN` and a `translation_key` in
  `strings.json` `exceptions`. Never raise with an f-string.
  `tests/unit/test_exception_translations.py` fails on one.
- **Resolve websocket and HTTP error text eagerly.** `connection.send_error` and
  `json_message` show the message as is. Use `backend_i18n.resolve_exception` through the
  `_err` helpers in `websocket_api.py`. Never pass a bare string.
- Text that is not an exception and has no place in `strings.json` (a completion prompt,
  a catalog description, CSV headers) uses `backend_i18n.resolve_string` and
  `backend_strings/<lang>.json`. A pure module takes `lang: str = "en"` as a parameter.
- **Load the tables in the executor before the first read.** `backend_i18n.preload` runs
  in `async_setup_entry`. Add each new table to `preload`.
- **Notification text is resolved in Python at send time**, from
  `notification_strings/<lang>.json`, because the phone gets it outside the frontend.
  hassfest rejects a new top-level category in `strings.json`, so these files are separate.
  Store each plural as `.one`, `.few`, `.many` and `.other` in every locale.
- Babel is the 1 Python runtime dependency, for CLDR plural rules.

## Profile filters

- **A profile filter is `{status, groups}`. Groups are the only shape.** A task matches
  the profile when it matches 1 active group. `profiles.matches_filter` and its TS twin
  `card-filter.profileMatches` read only `groups`.
  `tests/fixtures/profile_filter_cases.json` keeps the 2 in step.
- The v1 to v2 config-entry migration (`profiles.migrate_options_v1`) converts the flat
  keys once. `set_options` refuses them. A v1 reader refuses a v2 entry, so a downgrade
  needs a backup.
- The card is the 1 place that reads the old shape. `setConfig` lifts `labels`, `areas`,
  `devices` and `label_match` into `groups[0]`, because HA cannot rewrite a dashboard.

## Notification delivery

Details are in [profiles-notifications](../../docs/design/profiles-notifications.md).

- **Store a delivery field once, in Home Keeper's own words.** Every payload builder goes
  through `notifications.payload_data`, which writes both the Android and the iOS keys.
  Do not branch per target.
- An unset delivery field sends no key. Keep each new field to that rule.
- Never send `notification_icon_color`: Android reads it before `color`. Read the
  companion app source before you trust its docs about a payload key.
- A field that does nothing on 1 platform says so in its label and helper text.
- `normalize_icon` and `normalize_color` clamp a bad value to `""`. They never pass it on.

## Companions and contributions

- Companions are described in [companions-presets](../../docs/design/companions-presets.md).
  Store a self-registered descriptor as is, and never import a companion.
- Keep the companion catalog short. Do not add inline settings for a companion: the
  Configure link opens the companion's own integration page.
- A declarative companion is only called a declarative companion, never a recipe. In
  code, "spec" names its stored form.
- The dedicated upsert service for contributed tasks is not built. Contributors use
  `add_task` and the events. `const.SIGNAL_TASK_CONTRIBUTION` is the reserved hook. Do not
  build it without a decision (see `IDEAS.md`).
