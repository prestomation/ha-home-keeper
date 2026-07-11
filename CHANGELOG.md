# Changelog

All notable changes to Home Keeper are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses semantic
versioning (with PEP 440 pre-release suffixes — `bN`/`aN`/`rcN` — for betas).

## [0.9.0b2]

### Added

- **Link a spare part to a problem-sensor task — track inventory and where to buy
  it.** When Home Keeper mirrors a `device_class: problem` binary sensor as a task
  (e.g. an air filter reporting it needs replacing), you can now attach a **spare
  consumable part** to that task from its detail page (**Attach a spare part**). Once
  linked, the task surfaces **where to buy it** (the part's vendor and product link)
  and **how many spares you have on hand**, right next to the problem — closing the gap
  between "something needs attention" and "here's the part and where to reorder it".
  If the sensor's device has no appliance in Home Keeper yet, a **Create appliance for
  this device** shortcut sets one up so you have somewhere to record the part. Like the
  note, the link sticks with the sensor: it survives the task clearing and re-arming,
  and even the mirror being removed and recreated. Optionally, turn on **Use a spare
  when the problem clears** so that resolving the problem (the sensor returning to OK)
  automatically **draws down one spare** and fires the low/out-of-stock events you can
  automate a reorder from — off by default, so nothing moves your inventory unless you
  ask it to.

## [0.9.0b1]

### Added

- **Notes on problem-sensor tasks — remembered for next time.** When Home Keeper
  mirrors a `device_class: problem` binary sensor as a task, you can now attach a
  free-text note to it right from the task's detail page (**Add a note** → type →
  **Save**). The note is for the instructions you want next time the problem fires —
  the fix that worked last time, a part number, where the shut-off valve is. It sticks
  with that sensor: it survives the task clearing and re-arming, and even survives the
  mirror being removed and recreated (turning problem-sensor sync off and on, or
  temporarily excluding the sensor), so it reappears the next time the same problem
  goes off.

## [0.8.0] - 2026-07-04

### Added

- **Discover known companions from the panel.** The **Settings → Companions** section
  now links out to the docs catalog of integrations and glue that work with Home
  Keeper, so you can browse the full list even when nothing is detected on your setup.
  The docs page also invites you to open a GitHub issue to suggest a companion (or
  glue) integration that should be listed.
- **In-form help for creating tasks.** The task editor now explains itself as you fill
  it in: every field carries concise helper text, a **?** icon by the form title links
  straight to the docs, and **sensor-based** tasks gain a short primer plus a **live,
  computed hint** that reads the bound sensor and spells out what happens next — e.g.
  *"This sensor reads 660 h now. The task becomes due at 760 h, then every 100 h after
  each completion."* This clears up the most common confusion with usage-meter tasks:
  the target counts usage **from the sensor's current reading**, not from zero, and the
  count restarts after each completion.
- **Product URL on replaceable parts.** A part can now carry a link to where you buy
  it (e.g. an Amazon listing). When set, the part's name in the appliance detail page
  becomes a clickable link that opens the product page in a new tab, so reordering a
  worn or consumed part is one click away. (Fixes #118)
- **Attach a file to a replaceable part.** A part can now carry a single attached
  file (a receipt, spec sheet, or photo) alongside its product URL — upload it from
  the part's editor and open or remove it later, the same secure upload/storage path
  appliance documents already use.
- **A linked task's "Consumable link" points straight at the part's product page.**
  When a maintenance task is tied to a part that has a product URL, that link now
  opens the product page directly — in the panel's task detail and on the dashboard
  card's task row — instead of just naming the part.
- **Auto-create a "buy" task when a spare part runs low.** A replaceable part that
  tracks stock with a reorder threshold can now opt into an automatic shopping
  reminder: enable **Auto-create buy task** on the part, and whenever its stock drops
  to (or below) the reorder point Home Keeper adds a one-off **"Buy {part}"** task —
  on the appliance's device page, the to-do list, and the panel. The reminder clears
  itself once the part is restocked above the threshold (or you turn the option off).
  Completing the reminder **restocks the part** by a configurable **Restock quantity**
  (default 1), closing the low → buy → restocked loop with no automation to write.

### Changed

- **A task's appliance links now render as chips, inline with the rest.** On the
  dashboard card, a task's document/metadata links, uploaded files, and a linked
  part's product URL previously appeared as plain blue links in a separate row below
  the task's chips, which read inconsistently. They now render as primary-tinted
  link-chips in the same chip row as the status, area, and label chips — one tidy,
  wrapping row — while still opening in a new tab on tap.

### Fixed

- **Auto-generated maintenance task names now follow your Home Assistant language.**
  The name Home Keeper generates for a wear part (e.g. "Replace {part} ({appliance})")
  was always English; it's now translated into your configured language across every
  surface — the panel, the to-do list, the calendar, notifications, and the device
  pages — and updates automatically if you change the language. (Fixes #119)
- Fixed a batch of bugs found during an in-depth code review (correctness,
  security, and reliability), plus internal maintainability cleanups.

## [0.8.0b5]

### Changed

- **A task's appliance links now render as chips, inline with the rest.** On the
  dashboard card, a task's document/metadata links, uploaded files, and a linked
  part's product URL previously appeared as plain blue links in a separate row below
  the task's chips, which read inconsistently. They now render as primary-tinted
  link-chips in the same chip row as the status, area, and label chips — one tidy,
  wrapping row — while still opening in a new tab on tap.

## [0.8.0b4]

### Added

- **Auto-create a "buy" task when a spare part runs low.** A replaceable part that
  tracks stock with a reorder threshold can now opt into an automatic shopping
  reminder: enable **Auto-create buy task** on the part, and whenever its stock drops
  to (or below) the reorder point Home Keeper adds a one-off **"Buy {part}"** task —
  on the appliance's device page, the to-do list, and the panel. The reminder clears
  itself once the part is restocked above the threshold (or you turn the option off).
  Completing the reminder **restocks the part** by a configurable **Restock quantity**
  (default 1), closing the low → buy → restocked loop with no automation to write.

## [0.8.0b3]

### Added

- **Product URL on replaceable parts.** A part can now carry a link to where you buy
  it (e.g. an Amazon listing). When set, the part's name in the appliance detail page
  becomes a clickable link that opens the product page in a new tab, so reordering a
  worn or consumed part is one click away. (Fixes #118)

- **Attach a file to a replaceable part.** A part can now carry a single attached
  file (a receipt, spec sheet, or photo) alongside its product URL — upload it from
  the part's editor and open or remove it later, the same secure upload/storage path
  appliance documents already use.

- **A linked task's "Consumable link" points straight at the part's product page.**
  When a maintenance task is tied to a part that has a product URL, that link now
  opens the product page directly — in the panel's task detail and on the dashboard
  card's task row — instead of just naming the part.

### Fixed

- Fixed a batch of bugs found during an in-depth code review (correctness,
  security, and reliability), plus internal maintainability cleanups.

## [0.8.0b2]

### Added

- **In-form help for creating tasks.** The task editor now explains itself as you fill
  it in: every field carries concise helper text, a **?** icon by the form title links
  straight to the docs, and **sensor-based** tasks gain a short primer plus a **live,
  computed hint** that reads the bound sensor and spells out what happens next — e.g.
  *"This sensor reads 660 h now. The task becomes due at 760 h, then every 100 h after
  each completion."* This clears up the most common confusion with usage-meter tasks:
  the target counts usage **from the sensor's current reading**, not from zero, and the
  count restarts after each completion.

### Fixed

- **Auto-generated maintenance task names now follow your Home Assistant language.**
  The name Home Keeper generates for a wear part (e.g. "Replace {part} ({appliance})")
  was always English; it's now translated into your configured language across every
  surface — the panel, the to-do list, the calendar, notifications, and the device
  pages — and updates automatically if you change the language. (Fixes #119)

## [0.8.0b1]

### Added

- **Discover known companions from the panel.** The **Settings → Companions** section
  now links out to the docs catalog of integrations and glue that work with Home
  Keeper, so you can browse the full list even when nothing is detected on your setup.
  The docs page also invites you to open a GitHub issue to suggest a companion (or
  glue) integration that should be listed.

## [0.7.0] - 2026-06-30

### Added

- **Integration-provided metadata chips on tasks.** Integrations can now attach
  compact metadata chips to any task via the `task_chips` field on
  `home_keeper.add_task` / `update_task`. Each chip carries a label, an optional
  `mdi:` icon, and an optional link URL — making contextual information (e.g. battery
  type, part number) immediately visible in both the sidebar panel task list and the
  dashboard card without cluttering the task notes.

- **Richer appliance device pages.** A virtual appliance's Home Assistant device page
  now surfaces much more of its Home Keeper data: the device-info block shows a
  first-class **serial number** (alongside make/model), each stock-tracked part gets
  an editable **spare-stock number** and a **low-stock problem sensor**, and the
  page's **Visit** link deep-links straight to that appliance's panel page (manuals,
  full inventory, history) rather than the panel root. Per-device **diagnostics**
  download is scoped to just that appliance's tasks and parts.

- **Jump from the panel to an appliance's device page.** The **"Virtual device"**
  chip on the Appliances list and appliance detail is now a clickable link to that
  appliance's Home Assistant device page (it was a static marker before).

### Fixed

- **Problem Sensor Sync no longer leaves empty device cards behind.** When you
  disable Problem Sensor Sync — or exclude an individual sensor, device, area, or
  label — the synced task and its entities are removed as before, and now the
  associated device is cleaned up too: a device Home Keeper created for the synced
  task is removed outright, and a device owned by another integration simply loses
  its (now entity-less) Home Keeper association. No more orphaned, zero-entity Home
  Keeper devices under **Settings → Devices & Services → Home Keeper**.

- **Device chip on a task/appliance card row now opens the device page.** Clicking
  the device chip was hijacked by the card row's open-detail handler (it opened the
  task or appliance detail instead); the chip click no longer bubbles to the row.

## [0.7.0b4]

### Added

- **Richer appliance device pages.** A virtual appliance's Home Assistant device page now
  surfaces much more of its Home Keeper data: the device-info block shows a first-class
  **serial number** (alongside make/model), each stock-tracked part gets an editable
  **spare-stock number** and a **low-stock problem sensor**, and the page's **Visit** link
  deep-links straight to that appliance's panel page (manuals, full inventory, history)
  rather than the panel root. Per-device **diagnostics** download is scoped to just that
  appliance's tasks and parts. A task attached to a *foreign* device is left to its
  owning integration (Home Keeper only adds its per-task entities there).
- **Jump from the panel to an appliance's device page.** The **"Virtual device"** chip
  on the Appliances list and appliance detail is now a clickable link to that
  appliance's Home Assistant device page (it was a static marker before).

### Fixed

- **Device chip on a task/appliance card row now opens the device page.** Clicking the
  device chip was hijacked by the card row's open-detail handler (it opened the task or
  appliance detail instead of navigating to the device); the chip click no longer
  bubbles to the row.

## [0.7.0b3] - 2026-06-29

### Fixed

- **Problem Sensor Sync no longer leaves empty device cards behind.** When you
  disable Problem Sensor Sync — or exclude an individual sensor, device, area, or
  label — the synced task and its entities are removed as before, and now the
  associated device is cleaned up too: a device Home Keeper created for the synced
  task is removed outright, and a device owned by another integration simply loses
  its (now entity-less) Home Keeper association. No more orphaned, zero-entity
  Home Keeper devices under **Settings → Devices & Services → Home Keeper**.

## [0.7.0b2] - 2026-06-29

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

## [0.6.0b4]

### Added

- **Show appliance documents on a task's dashboard-card row.** Each task can now pick
  which of its appliance's documents to surface directly on the
  [dashboard task card](README.md#dashboard-task-card): external **document links**,
  **uploaded files** (a PDF manual, a photo), and free-form **metadata links** (e.g. a
  reorder or warranty page). Choose them in the panel's task editor under **Links to
  show on card** (the picker appears once the task's appliance has documents); the card
  renders each as a compact chip on the task's row — a link or file opens in a new tab
  (an uploaded file via a short-lived signed URL) — so a manual or parts page is one tap
  away while you work. The selection rides the existing `home_keeper.add_task` /
  `update_task` services (`card_links`), and entries resolve live — rename or remove one
  on the appliance and the card follows.

### Changed

- **Tapping a task row on the dashboard card no longer opens an edit form.** This made
  it easy to accidentally open (and delete from) a task when you only meant to mark it
  done. The card is now a focused do-and-glance surface: one-tap **Done**, add via the
  header **+**, and link chips — while **editing and deleting move to the sidebar
  panel**, where the full task editor lives.

### Fixed

- **The dashboard card and panel now reliably refresh after an update.** Their module
  URLs are cache-busted by the bundle's **content hash** instead of the integration
  version, so a rebuilt frontend always loads fresh — no more stale card (or "card
  configuration error" in the mobile app) after upgrading, including across preview
  builds that reuse a version string.
- **Uploaded file documents on the card now open in the mobile app.** A pinned file
  chip is now a plain link with its URL pre-signed when the card loads, so a tap opens
  it natively — the Home Assistant companion app (iOS/WKWebView) was silently blocking
  the previous open-on-tap because it happened just after an async request. (External
  links were always fine.)

## [0.6.0b3]

### Changed

- **Panel clarity pass for first-time users.** Several refinements make the task list
  easier to read at a glance:
  - A dismissible **"Welcome to Home Keeper"** banner on the Tasks tab explains the
    kinds of tasks you'll see mixed together (recurring, monitored, and companion-
    contributed). Dismiss it with **Got it** and it stays gone.
  - The recurrence picker uses **plain language** — "Repeats after each completion",
    "Repeats on a fixed schedule", "Just once", "Based on a sensor" — instead of the
    "Floating / Fixed / Sensor-based" jargon.
  - Overdue cards now show **how overdue** they are (e.g. "3 days overdue") next to the
    due date, so urgency reads at a glance.
  - Monitored tasks are labelled simply **"Monitored"** (the "(condition-driven)"
    parenthetical is gone), and a completion-blocked task shows a muted
    **"Clears automatically"** caption instead of a dead, greyed-out Done button.
  - Sensor-synced tasks owned by Home Keeper itself now show an **"Auto-synced"** chip
    rather than the redundant "Managed by Home Keeper", and companion **"Managed by …"**
    chips carry the integration's icon so owner/device/status chips read distinctly.
  - The appliance **"Virtual device"** chip has an explanatory tooltip, and the
    appliance editor's advanced **Custom fields** and **Parts & wear items** sections
    **collapse by default** on an empty appliance (and remember your choice while
    editing), so adding a first appliance isn't a wall of fields.

## [0.6.0b2]

### Added

- **Link a task to a consumable (sensor-driven reorder).** Any task can now be
  **linked to an appliance consumable** so that marking it done **consumes one spare**
  from the part's stock — and fires `home_keeper_part_low_stock` when you cross the
  reorder threshold, so an automation can add it to your shopping list. Pair it with a
  **sensor-based** task to cover the *"there's no schedule — my fridge tells me when the
  water filter is spent"* case: the sensor arms the task, and completing it (when you
  swap the filter) draws down inventory and signals **buy more**. Link from the task
  form's new **Linked consumable** picker — scoped to the consumables of the appliance
  the task is attached to — or with the new
  **`home_keeper.set_task_consumable`** service (omit the ids to unlink). The link is
  independent of the auto-generated wear-part tasks, so it's never reconciled away and
  the task stays fully editable.

## [0.6.0b1]

## [0.5.0] - 2026-06-26

This release adds **offline manuals & documents** so appliance files are available
even when a manufacturer's site isn't, **profiles** as named, reusable task filters
you define once and use everywhere, **actionable mobile notifications** so each
household member can complete, snooze, or skip tasks right from their phone, and
standalone **snooze** and **skip** services for any automation. Highlights, for
anyone upgrading from 0.4.0:

### Added

- **Offline manuals & documents.** An appliance can now hold a list of **documents** —
  manuals, warranties, receipts — each either an external **link** or an **uploaded
  file** (PDF or image) stored locally on your Home Assistant instance, so the manual
  is there even when the manufacturer's site isn't. Manage them in the appliance's
  **Manuals & documents** editor: each existing document shows as a card with its name
  and details (a link's URL, or an uploaded file's filename, size and type) and **Open**,
  **Edit** and **Remove** actions — open previews it in a new tab, edit renames it (and
  changes a link's URL; uploaded files are rename-only). A separate **Add a document**
  area adds another link or **uploads a file**; you can attach link documents while first
  creating an appliance, before it's saved. The appliance detail page lists them, opening
  a file through a short-lived signed URL. Uploaded files are served by an authenticated
  endpoint and removed from disk when you delete the document or the appliance. New
  `home_keeper.add_asset_document` / `home_keeper.update_asset_document` /
  `home_keeper.remove_asset_document` services (for links — files upload from the panel)
  and matching websocket commands. This replaces the single appliance `manual_url` field;
  your existing manual link is migrated automatically into a document on upgrade — no
  action needed.
- **Profiles (reusable saved filters).** A **Profile** is a named, saved filter —
  status (overdue / due soon / all) plus optional labels/areas/devices — that you define
  once in **Settings → Profiles** and reuse everywhere tasks are filtered: in a
  notification, in the **Profile** dropdown on the panel's **Tasks** tab, and in the
  dashboard card editor's **Filter by profile** picker. New `home_keeper.list_profiles`
  service and `home_keeper/get_profiles` websocket command read them.
- **Actionable notifications (per-person chore queues).** Home Keeper can now push a
  mobile-app notification for what's due, with **Mark done / Snooze / Skip / Open**
  buttons that route back into Home Keeper so the schedule is recalculated correctly
  (completing advances recurrence; snoozing re-arms a fresh reminder). Configure
  **notifications** in **Settings → Notifications**: each notification references a
  **Profile** (which tasks it covers) and targets one or more companion-app devices with
  its own **button set**, snooze duration, and **style** (a *walk* that sends the first
  due task and advances to the next as you action it, or a single *digest* summary). A
  notification can **auto-send** when a task goes overdue/due-soon, or be triggered on
  demand with the new **`home_keeper.notify`** service — e.g. from a "Chores" calendar
  event — so two household members each get their own filtered list. Tapping an action
  emits a `home_keeper_task_completed` / `_snoozed` / `_skipped` event with
  `origin: home_keeper_notification_action`.
- **Snooze and skip a task.** The notification buttons are also standalone services:
  `home_keeper.snooze_task` (defer a task's due date by a number of hours — "remind me
  later") and `home_keeper.skip_task` (advance to the next occurrence — "skip this one")
  move a task's schedule **without recording a completion** (the maintenance log and a
  floating task's clock are left untouched). Each fires a `home_keeper_task_snoozed` /
  `home_keeper_task_skipped` event, also available as device-automation triggers.

## [0.4.0] - 2026-06-22

This release adds **companion discovery** so integrations that work with Home Keeper
surface in the panel, **sensor-based tasks** driven by a numeric entity rather than the
clock, and **device exclusions** for problem-sensor sync. Highlights, for anyone
upgrading from 0.3.0:

### Added

- **Companion discovery (Settings → Companions).** Home Keeper now surfaces
  integrations that work with it, right in the panel. **Connected** companions
  (integrations that announce themselves — e.g. Pawsistant, or the Battery Notes
  bridge) get a **Configure** button that deep-links to their own settings.
  **Suggested** rows point you at a bridge for a *popular* integration you already have
  installed (e.g. **Battery Notes**) but haven't connected yet, with an **Install**
  link and a **Dismiss** to silence it. Two paths feed this: an integration can
  *register itself* via the new `home_keeper.register_companion` service (so Home
  Keeper never hard-codes it), and Home Keeper *detects* a small curated set of popular
  upstreams from a catalog. New `home_keeper_companion_connected` /
  `home_keeper_companion_suggested` events let automations react. See the
  [Companions](README.md#companions)
  README section and [docs/INTEGRATING.md](docs/INTEGRATING.md) §7.
- **Sensor-based tasks.** A recurrence type whose due-state is derived from a bound
  numeric Home Assistant entity rather than the clock, in two modes. **Usage / meter**
  generalises floating recurrence from elapsed time to elapsed sensor *units* — *"service
  every 500 running hours"*, *"oil every 15,000 km"* — arming once the reading advances
  the chosen **target** since the last completion (which resets the meter; a meter reset
  re-anchors automatically). **Threshold** arms when the reading crosses a comparison
  against a value, with an optional hold and attribute read — *"replace the filter when
  airflow drops below 60 %"* — and re-arms only on a fresh crossing. Armed sensor tasks
  appear on the to-do list and fire `home_keeper_task_overdue` like any
  other; the task detail shows live meter progress. Create them in the panel or via
  `home_keeper.add_task` with a `sensor` mapping.
- **Exclude devices from problem-sensor sync.** The problem-sensor sync feature gains
  an **Excluded devices** picker (panel **Settings**, the options flow, and the
  `home_keeper.set_options` service) alongside the existing entity / area / label
  exclusions. Excluding a device leaves out every `device_class: problem` binary sensor
  that belongs to it.

### Changed

- **Settings tab layout.** The completed one-off retention setting now lives in its own
  **General** card, separate from the **Problem sensor sync** card it's unrelated to.

## [0.4.0b1] - 2026-06-21

### Added

- **Companion discovery (Settings → Companions).** Home Keeper now surfaces
  integrations that work with it, right in the panel. **Connected** companions
  (integrations that announce themselves — e.g. Pawsistant, or the Battery Notes
  bridge) get a **Configure** button that deep-links to their own settings.
  **Suggested** rows point you at a bridge for a *popular* integration you already have
  installed (e.g. **Battery Notes**) but haven't connected yet, with an **Install**
  link and a **Dismiss** to silence it. Two paths feed this: an integration can
  *register itself* via the new `home_keeper.register_companion` service (so Home
  Keeper never hard-codes it), and Home Keeper *detects* a small curated set of popular
  upstreams from a catalog. New `home_keeper_companion_connected` /
  `home_keeper_companion_suggested` events let automations react. See the
  [Companions](README.md#companions)
  README section and [docs/INTEGRATING.md](docs/INTEGRATING.md) §7.
- **Sensor-based tasks.** A recurrence type whose due-state is derived from a bound
  numeric Home Assistant entity rather than the clock, in two modes. **Usage / meter**
  generalises floating recurrence from elapsed time to elapsed sensor *units* — *"service
  every 500 running hours"*, *"oil every 15,000 km"* — arming once the reading advances
  the chosen **target** since the last completion (which resets the meter; a meter reset
  re-anchors automatically). **Threshold** arms when the reading crosses a comparison
  against a value, with an optional hold and attribute read — *"replace the filter when
  airflow drops below 60 %"* — and re-arms only on a fresh crossing. Armed sensor tasks
  appear on the to-do list and fire `home_keeper_task_overdue` like any
  other; the task detail shows live meter progress. Create them in the panel or via
  `home_keeper.add_task` with a `sensor` mapping.

## [0.3.0] - 2026-06-21

This release adds three new ways to drive tasks — condition-driven `triggered`
tasks, one-off do-once tasks, and synced `problem` binary sensors — a Lovelace
dashboard card, rich per-completion history, a comprehensive event/automation
surface, in-panel Settings, and more flexible appliances, and moves the
integration onto the Platinum quality scale. Highlights, for anyone upgrading
from 0.2.0:

### Added

- **Condition-driven (`triggered`) tasks.** A recurrence type for maintenance that
  responds to a *condition* rather than a schedule — a battery going low, a leak, a
  filter past its threshold. A triggered task has no schedule: an owning integration
  arms it (the new `home_keeper.trigger_task` service, or by creating it) when the
  condition becomes true and clears it (`complete_task`) when it resolves, which
  records the event in history and returns the task to a dormant state. Dormant
  triggered tasks are invisible to the to-do list, calendar, and overdue sensors, and
  the panel tucks them into a collapsed **"Monitored"** section; armed ones read as
  due-now everywhere. This is the engine behind the Battery Notes glue integration.
- **One-off (do-once) tasks.** A recurrence type for tasks that happen once rather
  than on a schedule — renew a passport, register a car, replace a single item. Pick
  **One-off** on the task form and choose a **due date** (defaults to today); it shows
  on the to-do list, calendar and overdue sensors like any task until you complete it,
  then goes dormant and moves to a collapsed **Completed** section in the panel (its
  completion history is kept). Undoing the completion brings it back to its due date.
  Available to automations via `home_keeper.add_task` / `update_task`
  (`recurrence_type: one-off` with a `due`). A new **One-off retention (days)** option
  (Settings tab, options flow, and `home_keeper.set_options`) can auto-delete a
  completed one-off this many days after it's done; the default `0` keeps them forever.
- **Sync `problem` binary sensors as tasks (opt-in).** A new option automatically
  mirrors every `binary_sensor` with the `problem` device class as a Home Keeper task.
  The task is **armed** (shows as due-now on the to-do list, calendar and device page)
  while the sensor reports a problem and **clears itself automatically** once the
  originating integration resolves it. These synced tasks can't be completed inside
  Home Keeper — the underlying problem has to be fixed in real life — so the *Done*
  action is shown disabled on every surface and tapping it explains why. Each task
  inherits the sensor's **device and area**; narrow the scope with **entity / area /
  label exclusions**. Off by default.
- **Dashboard task card.** A resizable Lovelace card (`custom:home-keeper-card`) shows
  your tasks as a list with a one-tap **Done** button on each row, and opens an inline
  editor for adding, editing, and deleting tasks without leaving the dashboard. It is
  auto-registered as a resource (no manual setup) and appears in the "Add card" picker.
  A GUI config editor exposes filtering (by status, area, device, recurrence type,
  due-within horizon, and **labels**), sorting, status/area/device grouping, a
  max-items cap, and display toggles. Built entirely from Home Assistant's own
  components and theme variables, and it stays in sync with completions made from any
  other surface.
- **Task labels & per-subject cards.** Tasks now carry a `labels` field — editable in
  the panel/card task form and via `home_keeper.add_task` / `update_task`, and echoed
  on every task event. Point a card at one or more labels (e.g. `dog`, `car`, a kid's
  name) to get a focused list: a card per subject. The filter matches a task by its own
  labels **or** by the labels on its attached device or area.
- **Per-completion metadata (note, cost, photo, who).** A completion can now carry
  optional context: a free-form note, a cost, a photo (uploaded to Home Assistant's
  image store), and who did it (a `person` entity). Capture is a **per-task setting** —
  `none` (the default one-tap *Done*), `optional` (a details dialog, plus a *Skip*
  shortcut), or `required` (the dialog with mandatory field(s)). The panel shows each
  completion's note/cost/photo/who in the task history and lets you **edit** a past
  entry without changing the schedule. New `home_keeper.complete_task` fields and a new
  `home_keeper.update_completion` service expose this to automations; the latest
  completion's metadata is mirrored on the task's *next due* sensor attributes, and a
  `home_keeper_task_completion_updated` event fires when a past completion is edited.
- **Comprehensive lifecycle events + automation-editor device triggers.** Home Keeper
  now fires a Home Assistant bus event for every meaningful change, so you can automate
  on the full lifecycle instead of just completions and low-stock. New events: tasks
  **created / updated / deleted / uncompleted / triggered** and the time-based
  **overdue** and **due-soon** transitions; spare parts **out of stock** and
  **restocked** (alongside the existing low-stock); and appliances **created / updated
  / deleted**. The time and stock transitions are *edge-triggered* (one event per
  crossing) and silently baselined on restart, so a reboot never replays an "overdue"
  storm. Each event also shows up as a **device trigger** in the visual automation
  editor. See [docs/EVENTS.md](docs/EVENTS.md) for the full catalog and example
  automations.
- **A Settings tab in the panel.** Home Keeper's integration options are now editable
  right in the sidebar panel — a **Settings** tab alongside Tasks and Appliances — so
  you don't have to dig through *Settings → Devices & services → Configure*. It mirrors
  the options flow and **saves as you change it**. The options flow still works, and a
  new **`home_keeper.set_options`** service exposes the same settings to automations.
- **Flexible appliance metadata — custom fields.** An appliance's descriptive details
  are now a free-form list of **custom fields** instead of a fixed set of inputs. Each
  field has a label and a type — **text**, **link**, or **date** — and you add as many
  as you like, with one-click seeds for the common ones (serial number, warranty
  expiry, purchase/install dates, provider, vendor, notes). A date field is
  display-only unless you tick **Track as a sensor**, which surfaces it as a `date`
  sensor on the device for automations (e.g. *"warranty expiring in 30 days → notify"*).
  Manufacturer, model, manual link, cost, icon and area remain dedicated fields, and the
  insurance inventory export lists each appliance's custom fields in a new **Details**
  column. *Note: this changes how appliance metadata is stored — an existing
  appliance's old descriptive fields are not migrated; re-enter them as custom fields.*
- **Backdating when creating tasks and parts.** The New Task form has an optional
  **Last completed** field that seeds an initial completion so a floating task's
  next-due is measured from when the activity actually last happened; integrations can
  pass the same via `home_keeper.add_task`'s `last_completed`. The parts editor gains a
  matching **Last replaced** date for wear items so the maintenance task it creates
  starts its clock from the real replacement date. The appliance parts list was also
  redesigned into per-part cards (type icon/badge, cadence, last-replaced, spare-stock).
- **Platinum integration quality scale.** Home Keeper now declares the
  [Platinum quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/),
  with a per-rule ledger in `custom_components/home_keeper/quality_scale.yaml`. The
  codebase is fully type-checked (`mypy`, with `py.typed`) in CI.

### Changed

- **A wear-item replacement task with no recorded last-replaced date is now due now,
  not "assumed fresh".** When Home Keeper derives a replacement task from an appliance
  wear item that has no "Last replaced" date, it now reads as **due immediately**
  (matching brand-new floating tasks) instead of scheduling the first reminder a full
  interval out. Backdate the part's last-replaced date (or mark the task done) to start
  its clock from a known point. Wear items with a recorded replacement date are
  unaffected.
- **A spare part dropping straight to zero now fires `home_keeper_part_out_of_stock`,
  not `home_keeper_part_low_stock`.** Out-of-stock is the more specific event and takes
  precedence. If an automation listened for `home_keeper_part_low_stock` to catch a
  part reaching zero, switch it to (or also listen for) `home_keeper_part_out_of_stock`.
  A part crossing into low *without* hitting zero still fires `home_keeper_part_low_stock`.
- **User-facing error messages are now localizable.** Errors raised by Home Keeper
  services and entities use Home Assistant translation keys (`strings.json` →
  `exceptions`) so they can be translated (English-first for now).
- **Home Keeper now registers as a service-type integration** (`integration_type`), so
  Home Assistant groups it accordingly in the UI.

## [0.3.0b12] - 2026-06-21

### Added

- **Per-completion metadata (note, cost, photo, who).** A completion can now carry
  optional context: a free-form note, a cost, a photo (uploaded to Home Assistant's
  image store), and who did it (a `person` entity). Capture is a **per-task setting**
  chosen on the task form — `none` (the default one-tap *Done*), `optional` (a details
  dialog with everything optional, plus a *Skip* shortcut), or `required` (the dialog
  with mandatory field(s)). The panel shows each completion's note/cost/photo/who in
  the task history and lets you **edit** a past entry without changing the schedule;
  the dashboard card sends a *required* task to the panel to capture its details. The
  set of required fields is stored per task (`completion_required_fields`) so it can
  later be made field-by-field configurable without a data migration. New
  `home_keeper.complete_task` fields and a new `home_keeper.update_completion` service
  expose this to automations; the latest completion's metadata is mirrored on the
  task's *next due* sensor attributes, and a `home_keeper_task_completion_updated`
  event fires when a past completion is edited.
- **Platinum integration quality scale.** Home Keeper now declares the
  [Platinum quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/),
  with a per-rule ledger in `custom_components/home_keeper/quality_scale.yaml`. The
  codebase is fully type-checked (`mypy`, with `py.typed`) in CI.

### Changed

- **Error messages are now localizable.** Errors raised by Home Keeper services and
  entities use Home Assistant translation keys (`strings.json` → `exceptions`) so
  they can be translated (currently English-first across all locales, translated
  incrementally).
- Home Keeper now registers as a **service**-type integration (`integration_type`),
  so Home Assistant groups it accordingly in the UI.

### Fixed

- **Settings exclusions now take effect immediately.** Adding a problem-sensor
  entity, area, or label to a *skip* list in the panel's **Settings** tab is now
  reflected right away: the integration reload that re-runs the problem-sensor sync
  is awaited before the save returns, and the panel refreshes its task list so the
  excluded sensor's synced task disappears (or reappears when you clear the
  exclusion) without needing a manual refresh or page reload.

## [0.3.0b11] - 2026-06-20

### Added

- **Filter the dashboard card by label — one card per subject.** Tag tasks with
  Home Assistant labels (e.g. `dog`, `car`, a kid's name) and point a Home Keeper
  card at one or more of them to get a focused list: a card for the dog, one for
  home maintenance, one for the car, one per kid. The label filter matches a task
  by its own labels **or** by the labels on its attached device or area — so a
  Home Keeper virtual appliance you've labelled in *Settings → Devices* is picked
  up automatically, and a subject doesn't have to map onto an HA area or device.
  Configure it from the card editor (**Limit to labels**, plus an **Any/All** match
  mode and an optional **Show labels** toggle that renders each task's label chips).
  Tasks now carry a `labels` field, editable in the panel/card task form and via the
  `home_keeper.add_task` / `home_keeper.update_task` services; the value is also
  echoed on every task event.

## [0.3.0b10] - 2026-06-19

### Changed

- **A synced problem-sensor task now shows its *Done* button disabled instead of
  hiding it.** Previously the action just vanished for these un-completable tasks,
  which read as "missing" rather than "blocked". The button is now visibly greyed,
  and tapping it (in the panel or the dashboard card) pops up a short explanation
  that the problem clears automatically once the originating integration resolves it
  — so it's clear *why* you can't mark it done here.

## [0.3.0b9] - 2026-06-19

### Added

- **A Settings tab in the panel.** Home Keeper's integration options are now editable
  right in the sidebar panel — a **Settings** tab alongside Tasks and Appliances — so
  you don't have to dig through *Settings → Devices & services → Configure*. It's a
  plain form mirroring the options flow (the **problem-sensor sync** toggle plus
  entity / area / label exclusions) that **saves as you change it**. The options flow
  still works, and a new **`home_keeper.set_options`** service exposes the same
  settings to automations.

## [0.3.0b7] - 2026-06-19

### Added

- **Sync `problem` binary sensors as tasks (opt-in).** A new option —
  *Settings → Devices & services → Home Keeper → Configure* — automatically mirrors
  every `binary_sensor` with the `problem` device class as a Home Keeper task. The
  task is **armed** (shows as due-now on the to-do list, calendar and device page)
  while the sensor reports a problem and **clears itself automatically** once the
  originating integration resolves it (the sensor returns to OK). These synced tasks
  **can't be completed inside Home Keeper** — the underlying problem has to be fixed
  in real life — so the *Done* action is hidden on every surface (panel, dashboard
  card, to-do list, device button) and the completion service/websocket reject them
  with an explanation. Each task inherits the sensor's **device and area**, so it
  appears on the device's page. Narrow the scope with **entity / area / label
  exclusions** in the same options screen. Syncing is **off by default**.

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
