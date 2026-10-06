---
title: Ideas and open work
summary: The single backlog of Home Keeper work that is not built, for maintainers and agents.
---

# Ideas and open work

This file is the only list of work that is not built: bugs, gaps, refactors and ideas.
Nothing here is committed scope. When an item ships, remove it. The design docs in
`docs/design/` describe what is built.

## Architecture

- **Split the services out of `__init__.py`.** The file holds about 2,100 lines. Move the
  service handlers, schemas and the registration table to a new services module, and keep only
  the entry lifecycle in `__init__.py` (see `docs/design/architecture.md`).
- **Contract hygiene.** `transitions.py` calls the private `recurrence._parse`; give it a
  public parse helper. The `problem_tasks` reconciler changes store dicts in place, and
  the coordinator hands out live dicts (see `docs/design/coordinator-entities.md`).
- **One content-type allowlist.** `assets.py` and `documents.py` each keep a list of the
  allowed upload types. Keep one list in `const.py` (see `docs/design/documents-photos.md`).
- **Cross-integration contribution service.** A `home_keeper.contribute_task` service that
  upserts and reconciles tasks for a contributor, so the contributor does not own the
  CRUD. `const.SIGNAL_TASK_CONTRIBUTION` is reserved for it. Open questions: ownership,
  dedupe, user edits, a versioned payload schema (see `docs/design/events-api.md`).
- **Owner path for a locked task field.** An owner cannot change a locked field of its
  own task. A service like `update_managed_asset`, for tasks, would fix it.

## Recurrence

- **Season boundary on February 29.** `_next_season_start` clamps Feb 29 to Feb 28 in a
  non-leap year, but `in_season` does not clamp. A floating task can then land outside
  its own season. `test_r4b` pins the defect as a strict xfail. Decide which side is
  wrong, and check other `MM-DD` boundaries (see `docs/design/recurrence.md`).
- **Fixed season that never meets its grid.** When the grid does not meet the season in
  `MAX_EXPAND_ITERATIONS`, `_clamp_season` returns a date outside the season.
- **`set_due_today` on an overdue task.** The service does not refuse an overdue task.
  A call moves the due date later and clears the overdue state. The panel and the card
  hide the action, so only a service call can do this.
- **Fixed schedules that end, and custom durations.** `normalize_rule` refuses `COUNT`
  and `UNTIL`, so a fixed schedule cannot end. Calendar events are always 1 hour long.

## Completions

- **Orphan completion photos.** `recurrence.update_completion` returns `replaced_photo`,
  and `store.update_completion` ignores it. A replaced photo, and the photo of a deleted
  completion or task, stays in the image upload store (see `docs/design/completions.md`).
- **Required completion fields on the service.** `complete_task` does not enforce
  `completion_required_fields`. Only the panel does.
- **Fill `who` automatically.** Set `who` from the user who presses Done, when that user
  has a person entity.
- **Repair-vs-replace analytics.** Show the lifetime cost of an appliance from its
  completion costs, to help decide between repair and replacement.

## Coordinator and entities

- **Entity attribute names are not checked.** `tests/unit/test_api_surface.py` does not
  compare `api_surface.ENTITY_PLATFORMS` attribute names with each platform's
  `extra_state_attributes` (see `docs/design/coordinator-entities.md`).
- **One rule for entity ownership.** `store._task_owns_entities` repeats
  `coordinator.task_has_entities` to avoid an import cycle. Move the rule into
  `task_entities.py`.
- **Per-task entities for tasks without a device.** Only a task on a device gets its
  button, sensor and binary sensor. Decide if a task without a device gets them too.
- **Spares number entity is open to every user.** A non-admin can change a part's spare
  count from the dashboard. Gate it (the dashboard control then fails for non-admins), or
  state in `docs/SECURITY.md` that the write is open by design.

## Appliances

- **Device registry listener.** Add an `async_track_device_registry_updated_event`
  listener, so an appliance on a foreign device is reconciled when that device is
  removed or made again. Reconciliation runs only at setup and on an appliance change
  (see `docs/design/appliances.md`).
- **Leftover merged devices.** `devices.async_detach_legacy_merged_devices` skips a
  foreign device where Home Keeper is the last config entry. A repair must move the
  entities off before it removes the entry.
- **Durable key for contributed tasks.** A glue keys its tasks on
  `source.<ns>.device_id` only. When the registry gives the device a new id, the glue can
  make duplicate tasks. The Bambu Lab and Battery Notes glues have this problem in their
  repositories. `docs/INTEGRATING.md` does not say it.
- **Dead locked field.** A `locked_fields` entry whose value no longer resolves, such as
  a removed `device_id`, cannot be unlocked by the user.
- **Appliance photo and labels.** Add a photo to an appliance, and decide if Home
  Assistant labels replace a "category" field.
- **Edit native fields of a foreign device.** Home Keeper cannot change the manufacturer
  or model of a device it does not own.
- **Unicode name of a part file.** A part file has no display-name field, so it shows the
  ASCII file name. The fix needs a new stored field.
- **Shared battery stock per device.** Give each device a `Battery` wear part whose
  replacements use the stock of the shared battery type on the Batteries appliance. It
  needs a part that refers to a part on another appliance.
- **Appliance report formats.** The report is CSV only. Add JSON or PDF, photos, and
  depreciation. A related idea is a home-sale binder: the full history and documents as
  one package.
- **Warranty view.** A view that answers "is it under warranty?" with the provider, the
  terms, the manual link and the days left.

## Sensor tasks

- **Unit change on a usage meter.** A usage task keeps its target and baseline in the
  unit at bind time, and reads a new unit as the old one. The fix stores the unit on the
  sensor binding at every bind path. That field is a one-way door
  (see `docs/design/sensor-tasks.md`).
- **Predicted due date.** Compute a due date for a usage task from its rate of use, so
  the task shows in the calendar and in "due soon" before it arms.
- **Count mode.** A `mode: "count"` that counts state changes, for "descale after 50
  cycles".
- **Repair issue for a missing entity.** Raise a Home Assistant repair when a bound
  entity is missing or unavailable for longer than a grace period.
- **Compound conditions.** AND/OR conditions across several sensors in one binding.
- **Countdown entities.** `usage_remaining` and `usage_percent` are attributes. Expose
  them as entities if users want progress bars on a dashboard.
- **Weather and presence triggers.** Arm a task when the forecast first goes below
  freezing. Hold indoor tasks while nobody is home.

## Presets and companions

- **Preset gaps.** Declarative presets cannot yet express: a runtime counter mode; a
  state-change count mode; a reset-button action on completion; unit-aware usage targets;
  device filters (models, manufacturers, `device_has_keys`); one task per device; key
  suffix matching without a `translation_key`; an "Add all" bundle per integration;
  device-first suggestions; "adopt as normal tasks". `per_entity_overrides` is reserved
  and not used (see `docs/design/companions-presets.md`).
- **Per-instance task names for MOS and UNAS.** QNAP volumes get one task name per
  volume. MOS `pool_usage` and UNAS `storage_usage` need the upstream keys checked first.
- **Declarative companion passes.** Each pass saves once per change, and the pass does
  not filter registry events.
- **Bambu Lab glue in the catalog.** `companions_catalog.py` lists only Battery Notes,
  so Settings → Companions never suggests the Bambu Lab glue. Add an entry and a case in
  `tests/unit/test_companions.py`.
- **Disabled glue reads as Connected.** A disabled glue config entry still counts as
  installed.
- **Glue candidates.** The best targets with no glue yet: waste collection (one glue for
  `waste_collection_schedule` and its peers, date-driven); robot vacuums (`roborock`,
  `ecovacs`, consumable reset buttons); one odometer glue for any distance sensor;
  printers (`brother`, `ipp`, toner and drum life); `nut` UPS batteries; `oralb`; air
  purifier filter life (`vesync`, Dyson); `vicare` burner hours. Each glue then needs a
  `companions_catalog.py` entry (see `docs/GLUE_INTEGRATIONS.md`).
- **Starter templates.** A catalog of common appliances with default intervals (water
  heater anode, HVAC filter, dryer vent), so a new user does not start from nothing.

## Notifications and profiles

- **Notification ideas.** A schedule per notification, quiet hours, a `separate` style,
  repeat and escalation, several snooze buttons, per-task overrides, routing by assignee,
  non-mobile targets for the digest, and a shipped blueprint
  (see `docs/design/profiles-notifications.md`).
- **Profiles as entities.** Expose profiles as entities, or add a `set_profile` service.
- **Profile filter on `list_tasks`.** An optional `profile` field that returns only the
  tasks the profile selects, through the shared label matching. Build it when an
  automation needs it.
- **Snooze to an earlier date.** The snooze dialog refuses a date before the due date,
  but the `snooze_task` `until` field accepts one, because the two-way to-do sync moves
  tasks earlier through it. Decide if the service needs a separate path.

## Sync

- **Slow inbound CalDAV changes.** A tick-off on a CalDAV server can take about
  20 minutes to reach Home Keeper: the 15-minute HA poll plus the 5-minute sweep. The
  sweep can call `homeassistant.update_entity` before it reads a list. That costs a
  request per list every 5 minutes, so it needs a decision (see `docs/design/sync.md`).
- **Failed sync writes are silent.** A failed write to a sync target logs at debug
  only. Use `_warn_once` when the failure repeats.
- **CalDAV due-date report.** A user reported a due-date change that did not reach
  Nextcloud. The sync writes the date only, so a time-only change writes nothing. Add a
  debug log for that case.

## Events and API

- **Missed crossings while Home Assistant is down.** An overdue or due-soon crossing
  during downtime is never announced. Persist the per-task flags, then replay or clear
  them at startup (see `docs/design/events-api.md`).
- **Integration trigger platform.** Add a `triggers.yaml` trigger platform for
  automations that are not tied to a device.
- **Test fake events.** `testing.FakeHomeKeeper` cannot fire the overdue and due-soon
  events.
- **Voice completion.** "I just changed the furnace filter" through Assist marks the
  task done, and "what is due this week?" reads the list. No intent platform exists.

## Transfer

- **Import planning on the event loop.** Parsing runs in the executor, but
  `plan_import` reads the live store on the loop. Moving it needs a store snapshot
  (see `docs/design/transfer.md`).
- **No rollback on import.** When device setup fails after the appliance writes, the
  tasks import without their appliance. Only a warning shows.
- **Completion photos do not travel.** A site-relative photo exports as text, the image
  does not, and the skipped count does not include it.
- **Sections not in the document.** Declarative companions, profiles, notifications,
  options and uploaded file contents.
- **Spare stock on an integration-owned appliance.** The export leaves out a managed
  appliance, so the user's counts (`stock`, `reorder_at` and the other user keys) are
  lost on a new install. Export the user keys by source namespace and part name, or give
  the document a counts section.
- **Portable source-owned tasks.** A task with a reserved `source` does not travel, so a
  wear item's renewal log, costs, notes and photos are lost on a move. It needs `source`
  in the export, a planned-id remap for `source.part.asset_id`, and its own validation in
  `_plan_task`. Design it once for all 4 reconciler namespaces.

## Store

- **Live dicts to the HA store.** `_save` gives live dicts to the Home Assistant `Store`.
  An executor write can race a change on the loop. Check how HA serializes, and copy the
  data if needed (see `docs/design/store.md`).
- **`StoreClosedError` is not caught.** A stale pass after a reload logs an unhandled
  exception.
- **`_mutate_asset` is not atomic.** It awaits the operation before the save. The full
  state save makes it safe today.
- **One save per change on bulk paths.** The one-off purge saves once. Part file cleanup
  after import, declarative passes and device repair still save once per change. Do not
  use a delayed save, because it brings back the overwrite on reload.
- **Upload during a reload.** A short window remains between the file move and the
  save.

## Frontend

- **TypeScript 7.** TypeScript 7 changed the shape of the `ts` module, and
  `@rollup/plugin-typescript` crashes in `rollup -c`. `.github/dependabot.yml` ignores
  the major bump. Blocked on: a `@rollup/plugin-typescript` release with TypeScript 7
  support. Check with `npm view @rollup/plugin-typescript versions`, then remove the
  ignore rule.
- **Full task load on each refresh.** The panel loads every task in full on each
  refresh. Add a summary mode to `get_tasks` and per-task updates in the panel
  (see `docs/design/frontend.md`).
- **Panel list actions.** Bulk actions, drag to reorder, and an activity log of
  completions.
- **Per-task icons and colors.** Let a task carry an icon and a color for scanning.
- **Follow the user's time zone setting.** The panel and the card always show and read
  times in Home Assistant's zone (`setTimeZone(hass.config.time_zone)` in `panel.ts` and
  `card.ts`, X04-7). A user away from home sees times that do not match the clock on the
  device. Home Assistant has a per-user profile setting for this (`hass.locale.time_zone`:
  local or server). Use it to show and read times. Keep "due today", overdue and the day
  counts on Home Assistant's day. The schedule, the to-do list and the calendar use that
  day. Check which option Home Assistant uses as the default.

## Product ideas

- **Assignees.** A person responsible for a task, and rotation between household
  members. Notification routing and gamification depend on it.
- **Gamification.** Streaks, points and per-person statistics for household chores.
- **Task dependencies.** A task that becomes due only after another task is done.
- **Turnover checklists.** A reusable checklist that resets between guests.
- **Expiry tracking.** Fire extinguisher service, chimney and septic inspection,
  registration: things with an expiry date that are not appliances.
- **Natural-language task creation** and **nameplate scanning** to add an appliance.
- **Adaptive intervals.** Learn the interval from the completion history.
- **Photos from an owning integration.** Give each photo an optional owner
  (`photos[].managed_by`). The owner adds and removes only its own photos. The user keeps
  the rest, adds more and picks the cover, as with the user keys of a managed part.

## Testing and CI

- **Visual regression.** Use `toHaveScreenshot` on 3 to 5 stable surfaces. It needs
  fixed dates in the e2e seed, disabled animations, and baselines made only in the CI
  container.
- **Playwright report on success.** `e2e.yml` uploads the report only on failure.
  Upload it on success too.
- **Coverage gate for the recurrence engine.** A separate coverage floor for
  `recurrence.py`.
- **Unverified review findings.** 21 PLAUSIBLE findings in `RAW_FINDINGS.md` on the
  branch `ccr-ca7e8883-msamwh` are not worked on. A verifier could not confirm or refute
  them.

## Docs

- **CalDAV notes in the user guide.** Say that a Nextcloud Personal calendar takes
  events only (use a task list), and that inbound changes can take about 15 minutes.
