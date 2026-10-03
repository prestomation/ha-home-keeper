---
title: Events reference
summary: What each Home Keeper bus event means and how to automate on it, for automation authors and integrators.
---

# Home Keeper events & automation triggers

Home Keeper fires a Home Assistant **bus event** for every state change: a task is
created, edited, completed, deleted, or becomes overdue or due soon. It also fires on
spare-part stock changes (low stock, out of stock, restocked) and appliance changes
(added, changed, removed). Automations and other integrations use these events.

You can react to the events in 2 ways:

1. **Visual automation editor (device triggers).** On a Home Keeper **appliance**,
   *Add automation → When* lists Home Keeper triggers such as **"Task became overdue"**
   or **"Spare part out of stock"**. You do not need the event name. These triggers
   apply only to that device.

   Home Keeper offers device triggers only on devices that it owns (its appliances),
   not on a device of another integration that a task is attached to. In Home Assistant
   2026.8 and later, a device belongs to 1 integration only (see
   [device links](design/coordinator-entities.md#per-task-entities-and-device-links)).
   For those tasks, automate on the task's entities (`binary_sensor.<task>_overdue`,
   `sensor.<task>_next_due`) or use the event trigger below.
2. **Event trigger (any automation).** For global automations ("*any* part low → add to
   1 shopping list"), use a `platform: event` trigger on the event name.

The [API reference](https://prestomation.github.io/ha-home-keeper/developer/api#events)
lists each event with its payload and device trigger. Home Keeper generates that page
from the integration. This page tells what each event means and what a restart does.

> Integrators that push tasks into Home Keeper must also read
> [INTEGRATING.md](INTEGRATING.md).

## What the events mean

All event names use the pattern `home_keeper_<noun>_<verb>`. Task events share a common
**spine**. Stock events share 1 shape, and asset events share another.

### Task lifecycle

A snooze moves only `next_due`. The recurrence does not change. "Due today" is the
opposite: `next_due` moves to now, and the recurrence does not change.

A skip advances the schedule. The step depends on the kind of task:

* **floating** starts a new interval from now
* **fixed** moves to the next scheduled occurrence
* **one-off**, **triggered** and **sensor** tasks go dormant

A snooze, a due-today, and a skip all re-arm the overdue and due-soon events for the
new date.

Home Keeper records a skip in a `skips` list, next to the `completions` list. A skip
never sets `last_completed`, and nothing that uses the completion log counts it.
`home_keeper_task_skipped` includes the `ts` of the new entry. `update_skip`,
`move_skip`, and `delete_skip` use `ts` to find the entry, and the `_skip_updated` and
`_skip_removed` events include it.

A skip on a **usage** task resets its meter, as a completion does. The next interval
starts from the reading at the skip. The time backstop, `also_every`, starts from the
same point. The default `combinator` is `"any"`, so the meter or the backstop can re-arm
the task. If the backstop stays at its old point, it can re-arm the task soon after a
skip. When a user edits the `reading` on the completion or skip that anchors the meter,
Home Keeper re-anchors the meter, and the `_completion_updated` and `_skip_updated`
events can add a `meter_baseline`.

### Completion origins

Many paths complete a task through the ordinary `home_keeper_task_completed` event. The
`origin` tells you which path. No path adds a new event type.

| `origin` | Path |
|---|---|
| `home_keeper_tag_scan` | A scan of the NFC/RFID tag linked to the task. |
| `home_keeper_sensor_recover` | A `threshold` or `state` binding with `clear_on_recover` sees its condition go away. |
| `home_keeper_shopping_list` | A user ticks off a "Buy {part}" line on the synced shopping list. |
| `home_keeper_todo_sync` | A user ticks off an item on a to-do list that a Profile syncs to. |
| `home_keeper_problem_sensor_sync` | A synced `device_class: problem` sensor clears. |

To complete a task whose **Require tag scan** toggle blocks every UI surface, an
automation can pass `origin: home_keeper_tag_scan` to `complete_task`.

**Sensor tasks** use the triggered lifecycle. The watcher fires
`home_keeper_task_triggered` when a bound entity meets the condition of the task. A
usage meter that passes its target is one case. A `state` entity that enters its state is another.
The task then becomes `home_keeper_task_overdue` as any due task does. A user completion
clears it and resets the baseline of a usage meter. A usage meter with a **time
backstop** (`also_every` in its `sensor` block) arms on the first half that is due, also while the
entity is unavailable.

With `clear_on_recover`, the task completes itself. A task that a declarative companion
with `clear_on_recover` made cannot be completed by hand: `home_keeper.complete_task`
refuses it, and its device page has no Mark done button. If the task is linked to a
consumable, the auto-completion uses 1 spare. It can then fire `home_keeper_part_low_stock`
or `home_keeper_part_out_of_stock`. An `unavailable` or `unknown` entity is not a
recovery. It counts as no reading and fires no event. A device that goes off the network never
completes a task.

The baseline bookkeeping of the watcher (a new meter anchor, a re-anchor after a meter
reset) fires **no event**, because it is internal state. A baseline that a user moves
with the `set_task_meter` service fires `home_keeper_task_updated` with
`changed_fields: ["sensor"]`.

**Shopping list.** When *Settings → Shopping list* names a to-do list, each automatic
"Buy {part}" reminder goes on it. The completion has
`source: {"buy": {"asset_id": …, "part_id": …}}`. It restocks the part by its restock
quantity, which usually fires `home_keeper_part_restocked`. Home Keeper then deletes the
reminder with `home_keeper_task_deleted`.

**To-do sync.** When a Profile in *Settings → Profiles* names an external to-do list, its
tasks go on that list while they qualify. An item that disappears from a list whose
provider removes completed items also completes the task, while the *treat removed items
as completed* toggle is on. A completion in Home Keeper ticks off the synced item and
keeps it as the record. When a recurring task is due again, a new item goes next to it.

**Problem sensors.** When *Sync problem sensors* is on, Home Keeper creates a task for
each `device_class: problem` sensor. The task is `triggered` when the sensor reports a
problem and `completed` when it clears. The completion has
`source: {"problem_sensor": {"entity_id": …}}`. A user cannot complete these tasks by
hand.

The bookkeeping of each sync (which list item stands for which task) fires **no event**.

### Time-based transitions (edge-triggered)

`home_keeper_task_overdue` fires when a task first passes its due date
(`now ≥ next_due`). `home_keeper_task_due_soon` fires when it enters the 3-day window
before that date. The coordinator finds these on its refresh (every 5 minutes). They are
**edge-triggered**: each fires **at most once per `next_due` value**. A task that stays
overdue does not fire again. A completion or a new date re-arms the next event.

**Restart.** At startup Home Keeper records the current state with no events. A restart
never sends "overdue" events for tasks that were already overdue. Only changes that occur
while Home Assistant runs fire events. The per-task overdue `binary_sensor` always shows
the current state.

### Stock transitions (edge-triggered)

When spare stock falls to **≤ `reorder_at`**, `home_keeper_part_low_stock` fires. At
**0**, `home_keeper_part_out_of_stock` fires instead. When stock goes back above the
threshold, `home_keeper_part_restocked` fires.

Each crossing fires 1 event, not 1 event for each step while the part is low. A part must
track **both** `stock` and `reorder_at` to fire anything. If 1 change takes a low part to
0, only **`out_of_stock`** fires.

Stock goes down, and these events fire, when a user completes a task **linked to that
part**. This includes an automatic wear-part replacement task and a task linked by hand
with `home_keeper.set_task_consumable`. Each completion removes the **Used per
completion** amount of the part (1 spare if unset). With `0.33`, a bottle lasts 3 refills.

A deleted completion gives the stock back. The completion records the amount that it
really took: if it found 1 of the 2 spares it needed, it gives back 1. The return fires
`home_keeper_part_restocked` when it lifts the part above its reorder point.

With **Auto-create buy task** on, a part that crosses the reorder threshold gets a
one-off *"Buy {part}"* task (`home_keeper_task_created`). A restock removes the task
(`home_keeper_task_deleted`). A completion of the buy task restocks the part by its
`restock_quantity` and fires `home_keeper_part_restocked`. A deleted completion takes the
restock back and fires `home_keeper_part_low_stock` or `home_keeper_part_out_of_stock`
if the count crosses the threshold again.

### Asset (appliance) lifecycle

A change to an appliance **document** (a manual, warranty, or receipt link, or an
uploaded file) fires `home_keeper_asset_updated` with `changed_fields: ["documents"]`.
There is no separate document event. A change to the file of a **part** fires the same
event with `changed_fields: ["parts"]`.

A deleted entry in the **archived task history** of an appliance
(`home_keeper.delete_archived_completion`) fires `home_keeper_asset_updated` with
`changed_fields: ["archived_history"]`.

Archive (`home_keeper.archive_asset`) and restore (`home_keeper.restore_asset`) fire
their own events, not `home_keeper_asset_updated`. An archive only hides the appliance
from the default list in the panel. Its device, entities, and tasks continue to operate,
and `home_keeper_asset_deleted` does not fire.

### Companion discovery (edge-triggered)

Home Keeper shows integrations that work with it in **Settings → Companions** (see
[INTEGRATING.md §9](INTEGRATING.md#9-discovery-and-declarative-companions)).
As with time-based transitions, Home Keeper records the state at startup with no events.
An event fires only when a companion *changes* state at run time, as when it
registers itself or when a user installs a glue. Home Keeper checks the
state on each coordinator refresh (about 5 minutes). A read (the panel, or
`list_companions`) fires nothing.

A suggestion names the *glue* in `domain` and the upstream that Home Keeper found in
`upstream_domain`.

At setup and on reload, Home Keeper fires `home_keeper_register_companions` with empty
data. It asks companions to announce themselves again. A companion answers with a call
to `home_keeper.register_companion`.

### Declarative companion CRUD

A **declarative companion** is a spec that Home Keeper owns. It names a target integration
and entity filters, with a Jinja template for the task name and notes (see
[INTEGRATING.md §9](INTEGRATING.md#9-discovery-and-declarative-companions)). It makes 1 managed
sensor task for each matching entity. Changes to a spec fire their own events. The
sensor tasks fire the ordinary task events, so an automation on
`home_keeper_task_completed` works with no change. To filter to declarative tasks, read
`managed_by.integration == "home_keeper"` and `source.declarative_companion.spec_id`.

| Event | Fires when |
|---|---|
| `home_keeper_declarative_companion_added` | a spec was created (via the panel, `home_keeper.add_declarative_companion`, or the matching WS command); payload adds `spec_id`, `name`, `enabled`, `preset_id` |
| `home_keeper_declarative_companion_updated` | any field of a stored spec was changed; same payload |
| `home_keeper_declarative_companion_removed` | a spec was deleted (also fires `home_keeper_task_deleted` once per materialized task the spec had); same payload |

## Payloads

The [API reference](https://prestomation.github.io/ha-home-keeper/developer/api#payloads)
lists every field of every payload. Home Keeper generates it from the builders that make
the payloads.

`stock` and `reorder_at` can be fractional: a bottle topped up a third at a time reports
`0.67`. `unit` is the unit of the part (`"ml"`, `"bottles"`), or `""` for whole spares.
A notification can use `{{ trigger.event.data.stock }} {{ trigger.event.data.unit }}`
for both. Like the asset events, a stock event holds the `source` and `managed_by` of the
appliance. An integration that manages an appliance uses them to find its stock events.

## Example automations

### Notify when anything becomes overdue (event trigger)

```yaml
automation:
  - alias: "Maintenance overdue → notify"
    trigger:
      - platform: event
        event_type: home_keeper_task_overdue
    action:
      - service: notify.mobile_app_phone
        data:
          message: >-
            {{ trigger.event.data.name }} is overdue
            ({{ trigger.event.data.days_overdue }} day(s)).
```

### Add a spare to the shopping list when it runs out (event trigger)

```yaml
automation:
  - alias: "Spare out of stock → shopping list"
    trigger:
      - platform: event
        event_type: home_keeper_part_out_of_stock
    action:
      - service: todo.add_item
        target:
          entity_id: todo.shopping_list
        data:
          item: >-
            {{ trigger.event.data.part_name }}
            {{ trigger.event.data.part_number }} ({{ trigger.event.data.vendor }})
```

### React only to a specific appliance (device trigger)

In the automation editor, select the device of the appliance and the **"Spare part low
on stock"** trigger. The same automation in YAML:

```yaml
automation:
  - alias: "Furnace filter low"
    trigger:
      - platform: device
        domain: home_keeper
        device_id: <furnace device id>
        type: part_low_stock
    action: ...
```

A device trigger filters to the selected device. An appliance or existing-device trigger
matches the `device_id` of the event. The self-owned device of a standalone task matches
its `task_id`, because those task events have `device_id: null`.

## Notes for integrators

- The `home_keeper_task_completed` payload has the full task spine and the
  `completed_at` and `origin` fields.
- Home Keeper never reads `source`. Use it, and the `origin` on completions, to find your
  own tasks and remove duplicates. See [INTEGRATING.md](INTEGRATING.md).
- **An import fires 1 event per record, not 1 per completion.** A document that
  `home_keeper.import_data` reads holds old history, from before the import. A
  backfilled completion fires no `home_keeper_task_completed`. The record
  arrives as 1 `home_keeper_task_created` or `home_keeper_task_updated`. An update that
  only adds history still fires, with `completions` in its `changed_fields`. To mirror
  completions, read the task history on that event. Do not count completion events.
