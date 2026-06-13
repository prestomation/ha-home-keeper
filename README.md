# Home Keeper

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HACS Validation](https://github.com/prestomation/ha-home-keeper/actions/workflows/hacs.yml/badge.svg)](https://github.com/prestomation/ha-home-keeper/actions/workflows/hacs.yml)
[![License](https://img.shields.io/github/license/prestomation/ha-home-keeper)](LICENSE)

Track home **maintenance** and **chores** in Home Assistant — fridge/furnace filter
changes, water filters, taking medicine, and anything else that recurs.

> ⚠️ **Prototype.** This is an early UX prototype to try out interaction ideas. The
> data model, entities, and panel are functional but expect rough edges and change.
> See [IDEAS.md](IDEAS.md) for what's planned next.

![Home Keeper task list](docs/images/1-panel-task-list.png)

## Concepts

A **task** has a name, notes, an optional device it's attached to, and a recurrence:

- **Floating** — measured from the last completion: *"replace the fridge filter every
  1 month after I last did it."* Completing the task resets the clock; a missed task
  stays overdue rather than silently rolling forward.
- **Fixed** — an anchored calendar schedule: *"take medicine every day at 8am"*,
  independent of when you actually complete it.

An **appliance** (asset) is the physical thing a task is about — a fridge, furnace,
water heater. See [Appliances & virtual devices](#appliances--virtual-devices) below.

## How you interact with it

Administration and usage are intentionally **separated**:

- **Manage** tasks from the **Home Keeper** panel in the sidebar — a full-page admin
  UI to create/edit/delete tasks, configure recurrence, and optionally attach a task
  to an existing device.
- **Use** tasks through native Home Assistant entities, so they show up in HA's
  built-in cards and the mobile app:
  - `todo.home_keeper_tasks` — a to-do list; checking an item off completes the task
    and advances its recurrence.
  - `calendar.home_keeper_upcoming_tasks` — upcoming occurrences on a calendar.
  - For tasks **attached to a device**, per-task `button` (mark done), `sensor`
    (next due) and `binary_sensor` (overdue) entities appear **on that device's
    page** — so e.g. your fridge shows its filter task right alongside it.

## Appliances & virtual devices

Most appliances you actually maintain — a "dumb" fridge, furnace, or water heater —
aren't Home Assistant devices, so there's nowhere to hang their maintenance tasks or
record their warranty. Home Assistant core can't create devices by hand; they only
come from integrations. Home Keeper fills that gap with **appliances**, managed from
the **Appliances** tab in the panel.

![Appliances list](docs/images/5-panel-appliances-list.png)

There are two ways to use it:

- **New appliance** — Home Keeper registers a real **virtual device** for it. Now
  multiple tasks (replace filter, flush tank, change anode rod) share *one* device
  page instead of each becoming its own throwaway device. Because it's a genuine
  registry device, other integrations (e.g. Battery Notes) can attach to it too.
- **Existing device** — point Home Keeper at a device another integration already
  provides (a smart fridge) and enrich it with the same metadata, without owning it.

Either way you can record **asset metadata** — manufacturer/model/serial, purchase /
install / **warranty-expiry** dates, cost, vendor, manual link, and consumable part
numbers (filter/bulb models). Dates become real `date` **sensors** on the device
page, so they're automatable natively — e.g. *"warranty expiring in 30 days →
notify me"* — and show up in state history without any custom card.

![Add an appliance](docs/images/6-panel-appliance-create.png)

> **Example.** Add the *Garage water heater* as a new appliance with its warranty
> expiry and anode-rod part number, then create a floating *"flush tank every 6
> months"* task attached to it. The water heater now has its own device page showing
> the next-due flush, a mark-done button, an overdue indicator, and a warranty-expiry
> sensor you can build a reminder automation on.

## Services

Task services: `home_keeper.add_task`, `update_task`, `delete_task`, `complete_task`,
and `list_tasks` (returns a response).

Appliance services: `home_keeper.add_asset`, `update_asset`, `delete_asset`, and
`list_assets` (returns a response). All are available for automations.

## Development

- Backend: `custom_components/home_keeper/` (recurrence engine in `recurrence.py`).
- Panel frontend: `custom_components/home_keeper/frontend/` (TypeScript + Rollup).
- Tests: `pytest` unit (`tests/unit`), Docker integration (`tests/integration`),
  Playwright e2e (`tests/e2e`), and vitest frontend tests.

See [AGENTS.md](AGENTS.md) for workflow and [RELEASE.md](RELEASE.md) for releases.
