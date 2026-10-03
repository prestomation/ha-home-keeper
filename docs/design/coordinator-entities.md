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
  - custom_components/home_keeper/service_device.py
related: [architecture, store, events-api, appliances, profiles-notifications, sensor-tasks]
source_hash: 8c9493957e34
---

# Coordinator and entities

`HomeKeeperCoordinator` in `coordinator.py` holds the task map that every entity reads. A
refresh reads the local store and is also the clock for time-based work. The entity platforms
publish tasks, counts and part stock as Home Assistant entities on device pages.

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
4. `transitions.detect_transitions` compares the edge state with the tasks. When events are
   on, the coordinator fires each event, stores the new edge state, and passes
   `transitions.auto_crossings` to `notifier.async_send_auto`.
5. `companions.async_reconcile` runs, and the shopping and to-do list syncs schedule a sweep.

`coordinator.async_start_clock` refreshes every `SCAN_INTERVAL` (5 minutes). The base class
gets `update_interval=None`, because Home Assistant polls only while an entity listens. Each
service and websocket handler also asks for a refresh after a mutation.

### Edge state and the silent baseline

The edge state lives in `hass.data` per config entry, so it lives through an entry reload.
Until setup calls `coordinator.enable_transition_events`, a refresh fires no event. With no
stored edge state (a restart), the refresh adopts the detected state as a silent baseline, so
a task overdue at startup does not fire again. With stored state (a reload), the refresh keeps
it, and a crossing during the reload fires on the first refresh after setup.

`coordinator.discard_edge_state_if_disabled` drops the state when the user disables the
entry. Without it, a re-enable after days sends 1 event per crossing in that time.

### Reload or refresh

Home Assistant caches entity names, and platforms add entities only at setup. A change to
the entity set therefore needs an entry reload:

- `coordinator.task_has_entities`: an enabled task with a `device_id` owns entities. An add
  or delete of such a task reloads. `store._task_owns_entities` repeats this rule.
- `task_entities.entity_set_key`: on update, the key holds `device_id`, `enabled`, the name,
  the companion name, `completion_blocked` and `require_tag_scan`. A changed key reloads.
- `coordinator.async_settle_buy_tasks` reloads when a buy task with entities appears or
  goes, or when a part gains or loses its stock entities (`coordinator.part_entity_kinds`).
  It defers the reload with `async_create_task` and a guard flag, so the calling entity is
  not torn down mid-call and several changes start 1 reload.
- Without a reload, it sends `SIGNAL_PART_STOCK_CHANGED`. Only part entities listen, so a
  new count shows before the debounced refresh.

### Per-task entities and device links

`coordinator.device_attached_task_ids` lists enabled tasks with a `device_id`. Each gets
3 entities, built on `entity.HomeKeeperTaskEntity`:

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

### Part and appliance entities

On parts from `coordinator.virtual_asset_parts`, `number.py` gives a spares `number` per
stock-tracked part, and an edit calls `store.adjust_part_stock`. `binary_sensor.py` gives a
low-stock sensor per part with a reorder threshold. `sensor.py` gives a `date` sensor per
tracked date metadata entry. Before it adds entities, each platform calls
`entity.prune_registry_entries`. Its `keep` returns `None` for a unique ID shape that the
platform does not own, so no platform removes the entities of another.

### Count sensors and the service device

`sensor.py` always makes `home_keeper_tasks` (state: overdue tasks), plus
`home_keeper_profile_<profile_id>_tasks` per profile. `task_counts.count_tasks` computes the
state with the profile status filter, and the attributes over the scope with status `all`:
`total`, `overdue`, `due_soon` (in the window, not overdue), `due_today` (local calendar date),
`next_due`, `next_task_name`, `next_task_id` and `most_overdue_days`. Tasks first pass through
`notifier.effective_filter_tasks`, so inherited labels and areas count. The state class is
`MEASUREMENT` with no unit.

`service_device.service_device_info` describes 1 `SERVICE` device for counts, the to-do list
and the calendar. Home Assistant creates it from `device_info`, and the all-tasks sensor always
exists, so the device always has an entity.

## Trade-offs

- **Entity-level device links** over a copy of the device identifiers: copied identifiers fork
  a duplicate device. Cost: device triggers and per-device diagnostics are absent on a device
  that Home Keeper does not own, because Home Assistant reads them from `config_entries`.
- **Entry reload** for name changes over live renames: Home Assistant caches entity names.
- **Pure `task_counts.py`** over counts in the entity: unit tests need no Home Assistant, and
  the count uses the same `profiles` filter as the panel.

## One-way doors

- Unique ID shapes in the table above, plus `home_keeper_asset_<asset_id>_part_<part_id>_stock`,
  `..._low_stock` and `home_keeper_asset_<asset_id>_meta_<entry_id>`.
- Entity attributes, declared in `api_surface.ENTITY_PLATFORMS`. The `last_completion_<field>`
  keys follow `const.COMPLETION_ENTRY_FIELDS`, and `usage_*` keys exist only on usage tasks.
- The count semantics: `due_soon` excludes overdue tasks; `due_today` is a local calendar date.
