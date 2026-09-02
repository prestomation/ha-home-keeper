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
  ``on``, which is what the shipped **Low battery** preset matches.

Neither sensor has a device, so a materialized task owns no per-task entities. The
reconciler therefore asks the coordinator for a refresh instead of reloading the
entry — which is why the arming semantics below are the runtime ones, not the
after-a-restart ones.

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
        f"a declarative-companion task should be deletion-protected, got {r.status_code}"
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


# ── (e) the shipped Low battery preset ───────────────────────────────────────


def test_the_low_battery_preset_materializes_and_arms_on_the_battery_sensor(ha, specs):
    """The shipped preset, installed as the panel installs it, on a live registry.

    ``binary_sensor.hk_demo_remote_battery`` is already ``on`` when the recipe is
    added, and the task **arms**. That is the runtime path, and it is deliberate:
    ``SensorTaskWatcher.async_baseline`` records "already met, no crossing" once
    during setup, so it can only cover tasks that exist by then. A task the
    reconciler materializes afterwards carries no edge state, so the first
    evaluation reads the standing ``on`` as a fresh false -> true crossing and arms
    it — which is what a user adding a low-battery recipe wants to see.

    The other half of the same rule is covered by
    ``test_sensor_watcher.test_a_reload_with_the_sensor_already_on_does_not_rearm``:
    after a restart the baseline runs *after* the reconciler, so a battery that is
    still low does not resurrect a task the user already dealt with.
    """
    preset = declarative_presets.preset_by_id("low_battery")
    assert preset is not None, "the low_battery preset must ship"
    spec = specs(dict(preset["default_spec"]))
    assert spec["preset_id"] == "low_battery"

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
