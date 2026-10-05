---
title: Integrating with Home Keeper
summary: How another integration adds tasks and appliances to Home Keeper and keeps them in sync.
---

# Integrating with Home Keeper

This guide is for **authors of other Home Assistant integrations** that push recurring tasks
into Home Keeper, such as a battery, plant or pet integration. Your integration owns the
schedule. It uses only the **event bus and services**: there is no Python import in either
direction and no hard dependency. Home Keeper stores and echoes the `source` and `origin`
values verbatim. It never branches on their contents.

Every action, field, event and payload is in the generated
[API reference](https://prestomation.github.io/ha-home-keeper/developer/api). The event
catalog is in [EVENTS.md](EVENTS.md).

**Rules for every integration:**

- Guard every call with `hass.services.has_service("home_keeper", "<service>")`, so your
  integration works when Home Keeper is absent.
- When the Home Keeper config entry reloads or is disabled, a call raises
  `HomeAssistantError` with the translation key `integration_not_loaded`. Catch it where a
  failed call must not stop your code, and try again on `home_keeper_register_companions` (§9).
- Use ids, not names. Each `task_id`, `asset_id`, `part_id` and `document_id` field also
  accepts a name for hand-written YAML, but a name can change and is not unique.

## 1. Creating a task

Recurrence is **floating** (`interval` + `unit`, from the last completion) or **fixed**
(`rrule` + `anchor`; the older `freq` + `interval` still works). Keep the returned
`task_id`:

```python
DOMAIN_HK = "home_keeper"

if hass.services.has_service(DOMAIN_HK, "add_task"):
    resp = await hass.services.async_call(DOMAIN_HK, "add_task", {
        "name": "Replace smoke-detector battery",
        "notes": "Uses a **9V** battery.",  # Markdown source, stored verbatim
        "recurrence_type": "floating", "interval": 6, "unit": "months",
        # Fixed: "recurrence_type": "fixed", "rrule": "FREQ=MONTHLY;BYDAY=1TU",
        #        "anchor": "2026-01-06T08:00:00"
        "last_completed": "2026-01-01T08:00:00",  # optional; else the task is due now
        "device_id": my_device_id,  # optional device registry id
        "source": {"my_integration": {"thing_id": thing_id}},  # namespaced under YOUR domain
    }, blocking=True, return_response=True)
    task_id = resp["task_id"]
```

With a `device_id`, the next-due sensor, overdue binary_sensor and mark-done button show on
that device page. Get the id with `async_get_device_by_identifier` (Home Assistant 2026.9+).

**Find a task again** after a restart. Call `list_tasks` with `return_response=True`, then
match on your `source` namespace. Put a unique id of your own, such as a `schedule_id`, in
`source`. **Put a device id at the top level of your namespace, under the key
`device_id`.** When Home Assistant renumbers a device, Home Keeper heals only the task
`device_id` and `source.<your-namespace>.device_id`. Another place is not healed, and your
next reconcile makes a duplicate.

## 2. Reacting to a completion

Home Keeper fires `home_keeper_task_completed` on every completion, from every surface. These
include the to-do checkbox and the device button, the panel and the `complete_task` service.

```python
@callback
def _on_hk_completed(event):
    if event.data.get("origin") == "my_integration":
        return  # the echo of our own completion (§4)
    if src := (event.data.get("source") or {}).get("my_integration"):
        hass.async_create_task(_record_done(src, event.data.get("completed_at")))

entry.async_on_unload(hass.bus.async_listen("home_keeper_task_completed", _on_hk_completed))
```

The payload has `task_id`, `name`, `source`, `completed_at`, `origin` (`None` for a user),
`managed_by`, and the common
[task fields](https://prestomation.github.io/ha-home-keeper/developer/api#task-payload).

## 3. Completing from your side

Call `home_keeper.complete_task` with `task_id`, an optional `completed_at`, and
`origin: "my_integration"`. For an undo, Home Keeper fires `home_keeper_task_uncompleted`,
whose `ts` names the removed completion. To undo from your side, call
`home_keeper.delete_completion` with `task_id`, that `ts` and your `origin`.

## 4. Two-way sync and loop prevention

A call you make comes back to your listener as an event. Use **two guards** to stop a loop:

1. **`origin` marker.** Send your own `origin`. Your listener ignores events with it.
2. **No completion on the inbound path.** When your listener reacts to an event, write your
   record through a code path that does not call `complete_task` or `delete_completion`.

## 5. Lifecycle

- **Your config is removed:** call `home_keeper.delete_task` for the ids you stored. A call
  for an id that is already deleted succeeds. A name that matches no task fails with
  `task_not_found`.
- **The user deletes a task in Home Keeper:** `home_keeper_task_deleted` fires with your
  `source`. Also reconcile at setup with `list_tasks`, for deletions while you were stopped.

## 6. Declaring managed ownership (optional)

Pass `managed_by` with `source` on `add_task` to declare your integration as the owner of a
task. Home Keeper reads `managed_by` and acts on it.

| Field | Effect |
|---|---|
| `integration` | Required. Your domain. |
| `display_name` | Required. A **Managed by {name}** chip on the task card and page. |
| `icon` | An `mdi:` icon. |
| `locked_fields` | The panel removes these fields from the edit form. With every field locked, the task page shows no Edit button. |
| `config_entry_id` | Orphan detection, and an **Edit in {name}** link on the task page. |
| `completion_prompt` | A short hint near the **Done** button. |
| `deletion_protected` | The panel shows "Delete from {name} instead", and `delete_task` rejects the call while your entry is loaded. Requires `config_entry_id`. |

- Set `managed_by` once, on `add_task`. The `update_task` service has no `managed_by`
  field, so a call that sends one fails validation.
- Home Keeper removes the locked fields from every `update_task` payload, also from your
  own calls. A locked field keeps the value it had at creation. Lock only the fields your
  integration never changes. To change one, delete the task and add it again.
- `photos` cannot be locked. Photos belong to the household, like the stock of a managed
  part, so users can always add, remove and reorder them.
- `add_task` rejects `deletion_protected` without `config_entry_id` (`invalid_task`),
  because Home Keeper then cannot see that your integration is gone.

**Cleanup.** When the recorded config entry is not loaded, the task is *orphaned*. The chip
shows **Integration offline** and **Delete** comes back. The task list also offers **Remove
orphaned tasks** (`home_keeper.delete_orphaned_tasks`, admin-only). As a last resort,
`delete_task` with `force: true` ignores the protection.

## 7. Condition-driven (triggered) tasks

For work that a condition starts, such as a low battery or a wet water sensor, send
`recurrence_type: "triggered"` and no schedule fields. A triggered task is **armed**
(`next_due` is a time and the task is overdue on every surface) or **dormant** (`next_due` is
`null` and the task shows only in the panel **Monitored** section).

`add_task` creates the task armed. When the condition resolves, `complete_task` records a
completion and makes the task dormant. When the condition comes back, `trigger_task` arms it
again. Both calls are idempotent. Keep **one task per monitored thing** and toggle it, so
that the id and the history stay.

### Sensor-based tasks

With `recurrence_type: "sensor"` and a `sensor` mapping, Home Keeper watches an entity and
arms the task itself (`home_keeper_task_triggered`). The task starts dormant.

```python
# Usage: due when the reading advances by `target` since the last completion.
"sensor": {"entity_id": "sensor.x1c_total_usage_hours", "mode": "usage", "target": 300,
           "unit": "h",                                      # display label only
           "also_every": {"interval": 6, "unit": "months"},  # time backstop
           "combinator": "any",                              # or "all"
           "baseline": 660}                                  # else the first reading
# Threshold: due when the reading crosses the comparison for for_seconds.
"sensor": {"entity_id": "sensor.airflow", "mode": "threshold",
           "comparison": "<", "value": 60, "for_seconds": 120}
```

The `also_every` backstop applies also when the entity is unavailable.
`home_keeper.set_task_meter` moves the baseline. A completion records the live value as
`reading`. To mirror earlier work, send `reading` on `complete_task`, and send it again on
each `update_completion`, which clears a key that you omit.

### Task chips

`task_chips` on `add_task` or `update_task` puts chips on the task in the panel and the card.
Each chip has `label` (required), `icon` (an `mdi:` name) and `url` (`http(s)://`).
`update_task` changes the chips only when the call sends `task_chips`. Users cannot edit
chips. Do not send a chip for a linked part, because Home Keeper draws that chip (§8).

## 8. Managing an appliance

Send `managed_by` and `source` to `home_keeper.add_asset` to own an appliance and its parts.
Its block is the task block without `completion_prompt` and `completion_blocked`.
Both fields are **create-only**: `update_asset` ignores `source`, and accepts `managed_by`
only as `null`. Find your appliance again with `home_keeper.list_assets`.

### Locked parts

The vocabulary is `const.ASSET_LOCKED_FIELDS`. Each field except `parts` works as on a task.
A locked `parts` splits each part: the owner keys are yours, the stock keys are the user's.

| Owner keys (locked) | User keys (never yours) |
|---|---|
| `name`, `type`, `notes`, `part_number`, `vendor`, `url`, `cost` | `stock`, `reorder_at`, `stock_unit` |
| `replace_interval`, `replace_unit`, `replace_also_every`, `action` | `consume_quantity`, `create_buy_task` |
| `use_noun`, `use_task_name`, `last_replaced`, `carried_uses` | `restock_quantity` |

`update_asset` writes only user keys, on parts that exist. To write owner keys, call
`home_keeper.update_managed_asset` (admin-only, your appliances only) with `asset_id`, an
optional `name`, and the full `parts` list. Parts match on `id`. A part without a known `id`
is new and starts at `stock: null`. Do not send `stock`, because Home Keeper drops it. A part
you leave out is removed only if it tracks no stock. To name the devices that use shared
stock, write a "Used by" line in the part `notes`.

### Stock and `source`

`home_keeper.set_task_consumable` links a task to a part (omit `asset_id` and `part_id` to
unlink). Each completion takes `quantity` off the part `stock`, or the part
`consume_quantity` (default 1) when you omit it. The link is stored as
`source["part"] = {asset_id, part_id, manual: true, quantity}`. The task shows a chip such as
**Takes 2 AAA · 2 left**. `delete_completion` gives back the `stock_drawn` of that
completion. A count at the reorder level fires `home_keeper_part_low_stock` or
`home_keeper_part_out_of_stock`.

For a use that is not a task, call `home_keeper.adjust_part_stock` with a negative `delta`.
The response is `{stock, applied_delta, reorder_at, unit, status}`. To undo, send
`applied_delta` back negated, because it differs from `delta` when the count stops at 0. Each
counted part on a virtual appliance has a spares `number` entity,
`home_keeper_asset_<asset id>_part_<part id>_stock`, which all users can read.

`source` is a map of namespaces. Home Keeper owns `part`, `buy` and `declarative_companion`.
**Merge into `source` and remove only your own key.** On `update_task`, each namespace in the
call replaces the stored one, `null` removes it, and a reserved name fails with
`invalid_task`.

**Uninstall.** A delete of a managed appliance deletes the user's stock counts. In
`async_remove_entry`, call `update_asset` with `{"asset_id": asset_id, "managed_by": None}`.
The locks come off and the user keeps the appliance. Delete it only when no part tracks stock.

## 9. Discovery and declarative companions

Call `home_keeper.register_companion` at setup to show your integration in the panel
**Settings → Companions** section. Call it again on `home_keeper_register_companions`, which
Home Keeper fires at its own setup and reload.

```python
await hass.services.async_call(DOMAIN_HK, "register_companion", {
    "domain": "my_integration", "name": "My Integration", "icon": "mdi:puzzle",
    "description": "One line on what it does with Home Keeper.",
    "config_entry_id": entry.entry_id, "docs_url": "https://github.com/me/my-integration",
}, blocking=False)
```

Registering fires `home_keeper_companion_connected`.

A declarative companion makes one managed sensor task for each entity that matches a
selection. Users make them in **Settings → Companions → Declarative**. An integration can call
`add_declarative_companion`, `update_declarative_companion`, `delete_declarative_companion`
and `list_declarative_companions` (all admin-only).

- Select by `target_integration` and `selection.translation_keys` in preference to
  `entity_regex`: a translation key does not change on a rename or a language change.
  `selection.device_ids` limits the selection to those devices.
- `task_template.task_names` maps a key to a name, read as `{{ task_name }}`.
- A call returns after the reconcile, and after a config entry reload if one is necessary.
- Find these tasks by `managed_by.integration == "home_keeper"` and
  `source.declarative_companion.spec_id`. A Profile selects them with
  `home_keeper:declarative:<spec_id>`.
- The presets are in `declarative_presets_catalog.py`. An integration preset id is
  `<domain>_<shape>`, such as `roborock_life_low`.

Write a glue integration instead when you must write back to the upstream integration on
completion, or keep state across completions. See [GLUE_INTEGRATIONS.md](GLUE_INTEGRATIONS.md).

## Testing your integration

Add `home-keeper @ git+https://github.com/prestomation/ha-home-keeper@main` to your test
requirements, and use the fake with `pytest-homeassistant-custom-component`:

```python
from home_keeper.testing import async_setup_fake_home_keeper

async def test_two_way_sync(hass):
    hk = await async_setup_fake_home_keeper(hass)  # registers the real service names
    # ... set up your integration so it calls home_keeper.add_task ...
    task = hk.get_task_by_source("my_integration", thing_id="abc")
    hk.fire_user_completion(task["id"])  # a user completion, origin=None
    await hass.async_block_till_done()  # then assert your record, with no loop
```

`FakeHomeKeeper` also has `.tasks`. It uses the real model, recurrence and event payload code
(`home_keeper.events.completion_event_data`), so it cannot drift from production.
[Pawsistant](https://github.com/prestomation/pawsistant) is one client of this contract.
