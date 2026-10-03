---
title: To-do, calendar and list sync
summary: Shows tasks as a to-do list and a calendar, and syncs them to external to-do lists.
implements:
  - custom_components/home_keeper/todo.py
  - custom_components/home_keeper/todo_items.py
  - custom_components/home_keeper/todo_list.py
  - custom_components/home_keeper/todo_list_sync.py
  - custom_components/home_keeper/todo_sync_driver.py
  - custom_components/home_keeper/calendar.py
  - custom_components/home_keeper/shopping.py
  - custom_components/home_keeper/shopping_sync.py
  - custom_components/home_keeper/frontend/src/shopping-preview.ts
related: [profiles-notifications, appliances, coordinator-entities, store, recurrence]
source_hash: 2900cf120415
---

# To-do, calendar and list sync

Home Keeper shows its tasks as 1 native to-do list and 1 calendar. 2 syncs write to lists
that other integrations own: a profile syncs its tasks onto 1 external list, and the buy
reminders go onto 1 shopping list. Both syncs read changes back. Each is a pure planner
and a Home Assistant driver.

## Goals

- **G1. Native surfaces.** Every live task is a to-do item and a calendar event. A tick on
  the item completes the task through the recurrence engine.
- **G2. Profile sync.** A profile puts the tasks it selects on 1 external list. A tick, a
  vanish or a date change on that list comes back into Home Keeper.
- **G3. Hold, never duplicate.** An add that the list cannot show yet is held, not sent
  again. A duplicate item is permanent, so a late item is the better failure.
- **G4. Shopping list mirror.** Each open buy reminder is 1 line on the shopping list. A
  tick on the line means "bought" and restocks the part.
- **G5. Never break the caller.** A broken list costs a log line. A failed call is retried
  on the next pass and never compensated.

## Non-goals

- Import of foreign items. A bare summary cannot carry a recurrence, a device or a history.
- Time of day on a synced item. A to-do list holds a date, so the sync writes a date.
- Task selection (`profiles.matches_filter`) and buy reminders (`reconcile.reconcile_buy_tasks`).

## Design

### Own to-do entity

`todo.HomeKeeperTodoListEntity` lists 1 item per enabled task, with `uid` = task id. A
`one-off`, `triggered` or `sensor` task with no `next_due` is dormant and is not listed.
A `use` task has no date and stays listed. The due date is the local date of `next_due`.
The entity declares only `UPDATE_TODO_ITEM`. A tick calls `store.complete_task`, then
`coordinator.async_settle_buy_tasks`. A tick on a completed one-off is ignored. A new
summary or description goes to the task `name` and `notes` through `store.update_task`.
A `TaskValidationError` becomes a translated `HomeAssistantError`.

### Calendar entity

`calendar.HomeKeeperCalendarEntity` makes 1-hour events with `uid` = `{task_id}_{start}`.
`triggered` and `sensor` tasks have no schedule and never show. A `fixed` task expands with
`recurrence.expand_fixed_occurrences`, minus the occurrences outside its `active_season`.
`calendar._follow_next_due` removes the grid occurrences before `next_due` and adds a
`next_due` that a snooze moved off the grid. Every other task is 1 event at `next_due`.

### Pure planners and HA drivers

`todo_list.py` and `shopping.py` plan, with the shared item rules of `todo_items.py`.
`todo_list_sync.py` and `shopping_sync.py` read the lists and apply the plan. A plan holds
ops plus the bookkeeping after every op succeeds; `_apply` restores the entry of a failed op.
The base class `todo_sync_driver.TodoSyncDriver` holds the re-entrancy guard and the
4-pass budget (`async_sync`), `_read_lists`, `_gone_lists`, `_call`, `_capabilities` and
`_warn_once`. A list that is unavailable or does not answer is left out of the snapshot.
The planner then keeps its entries, so an unreadable list never reads as an empty one.
No driver syncs onto Home Keeper's own entity (`shopping_sync.own_todo_entity_ids`).

### Item matching and the hold

`todo_items.resolve_tracked` finds the item of an entry by `uid` first, then by summary,
an open item before a ticked one. A `claimed` set spans the whole plan, so 2 entries never
share 1 item. A planner adopts an open item with the same summary (`todo_items.find_open`)
before it adds one. Due date and description are written and compared only when the list
supports them (`CAP_DUE_DATE`, `CAP_DESCRIPTION`), or each pass rewrites them.

The `add_item` service returns no uid, so a new entry has `uid: None` and `added_at`. The
CalDAV entity shows a new item late. A pass that cannot find the item carries the entry
forward verbatim, because the summary is its only handle. When `todo_items.add_unconfirmed`
is true, after `todo_items.UNCONFIRMED_GRACE` (20 minutes, above the 15-minute CalDAV
poll), the item is added again. The hold uses the wall clock, because 4 passes can run in
milliseconds. `todo_items.added_stamp` replaces a bad or future stamp, so a hold ends.
During a hold, a ticked item with the same summary is not a tick.

### Profile sync

A sync is a profile: its `sync` block is `{entity_id, two_way, vanish_as_completed}` from
`profiles.normalize_sync`. Both toggles default on; `entity_id: ""` is off.
`todo_list.desired_by_sync` gives each profile its wanted tasks (name, local due date,
notes, `last_completed`, `blocked`), minus the buy reminders that the mirror owns. The
store key `todo_list_items` maps `todo_list.sync_key` (profile id, task id) to
`{entity_id, uid, summary, due, last_completed, added_at}`, plus `user_named`. When
`todo_list.completed_since` finds a newer `last_completed`, Home Keeper completed the task,
so the item is ticked off. When the task is due again, a new item goes next to it.

- **Tick.** With `two_way` on, the driver calls `store.complete_task` with
  `ORIGIN_TODO_SYNC`. With `two_way` off, the entry freezes. A completion-blocked task, or
  a task that refuses the completion, gets a new open item.
- **Vanish.** With both toggles on and a captured `uid`, the task completes (Todoist drops
  completed items). Otherwise the item is added again.
- **Rename.** An item with a `uid` whose summary is neither the last written name nor the
  new name gets `user_named: True`, and the sync never renames it again.
- **Date move.** With `two_way` on, a date that is neither `due` in the entry nor the wanted
  date gives a `RescheduleOp`. The driver calls `store.snooze_task`, which sets any date,
  earlier or later, and changes only `next_due`. `todo_list.reschedule_until` keeps the
  local time of day. A completion in the same pass wins. If the snooze fails, the next pass
  writes the task date back on the item.

A deleted or switched-off profile removes its open items from the list.

### Shopping list mirror

The `shopping_list_entity` option names the list. `shopping.buy_tasks_by_part` keys each
reminder by `shopping.part_key`, because each low episode makes a new reminder. The
`shopping_line_style` option sets the title: the reminder name or the part name.
`shopping.line_for` puts the amount in the description, or in brackets after the title.
A tick completes the reminder with `ORIGIN_SHOPPING_LIST`. A deleted line stays deleted.
A note that a person wrote is kept (`user_described`). `coordinator.async_settle_buy_tasks`
runs the mirror before and after the reconcile. `shopping-preview.ts` is the panel copy of
`shopping.buy_tasks_by_part` and `shopping.line_for`, for the Settings preview.

### When a pass runs

The first pass waits for Home Assistant to start. After a task event or a settle, a pass
reads the lists only if `needs_pass` finds drift. A list state change and the 5-minute
sweep force a read; only the sweep sees a task fall due or a hold end.

## Trade-offs

- **A sync inside a profile** over **a sync record**: a sync never points at a missing filter.
- **A wall-clock grace** over **a pass count or a forced refresh**: a pass count runs out in
  milliseconds. A forced refresh costs a round trip on each pass and still races the
  background refresh.
- **Vanish means done, with a uid only** over **vanish means deleted**: Todoist needs it.
- **Retry** over **compensating writes**: a failed call keeps its entry, so no item is orphaned.

## One-way doors

- Profile `sync` keys `entity_id`, `two_way`, `vanish_as_completed`.
- Options `shopping_list_entity` and `shopping_line_style` (`with_verb`, `product_only`).
- Origins `home_keeper_todo_sync` and `home_keeper_shopping_list` in event payloads.
- Unique ids `home_keeper_tasks`, `home_keeper_calendar`; calendar event `uid` shape.
- Storage keys `todo_list_items` and `shopping_items` and their entry fields.
