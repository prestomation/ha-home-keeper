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
| Learn the new task's id | Read `task_id` from `add_task`'s response (`return_response=True`) |
| React when a task is completed | Subscribe to the `home_keeper_task_completed` event |
| Complete a task from your side | Call `home_keeper.complete_task` with a unique `origin` |
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
   and reads the `task_id` from the `add_task` response.
2. **Complete in Home Keeper** (checkbox / device button) → `home_keeper_task_completed`
   fires with `origin=None`; Pawsistant logs a "medicine" event for that pet (writing
   straight to its store, so it doesn't re-complete the task).
3. **Log "medicine" in Pawsistant** → Pawsistant calls `complete_task` with
   `origin="pawsistant"`; the resulting event is ignored by its own listener.

The Home Keeper task and the Pawsistant care log thus behave as the same button, in both
directions, with no loop.
