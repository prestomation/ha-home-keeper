# Changelog

All notable changes to Home Keeper are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses semantic
versioning (with PEP 440 pre-release suffixes — `bN`/`aN`/`rcN` — for betas).

## [Unreleased]

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
