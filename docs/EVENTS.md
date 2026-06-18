# Home Keeper events & automation triggers

Home Keeper fires a Home Assistant **bus event** for every meaningful thing that
happens — a task is created, edited, completed, deleted, becomes overdue or due-soon; a
spare part runs low, runs out, or is restocked; an appliance is added, changed, or
removed. This is the surface automations and other integrations build on.

You can react to these events two ways:

1. **Visual automation editor (device triggers).** On a task's device page or an
   appliance, *Add automation → When* lists Home Keeper triggers like **“Task became
   overdue”** or **“Spare part out of stock”** — no need to know the event name. These
   are scoped to that device.
2. **Event trigger (any automation).** For global automations (“*any* part low → add to
   one shopping list”), use a plain `platform: event` trigger on the event name below.

> Integrators pushing tasks into Home Keeper should also read
> [INTEGRATING.md](INTEGRATING.md); this document is the full event reference.

## Event catalog

All event names follow `home_keeper_<noun>_<verb>`. Task events share a common
**spine**; stock events share one shape; asset events share another (see
[Payloads](#payloads)).

### Task lifecycle

| Event | Fires when |
|---|---|
| `home_keeper_task_created` | a task is created (panel, service, contributing integration, or a wear-part task auto-generated from an appliance) |
| `home_keeper_task_updated` | a task actually changes; payload adds `changed_fields` |
| `home_keeper_task_deleted` | a task is removed (directly, or because its appliance/part was) |
| `home_keeper_task_completed` | a task is completed from **any** surface (to-do checkbox, device button, `complete_task`); payload adds `completed_at`, `origin` |
| `home_keeper_task_uncompleted` | a completion is undone (`next_due` is re-derived) |
| `home_keeper_task_triggered` | a condition-driven (triggered) task is armed (dormant → due-now) |

### Time-based transitions (edge-triggered)

| Event | Fires when |
|---|---|
| `home_keeper_task_overdue` | a task first crosses its due date (`now ≥ next_due`); payload adds `days_overdue` |
| `home_keeper_task_due_soon` | a task enters the 3-day window before `next_due`; payload adds `due_in_hours` |

These are detected by the coordinator’s periodic refresh (every 5 minutes) and are
**edge-triggered**: each fires **at most once per `next_due` value**. A task that stays
overdue does not re-fire; completing or rescheduling it re-arms the next announcement.

**Restart behaviour.** On startup Home Keeper *baselines* the current state silently —
a restart never replays an “overdue” storm for tasks that were already overdue. Only
transitions observed while Home Assistant is running fire. (The per-task overdue
`binary_sensor` always reflects the steady state regardless.)

### Stock transitions (edge-triggered)

| Event | Fires when |
|---|---|
| `home_keeper_part_low_stock` | spare stock crosses to **≤ `reorder_at`** |
| `home_keeper_part_out_of_stock` | spare stock reaches **0** |
| `home_keeper_part_restocked` | spare stock recovers **back above `reorder_at`** |

Edge-triggered the same way: one event per crossing, never on every step while already
low. A part must track **both** `stock` and `reorder_at` to fire anything. A single
change that drops an already-low part to zero fires **`out_of_stock`** (the more
specific event), not `low_stock`.

### Asset (appliance) lifecycle

| Event | Fires when |
|---|---|
| `home_keeper_asset_created` | an appliance is created |
| `home_keeper_asset_updated` | an appliance changes; payload adds `changed_fields` |
| `home_keeper_asset_deleted` | an appliance is removed |

## Payloads

### Task event spine

Every task event carries this core (per-event extras noted above are merged in):

| Field | Type | Notes |
|---|---|---|
| `task_id` | `str` | |
| `name` | `str` | |
| `device_id` | `str \| None` | the task’s registry device id, or `None` when it’s a standalone task (its entities then live on a self-owned device) |
| `area_id` | `str \| None` | |
| `recurrence_type` | `str` | `floating` / `fixed` / `triggered` |
| `next_due` | `str \| None` | ISO; `None` for a dormant triggered task |
| `enabled` | `bool` | |
| `source` | `dict \| None` | opaque provenance, echoed verbatim ([INTEGRATING.md](INTEGRATING.md)) |
| `managed_by` | `dict \| None` | well-known ownership block, or `None` |

### Stock event payload

`asset_id`, `asset_name`, `device_id`, `part_id`, `part_name`, `part_number`, `vendor`,
`stock`, `reorder_at` — enough to drive a reorder/notify without re-querying. The three
stock events are interchangeable in one template.

### Asset event payload

`asset_id`, `asset_name`, `device_id` (+ `changed_fields` for an update).

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

In the automation editor, choose the appliance’s device and the **“Spare part low on
stock”** trigger. The equivalent YAML:

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

Device triggers filter to the chosen device automatically: an appliance/existing-device
trigger matches the event’s `device_id`; a standalone task’s self-owned device matches
its `task_id` (those task events carry `device_id: null`).

## Notes for integrators

- The `home_keeper_task_completed` payload now carries the full task spine in addition
  to its long-standing `completed_at`/`origin` fields. If you only read `task_id`,
  `source`, `origin`, and `completed_at`, nothing changes for you.
- Home Keeper never inspects `source`; use it (and the `origin` echo on completions) to
  recognise and de-dupe your own tasks. See [INTEGRATING.md](INTEGRATING.md).
