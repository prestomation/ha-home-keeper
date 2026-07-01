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
| `home_keeper_task_completed` | a task is completed from **any** surface (to-do checkbox, device button, `complete_task`); payload adds `completed_at`, `origin`, and any per-completion metadata that was recorded (`note`, `cost`, `photo`, `who`) |
| `home_keeper_task_uncompleted` | a completion is undone (`next_due` is re-derived) |
| `home_keeper_task_completion_updated` | a recorded completion's metadata (`note`/`cost`/`photo`/`who`) is edited after the fact; payload adds the edited completion's `ts`. The schedule is untouched. |
| `home_keeper_task_triggered` | a condition-driven (triggered) **or** sensor-based task is armed (dormant → due-now) |
| `home_keeper_task_snoozed` | a task's due date is deferred without recording a completion (`snooze_task` service or an actionable-notification **Snooze**); payload adds `snoozed_until`. The schedule/recurrence is untouched — only `next_due` moves |
| `home_keeper_task_skipped` | a task is advanced to its next occurrence without recording a completion (`skip_task` service or an actionable-notification **Skip**) — floating jumps an interval, fixed advances one occurrence, one-off/triggered/sensor go dormant |

**Sensor-based tasks** reuse the triggered lifecycle: Home Keeper's watcher fires
`home_keeper_task_triggered` when a bound numeric sensor meets the task's condition (a
usage meter passing its target, or a threshold crossing), the task then crosses to
`home_keeper_task_overdue` like any due task, and a normal user `home_keeper_task_completed`
clears it (resetting a usage meter's baseline). No new event types are introduced.

**Synced `problem` binary sensors** (when *Sync problem sensors* is on) ride these same
events: a mirror task is `created` for each `device_class: problem` sensor, `triggered`
when the sensor reports a problem, and `completed` when it clears — the completion event
carries `origin: home_keeper_problem_sensor_sync` and `source:
{"problem_sensor": {"entity_id": …}}` so an automation can tell a self-clearing problem
from a user-completed chore. (These tasks can’t be completed by hand — see the README.)

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

A spare is consumed (and these events fire) whenever a task **linked to that part** is
completed — both an auto-generated wear-part replacement task and a task you **manually
linked** to a consumable (via `home_keeper.set_task_consumable`). This is how a
sensor-armed "replace the fridge filter" task draws down inventory and signals a reorder
when you mark it done.

### Asset (appliance) lifecycle

| Event | Fires when |
|---|---|
| `home_keeper_asset_created` | an appliance is created |
| `home_keeper_asset_updated` | an appliance changes; payload adds `changed_fields` |
| `home_keeper_asset_deleted` | an appliance is removed |

Attaching or removing an appliance **document** (a manual/warranty/receipt link, or an
uploaded file) is an appliance change, so it surfaces as `home_keeper_asset_updated`
with `changed_fields: ["documents"]` — there is no separate document event. Attaching
or removing a **part's** single file works the same way, with
`changed_fields: ["parts"]`.

### Companion discovery (edge-triggered, baselined on startup)

Home Keeper surfaces integrations that work with it (see the panel's **Settings →
Companions** section, and [INTEGRATING.md](INTEGRATING.md) §7). Like the time-based
transitions above, the current state is **baselined silently at startup** — companions
already connected/suggested when HA starts do **not** fire — and an event fires only
when a companion *changes* into that state while HA is running (a companion
self-registers, a glue is installed, or a curated upstream is installed). State is
re-detected on the coordinator's refresh cadence (~5 min), so installing an upstream
surfaces a suggestion within one cycle. These never fire from a read (opening the
panel or calling `list_companions` fires nothing).

| Event | Fires when |
|---|---|
| `home_keeper_companion_connected` | a companion newly becomes connected — it self-registered via `home_keeper.register_companion`, or a known glue is newly detected installed; payload adds `domain`, `name`, `status`, `config_entry_id` |
| `home_keeper_companion_suggested` | a curated upstream is newly detected installed while its glue isn't; payload adds `domain` (the glue), `name`, `status`, `upstream_domain` |

There is also a fire-and-forget **request** event Home Keeper emits (at its setup and
on reload) to ask companions to (re-)announce themselves:

| Event | Fires when |
|---|---|
| `home_keeper_register_companions` | Home Keeper has set up; companion integrations should (re-)call `home_keeper.register_companion`. Carries no data |

## Payloads

### Task event spine

Every task event carries this core (per-event extras noted above are merged in):

| Field | Type | Notes |
|---|---|---|
| `task_id` | `str` | |
| `name` | `str` | |
| `device_id` | `str \| None` | the task’s registry device id, or `None` when it’s a standalone task (its entities then live on a self-owned device) |
| `area_id` | `str \| None` | |
| `recurrence_type` | `str` | `floating` / `fixed` / `one-off` / `triggered` / `sensor` |
| `next_due` | `str \| None` | ISO; `None` for a dormant triggered/sensor task or a completed one-off |
| `enabled` | `bool` | |
| `labels` | `list[str]` | HA label-registry ids attached to the task (empty list when none); used by the dashboard card's label filter |
| `source` | `dict \| None` | opaque provenance, echoed verbatim ([INTEGRATING.md](INTEGRATING.md)) |
| `managed_by` | `dict \| None` | well-known ownership block, or `None` |
| `task_chips` | `list[dict]` | integration-provided metadata chips (empty list when none); each entry has `label`, optional `icon` (`mdi:` name), optional `url` (`http(s)://`) |

### Stock event payload

`asset_id`, `asset_name`, `device_id`, `part_id`, `part_name`, `part_number`, `vendor`,
`stock`, `reorder_at` — enough to drive a reorder/notify without re-querying. The three
stock events are interchangeable in one template.

### Asset event payload

`asset_id`, `asset_name`, `device_id` (+ `changed_fields` for an update).

### Companion event payload

`domain`, `name`, `status` (`connected` / `suggested`), `config_entry_id` (the
companion's config entry, for a connected companion — `None` otherwise), and
`upstream_domain` (the detected upstream, for a catalog-suggested glue).

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
