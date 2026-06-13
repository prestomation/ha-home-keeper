# Home Keeper

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HACS Validation](https://github.com/prestomation/ha-home-keeper/actions/workflows/hacs.yml/badge.svg)](https://github.com/prestomation/ha-home-keeper/actions/workflows/hacs.yml)
[![License](https://img.shields.io/github/license/prestomation/ha-home-keeper)](LICENSE)

Track home **maintenance** and **chores** in Home Assistant — fridge/furnace filter
changes, water filters, taking medicine, and anything else that recurs.

> ⚠️ **Prototype.** This is an early UX prototype to try out interaction ideas. The
> data model, entities, and panel are functional but expect rough edges and change.
> See [IDEAS.md](IDEAS.md) for what's planned next.

## Concepts

A **task** has a name, notes, an optional device it's attached to, and a recurrence:

- **Floating** — measured from the last completion: *"replace the fridge filter every
  1 month after I last did it."* Completing the task resets the clock; a missed task
  stays overdue rather than silently rolling forward.
- **Fixed** — an anchored calendar schedule: *"take medicine every day at 8am"*,
  independent of when you actually complete it.

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

## Services

`home_keeper.add_task`, `update_task`, `delete_task`, `complete_task`, and
`list_tasks` (returns a response) are available for automations.

## Development

- Backend: `custom_components/home_keeper/` (recurrence engine in `recurrence.py`).
- Panel frontend: `custom_components/home_keeper/frontend/` (TypeScript + Rollup).
- Tests: `pytest` unit (`tests/unit`), Docker integration (`tests/integration`),
  Playwright e2e (`tests/e2e`), and vitest frontend tests.

See [AGENTS.md](AGENTS.md) for workflow and [RELEASE.md](RELEASE.md) for releases.
