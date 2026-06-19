# Home Keeper

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HACS Validation](https://github.com/prestomation/ha-home-keeper/actions/workflows/hacs.yml/badge.svg)](https://github.com/prestomation/ha-home-keeper/actions/workflows/hacs.yml)
[![License](https://img.shields.io/github/license/prestomation/ha-home-keeper)](LICENSE)

Track home **maintenance** and **chores** in Home Assistant — fridge/furnace filter
changes, water filters, taking medicine, and anything else that recurs.

![Home Keeper task list](docs/images/1-panel-task-list.png)

## Features at a glance

- **Recurring tasks, three ways** — **floating** (every N units after last done),
  **fixed** (anchored calendar schedule), and **triggered** (condition-driven, no
  schedule — armed/cleared by another integration).
- **Used through native HA entities** — a `todo` list, an upcoming-tasks `calendar`,
  and per-device **button / next-due sensor / overdue binary_sensor** on a task's
  device page.
- **Dashboard task card** — a bundled, auto-registered `custom:home-keeper-card` with
  one-tap **Done**, inline add/edit, and rich filtering/grouping.
- **Appliances & virtual devices** — give "dumb" appliances a real device page,
  structured metadata (with optional tracked-date sensors), **parts & wear items**,
  **spare-part inventory**, and a CSV **home-inventory export** for insurance.
- **Events & automation triggers** — a bus event for every meaningful change, plus
  visual-editor **device triggers** like *"Task became overdue."*
- **Services for everything** — every data action is a `home_keeper.*` service for
  automations, scripts, and voice.
- **Localized in 16 languages**, following your Home Assistant language.
- **Open to other integrations** — they can contribute their own recurring tasks and
  stay in sync with completions.

## Installation

Home Keeper is a custom integration installed via [HACS](https://hacs.xyz/):

1. In HACS, add this repository as a **custom repository** (category *Integration*):
   `https://github.com/prestomation/ha-home-keeper`.
2. Install **Home Keeper**, then restart Home Assistant.
3. Add the integration from **Settings → Devices & Services → Add Integration →
   Home Keeper**.

A **Home Keeper** panel then appears in the sidebar. Tasks and appliances are stored
locally in a single JSON document (`.storage/home_keeper`).

## Concepts

A **task** has a name, notes, an optional device it's attached to, and a recurrence:

- **Floating** — measured from the last completion: *"replace the fridge filter every
  1 month after I last did it."* Completing the task resets the clock; a missed task
  stays overdue rather than silently rolling forward.
- **Fixed** — an anchored calendar schedule: *"take medicine every day at 8am"*,
  independent of when you actually complete it.
- **Triggered** — *condition-driven, no schedule* (see below).

An **appliance** (asset) is the physical thing a task is about — a fridge, furnace,
water heater (see [Appliances & virtual devices](#appliances--virtual-devices)).

Administration and usage are intentionally **separated**: you **manage** tasks and
appliances from the **Home Keeper** sidebar panel, and **use** them through native HA
entities and the dashboard card. The panel list view can group/filter tasks, and
tapping any row opens a detail page with the full schedule, notes, and completion
history.

## Condition-driven (triggered) tasks

Some upkeep isn't periodic — it's a **reaction to a condition**: a battery dropping
low, a water sensor going wet, a filter past its pressure threshold. A **triggered**
task models exactly that. It has no schedule; an owning integration (for batteries,
the companion [Battery Notes glue](https://github.com/prestomation/ha-home-keeper-battery-notes))
**arms** it when the condition becomes true and **clears** it when resolved.

- While **armed**, it reads as **due now** everywhere — the to-do list, the device's
  overdue sensor, the panel — with a *"Managed by …"* chip showing who owns it.
- When you replace/fix the thing (from either side), the task records the event and
  goes **dormant**: it leaves the to-do list and calendar and tucks into a collapsed
  **"Monitored"** section until it's next needed.
- Because the task persists across cycles, its **completion history accumulates** — so
  you learn the real cadence ("you replace this smoke-detector battery every ~13
  months") instead of losing it on every replacement.

![Battery task detail — monitored, managed by Battery Notes, with replacement history](docs/images/14-panel-battery-detail.png)

## Dashboard task card

The bundled **Home Keeper Tasks** card (`custom:home-keeper-card`) is a resizable list
of your tasks with a one-tap **Done** button on each row; tapping a row opens an inline
add/edit/delete form. It's auto-registered (no resource setup) and appears in the
dashboard **"Add card"** picker. Its GUI editor lets you filter (by status, area,
device, recurrence type, or a "due within N days" horizon), sort, group, cap rows, and
toggle what each row shows. It's built from HA's own components and theme and reflects
completions made anywhere else in real time.

![Home Keeper task card grouped into status sections, with an inline add form](docs/images/card-grouped.png)

## Appliances & virtual devices

Most appliances you actually maintain — a "dumb" fridge, furnace, or water heater —
aren't Home Assistant devices, so there's nowhere to hang their maintenance tasks or
record their warranty. Home Keeper fills that gap with **appliances**, managed from the
**Appliances** tab in the panel. Two ways to use it:

- **New appliance** — Home Keeper registers a real **virtual device** for it, so
  multiple tasks share *one* device page and other integrations can attach to it too.
- **Existing device** — point Home Keeper at a device another integration already
  provides and enrich it with the same metadata, without owning it.

Either way you record **asset metadata**. A few structured fields wire into Home
Assistant — manufacturer/model, an mdi icon, a manual link, replacement cost — and
beyond that you add free-form **custom fields**, each a label with a value typed as
**text**, **link**, or **date** (seeded with common ones like serial number, warranty
expiry, purchase/install dates). Tick **track** on a date and it becomes a real `date`
**sensor** on the device page, so it's automatable natively (e.g. *"warranty expiring
in 30 days → notify me"*). Untracked dates stay display-only.

Tapping an appliance opens a **detail page** gathering its metadata, parts, related
tasks, subdevices, and full maintenance history (including retained history of tasks
deleted while still assigned to it). The tab also has an **Export inventory** button
that downloads a CSV **home inventory** — make/model, replacement cost, value of spares
on hand (with a grand total), and a Details column flattening each appliance's custom
fields. It's the grab-and-go record you want for an insurance claim.

![Appliance detail page](docs/images/8-panel-appliance-detail.png)

### Parts & wear items

Each appliance has a structured **parts** list — name, part number, vendor, cost, and a
type of *consumable* (a stocked spare) or *wear item*. Give a wear item a **replacement
interval** and Home Keeper automatically creates a maintenance **task** for it, attached
to the appliance's device — so it shows up in your to-do list and calendar, gets a
mark-done button and next-due sensor, and stamps the part's *last replaced* date when
completed. You can also backdate **when a wear item was last replaced** so the schedule
starts from the real date.

Any part can also track **spare inventory** — a *stock* count and a *reorder-at*
threshold. Completing a wear-item replacement consumes one spare, and when stock drops
to (or below) the threshold Home Keeper fires a `home_keeper_part_low_stock` event you
can automate on (add to a shopping list, notify, reorder).

### Relationships: subdevices & related devices

Real things nest. An appliance can be a **subdevice of** another appliance (wired
through HA's native `via_device` hierarchy, so it nests under its parent on the device
page). You can also tag arbitrary **related devices** — including ones from other
integrations HA won't let us reparent — which show up alongside the appliance.

> **Example.** Add the *Garage water heater* as a new appliance with its warranty
> expiry and an *Anode rod* **wear item** set to "replace every 12 months." The water
> heater now has its own device page with a warranty-expiry sensor, plus an automatic
> *"Replace Anode rod"* to-do that's due 12 months after each completion.

## Services

Every data action is a Home Assistant service, so it's usable from automations,
scripts, and voice:

- **Tasks** — `home_keeper.add_task`, `update_task`, `delete_task`, `complete_task`,
  `trigger_task` (arm a condition-driven task), and `list_tasks` (returns a response).
- **Appliances** — `home_keeper.add_asset`, `update_asset`, `delete_asset`,
  `adjust_part_stock`, `list_assets`, and `export_inventory` (the last two return a
  response).

## Events & automations

Home Keeper fires a Home Assistant **bus event** for every meaningful change so you can
automate on it — tasks (created, updated, completed, uncompleted, deleted, armed, and
the time-based **overdue** / **due-soon** transitions), spare parts (**low stock**,
**out of stock**, **restocked**), and appliances (created, updated, deleted).

You can trigger on these two ways: pick a **device trigger** in the visual automation
editor (e.g. *"Task became overdue"*, *"Spare part out of stock"* — no event names to
memorise), or use a plain `platform: event` trigger. For example, *spare part out of
stock → add it to the shopping list*:

```yaml
automation:
  - alias: "Spare out of stock → shopping list"
    trigger:
      - platform: event
        event_type: home_keeper_part_out_of_stock
    action:
      - service: todo.add_item
        target: { entity_id: todo.shopping_list }
        data:
          item: "{{ trigger.event.data.part_name }} ({{ trigger.event.data.vendor }})"
```

Events are **edge-triggered** (one event per crossing, never repeated each cycle) and
silently baselined on restart (no "overdue" storm after a reboot). The full catalog —
every event, its payload, and more examples — is in [docs/EVENTS.md](docs/EVENTS.md).

## Integrating with Home Keeper

Other integrations can contribute their own recurring tasks to Home Keeper and stay in
sync with completions — without Home Keeper knowing anything about them. See
[docs/INTEGRATING.md](docs/INTEGRATING.md) for the contract (the `source` field, the
`home_keeper_task_completed` event, and two-way completion sync).

## Localization

The integration and the sidebar panel are localized into **16 languages** and follow
your Home Assistant language, falling back to English for anything untranslated.
Translations live in `custom_components/home_keeper/translations/`.

## Development

- Backend: `custom_components/home_keeper/` (recurrence engine in `recurrence.py`).
- Panel frontend: `custom_components/home_keeper/frontend/` (TypeScript + Rollup).
- Tests: `pytest` unit (`tests/unit`), Docker integration (`tests/integration`),
  Playwright e2e (`tests/e2e`), and vitest frontend tests.

See [AGENTS.md](AGENTS.md) for workflow and [RELEASE.md](RELEASE.md) for releases.
