# Home Keeper — Ideas & Future Work

A running list of things we deliberately deferred from the first UX prototype, plus
ideas worth exploring. Nothing here is committed scope; it's a parking lot.

## Deferred from the prototype (known next steps)

- **Cross-integration contribution API** (the big one). A stable, documented
  interface so other integrations (e.g. Battery Notes) can push maintenance tasks
  into Home Keeper *without Home Keeper knowing anything about them*.
  - Proposed mechanism: a dispatcher signal `home_keeper_task_contribution` plus a
    `home_keeper.contribute_task` service. Contributors fire it with
    `{source, device_id, name, recurrence...}`; a listener in `__init__.py` creates
    (or updates) a task tagged with its `source` so it can be reconciled/removed
    when the contributor goes away.
  - Battery Notes example: when a battery goes low, it contributes a "replace
    battery" task attached to the same device. Home Keeper stores it like any other
    task; completing it could fire a signal back so the contributor can reset.
  - Open questions: lifecycle/ownership of contributed tasks, dedupe, whether
    contributed tasks are user-editable, and a versioned schema for the payload.
  - Hook points already left in code: `const.SIGNAL_TASK_CONTRIBUTION`, and a
    `# DEFERRED` marker at the service-registration block in `__init__.py`.

- **Advanced fixed-schedule rules.** Today fixed schedules are `FREQ` (DAILY/
  WEEKLY/MONTHLY) + `interval` + `anchor`. Add `BYDAY` (e.g. "first Monday"),
  multiple weekdays, `COUNT`/`UNTIL`, and custom durations. Consider adopting
  `dateutil.rrule` or `recurring-ical-events` if hand-rolled math gets unwieldy
  (would add a Python requirement — currently we ship none).

- **Per-task entities for standalone tasks.** The prototype only creates the
  per-task `button`/`sensor`/`binary_sensor` for tasks attached to a device (to
  keep device pages clean). Decide whether standalone tasks should also get these,
  or rely on the to-do + calendar surfaces only.

- **Internationalization.** Prototype ships English only. Pawsistant ships 16
  locales; mirror that (`strings.json` ↔ `translations/*.json` parity test, and a
  dependency-free i18n module in the panel frontend).

## UX exploration (the whole point of the prototype)

- Compare the three usage surfaces in real use: native **To-do** list, native
  **Calendar**, and **device-page** entities. Decide which to lead with, and
  whether a bespoke Lovelace "upcoming tasks" card is still worth building on top.
- Panel polish: grouping by area/room, filtering (overdue / due-soon / by device),
  bulk actions, drag-to-reorder, an "activity log" view of completion history.
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
- **Estimated effort / cost / parts.** Track filter model numbers, where to buy,
  cost history — turns "replace fridge filter" into a useful record.
- **Cost/usage-based recurrence.** Trigger maintenance off sensor data (e.g. run
  hours, cycles) instead of (or in addition to) calendar time.
- **Completion metadata.** Optional note/photo/cost on completion; surface history
  on the device page and in the panel.
- **Import/export & backup** of tasks (JSON), and migration tooling between
  versions.

## Quality & infra

- Diagnostics download (`diagnostics.py`) for support, like Pawsistant.
- Broaden e2e screenshots into a documented before/after gallery in the README.
- Coverage gate on the recurrence engine specifically (it's the correctness core).
