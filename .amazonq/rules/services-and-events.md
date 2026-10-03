---
title: Services and events rules
summary: How to add a service, a websocket command, an event or another surface that integrators use.
---

# Services and events rules

How the surfaces work is in [events-api](../../docs/design/events-api.md). Integrators read
[INTEGRATING.md](../../docs/INTEGRATING.md) and [EVENTS.md](../../docs/EVENTS.md).

## Services are the contract

- **Every action that changes or exports Home Keeper data is a `home_keeper.*` service.**
  This covers task and appliance CRUD, exports, stock adjustments and each new action.
  Automations, scripts, voice and other integrations build on services. A websocket
  command is only a UI speed-up and never replaces a service.
- **A new action is a service first.** Write the handler in `__init__.py`, register it in
  `_register_services`, add a `services.yaml` entry, and add `strings.json` text with
  parity in every `translations/<lang>.json`. A websocket command, if any, calls the same
  `HomeKeeperStore` method. Never give it a second code path.
- A websocket command is optional. If the service already does what the panel needs, the
  panel can call it through `call_service` with `return_response: true`. Settings,
  Notifications, **Test** (`api.runNotification`) does this on purpose.
- **Register services once, in `async_setup`, and never remove them.** A reload unloads the
  entry. A handler finds the coordinator for each call and raises the localized
  `integration_not_loaded` while no entry is loaded.
- A read-only or report service uses `SupportsResponse.ONLY`. A mutation reloads or
  refreshes exactly as the matching CRUD service does.
- A service or websocket call that starts a reload in the background waits for it before it
  answers, so the caller's next call does not meet an unloaded entry.

## Name or id

- **Every `*_id` service field accepts a name as well as an id, id first.** Keep it 1
  field. Never add a `task_name` field beside `task_id`, and never rename the key.
- `resolve.py` does the lookup: exact id, then exact name, then a trimmed, case-folded
  name. Parts and documents resolve inside their resolved appliance. The handlers wrap it
  with `_task_ref`, `_asset_ref`, `_part_ref` and `_document_ref`.
- **An ambiguous name raises `<kind>_ambiguous` with every candidate id.** It never
  guesses, because Home Keeper names are not unique and `delete_task` resolves names too.
  A name that matches no object goes to the handler unchanged, so its not-found error
  quotes what the user typed.
- Websocket commands take ids only.

## Uploads

- **An uploaded file is the 1 mutation that is not a service.** A binary cannot go through
  a service or the websocket, so it goes through the `HomeAssistantView`s in `manuals.py`.
  The metadata still goes through the store, so the event fires. Removal is a service.
- **Stream an upload to disk.** Never read a whole file into memory, and never add a
  `bytes`-returning read or write on this path. Validation works from the header and the
  size. The caller always ends with `async_discard_upload`.
- A generic `add_asset` or `update_asset` never writes or removes a file document or a
  part file. Only the upload view and the remove services can.
- A document mutation does not call `devices.async_apply_asset_change`. It changes no
  device, so the save and the event are the whole job.
- Keep the pure upload checks (type sniff, allowlist, size, file name, path guard) in
  `documents.py`. Details are in [documents-photos](../../docs/design/documents-photos.md).

## Events

- **Every state change fires a `home_keeper_<noun>_<verb>` event.** Build the payload with a
  pure function in `events.py`, so the test fake in `testing.py` and integrators test
  against the payload that ships.
- **Fire at the `store.py` chokepoint**, not in a handler, so every surface is observed.
  Each path that changes the task or asset map counts, including the reconcile, detach and
  cascade paths.
- **Fire a transition once per crossing.** Detect it in pure code
  (`transitions.detect_transitions`, `assets.stock_transition`), fire it from the
  coordinator, and set a silent baseline on startup so a restart replays nothing.
- Backfilled history from an import fires no completion event.
- An event needs no new service. It observes a change that a service already makes.

## The declared surface

- **`api_surface.py` declares every surface an integrator can touch**: services, events
  and payloads, device triggers, entity platforms and attributes, options, websocket
  commands and HTTP views. A new one is not done until it has a spec there.
  `tests/unit/test_api_surface.py` parses the source and fails on drift.
- A device-facing event also needs a `device_trigger.py` trigger with
  `strings.json` `device_automation` labels at full translation parity.
- **The runtime reads the model.** `device_trigger.py` builds its maps from
  `triggers_for()`. Never write a second literal list beside a modelled one.
- **The model holds names and structure only.** Labels and descriptions come from
  `services.yaml` and `strings.json` when the reference is generated. Never put a
  user-facing sentence in `api_surface.py`. `EventSpec.summary` is the 1 exception.
- **The API reference is generated, never written.** `ci/generate_api_docs.py` renders it
  into the gitignored `website/developer/`. A canonical doc links to it by its site URL.
- `SURFACE_KINDS` also lists the surfaces that Home Keeper does not offer, each with a
  reason. A new kind of surface gets a row there first.
- `docs/EVENTS.md` keeps only what a table cannot say: context, edge rules, restart
  behavior and example automations.

## Errors and escaping

- A service handler raises a localized `ServiceValidationError` for bad input
  ([architecture.md](architecture.md#localized-text)). A websocket command answers with
  `connection.send_error`.
- Escape all user content with `escapeHTML` before it goes into `innerHTML`. Rich user
  text goes through `markdown.ts` ([frontend.md](frontend.md#markdown)).
