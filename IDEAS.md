# Home Keeper — Ideas & Future Work

A running list of things we deliberately deferred from the first UX prototype, plus
ideas worth exploring. Nothing here is committed scope; it's a parking lot.

## Appliances / assets & device metadata (planned direction)

The motivating problem: a "dumb" appliance (e.g. a fridge) usually isn't a Home
Assistant device, so there's nothing to attach maintenance tasks — or Battery
Notes batteries — to. Home Assistant core has no way to create a device manually;
devices only come from integrations.

Direction (two **decoupled** layers — this is the key design decision):

1. **Asset-metadata layer — attach to / enrich ANY device (virtual or existing).**
   A record of descriptive/ownership attributes that can attach to *any* device in
   the registry: one we created for a dumb appliance, OR a real device from
   another integration (e.g. a smart fridge), OR a Battery Notes device. Metadata
   is keyed by `device_id` and must NOT be coupled to device creation.
   Attributes to support (extensible):
   - make / manufacturer, model, serial number
   - manufacture date, purchase date, install/commission date
   - warranty expiry, warranty provider/terms
   - location/room, category/type
   - cost / purchase price, vendor / where-to-rebuy
   - link to manual / docs, model/part numbers for consumables (filters, bulbs)
   - free-form notes, photo

   **Reuse HA-native primitives first (don't build a parallel system).** The
   device registry already carries `manufacturer`, `model`, `model_id`,
   `serial_number`, `hw_version`/`sw_version`, `area_id`, and `configuration_url`;
   **labels** (HA 2023.7+) cover arbitrary tagging/grouping/filtering. Our custom
   layer should own *only the gap* those can't express — primarily dates
   (manufacture/purchase/install), warranty, cost, vendor, manual link, consumable
   part numbers, photo, and notes.

   **Entities vs. stored metadata.** Make automatable/temporal fields real
   **entities** (e.g. a `sensor` with `device_class: date`/`timestamp` for
   warranty expiry, so "warranty expiring in 30 days → notify" works and shows in
   the UI without our panel and in state history). Keep purely descriptive,
   non-automatable fields (notes, manual links, part numbers) as stored metadata.

2. **Virtual-device provision — only when there's no device to attach to.**
   When the user has a dumb appliance with no existing device, Home Keeper can
   register one via `device_registry.async_get_or_create(config_entry_id=...,
   identifiers={(DOMAIN, asset_id)}, name, manufacturer, model, ...)`. Multiple
   tasks then share that one device page instead of becoming separate per-task
   devices (today each standalone task makes its own device). Because it's a real
   registry device, Battery Notes (and our future contribution API) can attach to
   it too — so tasks + batteries + asset metadata converge on one page.

Why decouple: the metadata is useful on real devices too, and shouldn't require
us to "own" the device. The virtual-device piece is just the fallback for hardware
no integration provides.

**Constraints / lifecycle (refined via review):**
- Only attach metadata to a device that **currently exists** — validate with
  `device_registry.async_get(device_id)` and reject if `None`. No pre-creating
  metadata for not-yet-existing devices (avoids a shadow registry).
- Devices owned by other integrations can be removed or recreated with a new
  `device_id`. Store **both** `device_id` (fast lookup) **and** the device's
  `identifiers`/`connections` (for reconciliation), and listen for device-registry
  removal/update events (`async_track_device_registry_updated_event`) to detect
  orphaned/re-created devices rather than silently losing metadata.
- On config-entry removal, **aggressively clean up** all our metadata, any
  diagnostic entities we created, and any virtual devices we own. Removing Home
  Keeper must not leave residue on other integrations' devices.

Existing ecosystem alternatives we evaluated for the virtual-device piece (and why
we'd rather provide it ourselves): MQTT discovery (needs a broker + hand-rolled
topics), `twrecked/hass-virtual`, `kuba2k2/hassio-virtual-devices`, and the
"Device Tools" custom integration. Providing managed appliances ourselves keeps it
on-mission and GUI-driven.

Open questions: exactly which gap-attributes warrant entities beyond the date/
warranty ones; how editing native device fields (manufacturer/model/serial) should
work when we don't own the device (HA may not allow it) vs. our own metadata; how
this interacts with the deferred cross-integration contribution API; and whether
"category/type" should be a label or our own field.

## Deferred from the prototype (known next steps)

- **Cross-integration contribution API** (the big one). A stable, documented
  interface so other integrations (e.g. Battery Notes) can push maintenance tasks
  into Home Keeper *without Home Keeper knowing anything about them*.
  - Proposed mechanism: a dispatcher signal `home_keeper_task_contribution` plus a
    `home_keeper.contribute_task` service. Contributors fire it with
    `{source, device_id, name, recurrence...}`; a listener in `__init__.py` creates
    (or updates) a task tagged with its `source` so it can be reconciled/removed
    when the contributor goes away.
  - Battery Notes example: when a battery goes low, it contributes a "replace
    battery" task attached to the same device. Home Keeper stores it like any other
    task; completing it could fire a signal back so the contributor can reset.
  - Open questions: lifecycle/ownership of contributed tasks, dedupe, whether
    contributed tasks are user-editable, and a versioned schema for the payload.
  - Hook points already left in code: `const.SIGNAL_TASK_CONTRIBUTION`, and a
    `# DEFERRED` marker at the service-registration block in `__init__.py`.

- **Advanced fixed-schedule rules.** Today fixed schedules are `FREQ` (DAILY/
  WEEKLY/MONTHLY) + `interval` + `anchor`. Add `BYDAY` (e.g. "first Monday"),
  multiple weekdays, `COUNT`/`UNTIL`, and custom durations. Consider adopting
  `dateutil.rrule` or `recurring-ical-events` if hand-rolled math gets unwieldy
  (would add a Python requirement — currently we ship none).

- **Per-task entities for standalone tasks.** The prototype only creates the
  per-task `button`/`sensor`/`binary_sensor` for tasks attached to a device (to
  keep device pages clean). Decide whether standalone tasks should also get these,
  or rely on the to-do + calendar surfaces only.

- **Internationalization.** Prototype ships English only. Pawsistant ships 16
  locales; mirror that (`strings.json` ↔ `translations/*.json` parity test, and a
  dependency-free i18n module in the panel frontend).

## UX exploration (the whole point of the prototype)

- Compare the three usage surfaces in real use: native **To-do** list, native
  **Calendar**, and **device-page** entities. Decide which to lead with, and
  whether a bespoke Lovelace "upcoming tasks" card is still worth building on top.
- Panel polish: grouping by area/room, filtering (overdue / due-soon / by device),
  bulk actions, drag-to-reorder, an "activity log" view of completion history.
- Quick-complete affordances: a dashboard card with one-tap "done" buttons; a
  notification action ("Mark done") from the mobile app.
- Snooze / skip an occurrence (especially for fixed schedules) vs. hard complete.
- Per-task icons & colors (like Pawsistant event types) for at-a-glance scanning.

## Modeling & features

- **Notifications / reminders.** Proactive nudges when a task is due/overdue
  (persistent notification, mobile push, or just well-shaped entities users can
  automate on). Consider a built-in blueprint.
- **Assignees / household members.** Who's responsible; rotate chores between
  people.
- **Categories & areas.** First-class area assignment and category tags;
  area-scoped views in the panel and on area pages.
- **Estimated effort / cost / parts.** Track filter model numbers, where to buy,
  cost history — turns "replace fridge filter" into a useful record.
- **Cost/usage-based recurrence.** Trigger maintenance off sensor data (e.g. run
  hours, cycles) instead of (or in addition to) calendar time.
- **Completion metadata.** Optional note/photo/cost on completion; surface history
  on the device page and in the panel.
- **Import/export & backup** of tasks (JSON), and migration tooling between
  versions.

## Quality & infra

- Diagnostics download (`diagnostics.py`) for support, like Pawsistant.
- Broaden e2e screenshots into a documented before/after gallery in the README.
- Coverage gate on the recurrence engine specifically (it's the correctness core).
