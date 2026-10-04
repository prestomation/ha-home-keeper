---
title: Events and API surface
summary: The events, device triggers, services and websocket commands, and their model.
implements:
  - custom_components/home_keeper/events.py
  - custom_components/home_keeper/transitions.py
  - custom_components/home_keeper/device_trigger.py
  - custom_components/home_keeper/api_surface.py
  - custom_components/home_keeper/resolve.py
  - custom_components/home_keeper/service_errors.py
  - custom_components/home_keeper/websocket_api.py
  - custom_components/home_keeper/services.yaml
  - custom_components/home_keeper/testing.py
related: [architecture, store, coordinator-entities, appliances, profiles-notifications]
source_hash: 604e25b5225d
---

# Events and API surface

Services (`home_keeper.*` actions) change or export data. Bus events
(`home_keeper_<noun>_<verb>`) report each change after it occurs. The panel uses websocket
commands, which call the same store methods as the services. `api_surface.py` declares
all of these surfaces, and tests compare that model with the source.

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

`events.py` has no Home Assistant imports. Each builder returns the dict for the bus, for
example `events.task_event_data` (the task spine) and `events.stock_event_data`. All task
events share 1 spine, so 1 automation template works for all of them. Per-event keys
(`changed_fields`, `days_overdue`, `due_in_hours`) merge on top through `extra`.

`store.py` fires at each mutation point, never in a handler, also on the wear-part
reconcile and the appliance delete cascade. An update that changes no field fires no event.

### Edge-triggered transitions

`transitions.detect_transitions` is pure. It takes the previous edge state, the task map
and an injected `now`, and returns the events plus the next state. The state per task is
`{"next_due", "due_soon_fired", "overdue_fired"}`. The flags are separate because a task
crosses due soon and then overdue against the same `next_due`. A changed `next_due` clears
both flags. A task with no `next_due`, or a disabled task, fires nothing.
`transitions.DUE_SOON_WINDOW` is 3 days, the same as the binary sensor attribute.

`coordinator._async_update_data` runs the detector on each periodic and post-mutation
refresh. Until setup calls `coordinator.enable_transition_events`, it keeps the detected
state as a silent baseline. The edge state lives in `hass.data` per config entry, so a
reload keeps it. `transitions.auto_crossings` drops a due-soon crossing that a snooze or a
completion caused, before notifications use the list.

`assets.stock_transition` gives the stock crossings. `out` wins over `low`, so a drop to 0
fires only `home_keeper_part_out_of_stock`. A part with no `reorder_at` never fires.

### Device triggers

`device_trigger.py` builds `TASK_TRIGGERS` and `ASSET_TRIGGERS` from `api_surface.triggers_for`.
`device_trigger.async_attach_trigger` wraps the event trigger with a filter on the data:

| Device | Identifier | Filter |
|---|---|---|
| Self-owned task device | `(home_keeper, <task_id>)` | `task_id` |
| Appliance device | `(home_keeper, asset_<id>)` | `device_id` |
| Other device with tasks attached | foreign | `device_id` |

A standalone task has `device_id: null` in its payload, so its device filters on `task_id`.
`device_trigger._attach_filter` reads only the device registry, because automations attach
at startup, often before the entry loads. `device_trigger._filters` reads the coordinator,
but only to choose which triggers to offer.

### Services and websocket commands

`__init__._register_services` runs 1 time, from `async_setup`, and a reload removes no
service. With no loaded entry, a handler raises `integration_not_loaded`. Read services
use `SupportsResponse.ONLY`. `services.yaml` and `strings.json` hold all labels.

`websocket_api._with_coordinator` finds the coordinator and maps store exceptions to error
codes. `backend_i18n.resolve_exception` localizes the text, because a websocket error gets
no later translation. Each `WebsocketSpec` names its service twin, if there is one.
`home_keeper/sign_task_photo_urls` signs a list, and its twin signs 1 photo.

An admin-only operation has 2 gates: `@websocket_api.require_admin` on the command, and
`await _verify_admin(call)` first in the service handler. A call with no user is trusted.

### Name or id, and errors

`resolve.resolve_task_id` tries an exact id, then an exact name, then a trimmed, case-folded
name. Parts and documents resolve only inside 1 resolved appliance. More than 1 match
raises `resolve.AmbiguousName`, and the error lists every candidate id. No match returns
the key unchanged, so the not-found error quotes the user's text. A delete of an unknown
uuid succeeds (`resolve.looks_like_id`).

`service_errors.store_errors` turns a store `KeyError`, `TaskValidationError` or
`AssetValidationError` into a `ServiceValidationError` with a translation key. The
innermost id given picks the key: `unknown_task_photo` or `unknown_part` before
`asset_not_found`.

### The declared surface

`api_surface.py` imports only `const`. Its tables (`SERVICES`, `EVENTS`, `PAYLOAD_SPINES`,
`DEVICE_TRIGGERS`, `WEBSOCKET_COMMANDS` and others) hold names and structure only. The one
text field is `EventSpec.summary`, because a bus event has no string in `strings.json`.
`tests/unit/test_api_surface.py` parses the source with `ast` and checks the services,
events, payload keys, websocket commands, views and admin gates against the model.
`tests/integration/test_api_surface.py` checks a running instance, and
`ci/generate_api_docs.py` renders the Developer Guide API page from the model.

`testing.async_setup_fake_home_keeper` registers a `FakeHomeKeeper` under the real service
names. It uses `models.build_task` and the `events.py` builders, but no overdue events.

## Trade-offs

- **Fire from the store** over **from the handlers**: every surface reaches 1 method.
- **Silent baseline at startup** over **saved edge state**: no overdue storm after a
  restart, and no storage write per tick. A crossing during downtime is not announced; the
  binary sensors still show the state.
- **Device triggers** over **an integration-level trigger platform**: users look on the
  device page. Global automations use a plain `platform: event` trigger.
- **Ambiguity raises** over **first match wins**: names are not unique; deletes must not guess.
- **Text in string files** over **text in the model**: the reference and the UI read 1 string.

## One-way doors

- Event names and every payload key in `PAYLOAD_SPINES`.
- Device trigger `type` values, which user automations store.
- Service names, field names, and the name-or-id form of each `*_id` field.
- The `testing.py` entry point and the `FakeHomeKeeper` helper names.
