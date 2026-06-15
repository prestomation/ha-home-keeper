# Home Keeper — Ideas & Future Work

A running list of things we deliberately deferred from the first UX prototype, plus
ideas worth exploring. Nothing here is committed scope; it's a parking lot.

## Appliances / assets & device metadata (implemented — see docs/DESIGN.md)

**Status: shipped.** Built as `assets.py` (pure model) + `devices.py` (registry
provisioning), an **Appliances** panel tab, `*_asset` services/websocket commands,
and `HomeKeeperAssetDateSensor` date entities. The notes below are the original
design rationale, kept for context; remaining open items are flagged at the end.

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

Also shipped since: **structured parts / wear items** (a wear item with a replacement
interval auto-creates a maintenance task via the task `source` field), **subdevices**
(`parent_asset_id` → native `via_device`) and **related devices**
(`related_device_ids`, panel-only for foreign devices), plus HA-integration polish
(`area_id` validation, `configuration_url`, per-appliance mdi icon, `diagnostics.py`).

Still open (deferred): a **photo** attribute and its storage; **labels** for arbitrary
tagging and whether "category/type" should be a label vs. our own field; editing an
existing device's native fields when we don't own it; a device-registry
**update/removal listener** (`async_track_device_registry_updated_event`) for live
orphan reconciliation of existing-device assets (today reconciliation runs on setup /
asset mutation and recovers via the stored identifiers snapshot); and generalizing the
task `source` field into the deferred cross-integration contribution API.

**Done since:** the panel now follows the HA **design language** end to end — every
form is built with `ha-form` schemas (which lazy-load HA's own selector widgets:
`ha-textfield`/`ha-textarea`/`ha-select`, the searchable device/area pickers, and the
`mdi` icon picker), list rows are `ha-card`s, navigation is `ha-tab-group`, status is
shown with `ha-assist-chip`, empty/error states use `ha-alert`, and actions use
`ha-button`/`ha-icon-button`. See `frontend/src/panel.ts`.

## Deferred from the prototype (known next steps)

- **Cross-integration contribution API** (the big one). A stable, documented
  interface so other integrations (e.g. Battery Notes) can push maintenance tasks
  into Home Keeper *without Home Keeper knowing anything about them*.
  - **Shipped (v1 contract, see [docs/INTEGRATING.md](docs/INTEGRATING.md)):**
    contributors call the existing `home_keeper.add_task` with an opaque, domain-
    namespaced `source` dict (stored verbatim) and subscribe to the new
    `home_keeper_task_completed` event to mirror completions. Two-way completion sync
    uses an opaque `origin` marker on `complete_task` for loop prevention. Pawsistant
    is the first example client (pet-care schedules). Home Keeper still inspects
    neither `source` nor `origin`.
  - **Still deferred:** a dedicated `home_keeper.contribute_task` upsert/reconcile
    service (and the `home_keeper_task_contribution` dispatcher signal) that would own
    contributed-task lifecycle for Home Keeper rather than leaving CRUD to the client.
    The v1 contract is enough when the contributor tracks the `task_id` it created.
  - Open questions for that fuller API: lifecycle/ownership of contributed tasks,
    dedupe, whether contributed tasks are user-editable, and a versioned payload schema.
  - Hook points left in code: `const.SIGNAL_TASK_CONTRIBUTION` (reserved for the
    deferred service).

- **Advanced fixed-schedule rules.** Today fixed schedules are `FREQ` (DAILY/
  WEEKLY/MONTHLY) + `interval` + `anchor`. Add `BYDAY` (e.g. "first Monday"),
  multiple weekdays, `COUNT`/`UNTIL`, and custom durations. Consider adopting
  `dateutil.rrule` or `recurring-ical-events` if hand-rolled math gets unwieldy
  (would add a Python requirement — currently we ship none).

- **Per-task entities for standalone tasks.** The prototype only creates the
  per-task `button`/`sensor`/`binary_sensor` for tasks attached to a device (to
  keep device pages clean). Decide whether standalone tasks should also get these,
  or rely on the to-do + calendar surfaces only.

- ~~**Internationalization.** Prototype ships English only. Pawsistant ships 16
  locales; mirror that (`strings.json` ↔ `translations/*.json` parity test, and a
  dependency-free i18n module in the panel frontend).~~ **Done.** Localized into
  16 locales: backend via HA-native `strings.json` ↔ `translations/<lang>.json`
  (plus an `entity` section for device-page entity names) and a parity test in
  `tests/unit/test_translations_parity.py`; frontend via a dependency-free
  `frontend/src/i18n.ts` (`t`/`tn`, `Intl.PluralRules`, English fallback) with
  bundled `src/locales/*.json` and a key-parity test in `test/i18n.test.js`.
  Remaining: the `todo`/`calendar` list entity names stay English (they carry the
  brand name and use `has_entity_name=False`), and developer-facing validation
  exceptions are intentionally not localized.

## UX exploration (the whole point of the prototype)

- Compare the three usage surfaces in real use: native **To-do** list, native
  **Calendar**, and **device-page** entities. Decide which to lead with, and
  whether a bespoke Lovelace "upcoming tasks" card is still worth building on top.
- Panel polish: ~~grouping by area/room, filtering (overdue / due-soon / by
  device)~~ **shipped** — the list view now has a persisted group-by control
  (Status / Area / Device for tasks; Area for appliances) rendering collapsible
  sections, plus an All / Overdue / Due soon quick filter for tasks. Tapping a
  row opens a full **detail page** for the task or appliance (schedule, notes,
  metadata, parts, related tasks, subdevices and completion history inline),
  replacing the old history-only dialog; overdue task cards carry a red accent.
  Still open: bulk actions, drag-to-reorder, and an "activity log" view of
  completion history.
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

## New use cases (brainstorm)

A round of "use cases we hadn't thought of yet," kept separate from the committed
next-steps above. Several of these reuse asset metadata or the parts model we already
ship rather than adding a parallel system.

### Leverage asset metadata we already collect

- **Home inventory for insurance.** The appliance registry *is* a home inventory.
  Add a "total replacement value" rollup and a one-click export (CSV/JSON/PDF with
  photos, serials, purchase dates, costs, warranty) — exactly what people scramble to
  assemble after a fire/flood/theft. Reuses fields we already store. **(Implementing.)**
- **Repair / service log (distinct from routine maintenance).** A place to record
  one-off events ("HVAC capacitor replaced, $180, ABC Heating, 2026-03") separate from
  recurring tasks, feeding **repair-vs-replace analytics** (lifetime cost per appliance).
- **Warranty-claim assist.** A human-facing view that answers "is it under warranty?"
  with provider, terms, manual link, and remaining days — on top of the existing
  warranty-expiry sensor.
- **Home-sale / handoff binder.** Export the full maintenance history + appliance docs
  as a package for the next owner (or one's own records on a move).

### Bridge to the physical world (HA-native)

- **NFC tag / QR per appliance.** Stick an HA NFC tag on the furnace; tapping it opens
  that appliance's page or marks its filter task done. Uniquely-HA affordance.
- **Voice / Assist completion.** "I just changed the furnace filter" → marks it done;
  "what maintenance is due this week?" → reads the list, via HA's conversation agent.

### Triggers beyond the calendar

- **Weather / season-triggered tasks.** Distinct from usage-based recurrence: "drain
  the garden hoses" when the forecast first dips below freezing; "service the AC" each
  spring. Tie a due condition to a weather entity or season, not just elapsed time.
- **Vacation / away-aware scheduling.** Use HA presence to defer indoor chores while
  away, or generate a pre-trip checklist (set thermostat, shut main water valve).

### New asset categories the model already fits

- **Vehicle maintenance.** A car is an asset; oil changes, rotation, registration, and
  inspection are tasks. Mileage-based intervals (odometer from a car integration)
  extend usage-based recurrence to a concrete, popular domain.
- **Generalized expiry / renewal tracking.** The warranty-expiry sensor pattern
  generalizes to fire-extinguisher service, chimney/septic inspection, registration,
  smoke-detector replacement (10-yr), even subscriptions/HOA dues — "things with an
  expiry date" is a broader job than "appliances."

### Onboarding & consumables

- **Starter template catalog.** A library of common appliances with sensible default
  maintenance intervals (water-heater anode rod 12mo, HVAC filter 3mo, smoke-detector
  battery 12mo, dryer-vent cleaning 12mo, fridge water filter 6mo) to kill the
  blank-slate adoption barrier; "add water heater" pre-fills its wear items.
- **Consumables inventory with stock counts.** Parts already carry part numbers. Track
  *how many* spares are on hand, decrement on completion, alert at low stock, and push
  the part onto HA's `todo` shopping list (or fire a reorder automation) when a task
  comes due — closing the loop from "due" → "bought" → "done." **(Implementing.)**

### Households & motivation

- **Chore gamification / streaks.** Completion streaks and per-person stats — strong for
  kids' chores and shared households; pairs with the assignees idea above.
- **Task dependencies / multi-step procedures.** "Flush tank" only becomes due after
  "drain tank"; sequencing for procedures bigger than a single checkbox.
- **Vacation-rental / guest turnover checklists.** A reusable checklist that resets
  between guests — adjacent to but distinct from the current recurrence model.

## Quality & infra

- Diagnostics download (`diagnostics.py`) for support, like Pawsistant.
- Broaden e2e screenshots into a documented before/after gallery in the README.
- Coverage gate on the recurrence engine specifically (it's the correctness core).
