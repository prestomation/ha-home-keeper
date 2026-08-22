# Home Keeper events & automation triggers

Home Keeper fires a Home Assistant **bus event** for every state change:
a task is created, edited, completed, deleted, or crosses into overdue or due-soon.
It also fires on spare-part stock transitions (low stock, out of stock, restocked)
and appliance changes (added, changed, removed). This is the surface automations and
other integrations build on.

You can react to these events two ways:

1. **Visual automation editor (device triggers).** On a Home Keeper **appliance**,
   *Add automation → When* lists Home Keeper triggers like **“Task became overdue”**
   or **“Spare part out of stock”**. No need to know the event name. These are scoped
   to that device.

   Device triggers are offered on devices Home Keeper owns, meaning its appliances.
   They are not offered on a device another integration owns that a task is merely
   attached to. Home Assistant builds that menu from the integrations a device belongs
   to, and since HA 2026.8 a device belongs to exactly one (see
   [DESIGN.md](DESIGN.md) → "Device attachment"). For those tasks, automate on the
   task's own entities (`binary_sensor.<task>_overdue`, `sensor.<task>_next_due`) or
   use the event trigger below. Both reach the same events.
2. **Event trigger (any automation).** For global automations (“*any* part low → add to
   one shopping list”), use a plain `platform: event` trigger on the event name below.

> Integrators pushing tasks into Home Keeper should also read
> [INTEGRATING.md](INTEGRATING.md). This document is the full event reference.

## Event catalog

All event names follow `home_keeper_<noun>_<verb>`. Task events share a common
**spine**; stock events share one shape; asset events share another (see
[Payloads](#payloads)).

### Task lifecycle

<!-- vale ai-tells.OverusedVocabulary = NO -->

| Event | Fires when |
|---|---|
| `home_keeper_task_created` | a task is created (panel, service, contributing integration, or a wear-part task auto-generated from an appliance) |
| `home_keeper_task_updated` | a task actually changes; payload adds `changed_fields` |
| `home_keeper_task_deleted` | a task is removed (directly, or because its appliance/part was) |
| `home_keeper_task_completed` | a task is completed from **any** surface (to-do checkbox, device button, `complete_task`); payload adds `completed_at`, `origin`, and any per-completion metadata that was recorded (`note`, `cost`, `photo`, `who`) |
| `home_keeper_task_uncompleted` | a completion is undone (`next_due` is re-derived). Payload adds the removed completion's `ts` and the `origin` marker the caller passed. Undoing a `ts` that isn't in the history changes nothing and fires nothing |
| `home_keeper_task_completion_updated` | a recorded completion's metadata (`note`/`cost`/`photo`/`who`) is edited after the fact; payload adds the edited completion's `ts`. The schedule is untouched. |
| `home_keeper_task_triggered` | a condition-driven (triggered) or sensor-based task is armed (dormant → due-now) |
| `home_keeper_task_snoozed` | a task's due date is deferred without recording a completion (`snooze_task` service or an actionable-notification **Snooze**). Payload adds `snoozed_until`. The schedule/recurrence is untouched, only `next_due` moves |
| `home_keeper_task_skipped` | a task is advanced to its next occurrence without recording a completion (`skip_task` service or an actionable-notification **Skip**). Floating jumps an interval, fixed advances one occurrence, one-off/triggered/sensor go dormant |

<!-- vale ai-tells.OverusedVocabulary = YES -->

**NFC/RFID tag scans** ride these same events: completing a task by scanning its
linked tag fires an ordinary `home_keeper_task_completed` carrying
`origin: home_keeper_tag_scan`. Match on that origin to tell a physical scan from a
press of Done. Passing that origin to `complete_task` is also the escape hatch for
automations that need to complete a task whose **Require tag scan** toggle blocks
every UI surface.

**Sensor-based tasks** reuse the triggered lifecycle: <!-- vale ai-tells.ColonUsage = NO -->Home Keeper's<!-- vale ai-tells.ColonUsage = YES --> watcher fires
`home_keeper_task_triggered` when a bound entity meets the task's condition (a
usage meter passing its target, a threshold crossing, or a `state` binding's entity
entering its state), the task then crosses to
`home_keeper_task_overdue` like any due task, and a normal user `home_keeper_task_completed`
clears it (resetting a usage meter's baseline). A usage meter carrying a **time backstop**
(`sensor.also_every`) arms on whichever half lands first (including while the bound
entity is unavailable) through the same `home_keeper_task_triggered`. No new event types
are introduced.

A `threshold` or `state` binding that sets **`clear_on_recover`** also clears itself when
its condition goes away, and that path fires an ordinary `home_keeper_task_completed`
carrying `origin: home_keeper_sensor_recover`. Match on that origin to tell a
self-clearing sensor task from someone pressing Done. If the task is linked to a
consumable, the auto-completion consumes one spare, potentially producing
`home_keeper_part_low_stock` or `home_keeper_part_out_of_stock` the same as any other
completion path. A bound entity going
`unavailable`/`unknown` counts as no reading rather than a recovery, and fires nothing,
so a device dropping off the network never completes a task.

The watcher's own baseline bookkeeping (anchoring a fresh meter, re-anchoring after a
meter reset) stays **silent**, because it is internal state, not a user action. A baseline moved
by hand through the `set_task_meter` service does fire `home_keeper_task_updated` with
`changed_fields: ["sensor"]`.

**Buy reminders ticked off on a mirrored shopping list** ride these same events too.
When *Settings → Shopping list* points at a to-do list, each auto-created **"Buy
{part}"** reminder is put on it. Ticking that line off there fires an ordinary
`home_keeper_task_completed` carrying `origin: home_keeper_shopping_list` and
`source: {"buy": {"asset_id": …, "part_id": …}}`. Match on that origin to tell "bought
at the shop" from a press of Done. Like any buy-reminder completion it restocks the part
by its restock quantity, so a `home_keeper_part_restocked` normally follows, and the
reminder is then retired with a `home_keeper_task_deleted`. The mirror's own bookkeeping
(which line on which list stands for which reminder) stays **silent**, the same
reasoning as the sensor watcher's baselines above.

**Synced `problem` binary sensors** (when *Sync problem sensors* is on) ride these same
events: a mirror task is `created` for each `device_class: problem` sensor, `triggered`
when the sensor reports a problem, and `completed` when it clears. The completion event
carries `origin: home_keeper_problem_sensor_sync` and `source:
{"problem_sensor": {"entity_id": …}}` so an automation can tell a self-clearing problem
from a user-completed chore. (These tasks can’t be completed by hand. See the README.)

### Time-based transitions (edge-triggered)

| Event | Fires when |
|---|---|
| `home_keeper_task_overdue` | a task first crosses its due date (`now ≥ next_due`); payload adds `days_overdue` |
| `home_keeper_task_due_soon` | a task enters the 3-day window before `next_due`; payload adds `due_in_hours` |

These are detected by the coordinator’s periodic refresh (every 5 minutes) and are
**edge-triggered**: each fires **at most once per `next_due` value**. A task that stays
overdue does not re-fire. Completing or rescheduling it re-arms the next announcement.

**Restart behaviour.** On startup Home Keeper *baselines* the current state silently.
A restart never replays an “overdue” storm for tasks that were already overdue. Only
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
completed. Both an auto-generated wear-part replacement task and a task you **manually
linked** to a consumable (via `home_keeper.set_task_consumable`) count. This is how a
sensor-armed "replace the fridge filter" task draws down inventory and signals a reorder
when you mark it done.

A part with **Auto-create buy task** enabled goes one step further: crossing the reorder
threshold auto-creates a one-off *"Buy {part}"* task (a `home_keeper_task_created` event)
and restocking removes it (`home_keeper_task_deleted`). No new event type is involved,
just the ordinary task lifecycle. Completing that buy task restocks the part by its
`restock_quantity`, which fires `home_keeper_part_restocked` like any other restock.

### Asset (appliance) lifecycle

| Event | Fires when |
|---|---|
| `home_keeper_asset_created` | an appliance is created |
| `home_keeper_asset_updated` | an appliance changes; payload adds `changed_fields` |
| `home_keeper_asset_deleted` | an appliance is removed |
| `home_keeper_asset_archived` | an appliance is archived (hidden without deleting its data) |
| `home_keeper_asset_restored` | an archived appliance is restored |

Attaching or removing an appliance **document** (a manual/warranty/receipt link, or an
uploaded file) is an appliance change, so it surfaces as `home_keeper_asset_updated`
with `changed_fields: ["documents"]`. There is no separate document event. Attaching
or removing a **part's** single file works the same way, with
`changed_fields: ["parts"]`.

Deleting an entry from an appliance's **archived task history** (via
`home_keeper.delete_archived_completion`) also surfaces as
`home_keeper_asset_updated` with `changed_fields: ["archived_history"]`.

Archiving (`home_keeper.archive_asset`) and restoring (`home_keeper.restore_asset`)
an appliance fire their own dedicated events rather than `home_keeper_asset_updated`,
since they're a distinct lifecycle action of their own. Archiving only hides the
appliance from the panel's default list; its device, entities, and any attached
tasks are left running untouched, and `home_keeper_asset_deleted` never fires for it.

### Companion discovery (edge-triggered, baselined on startup)

Home Keeper surfaces integrations that work with it (see the panel's **Settings →
Companions** section, and [INTEGRATING.md](INTEGRATING.md) §7). Like the time-based
transitions above, the current state is **baselined silently at startup** (companions
already connected/suggested when HA starts do not fire), and an event fires only
when a companion *changes* into that state while HA is running. A companion reaches
that state by self-registering. The same event also fires when a glue is installed, or
when a curated upstream is installed. State is
re-detected on the coordinator's refresh cadence (~5 min), so installing an upstream
surfaces a suggestion within one cycle. These never fire from a read (opening the
panel or calling `list_companions` fires nothing).

| Event | Fires when |
|---|---|
| `home_keeper_companion_connected` | a companion newly becomes connected. It self-registered via `home_keeper.register_companion`, or a known glue is newly detected installed; payload adds `domain`, `name`, `status`, `config_entry_id` |
| `home_keeper_companion_suggested` | a curated upstream is newly detected installed while its glue isn't; payload adds `domain` (the glue), `name`, `status`, `upstream_domain` |

There is also a fire-and-forget **request** event Home Keeper emits (at its setup and
on reload) to ask companions to (re-)announce themselves:

| Event | Fires when |
|---|---|
| `home_keeper_register_companions` | Home Keeper has set up. Companion integrations should (re-)call `home_keeper.register_companion`. The event has no data payload. |

## Payloads

### Task event spine

Every task event carries this core (per-event extras noted above are merged in):

| Field | Type | Notes |
|---|---|---|
| `task_id` | `str` | |
| `name` | `str` | |
| `device_id` | `str \| None` | the task’s registry device id, or `None` when it’s a standalone task (its entities then live on a self-owned device) |
| `area_id` | `str \| None` | |
| `tag_id` | `str \| None` | the HA tag whose scan completes the task, or `None` when no tag is linked |
| `recurrence_type` | `str` | `floating` / `fixed` / `one-off` / `triggered` / `sensor` |
| `next_due` | `str \| None` | ISO; `None` for a dormant triggered/sensor task or a completed one-off |
| `enabled` | `bool` | |
| `labels` | `list[str]` | HA label-registry ids attached to the task (empty list when none); used by the dashboard card's label filter |
| `source` | `dict \| None` | opaque provenance, echoed verbatim ([INTEGRATING.md](INTEGRATING.md)) |
| `managed_by` | `dict \| None` | well-known ownership block, or `None` |
| `task_chips` | `list[dict]` | integration-provided metadata chips (empty list when none); each entry has `label`, optional `icon` (`mdi:` name), optional `url` (`http(s)://`) |

### Stock event payload

`asset_id`, `asset_name`, `device_id`, `part_id`, `part_name`, `part_number`, `vendor`,
`stock`, `reorder_at`: enough to drive a reorder/notify without re-querying. The three
stock events are interchangeable in one template.

### Asset event payload

`asset_id`, `asset_name`, `device_id` (+ `changed_fields` for an update).

### Companion event payload

`domain`, `name`, `status` (`connected` / `suggested`), `config_entry_id` (the
companion's config entry, for a connected companion, `None` otherwise), and
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

- The `home_keeper_task_completed` payload now carries the full task spine as well as
  its long-standing `completed_at`/`origin` fields. If you only read `task_id`,
  `source`, `origin`, and `completed_at`, nothing changes for you.
- Home Keeper never inspects `source`; use it (and the `origin` echo on completions) to
  recognise and de-dupe your own tasks. See [INTEGRATING.md](INTEGRATING.md).
