# Changelog

All notable changes to Home Keeper are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses semantic
versioning (with PEP 440 pre-release suffixes — `bN`/`aN`/`rcN` — for betas).

## [Unreleased]

## [0.3.0b6] - 2026-06-19

### Added

- **Comprehensive events for everything that happens — and automation-editor
  triggers.** Home Keeper now fires a Home Assistant bus event for every meaningful
  change, so you can automate on the full lifecycle instead of just completions and
  low-stock. New events: tasks **created / updated / deleted / uncompleted / triggered**
  and the time-based **overdue** and **due-soon** transitions; spare parts **out of
  stock** and **restocked** (alongside the existing low-stock); and appliances
  **created / updated / deleted**. The time and stock transitions are *edge-triggered*
  (one event per crossing, never repeated every cycle) and are silently baselined on
  restart, so a reboot never replays an "overdue" storm. Each event also shows up as a
  **device trigger** in the visual automation editor — on a task's device or an
  appliance you can pick *"Task became overdue"* or *"Spare part out of stock"* without
  knowing the event name. The existing `home_keeper_task_completed` payload gains the
  full task spine (device/area/recurrence/next-due/enabled) on top of its long-standing
  fields. See the new [docs/EVENTS.md](docs/EVENTS.md) for the full catalog, payloads
  and example automations.

### Changed

- **A spare part dropping straight to zero now fires `home_keeper_part_out_of_stock`,
  not `home_keeper_part_low_stock`.** Out-of-stock is the more specific event and takes
  precedence. If you had an automation listening for `home_keeper_part_low_stock` to
  catch a part reaching zero, switch it to (or also listen for)
  `home_keeper_part_out_of_stock`. A part crossing into low *without* hitting zero still
  fires `home_keeper_part_low_stock` as before.

## [0.3.0b5] - 2026-06-17

- **Flexible appliance metadata — custom fields replace the fixed metadata form.**
  An appliance's descriptive details are now a free-form list of **custom fields**
  instead of a fixed set of inputs. Each field has a label and a type — **text**,
  **link**, or **date** — and you add as many as you like, with one-click seeds for
  the common ones (serial number, warranty expiry, purchase/install dates, provider,
  vendor, notes). Links are clickable and open in the browser. A date field is
  display-only unless you tick **Track as a sensor**, which surfaces it as a `date`
  sensor on the device for automations (e.g. *"warranty expiring in 30 days → notify"*)
  — so you no longer get a sensor for every date whether you use it or not.
  Manufacturer, model, manual link, cost, icon and area remain dedicated fields (they
  wire into the Home Assistant device card and the inventory export), and the
  insurance inventory export keeps its value totals while listing each appliance's
  custom fields in a new **Details** column. *Note: this changes how appliance
  metadata is stored; pre-release, an existing appliance's old descriptive fields are
  not migrated.*

- **A wear-item maintenance task with no recorded replacement date is now due now,
  not "assumed fresh".** When Home Keeper derives a replacement task from an appliance
  wear item that has no "Last replaced" date, it used to assume the part was fresh and
  schedule the first reminder a full interval out. It now reads as **due immediately**,
  matching how brand-new floating tasks behave: an unknown replacement history is
  surfaced now rather than hidden for a cycle. Backdate the part's last-replaced date
  (or mark the task done) to start its clock from a known point instead. Wear items
  with a recorded replacement date are unaffected.

## [0.3.0b4] - 2026-06-17

- **Backdate a wear item's last replacement when adding it.** The parts editor now
  has an optional "Last replaced" date field for wear items, so the maintenance task
  it creates starts its clock from the real replacement date instead of from today —
  useful for parts you'd already replaced before tracking them in Home Keeper.
- **Redesigned the appliance parts list.** On an appliance's detail page, each part
  now reads as a card with a type icon and badge, its replacement cadence, last-replaced
  date, and spare-stock chips at a glance, replacing the cramped one-line summary.

## [0.3.0b3] - 2026-06-17

- **Dashboard task card.** A new resizable Lovelace card (`custom:home-keeper-card`)
  shows your tasks as a list with a one-tap **Done** button on each row, and opens an
  inline editor for adding, editing, and deleting tasks without leaving the dashboard.
  It is auto-registered as a resource (no manual setup) and appears in the "Add card"
  picker. A GUI config editor exposes filtering (by status, area, device, recurrence
  type, due-within horizon), sorting, status/area/device grouping, a max-items cap, and
  display toggles. Built entirely from Home Assistant's own components and theme
  variables, and it stays in sync with completions made from any other surface.
- **Fix: the card no longer spins forever when tasks fail to load.** If the task
  fetch fails (e.g. the integration isn't set up yet, or was removed while a card
  is still on a dashboard), the card now shows a clear error and keeps retrying on
  the next update instead of an endless spinner.
- **Fix: a fast double-tap of a card's Done button no longer records two
  completions** — a completion already in flight ignores re-entrant taps.

## [0.3.0b2] - 2026-06-16

- **Backdate last completion when creating a task.** The New Task form now includes an optional "Last completed" datetime field. Setting it seeds an initial completion entry so a floating task's next-due date is measured from when the activity actually last happened, rather than being due immediately. Useful when you first install Home Keeper and already know the last time a task was done.

## [0.3.0b1] - 2026-06-16

- **Condition-driven (`triggered`) tasks.** A third recurrence type for maintenance
  that responds to a *condition* rather than a schedule — a battery going low, a leak,
  a filter past its threshold. A triggered task has no schedule: an owning integration
  arms it (the new `home_keeper.trigger_task` service, or by creating it) when the
  condition becomes true and clears it (`complete_task`) when it resolves, which records
  the event in history and returns the task to a dormant state. Dormant triggered tasks
  are invisible to the to-do list, calendar, and overdue sensors, and the panel tucks
  them into a collapsed **"Monitored"** section; armed ones read as due-now everywhere.
  This is the engine behind the Battery Notes glue integration. See
  `docs/INTEGRATING.md` §7 and `docs/BATTERY_NOTES_PLAN.md`.

## [0.2.0] - 2026-06-16

- **Managed tasks (stronger integration ownership).** Integrations that create tasks
  can declare a `managed_by` block that Home Keeper acts on (unlike the opaque
  `source`): managed tasks show a **"Managed by {name}"** chip, lock declared fields
  out of the edit form, surface an optional completion prompt and a deep link back to
  the owning integration, and can be grouped by integration. If the owner is
  uninstalled or disabled, its tasks flip to **"Integration offline"**, become
  deletable again, and a **"Remove orphaned tasks"** banner offers one-click cleanup;
  `home_keeper.delete_task` gains a `force` option as a last resort. See
  `docs/INTEGRATING.md` §6.

- **Home inventory export (for insurance).** An **Export inventory** button on the
  Appliances tab downloads a CSV — make/model/serial, purchase and warranty dates,
  replacement cost, and the value of spares on hand, with a grand total. Also exposed
  to automations as the `home_keeper.export_inventory` service.

- **Spare-inventory tracking for parts.** Any part can track a *stock* count and a
  *reorder-at* threshold. Completing a wear-item replacement consumes a spare, and
  when stock hits the threshold a `home_keeper_part_low_stock` event fires. The panel
  shows on-hand count and a **Low stock** chip; `home_keeper.adjust_part_stock`
  restocks or consumes spares from automations.

- **Deep links & a working Back button in the panel.** Tabs
  (`/home-keeper/appliances`) and detail pages (`/home-keeper/tasks/<id>`) are now in
  the URL — linkable, bookmarkable, and refresh-safe — and the browser **Back** button
  steps back inside the panel instead of leaving it.

- **A brand-new floating task is due now, not a full interval away.** A floating task
  with no completion history used to be dated one interval into the future (a chore
  you'd never done showed up as "due in 30 days"); it now reads as **due immediately**.
  Completing it — or seeding a "last done" date (below) — starts the clock from there.
  Fixed and appliance wear-part tasks are unaffected. Applies to newly-created tasks;
  an existing never-completed floating task keeps its current due date until next
  edited or completed.

- **`add_task` accepts an optional `last_completed` "last done" seed.** Integrations
  that already know when an activity last happened can pass `last_completed` so the
  first next-due is measured from that date (`next_due = last_completed + interval`)
  instead of due-now. See `docs/INTEGRATING.md`.

## [0.2.0b2] - 2026-06-15

- **A brand-new floating task is due now, not a full interval away.** A floating task
  with no completion history used to be dated one interval into the future (a chore
  you'd never done showed up as "due in 30 days"). It now reads as **due immediately** —
  a task you haven't done yet is due now. Completing it (or seeding a "last done" date,
  below) starts the clock from there. Fixed (calendar-anchored) tasks and appliance
  wear-part tasks are unaffected. This applies to newly-created tasks; an existing
  never-completed floating task keeps its current due date until next edited or completed.

- **`add_task` accepts an optional `last_completed` "last done" seed.** Integrations
  that already know when an activity last happened can pass `last_completed` to seed an
  initial completion, so the first next-due is measured from that date
  (`next_due = last_completed + interval`) instead of due-now. See `docs/INTEGRATING.md`.

## [0.2.0b1] - 2026-06-15

- **Managed tasks (stronger integration ownership).** Integrations that create tasks
  can now declare a `managed_by` block, which Home Keeper acts on (unlike the opaque
  `source`). Managed tasks show a **"Managed by {name}"** chip; declared fields are
  locked out of the edit form; and an optional completion prompt and a deep link back
  to the owning integration are surfaced. Tasks can also be grouped by integration.
  If the owning integration is uninstalled or disabled, its tasks flip to
  **"Integration offline"**, become deletable again, and a **"Remove orphaned tasks"**
  banner offers one-click cleanup; `home_keeper.delete_task` also gains a `force`
  option as a last resort. See `docs/INTEGRATING.md` §6.

- **Home inventory export (for insurance).** A new **Export inventory** button on
  the Appliances tab downloads a CSV — make/model/serial, purchase and warranty
  dates, replacement cost, and the value of spares on hand, with a grand total —
  built from metadata you've already entered. Also available to automations as the
  `home_keeper.export_inventory` service (returns the report plus CSV).

- **Spare-inventory tracking for parts.** Any part can now track a *stock* count and
  a *reorder-at* threshold. Completing a wear-item replacement consumes one spare,
  and when stock drops to/below the threshold a `home_keeper_part_low_stock` event
  fires so you can automate a shopping-list add or reorder. The panel shows the
  on-hand count and a **Low stock** chip; the `home_keeper.adjust_part_stock` service
  restocks or consumes spares from automations.

- **Deep links & a working Back button in the panel.** The panel's view now lives
  in the URL — tabs (`/home-keeper/appliances`) and detail pages
  (`/home-keeper/tasks/<id>`) are linkable and bookmarkable, and refreshing keeps
  your place. The browser **Back** button now steps back to the previous page
  inside the panel (e.g. detail → list) instead of navigating away from Home
  Keeper entirely.

## [0.1.0b5] - 2026-06-15

- **Group and filter the task list.** The panel's list view gains a persisted
  *group by* control — tasks by **Status** (overdue / due soon / later / no
  schedule), **Area**, or **Device**; appliances by **Area** — rendering
  collapsible sections with counts. Tasks also get quick **All / Overdue / Due
  soon** filter chips.

- **Full detail pages for tasks and appliances.** Tapping a row now opens a
  dedicated detail page instead of a history-only dialog. A task page shows its
  status, schedule, notes, and completion history; an appliance page gathers its
  metadata, parts & wear items, related tasks, subdevices, and full maintenance
  history (including the retained history of removed tasks) in one place.
  Done / Edit / Delete live on the detail page, and task rows keep a quick
  **Done** plus a red overdue accent.

## [0.1.0b4] - 2026-06-15

- **Completion history for tasks and appliances.** Click a task to see every time it
  was completed — the dates, how many, and the average cadence — or click an appliance
  to see a timeline of *all* maintenance done on it across every related task. Answers
  "when did I last do this / when was this serviced?" at a glance.

- **Appliance history outlives a deleted task.** When a task that belongs to an
  appliance is deleted, its completion history is kept on the appliance (shown as a
  "removed task") so the appliance's maintenance record survives. A standalone task's
  history is removed with it, and deleting an appliance clears its archive.

- **Undo an accidental completion.** Each entry in the history view has a delete button;
  removing a completion re-derives the task's next due date (a floating task rewinds to
  the previous completion; a fixed schedule is unaffected).

- **Device-page entities name themselves by task.** When several Home Keeper tasks
  are attached to the same existing device, their per-task entities (the *mark
  done* button, *next due* sensor, and *overdue* binary sensor) used to all share
  the same name, so there was no way to tell which control belonged to which task.
  Each is now prefixed with its task name (e.g. *"Replace filter: Mark done"*).
  Self-owned task devices are unaffected (the device is already named after the
  task). Renaming a task now refreshes its device-page entity names (and a
  self-owned task device's own name) instead of leaving them stale.

- **Sidebar panel device chips are now actionable.** The device chip on task and
  appliance rows links to that device's Home Assistant page when clicked (or via
  keyboard), and shows the device's integration brand logo (falling back to a
  generic device icon when no brand image is available).

### Fixed

- **Wear-part tasks no longer break the calendar and sensors.** A maintenance task
  derived from a wear part (with a "last replaced" date) computed a
  timezone-naive due date, which made its *next due* sensor, *overdue* binary
  sensor, and the **whole Home Keeper calendar** go *unavailable*. The due date is
  now timezone-aware, and existing affected tasks self-heal on the next reload.
- **Long-running fixed-schedule tasks no longer crash.** A fixed (anchored)
  daily/weekly task whose anchor was far in the past (a daily task left running
  ~1.4 years, a weekly one ~9.6 years) raised an internal error when computing its
  next occurrence — taking down the calendar and the next-due/overdue entities,
  and 500-ing the create form for a far-past anchor. Occurrences are now computed
  directly instead of by stepping to an iteration cap.
- **Absurd intervals are rejected cleanly.** A recurrence interval or wear-part
  replacement interval large enough to overflow date math now returns a clear
  validation error instead of an internal server error.
- **Wear-part maintenance tasks are managed only through their part.** They can no
  longer be deleted directly (which previously did nothing useful — the next
  reconcile recreated them); the panel hides edit/delete on these tasks and points
  you to the appliance part instead. Completing one is preserved across reconciles.
- **Editing a wear part's replacement interval no longer resets the clock.** The
  due date now re-bases off the part's last-replaced date (or its creation), so
  changing "every 3 months" to "every 4 months" extends the schedule instead of
  restarting it from today.
- **A future "last replaced" date is rejected**, and duplicate part identifiers are
  regenerated, so a part's derived task can't be silently hidden or mis-stamped.

## [0.1.0b3] - 2026-06-14

- **Cross-integration task contributions.** Other integrations can now contribute
  recurring tasks to Home Keeper and stay in two-way sync — with no code dependency in
  either direction. A task carries an opaque, caller-namespaced `source`;
  `home_keeper.add_task` returns the new `task_id` in its service response; and Home
  Keeper fires a `home_keeper_task_completed` event (carrying `source` and an `origin`
  marker) on every completion — whether checked off in the to-do list, pressed on the
  device button, or completed via the service — so a contributor can mirror completions
  both ways and break loops. A new `home_keeper.testing` helper (an in-memory fake of
  the services + completion event, built on Home Keeper's own model code) plus a public
  `docs/INTEGRATING.md` make it easy for other integrations to build and test against
  the contract.

- **Internationalization (16 languages).** Home Keeper is now localized into a
  common set of locales — English, German, French, Spanish, Italian, Dutch,
  Polish, Brazilian Portuguese, Norwegian Bokmål, Swedish, Danish, Finnish,
  Czech, Russian, Simplified Chinese, and Catalan. The config flow, service
  definitions, and device-page entity names use Home Assistant's native
  translation system (`strings.json` ↔ `translations/<lang>.json`), and the
  sidebar panel ships a small dependency-free i18n module that follows your HA
  language (with English fallback for anything untranslated). Plural forms use
  the browser's `Intl.PluralRules`, and parity tests keep every locale in sync
  with the English source on both the backend and the frontend.

- **Panel rebuilt on the Home Assistant design language.** The admin sidebar panel
  now uses HA's own components throughout instead of hand-rolled markup: every form
  is a native `ha-form` (with HA's text/number/select/date fields, the **searchable
  device & area pickers**, and the **mdi icon picker**), task/appliance rows are
  `ha-card`s, navigation uses `ha-tab-group`, status shows as `ha-assist-chip`, and
  actions use `ha-button`/`ha-icon-button`. Looks and behaves like the rest of HA
  (theming, dark mode, mobile) — no functional changes to tasks or appliances.

## [0.1.0b2] - 2026-06-14

- **Appliances & virtual devices.** A new **Appliances** tab in the panel lets you
  register an appliance Home Keeper provisions as a real **virtual device** (so
  multiple maintenance tasks share one device page), or attach **asset metadata** to
  an existing device from another integration. Metadata covers manufacturer/model/
  serial, purchase/install/**warranty-expiry** dates, cost, vendor, manual link, and
  consumable part numbers. Date fields are exposed as `date` **sensors** on the
  device page so they're automatable (e.g. warranty-expiry reminders).
  - New services: `add_asset`, `update_asset`, `delete_asset`, `list_assets`, plus
    matching websocket commands for the panel.
  - Virtual devices are owned by the config entry, so removing Home Keeper cleans
    them up; deleting an appliance detaches its tasks (they become standalone).
- **Structured parts & wear items.** Appliances now carry a structured parts list
  (name, part number, vendor, cost, consumable/wear type) replacing the old free-text
  part-numbers string. A **wear item** with a replacement interval automatically
  creates a maintenance task on the appliance's device (to-do + calendar + mark-done
  button + next-due sensor), and completing it stamps the part's *last replaced* date.
- **Subdevices & related devices.** An appliance can be a subdevice of another
  (native HA `via_device` nesting), and can list arbitrary related devices — including
  foreign ones — surfaced in the panel.
- **Tighter HA integration.** `area_id` is validated against real HA areas; virtual
  devices link back to the panel via `configuration_url`; appliances take an optional
  mdi icon; and a `diagnostics.py` download is available for support.

## [0.1.0b1] - 2026-06-13

Initial UX prototype (beta). Published as a pre-release — offered via HACS only to
users who enable "Show beta versions". The stable `0.1.0` will be cut from this
once the prototype settles.

- Recurrence engine supporting **floating** (reset-from-completion) and **fixed**
  (anchored DAILY/WEEKLY/MONTHLY schedule) tasks, with end-of-month clamping.
- Local task storage and a `DataUpdateCoordinator`.
- A dedicated **Home Keeper sidebar panel** for administration: list tasks, create/
  edit with a recurrence editor, and optionally attach a task to a device.
- Native usage entities: a `todo` list and a `calendar`, plus per-task `button`,
  `sensor`, and `binary_sensor` entities that attach to a device's page when a task
  is linked to a device.
- Services: `add_task`, `update_task`, `delete_task`, `complete_task`, `list_tasks`,
  and matching websocket commands for the panel.
- Full test harness: pytest unit tests for the recurrence engine/model, a Docker
  integration suite, Playwright e2e smoke tests + screenshot capture, and vitest
  frontend tests. PR-merge-driven release workflow with beta/stable channels.
