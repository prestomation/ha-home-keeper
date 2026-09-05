"""Integration coverage for the declarative-companion reconciler (real HA container).

A declarative companion is a recipe, not a task. The reconciler reads the **entity
registry**, matches it against the recipe's filters, renders the Jinja name/notes
templates against live state, and materializes one managed sensor task per match.
Every part of that rests on a Home Assistant framework contract — the registry, the
template engine, the state machine, the dispatcher signal the store fires after a
spec write — so a unit test with plain dicts cannot see it. That is what this suite
covers (see AGENTS.md, "Anything resting on an HA framework contract").

The container config ships two template binary sensors this suite drives:

* ``binary_sensor.hk_demo_water_tank_low`` (device_class ``moisture``) follows
  ``input_boolean.hk_demo_flag``, so a test can make a real off -> on transition.
* ``binary_sensor.hk_demo_remote_battery`` (device_class ``battery``) is always
  ``on``, so a recipe that selects it meets its trigger condition from the start.

The config also ships one template update entity,
``update.hk_demo_router_firmware``, whose latest version differs from its installed
version. It is the only ``update`` entity in the container, so the shipped
**Firmware update available** preset matches it and nothing else.

None of the 3 has a device, so a task made from any of them owns no per-task entities
and the reconciler asks the coordinator for a refresh instead of reloading the entry.
The **device-backed** path matters just as much, and it is the harder one: a task with
per-task entities forces an entry reload, the reload re-runs setup, and setup
baselines the sensor watcher. ``sensor.e2e_battery_device_battery`` (the Battery
Notes stub's static 42%, on a real registry device) is what this suite points at for
that case.

Every spec this suite creates is removed again in the ``specs`` fixture: the
container's store is the committed seed fixture, so a leak is a permanent addition
to it.
"""

import importlib.util
import sys
import time
from pathlib import Path

import pytest
from conftest import HA_URL, call_service, poll_state

TANK = "binary_sensor.hk_demo_water_tank_low"
BATTERY = "binary_sensor.hk_demo_remote_battery"
FLAG = "input_boolean.hk_demo_flag"
# The one update entity in the container. The Firmware update available preset
# selects the whole ``update`` domain, so this is the only entity it can match.
FIRMWARE = "update.hk_demo_router_firmware"
# The one entity in the container that has a real device AND is not Home Keeper's own.
DEVICE_BATTERY = "sensor.e2e_battery_device_battery"

_ROOT = Path(__file__).resolve().parents[2]

# How long a reconcile pass may take to show up in the task list. The store fires a
# dispatcher signal, the reconciler schedules a task, and the coordinator refresh
# behind it is debounced, so none of this is synchronous with the service call.
SETTLE = 45


def _declarative_presets():
    """Load the shipped preset catalog straight from the component source.

    ``declarative_presets.py`` imports nothing but ``typing``, so it loads by path
    with no package dance. Reading it here rather than restating a preset means the
    test exercises what actually ships — the same defaults the panel's preset picker
    hands the Add dialog.
    """
    path = _ROOT / "custom_components" / "home_keeper" / "declarative_presets.py"
    spec = importlib.util.spec_from_file_location("hk_declarative_presets", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


declarative_presets = _declarative_presets()


# ── service helpers ──────────────────────────────────────────────────────────


def _list_tasks(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def _list_specs(ha):
    resp = call_service(
        ha, "home_keeper", "list_declarative_companions", {}, return_response=True
    )
    return resp.get("service_response", resp)["companions"]


def _add_spec(ha, spec):
    resp = call_service(
        ha, "home_keeper", "add_declarative_companion", spec, return_response=True
    )
    return resp.get("service_response", resp)["companion"]


def _update_spec(ha, spec_id, updates):
    resp = call_service(
        ha,
        "home_keeper",
        "update_declarative_companion",
        {"id": spec_id, **updates},
        return_response=True,
    )
    return resp.get("service_response", resp)["companion"]


def _delete_spec(ha, spec_id):
    call_service(ha, "home_keeper", "delete_declarative_companion", {"id": spec_id})


def _set_flag(ha, on):
    """Flip the helper, then wait for the template sensor to follow it.

    ``binary_sensor.hk_demo_water_tank_low`` is a template of the helper, so the
    service call returning does not mean the sensor has moved yet. Waiting here
    keeps "the tank is fine" a fact rather than a hope.
    """
    call_service(
        ha, "input_boolean", "turn_on" if on else "turn_off", {"entity_id": FLAG}
    )
    poll_state(ha, TANK, lambda state: state == ("on" if on else "off"))


# ── polling helpers ──────────────────────────────────────────────────────────


def _spec_tasks(ha, spec_id):
    """Every task the reconciler materialized for *spec_id*.

    Raises if the task list cannot be read. An unreadable list is not an empty
    list: swallowing the transient "No active coordinator" (HTTP 500) the entry
    answers with mid-reload would make every "the task is gone" assertion pass for
    the wrong reason. :func:`_poll_spec_tasks` retries instead.
    """
    found = []
    for task in _list_tasks(ha):
        src = (task.get("source") or {}).get("declarative_companion")
        if src and src.get("spec_id") == spec_id:
            found.append(task)
    return found


def _poll_spec_tasks(ha, spec_id, predicate, timeout=SETTLE):
    """Wait until the spec's task list satisfies *predicate*, then return it."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = _spec_tasks(ha, spec_id)
        except Exception:
            time.sleep(1)
            continue
        if predicate(last):
            return last
        time.sleep(1)
    raise AssertionError(
        f"tasks for spec {spec_id} never satisfied the predicate; last={last}"
    )


def _one_task(ha, spec_id, timeout=SETTLE):
    """Wait for the spec to materialize exactly one task, and return it."""
    return _poll_spec_tasks(ha, spec_id, lambda tasks: len(tasks) == 1, timeout)[0]


def _poll_task(ha, spec_id, predicate, timeout=SETTLE):
    """Wait until the spec's single task satisfies *predicate*, then return it."""
    tasks = _poll_spec_tasks(
        ha,
        spec_id,
        lambda found: len(found) == 1 and predicate(found[0]),
        timeout,
    )
    return tasks[0]


def _let_the_watcher_subscribe():
    """Give the sensor watcher time to point its listener at the new task's entity.

    The watcher re-subscribes at the start of each evaluation, and the evaluation
    runs on a coordinator refresh. The reconciler requests that refresh, but the
    request is debounced, so a flag flip made the instant the task appears can land
    before the subscription exists — and then only the five-minute tick would see
    it. Waiting here keeps the arm a fact about the watcher, not about timing.
    """
    time.sleep(5)


# ── spec bodies ──────────────────────────────────────────────────────────────


def _tank_spec(**overrides):
    """A ``state``-mode recipe that matches the one moisture sensor in the config."""
    spec = {
        "name": "Water tank",
        "description": "One task per water-tank sensor",
        "selection": {"domain": "binary_sensor", "device_class": "moisture"},
        "trigger": {"mode": "state", "state": "on", "clear_on_recover": True},
        "task_template": {
            "name_template": "Fill {{ friendly_name }}",
            "notes_template": "Reported by {{ entity_id }}.",
        },
    }
    spec.update(overrides)
    return spec


def _battery_spec(**overrides):
    """A ``state``-mode recipe that matches the one battery sensor in the config.

    ``binary_sensor.hk_demo_remote_battery`` is already ``on`` when the recipe is
    added, so this recipe covers the case where the trigger condition holds from
    the first evaluation. The sensor has no device.
    """
    spec = {
        "name": "Remote battery",
        "description": "One task per low battery sensor",
        "selection": {"domain": "binary_sensor", "device_class": "battery"},
        "trigger": {"mode": "state", "state": "on", "clear_on_recover": True},
        "task_template": {
            "name_template": "Replace {{ device_name or friendly_name }} battery",
            "notes_template": "",
        },
    }
    spec.update(overrides)
    return spec


def _device_battery_spec(**overrides):
    """A ``threshold`` recipe matching the one device-backed sensor in the config.

    The sensor reads a static 42%, so the condition (``<= 50``) is **already true**
    when the recipe is added. The task it makes carries the sensor's device, which is
    what forces the entry reload the arming tests below are about.
    """
    spec = {
        "name": "Device battery",
        "description": "One task per device battery below half",
        "selection": {
            "domain": "sensor",
            "target_integration": "home_keeper_battery_notes",
        },
        "trigger": {"mode": "threshold", "comparison": "<=", "value": 50},
        "task_template": {
            "name_template": "Change the {{ device_name }} battery",
            "notes_template": "{{ friendly_name }} reads {{ state }}%.",
        },
    }
    spec.update(overrides)
    return spec


def _reload_entry(ha):
    """Reload the Home Keeper config entry — the code path an HA restart takes."""
    call_service(
        ha,
        "homeassistant",
        "reload_config_entry",
        {"entity_id": "todo.home_keeper_tasks"},
    )


@pytest.fixture
def specs(ha):
    """Create declarative-companion specs and remove every one of them afterwards.

    The container's store is the committed seed fixture, so a spec left behind
    becomes part of it. Deleting the spec also deletes the tasks it materialized,
    which is the only way to remove them: they are deletion-protected.
    """
    created = []

    def _create(spec):
        stored = _add_spec(ha, spec)
        created.append(stored["id"])
        return stored

    yield _create

    for spec_id in reversed(created):
        try:
            _delete_spec(ha, spec_id)
        except Exception:
            pass
    _set_flag(ha, False)


# ── (a) materialization ──────────────────────────────────────────────────────


def test_a_state_recipe_materializes_one_managed_task_per_matching_entity(ha, specs):
    """The recipe reaches the registry, renders its templates, and owns the result."""
    _set_flag(ha, False)
    spec = specs(_tank_spec())
    task = _one_task(ha, spec["id"])

    # Rendered from the live entity, not copied from the template source.
    assert task["name"] == "Fill HK demo water tank low"
    assert task["notes"] == f"Reported by {TANK}."

    # Provenance: which recipe made it, and which registry entry it follows.
    src = task["source"]["declarative_companion"]
    assert src["spec_id"] == spec["id"]
    assert src["entity_id"] == TANK
    assert src["entity_registry_id"]

    # It is an ordinary sensor task, so the existing watcher can arm it.
    assert task["recurrence_type"] == "sensor"
    assert task["sensor"]["entity_id"] == TANK
    assert task["sensor"]["mode"] == "state"
    assert task["sensor"]["state"] == "on"
    assert task["sensor"]["clear_on_recover"] is True

    # Ownership: Home Keeper made it, the reconciler rewrites these fields, and a
    # user may complete it but may not delete it.
    managed_by = task["managed_by"]
    assert managed_by["integration"] == "home_keeper"
    assert managed_by["display_name"] == "Water tank"
    assert managed_by["deletion_protected"] is True
    assert managed_by["completion_blocked"] is False
    assert "name" in managed_by["locked_fields"]

    # Born dormant: the tank is fine, so there is nothing to do yet.
    assert task["next_due"] is None


def test_a_materialized_task_cannot_be_deleted_by_hand(ha, specs):
    """Deletion protection holds while Home Keeper is loaded (the spec owns it)."""
    _set_flag(ha, False)
    spec = specs(_tank_spec())
    task = _one_task(ha, spec["id"])

    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/delete_task",
        json={"task_id": task["id"]},
    )
    assert r.status_code >= 400, (
        "a declarative-companion task should be deletion-protected, "
        f"got {r.status_code}"
    )
    assert len(_spec_tasks(ha, spec["id"])) == 1


# ── (b) arm and clear ────────────────────────────────────────────────────────


def test_the_bound_sensor_arms_the_task_and_recovery_clears_it(ha, specs):
    """A real state change drives the materialized task, like any sensor task."""
    _set_flag(ha, False)
    spec = specs(_tank_spec())
    task = _one_task(ha, spec["id"])
    assert task["next_due"] is None
    _let_the_watcher_subscribe()

    # The tank empties: a genuine off -> on crossing arms the task.
    _set_flag(ha, True)
    armed = _poll_task(ha, spec["id"], lambda t: t.get("next_due") is not None)
    assert armed["id"] == task["id"], "arming must not replace the task"

    # Somebody fills it. ``clear_on_recover`` completes the task itself and records
    # a real completion, so the work still shows in history.
    _set_flag(ha, False)
    cleared = _poll_task(ha, spec["id"], lambda t: t.get("next_due") is None)
    assert cleared["last_completed"] is not None
    assert len(cleared["completions"]) == 1


def test_the_notes_are_rendered_again_from_the_reading_that_armed_the_task(ha, specs):
    """The note must describe the reading that armed the task, not an older one.

    Notes are rendered by the reconcile pass, which runs on registry changes — not on
    state changes. A note that quotes the entity ("{{ state }} hours left") therefore
    froze at whatever the entity read when the task was made. The watcher re-renders
    it on the arm transition, so the note a person opens matches the reason it is
    there.
    """
    _set_flag(ha, False)
    spec = specs(
        _tank_spec(
            name="Water tank reading",
            task_template={
                "name_template": "Fill {{ friendly_name }}",
                "notes_template": "{{ entity_id }} reads {{ state }}.",
            },
        )
    )
    task = _one_task(ha, spec["id"])
    assert task["notes"] == f"{TANK} reads off."
    _let_the_watcher_subscribe()

    _set_flag(ha, True)
    armed = _poll_task(ha, spec["id"], lambda t: t.get("next_due") is not None)
    assert armed["notes"] == f"{TANK} reads on.", (
        "the note still quotes the reading from creation time"
    )


def test_a_device_backed_recipe_arms_on_a_condition_that_is_already_true(ha, specs):
    """A recipe made for a condition standing right now must arm, device or not.

    This is the case the device-less tests above cannot see. The battery reads 42%,
    the recipe wants ``<= 50``, and the task it makes owns per-task entities — so the
    reconciler reloads the entry, the reload re-runs setup, and setup calls
    ``SensorTaskWatcher.async_baseline``. That pass records every already-matching
    sensor task as met-without-a-crossing, which is right after a restart and wrong
    for a task made a second ago: it would eat the rising edge and leave the task
    dormant until the battery recovered and dropped again.

    The reconciler therefore names the ids it materialized
    (``sensor_watcher.async_mark_tasks_new``, held on ``hass.data`` so it survives the
    reload) and the baseline leaves their edge unset. The first evaluation then reads
    the standing 42% as a fresh crossing and arms.
    """
    spec = specs(_device_battery_spec())
    task = _one_task(ha, spec["id"])
    assert task["source"]["declarative_companion"]["entity_id"] == DEVICE_BATTERY
    assert task["device_id"], (
        "the whole point of this test is the device-backed reload path; "
        "without a device the reconciler never reloads"
    )

    armed = _poll_task(ha, spec["id"], lambda t: t.get("next_due") is not None)
    assert armed["id"] == task["id"], "arming must not replace the task"


def test_a_task_that_survived_a_reload_stays_dormant_while_the_sensor_is_still_met(
    ha, specs
):
    """The rule the fix above must not break, on the same device-backed task.

    Once a task exists, an already-true condition at setup is history the user has
    dealt with: the battery is still 42% after every reload, and a task completed at
    42% must not come back each time Home Assistant restarts. Only the pass that
    *made* the task skips the baseline, and the set of just-made ids is consumed by
    the first baseline that reads it — so the second reload gets the ordinary
    treatment.

    ``test_sensor_watcher.test_a_reload_with_the_sensor_already_on_does_not_rearm``
    pins the same rule for a hand-made sensor task.
    """
    spec = specs(_device_battery_spec(name="Device battery (reload)"))
    task = _one_task(ha, spec["id"])
    _poll_task(ha, spec["id"], lambda t: t.get("next_due") is not None)

    # Somebody changes the battery. The sensor is a stub and stays at 42%.
    call_service(ha, "home_keeper", "complete_task", {"task_id": task["id"]})
    _poll_task(ha, spec["id"], lambda t: t.get("next_due") is None)

    _reload_entry(ha)
    time.sleep(20)
    after = _poll_task(ha, spec["id"], lambda t: t["id"] == task["id"])
    assert after["next_due"] is None, (
        "a reload with the sensor still below the threshold must not re-arm a task "
        "the user already dealt with"
    )


# ── (c) re-selection ─────────────────────────────────────────────────────────


def test_narrowing_the_selection_removes_the_task_and_widening_makes_a_new_one(
    ha, specs
):
    """The match set is the task set — and losing a match is a delete, not a pause.

    Widening again re-creates the task, but it is a **fresh** task: the orphan pass
    deletes, it does not tombstone, so completions recorded before the narrowing do
    not come back. Narrowing a live recipe therefore throws history away, which is
    what this pins.
    """
    _set_flag(ha, False)
    spec = specs(_tank_spec())
    first = _one_task(ha, spec["id"])

    # Record a completion so the history has something to lose.
    call_service(ha, "home_keeper", "complete_task", {"task_id": first["id"]})
    _poll_task(ha, spec["id"], lambda t: len(t.get("completions") or []) == 1)

    # Narrow: exclude the only entity that matched. The task is orphaned and gone.
    _update_spec(
        ha,
        spec["id"],
        {
            "selection": {
                "domain": "binary_sensor",
                "device_class": "moisture",
                "exclude_entity_ids": [TANK],
            }
        },
    )
    _poll_spec_tasks(ha, spec["id"], lambda tasks: tasks == [])

    # Widen back: the entity matches again, so the recipe materializes it again.
    _update_spec(
        ha,
        spec["id"],
        {"selection": {"domain": "binary_sensor", "device_class": "moisture"}},
    )
    second = _one_task(ha, spec["id"])
    assert second["id"] != first["id"], "the re-created task is a new task"
    assert second["completions"] == []
    assert second["last_completed"] is None
    assert second["name"] == "Fill HK demo water tank low"


def test_disabling_the_spec_drops_its_tasks_and_enabling_brings_them_back(ha, specs):
    """``enabled: false`` cleans up without deleting the recipe."""
    _set_flag(ha, False)
    spec = specs(_tank_spec())
    _one_task(ha, spec["id"])

    _update_spec(ha, spec["id"], {"enabled": False})
    _poll_spec_tasks(ha, spec["id"], lambda tasks: tasks == [])
    stored = [s for s in _list_specs(ha) if s["id"] == spec["id"]]
    assert stored and stored[0]["enabled"] is False, "the recipe itself must survive"

    _update_spec(ha, spec["id"], {"enabled": True})
    _one_task(ha, spec["id"])


# ── (d) deletion ─────────────────────────────────────────────────────────────


def test_deleting_the_spec_removes_the_recipe_and_every_task_it_made(ha, specs):
    _set_flag(ha, False)
    spec = specs(_tank_spec())
    _one_task(ha, spec["id"])

    _delete_spec(ha, spec["id"])

    _poll_spec_tasks(ha, spec["id"], lambda tasks: tasks == [])
    assert all(s["id"] != spec["id"] for s in _list_specs(ha))


# ── (e) already-true conditions, and a shipped preset ────────────────────────


def test_a_battery_recipe_materializes_and_arms_on_the_battery_sensor(ha, specs):
    """A ``state`` recipe on a live registry, on a sensor that is already ``on``.

    ``binary_sensor.hk_demo_remote_battery`` is already ``on`` when the recipe is
    added, and the task **arms**. The sensor has no device, so this recipe never
    reloads the entry and the first evaluation reads the standing ``on`` as a fresh
    crossing. ``test_a_device_backed_recipe_arms_on_a_condition_that_is_already_true``
    covers the harder path, where the reload runs the baseline in between.

    The other half of the same rule is covered by
    ``test_a_task_that_survived_a_reload_stays_dormant_while_the_sensor_is_still_met``
    and by ``test_sensor_watcher``'s
    ``test_a_reload_with_the_sensor_already_on_does_not_rearm``: once a task exists,
    a battery that is still low does not resurrect it.
    """
    spec = specs(_battery_spec())

    task = _one_task(ha, spec["id"])
    src = task["source"]["declarative_companion"]
    assert src["entity_id"] == BATTERY
    # The sensor has no device, so ``{{ device_name or friendly_name }}`` falls back.
    assert "HK demo remote battery" in task["name"]
    assert task["sensor"] == {
        "entity_id": BATTERY,
        "mode": "state",
        "state": "on",
        "clear_on_recover": True,
    }

    armed = _poll_task(ha, spec["id"], lambda t: t.get("next_due") is not None)
    assert armed["id"] == task["id"]


def test_a_shipped_preset_installs_and_materializes_as_the_picker_installs_it(
    ha, specs
):
    """A catalog preset's ``default_spec``, saved unchanged, reaches a real task.

    This is the one test that installs a **shipped** preset the way the panel's
    picker does. It reads ``default_spec`` from the catalog and hands it straight to
    ``add_declarative_companion``. A default_spec whose selection matches nothing, or
    whose trigger the store rejects, fails here instead of shipping green.

    ``test_every_preset_normalizes`` already runs every shipped default_spec through
    ``normalize_declarative_companion``, and so through ``normalize_sensor``. This
    test covers the other half: the recipe materializes a task on a live registry,
    and the task arms.

    ``update.hk_demo_router_firmware`` is the one update entity in the container. It
    reports ``on`` from the start, because its latest version differs from its
    installed version.
    """
    preset = declarative_presets.preset_by_id("firmware_update_available")
    assert preset is not None, "the firmware_update_available preset must ship"
    spec = specs(dict(preset["default_spec"]))
    assert spec["preset_id"] == "firmware_update_available"

    task = _one_task(ha, spec["id"])
    src = task["source"]["declarative_companion"]
    assert src["entity_id"] == FIRMWARE
    # What the preset's own ``name_template`` renders for this entity.
    assert task["name"] == "Update HK demo router firmware"
    assert task["sensor"] == {
        "entity_id": FIRMWARE,
        "mode": "state",
        "state": "on",
        "clear_on_recover": True,
    }

    armed = _poll_task(ha, spec["id"], lambda t: t.get("next_due") is not None)
    assert armed["id"] == task["id"]
