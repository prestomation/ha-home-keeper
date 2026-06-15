# Changelog

All notable changes to Home Keeper are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses semantic
versioning (with PEP 440 pre-release suffixes — `bN`/`aN`/`rcN` — for betas).

## [Unreleased]

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
