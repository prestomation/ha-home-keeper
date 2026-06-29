# Changelog

All notable changes to Home Keeper are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses semantic
versioning (with PEP 440 pre-release suffixes — `bN`/`aN`/`rcN` — for betas).

## [0.7.0b2]

### Added

- **Integration-provided metadata chips on tasks.** Integrations can now attach
  compact metadata chips to any task via the `task_chips` field on
  `home_keeper.add_task` / `update_task`. Each chip carries a label, an optional
  `mdi:` icon, and an optional link URL — making contextual information (e.g. battery
  type, part number) immediately visible in both the **sidebar panel task list** and
  the **dashboard card** without cluttering the task notes.

## [0.7.0b1] - 2026-06-29

Internal version bump after 0.6.0 stable shipped.

## [0.6.0] - 2026-06-29

This release adds **consumable linking** so completing a task (e.g. swapping a water
filter) automatically draws down your spare stock and fires a reorder alert,
**appliance document shortcuts** directly on dashboard card rows so a manual or parts
page is one tap away, and a round of **panel clarity improvements** that make the task
list easier to read at a glance. Highlights, for anyone upgrading from 0.5.0:

### Added

- **Link a task to a consumable (sensor-driven reorder).** Any task can now be
  **linked to an appliance consumable** so that marking it done **consumes one spare**
  from the part's stock — and fires `home_keeper_part_low_stock` when you cross the
  reorder threshold, so an automation can add it to your shopping list. Pair it with a
  **sensor-based** task to cover the *"there's no schedule — my fridge tells me when
  the water filter is spent"* case: the sensor arms the task, and completing it (when
  you swap the filter) draws down inventory and signals **buy more**. Link from the
  task form's new **Linked consumable** picker — scoped to the consumables of the
  appliance the task is attached to — or with the new
  **`home_keeper.set_task_consumable`** service (omit the ids to unlink).

- **Show appliance documents on a task's dashboard-card row.** Each task can now pick
  which of its appliance's documents to surface directly on the
  [dashboard task card](README.md#dashboard-task-card): external **document links**,
  **uploaded files** (a PDF manual, a photo), and free-form **metadata links** (e.g. a
  reorder or warranty page). Choose them in the panel's task editor under **Links to
  show on card** (the picker appears once the task's appliance has documents); the card
  renders each as a compact chip on the task's row — a link or file opens in a new tab
  (an uploaded file via a short-lived signed URL) — so a manual or parts page is one
  tap away while you work. The selection rides the existing `home_keeper.add_task` /
  `update_task` services (`card_links`), and entries resolve live — rename or remove
  one on the appliance and the card follows.

### Changed

- **Panel clarity improvements for first-time users.** Several refinements make the
  task list easier to read at a glance: a dismissible **"Welcome to Home Keeper"**
  banner on the Tasks tab explains the kinds of tasks you'll see; the recurrence
  picker now uses **plain language** ("Repeats after each completion", "Repeats on a
  fixed schedule", "Just once", "Based on a sensor") instead of internal jargon;
  overdue tasks show **how overdue** they are (e.g. "3 days overdue"); monitored tasks
  are labelled simply **"Monitored"** and a completion-blocked task shows a muted
  **"Clears automatically"** caption; sensor-synced tasks owned by Home Keeper show an
  **"Auto-synced"** chip; and the appliance editor's **Custom fields** and
  **Parts & wear items** sections collapse by default on a new appliance so first
  setup isn't a wall of fields.

- **Tapping a task row on the dashboard card no longer opens an edit form.** The card
  is now a focused do-and-glance surface: one-tap **Done**, add via the header **+**,
  and link chips — while editing and deleting move to the sidebar panel, where the
  full task editor lives.

### Fixed

- **The dashboard card and panel now reliably refresh after an update.** Their module
  URLs are cache-busted by the bundle's **content hash** instead of the integration
  version, so a rebuilt frontend always loads fresh — no more stale card (or "card
  configuration error" in the mobile app) after upgrading, including across preview
  builds that reuse a version string.
- **Uploaded file documents on the card now open in the mobile app.** A pinned file
  chip is now a plain link with its URL pre-signed when the card loads, so a tap opens
  it natively — the Home Assistant companion app (iOS/WKWebView) was silently blocking
  the previous open-on-tap.
- **Back navigation from a cross-view detail page now returns to the correct previous
  page.** Navigating Appliance → device → related Task and pressing Back used to jump
  to the top-level Tasks tab instead of back to the appliance/device view. (Fixes #105)
- **Problem Sensor Sync no longer leaves stale entities after disabling or excluding.**
  Disabling the sync, or adding a device/entity/label exclusion, now removes the
  `next_due` sensor and `overdue` binary sensor that were created for the synced task —
  they no longer linger on the device after the task is gone. (Fixes #104)
