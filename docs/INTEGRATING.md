# Integrating with Home Keeper

This guide is for **authors of other Home Assistant integrations** who want to push
recurring tasks into Home Keeper and keep them in sync with completions — for example a
battery integration that schedules "replace battery", a plant integration that schedules
"water the fern", or a pet integration that schedules "trim nails".

Home Keeper is the recurring-task engine. **Your integration owns the schedule
configuration**; it talks to Home Keeper purely over the Home Assistant **event bus and
services**. There is no Python import in either direction and no hard dependency: if Home
Keeper isn't installed, your calls are simply skipped.

> **Home Keeper knows nothing about your integration.** The `source` and `origin` values
> below are *opaque* to Home Keeper — it stores and echoes them verbatim and never
> branches on their contents. Everything domain-specific lives in your integration.

## At a glance

| You want to… | Do this |
|---|---|
| Create a recurring task | Call `home_keeper.add_task` with a `source` namespaced under your domain |
| Create a *condition-driven* task | Call `home_keeper.add_task` with `recurrence_type: "triggered"` (no schedule) |
| Create a *sensor-based* task | Call `home_keeper.add_task` with `recurrence_type: "sensor"` and a `sensor` mapping (Home Keeper evaluates it for you — see §7) |
| Learn the new task's id | Read `task_id` from `add_task`'s response (`return_response=True`) |
| React when a task is completed | Subscribe to the `home_keeper_task_completed` event |
| Complete a task from your side | Call `home_keeper.complete_task` with a unique `origin` |
| Re-arm a triggered task | Call `home_keeper.trigger_task` when the condition becomes true again |
| Avoid infinite loops | Filter the event by `origin`, and apply your side-effect without re-calling `complete_task` |
| Remove a task | Call `home_keeper.delete_task` |

Guard **every** service call with
`hass.services.has_service("home_keeper", "<service>")` so your integration works fine
when Home Keeper is absent.

## 1. Creating a task

Call the existing `home_keeper.add_task` service. Recurrence is either **floating**
(`interval` + `unit`) or **fixed** (`freq` + `interval` + `anchor`):

```python
DOMAIN_HK = "home_keeper"

if hass.services.has_service(DOMAIN_HK, "add_task"):
    await hass.services.async_call(
        DOMAIN_HK,
        "add_task",
        {
            "name": "Replace smoke-detector battery",
            # floating: every N days/weeks/months, measured from completion
            "recurrence_type": "floating",
            "interval": 6,
            "unit": "months",
            # fixed alternative:
            #   "recurrence_type": "fixed",
            #   "freq": "MONTHLY",            # DAILY | WEEKLY | MONTHLY
            #   "interval": 1,
            #   "anchor": "2026-01-01T08:00:00",  # sets the time-of-day; naive is OK
            #
            # Optional "last done" seed. A floating task with no completion history
            # is due *immediately* (a chore you've never done is due now, not a full
            # interval from now). If you already know when the activity last happened,
            # pass it here to seed an initial completion so the first next-due is
            # measured from it (next_due = last_completed + interval) instead:
            #   "last_completed": "2026-01-01T08:00:00",  # naive is OK
            #
            # Optional: attach the task to an existing device so Home Keeper's
            # next-due sensor, overdue binary_sensor and mark-done button appear on
            # that device's page. Pass a device *registry id* (not your own key).
            "device_id": my_device_id,
            # Opaque provenance, namespaced under YOUR domain. Put whatever you need
            # here to recognise the task later. Home Keeper stores it verbatim.
            "source": {"my_integration": {"thing_id": thing_id}},
        },
        blocking=True,
    )
```

Resolving a device registry id from your own identifiers:

```python
from homeassistant.helpers import device_registry as dr

dev = dr.async_get(hass).async_get_device(identifiers={("my_integration", thing_id)})
my_device_id = dev.id if dev else None  # omit device_id if None
```

## 2. Getting the task id back

`add_task` returns the new task's id in its service response. Call it with
`return_response=True` and read `task_id`:

```python
resp = await hass.services.async_call(
    DOMAIN_HK, "add_task", data, blocking=True, return_response=True
)
task_id = resp["task_id"]
# Persist task_id on your side so you can complete/delete it later.
```

If you need to resolve an id you didn't capture (e.g. reconciling after a restart),
`list_tasks` returns every task and you can match on your `source` namespace:

```python
resp = await hass.services.async_call(
    DOMAIN_HK, "list_tasks", {}, blocking=True, return_response=True
)
task_id = next(
    (
        t["id"]
        for t in resp["tasks"]
        if (t.get("source") or {}).get("my_integration", {}).get("thing_id") == thing_id
    ),
    None,
)
```

> Embed a unique id of your own (e.g. a `schedule_id` you generate) inside `source` so
> the match is unambiguous even if the user creates similarly named tasks.

## 3. Reacting to a completion

Home Keeper fires `home_keeper_task_completed` on **every** completion, whatever the
surface — the to-do list checkbox, the device mark-done button, or the `complete_task`
service. Subscribe in `async_setup_entry` and unsubscribe on unload:

```python
EVENT_HK_COMPLETED = "home_keeper_task_completed"

@callback
def _on_hk_completed(event):
    # Ignore completions we initiated ourselves (see §4, loop prevention).
    if event.data.get("origin") == "my_integration":
        return
    src = (event.data.get("source") or {}).get("my_integration")
    if not src:
        return  # not one of our tasks
    # Apply your side-effect WITHOUT calling complete_task again (see §4).
    hass.async_create_task(_record_done(src, event.data.get("completed_at")))

entry.async_on_unload(hass.bus.async_listen(EVENT_HK_COMPLETED, _on_hk_completed))
```

Event payload:

| Field | Type | Meaning |
|---|---|---|
| `task_id` | `str` | The completed task. |
| `name` | `str` | Its display name. |
| `source` | `dict \| None` | Exactly what you passed to `add_task`. |
| `completed_at` | `str` (ISO) | When it was completed. |
| `origin` | `str \| None` | Whatever the completer passed; `None` for a manual/Home-Keeper-UI completion. |

The payload also carries the common task **spine** (`device_id`, `area_id`,
`recurrence_type`, `next_due`, `enabled`, `managed_by`) — see
[EVENTS.md](EVENTS.md#task-event-spine). If you only read the fields above, nothing
changes for you.

> **`home_keeper_task_completed` is one of a full catalog.** Home Keeper fires events
> for the entire lifecycle — tasks created/updated/deleted/uncompleted/triggered,
> overdue/due-soon, spare parts low/out/restocked, and appliances created/updated/
> deleted — all built by the same pure payload builders in `events.py`. If your
> integration needs to react to more than completion, see [EVENTS.md](EVENTS.md) for the
> catalog. Everything below stays focused on the completion contract.

## 4. Two-way sync and loop prevention

To make the task behave like "the same button" on both sides you complete it from your
side too. The danger is an infinite loop: you complete the task → Home Keeper fires the
event → your listener completes it again → … Break it with **two independent guards**:

1. **`origin` marker.** When *you* complete a task, pass a value you recognise. Home
   Keeper echoes it in the event; your listener ignores events whose `origin` is yours.

   ```python
   await hass.services.async_call(
       DOMAIN_HK,
       "complete_task",
       {"task_id": task_id, "origin": "my_integration", "completed_at": when_iso},
       blocking=True,
   )
   ```

2. **Don't re-complete on the inbound path.** When your listener reacts to a completion
   it did *not* initiate (§3), apply the side-effect through a code path that does **not**
   call `home_keeper.complete_task`. Then even if the `origin` check were ever bypassed,
   no loop can form. (In Home Keeper's own first client this means writing the mirrored
   record straight to storage rather than re-entering the user-facing "log" service that
   itself triggers completion.)

Either guard alone closes the loop; together they are robust.

## 5. Lifecycle

Keep the two sides from drifting:

- **Your config is removed** → call `home_keeper.delete_task` for the task ids you stored.
- **Home Keeper is absent** → the `has_service` guards make every call a no-op; your
  integration keeps working, and tasks you couldn't create simply don't sync.
- **The user deletes a task directly in Home Keeper** → no event fires for it. Reconcile
  on your own setup: call `list_tasks`, and for any of your schedules whose stored
  `task_id` is gone, recreate it (re-`add_task` with the same `source`) so it self-heals.
- **A device you attached to disappears** → Home Keeper degrades gracefully (the task
  falls back to a self-owned device); still delete the task when your thing goes away.

## 6. Declaring managed ownership (optional)

Pass `managed_by` alongside `source` in your `add_task` call to tell Home Keeper that
your integration is the authoritative owner of this task. Unlike `source` (which Home
Keeper never inspects), `managed_by` is a **well-known block that Home Keeper acts on**:

```python
await hass.services.async_call(
    DOMAIN_HK,
    "add_task",
    {
        "name": "Buddy: Medicine",
        "device_id": pet_device_id,
        "source": {"my_integration": {"schedule_id": schedule_id}},
        "managed_by": {
            # Required.
            "integration": "my_integration",   # your DOMAIN
            "display_name": "My Integration",  # shown in the UI chip
            # Optional.
            "icon": "mdi:pill",                # mdi icon (future use)
            "locked_fields": ["device_id", "name"],  # user cannot change these
            "config_entry_id": entry.entry_id, # enables orphan detection + deep link
            "completion_prompt": "Log as Buddy's medicine dose?",  # shown near Done
            "deletion_protected": True,        # blocks deletion from HK panel
        },
        **recurrence_payload,
    },
    blocking=True,
    return_response=True,
)
```

### What Home Keeper does with `managed_by`

| Field | Effect |
|---|---|
| `display_name` | Shows a **"Managed by {name}"** chip on every task card and detail page. |
| `locked_fields` | Those fields are **removed from the edit form** — user edits are silently ignored by `update_task`. |
| `config_entry_id` | If the entry is unloaded, the chip becomes **"Integration offline"** (orphan detection). Also enables an **"Edit in {name}"** deep link on the detail page. |
| `completion_prompt` | A short hint shown near the **Done** button so users know a completion triggers an action in your integration. |
| `deletion_protected` | Replaces the **Delete** button with "Delete from {name} instead." The `delete_task` service also rejects the call with a descriptive error — **but only while your integration is still loaded** (see cleanup below). **Requires `config_entry_id`**; `add_task` rejects a protected task without one. |

### Cleanup when your integration is gone or broken

Deletion protection is intentionally **not a one-way trap**. It only holds while the
owner is present, so a user is never stuck with tasks they can't remove:

- **Orphan detection.** When the `config_entry_id` you recorded is no longer loaded
  (uninstalled, disabled, or failing to set up), Home Keeper treats the task as
  *orphaned*: the chip flips to **"Integration offline"**, the **Delete** button comes
  back, and the task list shows a **"Remove orphaned tasks"** banner for one-click bulk
  cleanup. This is why supplying `config_entry_id` matters — it's how Home Keeper knows
  your integration went away.
- **Force escape hatch.** `home_keeper.delete_task` accepts `force: true`, which bypasses
  protection entirely. It's the last-resort path (e.g. Developer Tools → Actions) for a
  task that has no `config_entry_id` recorded, or any other edge case:

  ```yaml
  action: home_keeper.delete_task
  data:
    task_id: "abc-123"
    force: true
  ```

> **`config_entry_id` is required when `deletion_protected` is set.** `add_task` rejects
> a protected task without it (`TaskValidationError` / `invalid_task`), because without it
> Home Keeper couldn't auto-detect that you've been removed and the protection would
> become a permanent trap. The `force` delete remains as a last resort for any task that
> predates this rule.

Your integration should still proactively `delete_task` for the ids it owns when its
config entry is removed (see §5) — orphan cleanup is the safety net for when it can't.

### What to be aware of

- `managed_by` is a **UI contract**, not an access-control fence. Other integrations or
  automations can still call `complete_task` or `update_task` on non-locked fields.
- Set `managed_by` once at creation via `add_task`. The `update_task` service ignores it.
- Because locked fields are stripped from the `update_task` payload, your reconciler can
  safely call `update_task` to change a locked field (e.g. rename when the pet's name
  changes) without risk of the user having overwritten it first.

### `managed_by` in the completion event

The `home_keeper_task_completed` event now includes a `managed_by` field (same shape as
above, or `None` for unmanaged tasks). Integrations that own tasks don't need to inspect
it — your `origin` guard and `source` namespace already identify your completions.

## 7. Condition-driven (triggered) tasks

Some maintenance isn't periodic — it's a response to a **condition** your integration
detects: a battery dropped low, a water sensor went wet, a filter's pressure-drop
crossed a threshold. For these, pass `recurrence_type: "triggered"` instead of a
floating/fixed schedule. A triggered task has **no schedule at all** (no
`interval`/`unit`/`freq`/`anchor`); your integration owns its lifecycle entirely.

A triggered task has two states, carried by its `next_due`:

- **armed / due-now** — `next_due` is a timestamp. It reads as overdue on every surface
  (to-do list, device overdue binary_sensor, panel) the whole time it's armed.
- **dormant** — `next_due` is `null`. It is invisible to the to-do list, the calendar,
  and the overdue/due-soon sensors — present but quietly waiting. The panel buckets it
  into a collapsed **"Monitored"** section so it's browsable without cluttering the list.

The lifecycle, mapped to the three services:

| When your condition… | Call | Effect |
|---|---|---|
| first becomes true | `add_task` with `recurrence_type: "triggered"` | creates the task **armed** (due-now) |
| becomes true again later | `home_keeper.trigger_task` (`task_id`) | re-arms a dormant task (→ due-now) |
| resolves | `home_keeper.complete_task` (`task_id`, `origin`) | records a completion **and** returns the task to dormant |

Completing a triggered task is what *clears* it — it records the event in the task's
completion history (so the full cadence accumulates, e.g. "battery replaced every
~13 months") and then goes dormant rather than rescheduling. `trigger_task` is the
inverse: it arms the task without recording anything. Both are idempotent.

```python
# Condition first detected → create the task, armed/due-now:
resp = await hass.services.async_call(
    DOMAIN_HK, "add_task",
    {
        "name": f"Replace battery: {device_name}",
        "recurrence_type": "triggered",     # no interval/unit/freq/anchor
        "device_id": device_id,
        "source": {"my_integration": {"device_id": device_id}},
        "managed_by": {                      # see §6 — recommended for owned tasks
            "integration": "my_integration",
            "display_name": "My Integration",
            "config_entry_id": entry.entry_id,
            "deletion_protected": True,
            "locked_fields": ["name", "device_id"],
        },
    },
    blocking=True, return_response=True,
)
task_id = resp["task_id"]

# Condition resolved (records history, goes dormant):
await hass.services.async_call(
    DOMAIN_HK, "complete_task",
    {"task_id": task_id, "origin": "my_integration"}, blocking=True,
)

# Condition true again later (re-arm the same task — history is preserved):
await hass.services.async_call(
    DOMAIN_HK, "trigger_task", {"task_id": task_id}, blocking=True,
)
```

> **Don't delete-and-recreate on every cycle.** Keep one persistent triggered task per
> monitored thing and toggle it with `complete_task` / `trigger_task`. That keeps the
> task id stable and preserves the replacement history on the task. Reconcile after a
> restart with `list_tasks` (match your `source`), arming/clearing to match the current
> condition; only `delete_task` when the monitored thing goes away for good.

Two-way sync works exactly as in §3–§4: a user checking the task off in Home Keeper
fires `home_keeper_task_completed` (origin `None`) and Home Keeper has already set the
task dormant for you — your listener just applies its own side-effect (without
re-calling `complete_task`). Triggered tasks never appear on the calendar.

### Sensor-based tasks (Home Keeper arms them for you)

A **sensor** task is the self-driven cousin of a triggered task: instead of *you*
arming it, you hand Home Keeper a numeric entity and a condition and it arms the task
itself. Pass `recurrence_type: "sensor"` and a `sensor` mapping:

```python
# Usage / meter: due once the reading advances 15000 units since the last completion.
{"recurrence_type": "sensor",
 "sensor": {"entity_id": "sensor.odometer", "mode": "usage", "target": 15000}}

# Threshold: due when the reading crosses the comparison (optional for_seconds hold,
# optional attribute to read instead of the state).
{"recurrence_type": "sensor",
 "sensor": {"entity_id": "sensor.airflow", "mode": "threshold",
            "comparison": "<", "value": 60, "for_seconds": 120}}
```

The task starts **dormant**; Home Keeper's internal watcher arms it (firing
`home_keeper_task_triggered`, then `home_keeper_task_overdue`) when the condition is
met. Completing it clears it like any user task — and for a `usage` meter, resets the
baseline so the next interval is measured from the reading at completion. You don't
arm/clear it yourself; this is internal to Home Keeper, so no contribution API is
involved.

### Linking a task to a consumable (draw down stock on completion)

Any task — sensor-armed or not — can be **linked to an appliance consumable/part** so
that completing it consumes one spare from the part's `stock` and fires the
edge-triggered `home_keeper_part_low_stock` / `_out_of_stock` events at the reorder
threshold (see [docs/EVENTS.md](EVENTS.md)). Use the `home_keeper.set_task_consumable`
service:

```yaml
service: home_keeper.set_task_consumable
data:
  task_id: "<task id>"
  asset_id: "<appliance id>"
  part_id: "<consumable part id>"   # omit asset_id/part_id to clear the link
```

This is the end-to-end recipe for *"my fridge tells me when the water filter is spent,
auto-subtract a spare and tell me to buy more"*: create a `sensor` task bound to the
filter's life/usage entity, link it to the filter consumable, and an automation on
`home_keeper_part_low_stock` adds it to your shopping list. The link is recorded on the
task's `source` (`{"part": {asset_id, part_id, manual: true}}`); the `manual` flag keeps
it independent of the wear-part reconciler, so it is never auto-deleted and stays fully
editable. A reconciler-derived wear-part task is already bound to its part and cannot be
re-linked by hand.

### Attaching metadata chips to a task (`task_chips`)

Any task can carry a list of **integration-provided metadata chips** that appear in
both the sidebar panel's task list and the dashboard card. Chips are a compact way to
surface contextual information alongside a task — for example, the battery type needed
to replace a low battery, or a part number.

**Schema** — each chip is an object with one required and two optional fields:

| Field   | Required | Description |
|---------|----------|-------------|
| `label` | ✅ | Display text shown on the chip. |
| `icon`  | optional | An `mdi:` icon name (e.g. `mdi:battery`). Shown at the start of the chip. |
| `url`   | optional | An `http(s)://` URL. When present the chip becomes a clickable link (opens in a new tab). |

Pass `task_chips` in your `add_task` call:

```yaml
service: home_keeper.add_task
data:
  name: "Replace battery: Front door sensor"
  recurrence_type: triggered
  device_id: "abc123"
  task_chips:
    - label: "2× AAA"
      icon: "mdi:battery"
  managed_by:
    integration: my_integration
    display_name: My Integration
    deletion_protected: true
    config_entry_id: "..."
```

Chips can also be updated later via `update_task`. Home Keeper only rewrites `task_chips`
when you explicitly send the field — a routine name/notes update will never clear chips
set at creation time:

```yaml
service: home_keeper.update_task
data:
  task_id: "<task id>"
  task_chips:
    - label: "CR2032"
      icon: "mdi:battery"
```

**Chips are integration-owned** — the panel does not expose a chip editor to users.
Chips survive renaming (they are stored on the task, not derived at render time) and
are included in every `home_keeper_task_*` event's payload under `task_chips`.

## 7. Discovery: announce yourself so users can find you (optional)

Everything above works without Home Keeper knowing your integration exists. But users
generally don't know two integrations work together until they stumble onto it. To
close that gap, Home Keeper has a **companion registry**: announce yourself and you'll
appear in the panel's **Settings → Companions** section, with a **Configure** button
that deep-links to your own integration page (`/config/integrations/integration/<your
domain>`, where your **Configure** is one click away — the same deep link Home Keeper
uses for "Edit in X"; there's no stable public URL to open an options *dialog*
directly).

Call the `home_keeper.register_companion` service at your setup (guarded so you degrade
gracefully when Home Keeper is absent), and again whenever Home Keeper asks companions
to re-announce — it fires `home_keeper_register_companions` at its own setup (and on
reload), which covers the case where Home Keeper starts *after* you:

```python
DOMAIN_HK = "home_keeper"

async def _announce(hass, entry):
    if not hass.services.has_service(DOMAIN_HK, "register_companion"):
        return
    await hass.services.async_call(
        DOMAIN_HK,
        "register_companion",
        {
            "domain": "my_integration",
            "name": "My Integration",
            "icon": "mdi:puzzle",
            "description": "One line on what it does with Home Keeper.",
            # Carried for the panel's "Configure" button (today it deep-links by
            # domain to your integration page; the entry id is stored for future use).
            "config_entry_id": entry.entry_id,
            "docs_url": "https://github.com/me/my-integration",
            "capabilities": ["whatever_you_provide"],
        },
        blocking=False,
    )

# In async_setup_entry:
await _announce(hass, entry)
entry.async_on_unload(
    hass.bus.async_listen("home_keeper_register_companions", lambda _e: hass.async_create_task(_announce(hass, entry)))
)
```

Home Keeper stores the descriptor **verbatim** and never imports your integration. The
registry is in-memory and best-effort: it survives Home Keeper config-entry reloads and
is rebuilt on restart as companions re-announce. Registering fires
`home_keeper_companion_connected` (edge-triggered) so automations can react.

> **Popular integrations that aren't Home-Keeper-aware.** Home Keeper also ships a tiny
> curated *catalog* so it can detect a popular upstream (e.g. Battery Notes) and
> **suggest** the glue that bridges it — even before that glue is installed. That path
> is for integrations Home Keeper can't expect to call `register_companion` themselves;
> if you're writing a Home-Keeper-aware integration, just register. The glue itself
> registers like any other companion once installed.

## Testing your integration

Home Keeper ships a fake so you can test the contract end-to-end **without** standing
up its panel, storage, or entities, and **without publishing anything to PyPI**. Add
Home Keeper as a git test dependency:

```
# requirements-test.txt (or your pyproject test extra)
home-keeper @ git+https://github.com/prestomation/ha-home-keeper@main
```

Then, in a real Home Assistant test environment (e.g.
`pytest-homeassistant-custom-component`):

```python
from home_keeper.testing import async_setup_fake_home_keeper

async def test_my_integration_two_way_sync(hass):
    hk = await async_setup_fake_home_keeper(hass)   # registers the real service names
    # ... set up your integration so it calls home_keeper.add_task ...

    task = hk.get_task_by_source("my_integration", thing_id="abc")
    assert task is not None                         # you created the task

    # Inbound: simulate a user checking the task off in Home Keeper (origin=None).
    hk.fire_user_completion(task["id"])
    await hass.async_block_till_done()
    # ... assert your integration mirrored the completion (and didn't loop) ...
```

`async_setup_fake_home_keeper` returns a `FakeHomeKeeper` with `.tasks`,
`.get_task_by_source(namespace, **match)`, and `.fire_user_completion(task_id)`. The
fake is built on Home Keeper's own model/recurrence code and the same event-payload
builder the real integration uses (`home_keeper.events.completion_event_data`), so it
can't drift from production. For the highest fidelity you can instead set up the real
Home Keeper config entry in your test `hass`; the fake is the lighter-weight default.

## Worked example: Pawsistant (one example client)

[Pawsistant](https://github.com/prestomation/pawsistant) (a pet-care logger) is the first
integration built on this contract — it is *one example*, not anything Home Keeper is
aware of. A user attaches a recurring schedule to a pet activity (e.g. "medicine every 2
weeks"):

1. Pawsistant calls `add_task` with `recurrence_type="floating"`, `interval=2`,
   `unit="weeks"`, the pet's `device_id`, and
   `source={"pawsistant": {"dog_id": …, "event_type": "medicine", "schedule_id": …}}`,
   and reads the `task_id` from the `add_task` response. If the pet already has a
   logged "medicine" event, Pawsistant passes its timestamp as `last_completed` so the
   first due date is measured from when it was actually last done; otherwise the task
   is due now.
2. **Complete in Home Keeper** (checkbox / device button) → `home_keeper_task_completed`
   fires with `origin=None`; Pawsistant logs a "medicine" event for that pet (writing
   straight to its store, so it doesn't re-complete the task).
3. **Log "medicine" in Pawsistant** → Pawsistant calls `complete_task` with
   `origin="pawsistant"`; the resulting event is ignored by its own listener.

The Home Keeper task and the Pawsistant care log thus behave as the same button, in both
directions, with no loop.
