"""Integration coverage for sensor-based tasks (real HA container).

Exercises the HA-aware sensor watcher end to end: a sensor task bound to the
``input_number.hk_demo_meter`` helper is armed by Home Keeper when the helper's
value crosses the task's condition (a threshold crossing, or a usage meter passing
its target), and cleared again when the task is completed. Driving a real
``input_number`` produces genuine state-change events, so this covers the watcher's
subscription + evaluation path that the pure unit tests can't.
"""

import time
from datetime import UTC, datetime, timedelta

from conftest import HA_URL, call_service

METER = "input_number.hk_demo_meter"


def _list_tasks(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def _set_meter(ha, value):
    call_service(ha, "input_number", "set_value", {"entity_id": METER, "value": value})


def _add_sensor_task(ha, sensor):
    resp = call_service(
        ha,
        "home_keeper",
        "add_task",
        {"name": "Sensor watcher test", "recurrence_type": "sensor", "sensor": sensor},
        return_response=True,
    )
    return resp.get("service_response", resp)["task_id"]


def _get_task(ha, task_id):
    """Return the task dict by id, tolerating transient mid-reload 500s."""
    try:
        for task in _list_tasks(ha):
            if task.get("id") == task_id:
                return task
    except Exception:
        pass
    return None


def _poll_task(ha, task_id, predicate, timeout=40):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = _get_task(ha, task_id)
        if last is not None and predicate(last):
            return last
        time.sleep(1)
    raise AssertionError(f"task {task_id} never satisfied predicate; last={last}")


def _delete(ha, task_id):
    try:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})
    except Exception:
        pass


def test_usage_sensor_task_arms_when_meter_advances(ha):
    # Anchor the meter, then create a usage task with target 50 so its baseline is
    # stamped at the current reading on setup.
    _set_meter(ha, 1000)
    task_id = _add_sensor_task(ha, {"entity_id": METER, "mode": "usage", "target": 50})
    try:
        # Born dormant (the meter hasn't advanced past the baseline yet).
        task = _poll_task(
            ha, task_id, lambda t: t.get("sensor", {}).get("baseline") is not None
        )
        assert task["recurrence_type"] == "sensor"
        assert task["next_due"] is None

        # Advance the meter past the target -> the watcher arms the task.
        _set_meter(ha, 1100)
        armed = _poll_task(ha, task_id, lambda t: t.get("next_due") is not None)
        assert armed["next_due"] is not None

        # Completing it clears the task and resets the meter baseline to "now".
        call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
        cleared = _poll_task(ha, task_id, lambda t: t.get("next_due") is None)
        assert cleared["sensor"]["baseline"] == 1100
    finally:
        _delete(ha, task_id)


def test_threshold_sensor_task_arms_on_crossing(ha):
    # Start below the threshold so the task is created with the condition false.
    _set_meter(ha, 10)
    task_id = _add_sensor_task(
        ha, {"entity_id": METER, "mode": "threshold", "comparison": ">", "value": 50}
    )
    try:
        task = _poll_task(ha, task_id, lambda t: t.get("recurrence_type") == "sensor")
        assert task["next_due"] is None  # condition not yet met

        # Cross the threshold -> rising edge arms the task.
        _set_meter(ha, 100)
        armed = _poll_task(ha, task_id, lambda t: t.get("next_due") is not None)
        assert armed["next_due"] is not None

        # A user completion clears it back to dormant.
        call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
        cleared = _poll_task(ha, task_id, lambda t: t.get("next_due") is None)
        assert cleared["next_due"] is None
    finally:
        _delete(ha, task_id)
        _set_meter(ha, 0)


def test_sensor_task_completable_unlike_problem_sync(ha):
    # Unlike a synced problem task, a sensor task is user-completable (no managed_by
    # completion block) — completing it must succeed, not 4xx.
    _set_meter(ha, 0)
    task_id = _add_sensor_task(
        ha, {"entity_id": METER, "mode": "threshold", "comparison": ">=", "value": 0}
    )
    try:
        _poll_task(ha, task_id, lambda t: t.get("recurrence_type") == "sensor")
        r = ha.post(
            f"{HA_URL}/api/services/home_keeper/complete_task",
            json={"task_id": task_id},
        )
        assert r.status_code < 400, (
            f"sensor task should be completable, got {r.status_code}"
        )
    finally:
        _delete(ha, task_id)


def _add_backstop_task(ha, *, target, also_every, combinator, last_completed=None):
    payload = {
        "name": "Backstop test",
        "recurrence_type": "sensor",
        "sensor": {
            "entity_id": METER,
            "mode": "usage",
            "target": target,
            "unit": "h",
            "also_every": also_every,
            "combinator": combinator,
        },
    }
    if last_completed:
        payload["last_completed"] = last_completed
    resp = call_service(ha, "home_keeper", "add_task", payload, return_response=True)
    return resp.get("service_response", resp)["task_id"]


def test_time_backstop_arms_without_the_meter_moving(ha):
    # Seed "last serviced two days ago" against a one-day backstop, so the calendar
    # half is already elapsed at creation. The meter never advances: only the time
    # half can arm this task.
    _set_meter(ha, 500)
    stale = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    task_id = _add_backstop_task(
        ha,
        target=100000,  # unreachable by the meter within the test
        also_every={"interval": 1, "unit": "days"},
        combinator="any",
        last_completed=stale,
    )
    try:
        # Two nudges, both far below target. A usage task created *after* Home Keeper
        # started has no meter baseline yet — the first evaluation of the bound sensor
        # stamps it (and does nothing else), so it takes a second state change to reach
        # the arming branch. Neither nudge comes close to the target, so if the task
        # arms it can only be the backstop that did it.
        _set_meter(ha, 501)
        _poll_task(ha, task_id, lambda t: t.get("sensor", {}).get("baseline") == 501)
        _set_meter(ha, 502)
        armed = _poll_task(ha, task_id, lambda t: t.get("next_due") is not None)
        assert armed["sensor"]["also_every"] == {"interval": 1, "unit": "days"}
        assert armed["sensor"]["unit"] == "h"

        # Completing it re-anchors both halves: dormant again, baseline at the reading.
        call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
        cleared = _poll_task(ha, task_id, lambda t: t.get("next_due") is None)
        assert cleared["sensor"]["baseline"] == 502
    finally:
        _delete(ha, task_id)
        _set_meter(ha, 0)


def test_combinator_all_holds_the_task_until_both_halves_are_met(ha):
    # Meter target is trivially reachable, but the calendar half is a year out, so
    # "both must be met" keeps it dormant.
    _set_meter(ha, 0)
    task_id = _add_backstop_task(
        ha,
        target=10,
        also_every={"interval": 12, "unit": "months"},
        combinator="all",
    )
    try:
        _poll_task(
            ha, task_id, lambda t: t.get("sensor", {}).get("baseline") is not None
        )
        _set_meter(ha, 100)  # meter half satisfied several times over
        # Give the watcher time to see it and (correctly) do nothing.
        time.sleep(5)
        task = _get_task(ha, task_id)
        assert task is not None and task["next_due"] is None, (
            "combinator 'all' must not arm on the meter alone"
        )
    finally:
        _delete(ha, task_id)
        _set_meter(ha, 0)


def test_set_task_meter_reanchors_without_recording_a_completion(ha):
    _set_meter(ha, 1000)
    task_id = _add_sensor_task(ha, {"entity_id": METER, "mode": "usage", "target": 50})
    try:
        _poll_task(ha, task_id, lambda t: t.get("sensor", {}).get("baseline") == 1000)
        # Re-anchor explicitly (as if the work was done before Home Keeper watched).
        call_service(
            ha, "home_keeper", "set_task_meter", {"task_id": task_id, "baseline": 900}
        )
        moved = _poll_task(ha, task_id, lambda t: t["sensor"].get("baseline") == 900)
        assert moved["completions"] == []  # no completion was recorded
        assert moved["last_completed"] is None

        # Omitting the baseline anchors to the sensor's live reading instead.
        call_service(ha, "home_keeper", "set_task_meter", {"task_id": task_id})
        live = _poll_task(ha, task_id, lambda t: t["sensor"].get("baseline") == 1000)
        assert live["completions"] == []
    finally:
        _delete(ha, task_id)
        _set_meter(ha, 0)


def _a_seeded_device_id(ha):
    """A device_id from a seeded task, so ours can own per-task entities.

    Home Keeper creates the per-task ``sensor.*_next_due`` entity only for a
    device-attached task (``coordinator.task_has_entities``), which is where the usage
    attributes ride. Rather than hard-code a registry id, reuse whatever device the
    seeded fixtures already attached a task to.
    """
    for task in _list_tasks(ha):
        if task.get("device_id"):
            return task["device_id"]
    raise AssertionError("no seeded device-attached task to borrow a device from")


def test_usage_progress_attributes_land_on_the_next_due_sensor(ha):
    _set_meter(ha, 1000)
    device_id = _a_seeded_device_id(ha)
    resp = call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Usage attributes test",
            "recurrence_type": "sensor",
            "device_id": device_id,
            "sensor": {
                "entity_id": METER,
                "mode": "usage",
                "target": 200,
                "unit": "h",
                "also_every": {"interval": 6, "unit": "months"},
                "combinator": "any",
            },
        },
        return_response=True,
    )
    task_id = resp.get("service_response", resp)["task_id"]
    try:
        _poll_task(ha, task_id, lambda t: t.get("sensor", {}).get("baseline") == 1000)
        _set_meter(ha, 1050)  # 50 of 200 used

        def _attrs():
            for state in ha.get(f"{HA_URL}/api/states").json():
                attrs = state.get("attributes", {})
                if attrs.get("task_id") == task_id and state["entity_id"].startswith(
                    "sensor."
                ):
                    return attrs
            return None

        deadline = time.monotonic() + 60
        attrs = None
        while time.monotonic() < deadline:
            attrs = _attrs()
            if attrs and attrs.get("usage_consumed") == 50:
                break
            time.sleep(1)
        assert attrs is not None, "no next-due sensor found for the task"
        assert attrs["usage_target"] == 200
        assert attrs["usage_consumed"] == 50
        assert attrs["usage_remaining"] == 150
        assert attrs["usage_percent"] == 25.0
        assert attrs["usage_unit"] == "h"
        assert attrs["backstop_due"]  # a real projected timestamp
    finally:
        _delete(ha, task_id)
        _set_meter(ha, 0)
