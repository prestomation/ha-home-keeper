---
title: Events and API surface
summary: The events, triggers, services and websocket commands, and their model.
implements:
  - custom_components/home_keeper/events.py
  - custom_components/home_keeper/logbook.py
  - custom_components/home_keeper/caller.py
  - custom_components/home_keeper/transitions.py
  - custom_components/home_keeper/device_trigger.py
  - custom_components/home_keeper/trigger.py
  - custom_components/home_keeper/trigger_targets.py
  - custom_components/home_keeper/triggers.yaml
  - custom_components/home_keeper/icons.json
  - custom_components/home_keeper/api_surface.py
  - custom_components/home_keeper/resolve.py
  - custom_components/home_keeper/service_errors.py
  - custom_components/home_keeper/websocket_api.py
  - custom_components/home_keeper/services.yaml
  - custom_components/home_keeper/testing.py
related: [architecture, store, coordinator-entities, appliances, profiles-notifications]
source_hash: 901ed9dcb0e9
---

# Events and API surface

Services (`home_keeper.*` actions) change or export data. Bus events
(`home_keeper_<noun>_<verb>`) report each change after it occurs. The panel uses websocket
commands, which call the same store methods. `api_surface.py` declares all of these
surfaces, and tests compare that model with the source.

Payloads: [EVENTS.md](../EVENTS.md). Integration contract: [INTEGRATING.md](../INTEGRATING.md).
Privileges: [SECURITY.md](../SECURITY.md).

## Goals

- **G1. One action, one service.** Each operation that changes or exports data is a
  service. A websocket command is an optional fast path to the same store method.
- **G2. One event per state change.** Every path that changes a task, appliance, part or
  companion fires an event, whatever surface started the change.
- **G3. Announce a crossing once.** Overdue, due soon and stock crossings fire 1 time per
  crossing. A restart or a reload does not replay old crossings.
- **G4. Device triggers.** A user picks a trigger on a device page, not an event name.
- **G5. A declared surface.** One model lists every surface, and a test catches drift.
- **G6. Usable by hand.** A `*_id` field accepts a name or an id. Errors are localized.
- **G7. A fake for integrators.** Integrations test against the real payload builders.

## Non-goals

- Data changes are in `store`, the refresh and entities in `coordinator-entities`, and
  notifications on crossings in `profiles-notifications`.
- There are no device conditions and no device actions. `api_surface.SURFACE_KINDS` gives
  the reason for each kind of surface that Home Keeper does not offer.

## Design

### Payload builders

`events.py` has no Home Assistant imports. Each builder, such as `events.task_event_data`,
returns the dict for the bus. All task events share 1 spine, so 1 template works for all.
Per-event keys (`changed_fields`, `days_overdue`) merge on top through `extra`.

`store.py` fires through `_fire` at each mutation point, never in a handler, also on the
wear-part reconcile and the appliance delete cascade. An update that changes no field fires
no event. `_fire` gives the event the context of `caller.current()`: the service call,
websocket command, upload or entity action that made the change, so the logbook names the user.
A change that Home Keeper makes on its own gets a new context. Entry setup runs with no caller,
so the timers of a reload that a service started do not keep its user.
`transfer_runner.py` fires the export and import summary events ([transfer](transfer.md)).
`logbook.py` describes each event in `events.LOGBOOK_EVENTS`. It matches the spine `entity_id`
(the to-do list) and `device_id`. A completion row names its day if the row fired on another day.

### Edge-triggered transitions

`transitions.detect_transitions` is pure. It takes the previous edge state, the task map
and an injected `now`, and returns the events plus the next state. The state per task is
`{"next_due", "due_soon_fired", "overdue_fired"}`. A changed `next_due` clears both flags,
but `due_soon_fired` stays true if the old date announced and the new one is in the window.
No `next_due`, or disabled: nothing fires. `DUE_SOON_WINDOW` is 3 days.
`coordinator._async_update_data` runs the detector on each periodic and post-mutation
refresh. Until setup calls `coordinator.enable_transition_events`, it keeps the detected
state as a silent baseline. The edge state lives in `hass.data` per config entry, so a
reload keeps it. `transitions.auto_crossings` drops a due-soon crossing that a snooze or a
completion caused, before notifications use the list.
`assets.stock_transition` gives the stock crossings. `out` wins over `low`, so a drop to 0
fires only `home_keeper_part_out_of_stock`. A part with no `reorder_at` never fires.

### Triggers

`trigger.py` gives 1 trigger (`home_keeper.<key>`) for each `api_surface.TRIGGERS` entry:
each fired event with a payload. `triggers.yaml` and `icons.json` describe them to the
editor. A task, part or appliance trigger requires a target. Each trigger listens on its
bus event. `trigger.resolve_target` resolves the target with the Home Assistant target
helper for each event, and the pure `trigger_targets.matches` applies the rule of the
payload: a task matches by its entities, `device_id`, `area_id` or `labels`.
`device_trigger.py` builds its maps from `api_surface.triggers_for`. It filters the event
on `task_id` for a self-owned task device `(home_keeper, <task_id>)`, else on `device_id`.
`device_trigger._attach_filter` reads only the device registry, because automations attach
at startup, often before the entry loads. `event.py` mirrors events onto 1 event entity.

### Services and websocket commands

`__init__._register_services` runs 1 time, from `async_setup`; a reload removes no service.
With no loaded entry, a handler raises `integration_not_loaded`. Read services use
`SupportsResponse.ONLY`. `services.yaml` and `strings.json` hold labels.
`websocket_api._with_coordinator` finds the coordinator and maps store errors to codes.
`backend_i18n.resolve_exception` localizes the text, as a websocket error gets no later
translation. Each `WebsocketSpec` names its service twin, except the panel tab list and the
reads `get_options` and `get_spend`. `sign_task_photo_urls` signs a list of photos.
An admin-only operation has 2 gates: `@websocket_api.require_admin` on the command, and
`await _verify_admin(call)` first in the service handler. A call with no user is trusted.

### Name or id, and errors

`resolve.resolve_task_id` tries an exact id, an exact name, then a trimmed, case-folded name.
Parts and documents resolve only inside 1 resolved appliance. More than 1 match raises
`resolve.AmbiguousName` with every candidate id. No match returns the key, so the error
quotes the user's text. A delete of an unknown uuid succeeds (`resolve.looks_like_id`).
`service_errors.store_errors` turns a store error into a `ServiceValidationError`. The
innermost id picks the key: `unknown_task_photo` or `unknown_part` first.

### The declared surface

`api_surface.py` imports only `const`. Its tables (`SERVICES`, `EVENTS`, `TRIGGERS` and others)
hold names and structure only, plus `summary` texts. `tests/unit/test_api_surface.py` checks
the source against the model with `ast`, and `tests/integration/test_api_surface.py` checks a
running instance. `ci/generate_api_docs.py` renders the API page from the model.

`testing.async_setup_fake_home_keeper` registers a `FakeHomeKeeper` under the real service names.
It uses `models.build_task` and the `events.py` builders, but no overdue events.

## Trade-offs

- **Fire from the store** over **from the handlers**: every surface reaches 1 method.
- **Silent baseline at startup** over **saved edge state**: no overdue storm after a
  restart, no storage write per tick. A crossing during downtime is not announced.
- **Home Keeper triggers** over **an event entity on each device**: the Add trigger dialog
  of Home Assistant 2026.7 lists only these by target, and 2026.8 offers device triggers
  only on Home Keeper's own devices. A trigger works on each device from 2026.1 and reads
  the bus, so a reload loses no event. Cost: the trigger API is young.
- **A context variable** over **a context argument on each store method**: no API changes.
- **Ambiguity raises** over **first match wins**: names are not unique; deletes must not guess.
- **Text in string files** over **text in the model**: the reference and the UI read 1 string.

## One-way doors

- Event names, each payload key in `PAYLOAD_SPINES`, the logbook text and the caller context.
- Device trigger `type` values and trigger keys (`home_keeper.<key>`), which user
  automations store. What a target means for each payload, and the `event` variable.
- Service names, field names, and the name-or-id form of each `*_id` field.
- The `testing.py` entry point and the `FakeHomeKeeper` helper names.
