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
    """The task mirroring SENSOR, or None — polled (sync runs after a reload).

    Tolerates the transient "No active coordinator" (HTTP 500) while the entry is
    mid-reload by simply retrying.
    """
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            for task in _list_tasks(ha):
                src = (task.get("source") or {}).get("problem_sensor")
                if src and src.get("entity_id") == SENSOR:
                    return task
        except Exception:
            pass
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


def test_synced_problem_task_note_is_editable_and_persists(ha):
    # Unlike completion, a synced problem task's *note* is user-editable — it's the
    # place to record what to remember next time this problem fires (there's no device
    # to model). update_task is not blocked by the synced-task guard.
    task = _synced_task(ha)
    assert task is not None
    note = "Reset the pump breaker in the garage panel, then prime it."
    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/update_task",
        json={"task_id": task["id"], "notes": note},
    )
    assert r.status_code < 400, (
        f"editing a synced task's note should be allowed, got {r.status_code}"
    )
    # The note round-trips on the same synced task (matched by sensor entity_id).
    deadline = time.monotonic() + 15
    again = None
    while time.monotonic() < deadline:
        again = _synced_task(ha)
        if again is not None and again.get("notes") == note:
            break
        time.sleep(1)
    assert again is not None and again["notes"] == note, (
        "note did not persist on the synced task"
    )


def test_synced_problem_task_has_hydrated_consumable_link(ha):
    # The seed links this sensor to the sump-pump appliance's spare float switch via the
    # durable `problem_consumables` side-store; the sync re-hydrates it onto the mirror,
    # so the task surfaces the spare part (where-to-buy + stock) despite the mirror being
    # runtime-created. Proves the decoupled link + hydration end to end.
    task = _synced_task(ha)
    assert task is not None
    assert task.get("consumable") == {
        "asset_id": "asset_sump_pump",
        "part_id": "part_float_switch",
    }, task.get("consumable")
    assert task.get("consume_on_clear") == "auto"


def test_synced_problem_task_consumable_is_editable_via_update_task(ha):
    # Like the note, the consumable link + its consume-on-clear mode are user-editable on
    # a synced task (not in locked_fields, not gated by the synced-task guard). Flip the
    # mode off through update_task and confirm it round-trips on the same mirror.
    task = _synced_task(ha)
    assert task is not None
    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/update_task",
        json={"task_id": task["id"], "consume_on_clear": "off"},
    )
    assert r.status_code < 400, f"editing consume_on_clear should be allowed, got {r.status_code}"
    deadline = time.monotonic() + 15
    again = None
    while time.monotonic() < deadline:
        again = _synced_task(ha)
        if again is not None and again.get("consume_on_clear") == "off":
            break
        time.sleep(1)
    assert again is not None and again.get("consume_on_clear") == "off", (
        "consume_on_clear did not persist on the synced task"
    )
    # The part link itself is untouched by a mode-only edit.
    assert again.get("consumable") == {
        "asset_id": "asset_sump_pump",
        "part_id": "part_float_switch",
    }
