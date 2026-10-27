---
title: Coordinator and entities
summary: The coordinator reads the task map, runs time-based work, and feeds the entities.
implements:
  - custom_components/home_keeper/coordinator.py
  - custom_components/home_keeper/entity.py
  - custom_components/home_keeper/task_entities.py
  - custom_components/home_keeper/task_counts.py
  - custom_components/home_keeper/sensor.py
  - custom_components/home_keeper/binary_sensor.py
  - custom_components/home_keeper/button.py
  - custom_components/home_keeper/number.py
  - custom_components/home_keeper/event.py
  - custom_components/home_keeper/service_device.py
related: [architecture, store, events-api, appliances, profiles-notifications, sensor-tasks]
source_hash: e929c051359a
---

# Coordinator and entities

`HomeKeeperCoordinator` in `coordinator.py` holds the task map that every entity reads. A
refresh reads the local store and is also the clock for time-based work. The platforms publish
tasks, counts, part stock and events as entities on device pages.

## Goals

- **G1. One read path.** Entities read through the coordinator. Only the store writes data.
- **G2. Current time-based state.** Overdue and due-soon follow the clock with no mutation.
- **G3. Entities on the right device.** A device-attached task shows its entities on that
  device page, and Home Keeper does not claim a device that another integration owns.
- **G4. Stable identity.** A rename keeps the `entity_id` that a dashboard or automation uses.
- **G5. Attributes are a contract.** Attribute names and meanings stay stable for templates.
- **G6. Few reloads.** A mutation reloads the entry only when the entity set changes.

## Non-goals

- Edge detection of crossings. `transitions.py` decides what fires (see `events-api`).
- The device registry itself: virtual appliance devices, the split repair and the device
  prune live in `devices.py` (see `appliances`).
- The `todo` and `calendar` entities, which only share the service device.

## Design

### Refresh cycle

`coordinator._async_update_data` runs these steps in order:

1. `coordinator._purge_expired_one_offs` deletes completed one-offs past the retention option.
2. `store.settle_use_tasks` brings due a counted wear item whose time backstop passed.
3. The sensor watcher evaluates sensor tasks with `refresh=False`.
4. `transitions.detect_transitions` compares the edge state with the tasks. With events on, the
   coordinator fires them, stores the state, and passes `transitions.auto_crossings` on.
5. `companions.async_reconcile` runs, and the shopping and to-do list syncs schedule a sweep.

`coordinator.async_start_clock` refreshes every `SCAN_INTERVAL` (5 minutes). The base class gets
`update_interval=None`: it polls only while an entity listens. Handlers refresh after a change.

### Edge state and the silent baseline

The edge state lives in `hass.data` per config entry, so it lives through a reload. Until
`coordinator.enable_transition_events`, a refresh fires no event. After a restart (no stored
state) the refresh adopts the state as a silent baseline. After a reload it keeps the stored
state, so a crossing during the reload fires after setup. When the user disables the entry,
`coordinator.discard_edge_state_if_disabled` drops the state, or a re-enable fires each crossing.

### Reload or refresh

Platforms add entities only at setup, and Home Assistant caches names. So these reload:

- `task_entities.owns_entities`: an enabled task with a `device_id` owns entities. An add
  or delete of such a task reloads. `task_entities.update_needs_reload`: an update reloads
  only if the task owns entities before or after it and `entity_set_key` changed. The key
  holds `device_id`, `enabled`, the names, `completion_blocked` and `require_tag_scan`.
- `coordinator.async_settle_buy_tasks` reloads when a buy task with entities comes or goes,
  or a part gains or loses stock entities (`coordinator.part_entity_kinds`). An
  `async_create_task` and a guard flag defer it, so several changes start 1 reload. Else it
  sends `SIGNAL_PART_STOCK_CHANGED`, so part entities show a new count before the refresh.
- An options change reloads for a new `options.options_entity_key`, an unloaded entry, a live
  step that raises, or a problem-sensor reconcile that changes the entity set.
  An `update_task` or `update_asset` that changes no field does not save, fire or reload.

### Per-task entities and device links

`coordinator.device_attached_task_ids` lists enabled tasks with a `device_id`. Each gets 3
entities on `entity.HomeKeeperTaskEntity` (ids from `task_entities.task_entity_unique_id`):

| Platform | Unique ID | State | Attributes |
|---|---|---|---|
| `button` | `home_keeper_<task_id>_done` | press completes | none |
| `sensor` | `home_keeper_<task_id>_next_due` | `next_due` timestamp | task, last completion, usage |
| `binary_sensor` | `home_keeper_<task_id>_overdue` | overdue | `task_id`, `due_soon`, `next_due` |

`task_entities.has_mark_done_button` skips the button for a task that refuses a completion
with no origin: a problem-sensor task, a self-clearing companion task, a tag-scan task.

`coordinator.device_link_for_task` returns exactly 1 of `(DeviceInfo, DeviceEntry)`. If the
`device_id` resolves through `device_compat.resolve_device`, the entity sets `device_entry`
and links to the device without a claim. If not, it gets a self-owned device with the task
name. On a shared device, `task_entities.entity_name_prefix` puts a label before each name:
the companion name, or the task name without the device name.

With the `task_device_entities` option off, `entity.HomeKeeperTaskEntity` sets
`entity_registry_enabled_default` false, so a new entity starts disabled. A change runs
`coordinator._switch_task_entities` once: `task_entities.switched_disabled_by` sets
`disabled_by=integration` for off and clears only that value for on. A user-disabled entry stays.
Off needs no reload. For on, Home Assistant reloads the entry itself 30 seconds after.

### Part, appliance and event entities

For parts from `coordinator.virtual_asset_parts`, `number.py` gives a spares `number` per
stock-tracked part (an edit calls `store.adjust_part_stock`), and `binary_sensor.py` a low-stock
sensor per part with a reorder threshold. `sensor.py` gives a `date` sensor per tracked date.
Each platform calls `entity.prune_registry_entries` first. Its `keep` returns `None` for a
unique ID shape that the platform does not own, so no platform removes another's entities.
`event.py` gives 1 `event` entity, `home_keeper_events`, on the service device, for every event
with a payload. It listens on the bus, so a reload can lose an event. Automations that target
1 device, area or task use the triggers ([events-api](events-api.md)).

### Count sensors and the service device

`sensor.py` always makes `home_keeper_tasks` (state: overdue tasks), plus
`home_keeper_profile_<profile_id>_tasks` per profile. `task_counts.count_tasks` computes the
state with the profile status filter, and over the scope with status `all` the attributes
`total`, `overdue`, `due_soon` (in the window, not overdue), `due_today` (local calendar date),
`next_due`, `next_task_name`, `next_task_id` and `most_overdue_days`. Tasks pass through
`notifier.effective_filter_tasks`, so inherited labels and areas count. The state class is
`MEASUREMENT` with no unit. A profile sensor reads its filter on each update.

`service_device.service_device_info` describes 1 `SERVICE` device for counts, the to-do list,
the calendar and the [cost](cost-summary.md) sensors. The all-tasks sensor is always on it.

## Trade-offs

- **Entity-level device links** over a copy of the device identifiers: copied identifiers fork
  a duplicate device. Cost: device triggers and per-device diagnostics are absent on a device
  that Home Keeper does not own, because Home Assistant reads them from `config_entries`.
- **Entry reload** for name changes over live renames: Home Assistant caches entity names.
- **Pure `task_counts.py`** over counts in the entity: unit tests need no Home Assistant, and
  the count uses the same `profiles` filter as the panel.
- **Disable in the registry** over no entities: ids stay and 1 can come back. Cost: "+N disabled".

## One-way doors

- Unique ID shapes in the table above, plus `home_keeper_asset_<asset_id>_part_<part_id>_stock`,
  `..._low_stock`, `home_keeper_asset_<asset_id>_meta_<entry_id>` and `home_keeper_events`.
  `trigger_targets.py` reads the task, part and appliance shapes.
- Entity attributes, declared in `api_surface.ENTITY_PLATFORMS`. The `last_completion_<field>`
  keys follow `const.COMPLETION_ENTRY_FIELDS`, and `usage_*` keys exist only on usage tasks.
- The count semantics: `due_soon` excludes overdue tasks; `due_today` is a local calendar date.
- `task_device_entities` off means disabled by the integration, not removed.
