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
  bundled `src/locales/*.json` and a key-parity test in `test/i18n.test.js`. Mobile
  actionable-notification text (action buttons, overdue/digest/all-clear copy) is
  localized too, resolved eagerly in `notifications.py` since it's delivered outside
  HA's frontend translation loading — bundled as its own flat-key
  `notification_strings/<lang>.json` files (hassfest rejects a custom top-level key in
  `strings.json`), with Babel for correct CLDR plural forms — see
  `.amazonq/rules/architecture-and-code.md` → "Notification payload text is
  localized". A follow-up audit (see `.amazonq/rules/architecture-and-code.md` →
  "Eagerly-resolved backend text") found and closed the remaining gaps: the websocket
  API's and document-upload views' error messages (`backend_i18n.resolve_exception`,
  reusing `strings.json` `exceptions`), and backend-generated strings with no home
  in `strings.json` — the problem-sensor completion prompt, a companion suggestion's
  description, the inventory CSV headers (`backend_i18n.resolve_string` against a
  new `backend_strings/<lang>.json` bundle) — plus a handful of frontend runtime
  strings that had been miscategorized as "editor-only" (`card.ts`'s empty/error/
  "+N more" text, a card confirm-dialog, and two form default-name fallbacks). Two
  new pure-AST drift-guards
  (`tests/unit/test_backend_error_surface_translations.py`) stop a bare-string
  `connection.send_error`/`json_message` from regressing.
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
- ~~**Estimated effort / cost / parts.** Track filter model numbers, where to buy,
  cost history — turns "replace fridge filter" into a useful record.~~ **Shipped:**
  wear parts carry part numbers, vendor, and reorder links; completion metadata
  carries `cost`; the panel history shows cost per completion.
- ~~**Cost/usage-based recurrence.** Trigger maintenance off sensor data (e.g. run
  hours, cycles) instead of (or in addition to) calendar time.~~ **Shipped** as
  sensor tasks (`REC_SENSOR`): usage/meter mode (arms when `current − baseline ≥
  target`, resets baseline on completion, handles meter rollover) and threshold
  mode (arms on a `false → true` crossing of a numeric comparison with optional
  hold-time for debouncing). See `sensor_tasks.py`, `sensor_watcher.py`.
- ~~**Completion metadata.** Optional note/photo/cost on completion; surface history
  on the device page and in the panel.~~ **Shipped:** `complete_task` and the new
  `update_completion` service accept `note`, `cost`, `photo`, and `who` (person
  entity id); metadata is stored per-completion, surfaced as entity attributes, and
  editable in the panel history view. See `docs/PER_COMPLETION_METADATA_PLAN.md`.
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
  assemble after a fire/flood/theft. Reuses fields we already store. **Shipped** (CSV):
  pure `inventory.py` (`build_inventory` + `inventory_to_csv`), a
  `home_keeper/export_inventory` websocket command, and an **Export inventory** button
  on the Appliances tab. Still open: JSON/PDF formats, photos, and depreciation.
- ~~**Repair / service log (distinct from routine maintenance).** A place to record
  one-off events ("HVAC capacitor replaced, $180, ABC Heating, 2026-03") separate from
  recurring tasks, feeding **repair-vs-replace analytics** (lifetime cost per appliance).~~
  **Shipped** as one-off tasks (`REC_ONE_OFF`): a due date, full completion metadata
  (note/cost/photo/who), goes dormant after completion, history is archived to the
  appliance on deletion. Repair-vs-replace analytics (lifetime cost rollup) remain open.
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
  comes due — closing the loop from "due" → "bought" → "done." **Shipped (v1):** parts
  gain optional `stock`/`reorder_at`; completing a wear-part replacement consumes a
  spare; at/below the threshold a `home_keeper_part_low_stock` event fires (so users
  automate the shopping-list add / reorder themselves). Manual `adjust_part_stock`
  websocket command for restock. Still open: a built-in shopping-list blueprint and a
  one-tap restock control in the panel.

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

---

## Companion / glue integration candidates (beyond Battery Notes)

Battery Notes' pattern — an integration whose *primary* purpose is something else, but
that exposes a "this consumable is wearing out" signal as a secondary/implied feature —
generalizes. Below is a survey of other popular HA integrations checked against that
pattern, to seed future `companions_catalog.py` entries and glue integrations (see
`docs/GLUE_INTEGRATIONS.md`). Install counts are from
[analytics.home-assistant.io](https://analytics.home-assistant.io/) (core-integration
installs only — HACS-only integrations like Bambu Lab aren't counted there). Entity
lists were checked against each integration's HA docs page, not assumed.

**Ready now — exposes a numeric "remaining life" sensor, same shape as a battery %:**

- **Brother** (printer, 44k installs) — per-color toner % *and* drum/belt/fuser/laser
  "remaining lifetime" % sensors. The closest analogue to Battery Notes: printing is the
  point, supply depletion is implied.
  Marketing target: ["Show values which are only temporary available (printer toner
  status)"](https://community.home-assistant.io/t/show-values-which-are-only-temporary-available-printer-toner-status/207106)
  — users already fighting the exact problem a persistent Home Keeper task (vs. a
  volatile sensor) solves; also the general
  ["Brother printer integration"](https://community.home-assistant.io/t/brother-printer-integration/591748)
  hub thread.
- **IPP** (generic network-printer protocol, 150k installs — the single largest printer
  integration, covers most non-Brother printers via the standard "marker-levels"
  attribute) — same shape, broader device coverage, less granular (no per-component
  breakdown).
  Marketing target: ["IPP printer sensors with custom button-card"](https://community.home-assistant.io/t/ipp-printer-sensors-with-custom-button-card/250719)
  — long-running, multi-page thread of users hand-rolling ink-level dashboards; prime
  audience for a glue that turns the sensor into an actual task.
- **Roborock** (robot vacuum, 47k installs) — "filter time left", "main brush time
  left", "side brush time left", "strainer time left" sensors, literally time-remaining.
  Marketing target: ["Roborock maintenance reminder"](https://community.home-assistant.io/t/roborock-maintenance-reminder/602942)
  — a community blueprint already reinventing this with helpers; also the feature
  request ["Roborock Integration, add Dock Maintence items"](https://community.home-assistant.io/t/roborock-integration-add-dock-maintence-items/712274).
- **Ecovacs** (robot vacuum, 11k installs) — per-component lifespan % (filter, brush),
  disabled-by-default sensors.
  Marketing target: ["Information about DEEBOT OZMO 900 Series(y79a7u)
  filter"](https://community.home-assistant.io/t/information-about-deebot-ozmo-900-series-y79a7u-filter/895150)
  — a Deebot (Ecovacs) owner asking specifically about the filter-lifespan attribute.
- **LG ThinQ** (air purifiers/AC/fridges/washers/dishwashers, 22k installs) — explicit
  `time_to_change_filter` / `time_to_change_water_filter` events plus "filter remaining"
  sensors across several appliance types in one integration; highest-leverage target
  since one glue covers many appliance categories.
  Marketing target: the long-running ["LG Smart ThinQ - Component"](https://community.home-assistant.io/t/lg-smart-thinq-component/93944)
  mega-thread (80+ replies) and ["ThinQ status sensor in automation"](https://community.home-assistant.io/t/thinq-status-sensor-in-automation/1015588).

**Real signal, but weaker or needs inference:**

- **NUT — Network UPS Tools** (21k installs) — exposes battery install/manufacture date
  and self-test result, but no raw remaining-life %. UPS batteries have a well-known
  ~3-5yr replace cadence; a glue would need to infer "due" from age the way Battery
  Notes infers expected life from battery *type*. Power monitoring is the integration's
  job; battery aging is the implied secondary need nobody currently tracks.
  Marketing target: ["NUT UPS alert: battery needs to be replaced?"](https://community.home-assistant.io/t/nut-ups-alert-battery-needs-to-be-replaced/878003)
  and the active blueprint thread ["UPS Monitor via NUT – Battery, Status &
  Self-Test Notifications"](https://community.home-assistant.io/t/ups-monitor-via-nut-battery-status-self-test-notifications/902489).
- **Miele** (dishwashers/washers/coffee machines, 9k installs) — detergent/rinse-aid/
  salt level sensors, plus descale/degrease cycle counters on coffee machines and steam
  ovens. More "needs refilling" than "wears out," but same trigger shape.
  Marketing target: the long-running ["Integration for Miele@Home"](https://community.home-assistant.io/t/integration-for-miele-home/230417)
  feature-request thread. (The sibling **Home Connect** integration — Bosch/Siemens
  appliances — has the identical ask in
  ["Home Connect - Addition of 'rinse aid' and 'salt' sensors for
  dishwasher"](https://community.home-assistant.io/t/home-connect-addition-of-rinse-aid-and-salt-sensors-for-dishwasher/377084);
  worth a look as a second appliance-glue candidate alongside Miele.)
- **Roomba (iRobot)** (11k installs) — only "bin full" is exposed (no filter/brush wear,
  unlike Roborock/Ecovacs); still a usable trigger on bin-equipped models.
  Marketing target: ["Roomba automations - bin full, getting stuck and
  auto-start"](https://community.home-assistant.io/t/roomba-automations-bin-full-getting-stuck-and-auto-start/31515).
- **Synology DSM** (49k installs — very popular) — disk SMART "remaining life" and
  bad-sector-threshold binary sensors exist. Not a consumable, but "replace this failing
  drive" is a high-stakes maintenance task that's otherwise invisible outside the
  Synology app.
  Marketing target: weak — no dedicated disk-health thread turned up; closest is
  ["Synology System Health widget in a
  dashboard"](https://community.home-assistant.io/t/synology-system-health-widget-in-a-dashboard/944883).
- **Husqvarna Automower** (2.3k installs) — exposes raw "cutting blade usage time" but
  no built-in threshold/reminder; a glue would own the "replace every N cutting-hours"
  logic itself (configurable, like Battery Notes' per-battery-type estimate).
  Marketing target: no blade-specific thread found; the long-running ["Husqvarna
  Automower monitoring"](https://community.home-assistant.io/t/husqvarna-automower-monitoring/4808)
  mega-thread (100+ replies) is still the highest-traffic venue to reach owners.

**Speculative — no usable entity today, but the upstream device has the feature:**

- **Ecobee** — the thermostat hardware/app has built-in filter, UV-light, and humidifier
  pad reminders, but the HA `ecobee` integration does not surface them as entities.
  Real opportunity, blocked upstream until/unless the integration adds the entity.
  Marketing target: ["Please Add Alerts to Ecobee
  Integration"](https://community.home-assistant.io/t/please-add-alerts-to-ecobee-integration/405520)
  — the exact ask (air filter / UV filter / AC service alerts) is already an open
  feature request; also
  ["EcoBee additions"](https://community.home-assistant.io/t/ecobee-additions/344598).
- **3D printers — OctoPrint / PrusaLink / Bambu Lab (HACS)** — no dedicated nozzle- or
  belt-wear sensor in any of these today. Nozzle replacement and bed releveling are
  well-known maintenance items the hobbyist community already tracks by print-hours —
  closer to the existing *usage-based recurrence* idea above (seed a recurring task from
  cumulative print time) than a sensor-triggered glue.
  Marketing target: ["3D Printer Maintenance
  Reminder"](https://community.home-assistant.io/t/3d-printer-maintenance-reminder/643313)
  — someone already asking for exactly this; Bambu Lab owners cluster in
  ["My Bambu Lab X1C Dashboard &
  Automations"](https://community.home-assistant.io/t/my-bambu-lab-x1c-dashboard-automations/665646).
- **EVs — Tesla Fleet / Teslemetry** (~4.6k installs combined) — odometer and tire-
  pressure sensors exist (disabled by default) but no service-reminder entity; a
  mileage-based recurring task (e.g. "rotate tires every 6,250 mi") is again the
  usage-based pattern, not a triggered one.
  Marketing target: ["Sensor that activates on a certain
  increment"](https://community.home-assistant.io/t/sensor-that-activates-on-a-certain-increment/331690)
  — a TeslaMate user asking for exactly a 7,000-mile tire-rotation reminder off the
  odometer, i.e. asking Home Keeper to exist.
- **Pool/spa controllers — iAqualink, Ondilo ICO, Balboa** (combined < 2k installs) —
  small install base individually, but filter cleaning / chemical dosing is a classic
  recurring-maintenance domain. Probably better served by a generic recurring "Pool
  maintenance" template than per-integration glue, given how thin the signal is on each.
  Marketing target: the long-running ["Jandy iAqualink Pool
  Integration"](https://community.home-assistant.io/t/jandy-iaqualink-pool-integration/105633)
  thread (160+ replies) — no maintenance-specific thread found, but it's the highest-
  traffic pool-owner venue.

Not pursued: locks (august/yale/schlage/nuki) and garage openers (myq/gogogate2) only
expose a generic `battery` sensor — already covered by Battery Notes itself, no new glue
needed.

---

## Community feature requests

Things people in the Home Assistant community have asked for publicly — collected from
Reddit and the HA community forums. Linked to the original source so the context is
preserved.

### Recurring / interval-based tasks (core model)

- **Interval-based recurrence that resets from actual completion date, not the calendar.**
  The most common complaint in every discussion: standard calendar tools drift when you
  complete a task late, but people want "remind me again *now*+interval." Raised across
  many threads independently.
  - ["Best way to manage many repeating interval tasks" — Configuration](https://community.home-assistant.io/t/best-way-to-manage-many-repeating-interval-tasks/486500):
    *"I can't easily say 'I did it now, remind me again now()+interval'"* — users
    resorted to five helper entities per task (DateTime, Text, Number, Boolean, button)
    just to replicate this.
  - ["Home Maintenance Tracker" — Configuration](https://community.home-assistant.io/t/home-maintenance-tracker/551879):
    *"Creating each of these helpers for a single task is a bit tedious but I can't seem
    to find a better way to scale this"* — tracking AC filters, oil burner, generator,
    sprinkler with the same multi-helper workaround.

- **Recurring to-do tasks — native HA To-do list support.**
  Multiple feature requests ask for the To-do list to natively support recurring tasks
  that reappear after being checked off:
  - ["To-do list — recurring task" — Feature Requests](https://community.home-assistant.io/t/to-do-list-recurring-task/684471):
    *"Quite often I need to have recurring tasks → once per month, quarter or a year."*
    Replies called out CalDAV recurrence support as a minimum bar.
  - ["To-Do list 'recurring' feature request (GUI)" — Feature Requests](https://community.home-assistant.io/t/to-do-list-recurring-feature-request-gui/857452):
    *"I want it for a few things that I do weekly, daily and monthly, but I could see
    others using it for chores for their kids on a Kitchen Dashboard."* Requested a
    recurring checkbox with day-of-week / day-of-month pickers directly in the add-item
    UI.
  - ["WTH | Recurring interval attribute for local todo tasks + task status by sensor
    statuses" — WTH 2024](https://community.home-assistant.io/t/wth-recurring-interval-attribute-for-local-todo-tasks-task-status-by-sensor-statuses/812082):
    *"Recurring tasks like - cleaning filter, maintenance for device, buying… will
    automatically change their status to 'need_action' after given time cycle."* Also
    requests sensor-driven status (battery %, soil moisture → task armed).

### Device details, warranty & appliance metadata

- **Store warranty, invoice, manual and service info per device.**
  ["Device details (description, warranty, invoice, user manual, service)" — WTH 2022](https://community.home-assistant.io/t/device-details-description-warranty-invoice-user-manual-service/469871):
  *"I have HomeAssistant and I need to store device details on my computer. The following
  options are missing from the device settings"* — requests warranty date ranges with
  file upload, invoice attachment, user-manual link, service-date tracking, all directly
  on the HA device page.

- **Device inventory with richer metadata** (static IP, install date, manual URL,
  room-level location, behavioral notes).
  ["Device Inventory Solutions" — Frontend](https://community.home-assistant.io/t/device-inventory-solutions/595431):
  *"I want more data-basey functionality, like additional metadata for each device."*
  The community's only suggestion was the external NetBox tool — no HA-native path.

### Battery replacement tracking (condition-driven tasks)

- **Battery replacement logging with replacement-date history and interval reminders.**
  ["WTH Battery Device Alerts and Replacement Tracking" — WTH 2024](https://community.home-assistant.io/t/wth-battery-device-alerts-and-replacement-tracking/808695):
  requests automatic low-battery notifications, manual replacement logging, replacement-
  date tracking with interval reminders, and a dashboard overview of all device battery
  health. Respondents noted the Battery Notes integration exists but the missing piece is
  keeping the replacement *history* across cycles.

### Vehicle maintenance

- **Vehicle maintenance (mileage- and time-based) inside Home Assistant.**
  ["Home and Vehicle Maintenance Integration" — Configuration](https://community.home-assistant.io/t/home-and-vehicle-maintenance-integration/739318):
  *"I am thinking of writing a custom integration to consolidate all home and vehicle
  maintenance items"* — HVAC filter, oil changes, tire rotation, registration, all in
  one place. Led to the Vehicle Service Manager custom integration, but it remains
  separate from home-maintenance tracking.
  - ["Track Miles Driven — Time for oil change" — Configuration](https://community.home-assistant.io/t/track-miles-driven-time-for-oil-change/76762):
    earliest thread (2018) describing the mileage-based maintenance reminder pattern via
    OBD / telematics sensors.

### NFC tags on appliances

- **NFC tag stuck on the appliance → tap to mark maintenance done / open its page.**
  - ["Custom Home Inventory / Maintenance w/ NFC Tags" — Share your Projects](https://community.home-assistant.io/t/custom-home-inventory-maintenance-w-nfc-tags/985862):
    someone built this themselves with Node-Red: NFC tag on each appliance creates a
    "digital passport" (warranty, repair history, manuals, maintenance schedule) and a
    one-click "I just did it" button. The complexity of the DIY setup illustrates the
    demand for a first-class solution.
  - ["Home Assistant: Maintenance reminders using NFC tags"](https://www.creatingsmarthome.com/index.php/2023/12/28/home-assistant-maintenance-reminders-using-nfc-tags/):
    blog post showing the heat-pump filter-vacuuming use case: scan the tag after
    completing maintenance → resets the timer, calculates the next due date.

### Chore assignment to household members

- **Assign tasks to specific people; shared-household visibility.**
  ["Chore Helper — Track recurring or manual chores with flexible scheduling" — Custom Integrations](https://community.home-assistant.io/t/chore-helper-track-recurring-or-manual-chores-with-flexible-scheduling/557470):
  chore assignment to household members was listed as a top open feature request alongside
  the front-end editor card and workday/holiday integration. Mirrors the "Assignees /
  household members" idea already in this file.

### Companion app / voice completion

- **"I just changed the furnace filter" → voice-complete a task via Assist.**
  ["Reminders — Create and List Tasks with Conversational Commands" — Blueprints Exchange](https://community.home-assistant.io/t/reminders-create-and-list-tasks-with-conversational-commands/820470):
  community workaround using Assist + a blueprint to create and surface To-do items via
  voice. The gap: no way to say "I just did X" and have it log against a maintenance task
  and recalculate the due date — that part still requires the custom panel or services.

### Seasonal / weather-triggered tasks

- **"Drain garden hoses" when forecast first dips below freezing; spring/fall task lists.**
  ["Seasonal automation management" — Share your Projects](https://community.home-assistant.io/t/seasonal-automation-management/742995) and
  ["Winter / Summer Automations" — GitHub Discussions](https://github.com/orgs/home-assistant/discussions/2602):
  people build elaborate YAML to trigger seasonal tasks off the HA Season sensor and
  weather entities. The missing piece is a task that *arms itself* when a weather
  condition is met and *clears* when resolved — exactly the triggered-task model Home
  Keeper already has for batteries, applied to weather sensors instead.

### Usage-based / sensor-triggered maintenance (beyond batteries)

- **"Replace filter after N run-hours" or "clean after N cycles."**
  People track washing-machine cycles with smart-plug power monitoring and want a task
  that fires after a cycle-count threshold, not a calendar interval.
  - ["Using power consumption to show information (status, elapsed time, count) of cycles
    on a dishwasher" — Configuration](https://community.home-assistant.io/t/using-power-consumption-to-show-information-status-elapsed-time-count-of-cycles-on-a-dish-washer/382248):
    users manually watch the counter and wish the reminder were automatic.
  - [Maintenance Supporter — Custom Integrations](https://community.home-assistant.io/t/custom-integration-maintenance-supporter-sensor-triggered-adaptive-maintenance-for-your-home/995556):
    the most feature-complete attempt at this pattern, with five trigger types (threshold,
    counter, state-change, runtime, compound). Its key insight: *"Fixed-interval reminders
    either fire too early (wasting parts and effort) or too late (risking equipment
    damage)."* Also does adaptive scheduling via Weibull reliability modelling and QR-code
    scan-to-complete. Feature requests still open: multi-stage filters (multiple
    components with different intervals on one unit) and numeric countdown entities for
    dashboard progress bars.

- **Long-term test-date tracking where `last_changed` is unreliable.**
  ["Smoke detector test reminder (how to perform long-term state monitoring)?" — Configuration](https://community.home-assistant.io/t/smoke-detector-test-reminder-how-to-perform-long-term-state-monitoring/440461):
  users want a 6-monthly smoke-detector test reminder, but `state.last_changed` resets
  whenever the Zigbee network restarts — not just on an actual test. The thread lands on a
  datetime helper as the only reliable anchor. The same fragility affects any "when did I
  last do X" use case not backed by a persistent store like Home Keeper's completion log.

### Lovelace card for upcoming/overdue tasks

- **A visual maintenance dashboard card with color-coded urgency.**
  ["Home Maintenance Cards Dashboard" — Dashboards & Frontend](https://community.home-assistant.io/t/home-maintenance-cards-dashboard/994581):
  someone built a custom Lovelace card (color-coded green/yellow/red rings with a pulsing
  glow for overdue items, one-tap completion, auto-discovery of maintenance entities). The
  proliferation of such cards — this one, `ha-chore-card`, the Chore Helper card — shows
  people want a glanceable summary that the native To-do and Calendar surfaces don't provide.
  ["Lovelace card to display pending tasks" — Configuration](https://community.home-assistant.io/t/lovelace-card-to-display-pending-tasks/155336):
  *"I'd like to add a card to it highlighting any issues which we might need to take care of.
  For example, remote batteries getting low."* — the auto-entities workaround requires
  manually maintaining entity lists.

### Kids' chores & gamification

- **Gamified chore tracking with per-person points, streaks, rewards, and parental approval.**
  [KidsChores custom integration](https://community.home-assistant.io/t/kidschores-family-chore-management-integration/827719)
  and its successor ChoreOps are entire integrations dedicated to this pattern. Feature set:
  claim-and-approve workflow, coins/stars/XP, badges, streaks, challenges, penalties, and a
  dedicated kid-facing dashboard. The existence of two mature forks targeting this use case
  confirms strong demand. Relevant to Home Keeper's "assignees / household members" idea —
  the family-chore audience wants reward mechanics that pure maintenance tracking doesn't need.

### Actionable (snoozable) notifications

> **Status: planned** — design written up in
> [docs/ACTIONABLE_NOTIFICATIONS_PLAN.md](docs/ACTIONABLE_NOTIFICATIONS_PLAN.md)
> (built-in sender configured via the options flow + a Settings → Notifications
> panel card, with a configurable button set and new `snooze_task` / `skip_task`
> services).

- **"Mark done" or "snooze 1 day" directly from the mobile push notification.**
  ["Actionable Task Reminder" — Blueprints Exchange](https://community.home-assistant.io/t/actionable-task-reminder-a-powerful-task-reminder-automation/636946):
  a popular blueprint for snoozable reminders. Its key limitation: acknowledging or
  snoozing does not recalculate the next due date for a recurring maintenance task —
  the blueprint knows nothing about intervals. People bolt it onto Grocy or datetime
  helpers to get the recalculation side, but there is no clean integration.

### Grocy as a stopgap — and its limits

- **Grocy fills the maintenance/chore gap but requires a separate app.**
  The [Grocy community thread](https://community.home-assistant.io/t/grocy-custom-component-and-card-s/218978)
  repeatedly surfaces: *"this works just fine in Grocy but I'd love to pull this data into
  Home Assistant."* Grocy's chore and task model is richer than anything native HA offered,
  but switching contexts out of HA is friction. The custom card for Grocy tasks/chores
  (`grocy-tasks-chores`) exists precisely because people want the Grocy data on their HA
  dashboard and as automation triggers. Home Keeper aims to close that gap without a
  separate server.

### Generalized expiry / annual service tracking

- **Track chimney sweeps, septic inspections, fire-extinguisher service, smoke-detector
  10-year replacement — anything with an annual or multi-year expiry.**
  ["Basic countdown/reminder for maintenance items" — Configuration](https://community.home-assistant.io/t/basic-countdown-reminder-for-maintenance-items/980690):
  *"All I need is a reminder of some sort to nag at me when it's time to deal with these
  tasks"* — for an HVAC filter on a 90-day cycle. The community reaches for the Home
  Maintenance integration as the answer; but the broader pattern (arbitrary expiry date +
  notification) is exactly what Home Keeper's warranty-expiry sensor and fixed-schedule
  tasks already model.
