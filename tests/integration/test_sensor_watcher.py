"""Integration coverage for sensor-based tasks (real HA container).

Exercises the HA-aware sensor watcher end to end: a sensor task bound to the
``input_number.hk_demo_meter`` helper is armed by Home Keeper when the helper's
value crosses the task's condition (a threshold crossing, or a usage meter passing
its target), and cleared again when the task is completed. Driving a real
``input_number`` produces genuine state-change events, so this covers the watcher's
subscription + evaluation path that the pure unit tests can't.
"""

import time

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
