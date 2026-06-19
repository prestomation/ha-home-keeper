"""Integration coverage for the problem-sensor → task sync (real HA container).

The test config enables ``sync_problem_sensors`` on the Home Keeper entry and ships
a ``device_class: problem`` template binary sensor (``binary_sensor.sump_pump_problem``,
kept on). So Home Keeper should mirror it as an armed, un-completable triggered task.
"""

import time

from conftest import HA_URL, call_service

SENSOR = "binary_sensor.sump_pump_problem"


def _list_tasks(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def _synced_task(ha):
    """The task mirroring SENSOR, or None — polled (sync runs after a reload)."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        for task in _list_tasks(ha):
            src = (task.get("source") or {}).get("problem_sensor")
            if src and src.get("entity_id") == SENSOR:
                return task
        time.sleep(1)
    return None


def test_problem_sensor_is_mirrored_as_an_armed_managed_task(ha):
    task = _synced_task(ha)
    assert task is not None, "expected a synced task for the problem binary sensor"
    assert task["recurrence_type"] == "triggered"
    # The sensor is on (problem active), so the task is armed (due now), not dormant.
    assert task["next_due"] is not None
    mb = task.get("managed_by") or {}
    assert mb.get("completion_blocked") is True
    assert mb.get("deletion_protected") is True


def test_synced_problem_task_cannot_be_completed(ha):
    task = _synced_task(ha)
    assert task is not None
    # complete_task is rejected: the problem must be resolved in the originating
    # integration (the sensor returns to OK), not marked done in Home Keeper.
    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/complete_task",
        json={"task_id": task["id"]},
    )
    assert r.status_code >= 400, (
        f"completing a synced problem task should be rejected, got {r.status_code}"
    )
