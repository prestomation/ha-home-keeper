# Events & automations

Home Keeper fires a Home Assistant bus event for every state change. Use these
events to build automations. The events are:

| Object | Events |
| --- | --- |
| Task | created, updated, completed, uncompleted, completion edited, deleted, armed, snoozed, due today set, skipped, overdue, due soon |
| Part | low stock, out of stock, restocked |
| Appliance | created, updated, deleted, archived, restored |
| Companion | connected, suggested |

There are 2 ways to trigger on an event. Select a device trigger in the visual
automation editor on a Home Keeper appliance, such as "Task became overdue" or
"Spare part out of stock". Or use a plain `platform: event` trigger.

For a task attached to a device that another integration owns, automate on the
task's own entities or on the event. Home Assistant offers device triggers only
for the one integration a device belongs to.

An automation can add a part to the shopping list when the part goes out of stock.
This is useful for a part without
[Auto-create buy task](../appliances/appliances.md#auto-create-a-buy-task-when-a-part-runs-low):

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

The built-in [shopping-list sync](../appliances/appliances.md#send-buy-reminders-to-your-shopping-list) does
this for a part already on auto-buy, and removes the line again when the part is
restocked.

Events are edge-triggered. Home Keeper fires 1 event per transition and does not
repeat it each cycle. Events are baselined on restart, so no overdue events are
fired after a reboot. The full catalog with every event and payload is in
[docs/EVENTS.md](../../EVENTS.md).

## Task history in the logbook

Home Keeper writes a logbook row for each of these task events:

| Event | Row |
| --- | --- |
| Completed | was completed by Ann |
| Completed by a sensor | was completed by its sensor |
| Completion removed | had a completion removed |
| Skipped | was skipped |
| Snoozed | was snoozed until 2026-10-20 |
| Due soon | is due in 48 hours |
| Overdue | became overdue |
| Armed | became due |
| Due today set | was set to due today |
| Occurrence moved | has its occurrence on 2026-11-01 moved to 2026-11-03 |

Each row starts with the task name. The rows show in these places:

- **Activity** in the sidebar, filtered to the Home Keeper to-do list
- the logbook of the Home Keeper to-do list
- the Activity card on the device page of the task, if the task has a device

The logbook text is in English. Created, updated and deleted tasks get no row.

![The Activity page filtered to the Home Keeper to-do list, with a row for each task event](../../images/logbook-after-panel.png)

![The Activity card on the device page of a water heater, with the completion of its task](../../images/logbook-after-device.png)

### Show the history on a dashboard

A card that reads the logbook can show the rows. Use the `logbook` source of
[Chronicle Card](https://github.com/KadenThomp36/chronicle-card) with the to-do list:

```yaml
type: custom:chronicle-card
title: Task history
days_back: 30
sources:
  - type: logbook
    entities:
      - todo.home_keeper_tasks
```

The logbook keeps the rows for as long as the recorder keeps its data. The default is
10 days. To keep the rows longer, set `purge_keep_days`:

```yaml
recorder:
  purge_keep_days: 90
```
