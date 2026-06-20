"""Integration coverage for the Home Keeper conversation/voice intents.

Drives the real HA ``/api/intent/handle`` endpoint (enabled via ``intent:`` in the
test config) so the registered intent handlers run end-to-end against the live store:
completing a task by name advances its recurrence and fires
``home_keeper_task_completed`` with ``origin=home_keeper_intent`` (asserted via the
configuration.yaml automation), ambiguous/unknown names are reported without
mutating anything, a problem-sensor-synced task is rejected with a spoken reason,
the due-task query reads back armed tasks, and the handlers survive an entry reload.

The sentence -> intent NLU layer is covered separately and deterministically by the
hassil unit test (tests/unit/test_intent_sentences.py).
"""

import time

from conftest import HA_URL, call_service, get_state, poll_state

SENSOR = "binary_sensor.sump_pump_problem"
ORIGIN_INTENT = "home_keeper_intent"


def _handle(ha, intent_name, data):
    r = ha.post(
        f"{HA_URL}/api/intent/handle",
        json={"name": intent_name, "data": data},
    )
    r.raise_for_status()
    return r.json()


def _speech(resp):
    return resp.get("speech", {}).get("plain", {}).get("speech", "")


def _list_tasks(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def _add_task(ha, name, **extra):
    data = {
        "name": name,
        "recurrence_type": "floating",
        "interval": 7,
        "unit": "days",
        **extra,
    }
    resp = call_service(ha, "home_keeper", "add_task", data, return_response=True)
    return resp.get("service_response", resp)["task_id"]


def _get_task(ha, task_id):
    return next((t for t in _list_tasks(ha) if t["id"] == task_id), None)


def _synced_task(ha):
    """The triggered task mirroring the problem sensor, polled (sync is async)."""
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


def test_complete_task_by_name_via_intent(ha):
    task_id = _add_task(ha, "Vacuum the stairs")
    resp = _handle(ha, "HomeKeeperCompleteTask", {"name": "vacuum the stairs"})
    assert "completed" in _speech(resp).lower()

    # The completion went through store.complete_task with the intent origin marker
    # (captured by the configuration.yaml automation into an input_text).
    origin = poll_state(
        ha,
        "input_text.hk_last_completed_origin",
        lambda s: s == ORIGIN_INTENT,
    )
    assert origin == ORIGIN_INTENT
    # ...and the recurrence advanced.
    assert _get_task(ha, task_id)["last_completed"] is not None


def test_unknown_task_name_is_reported(ha):
    resp = _handle(ha, "HomeKeeperCompleteTask", {"name": "fly to the moon"})
    assert "couldn't find" in _speech(resp).lower()


def test_ambiguous_name_asks_to_disambiguate(ha):
    _add_task(ha, "Clean upstairs windows")
    _add_task(ha, "Clean downstairs windows")
    before = get_state(ha, "input_text.hk_last_completed_origin")
    before_val = before["state"] if before else None

    resp = _handle(ha, "HomeKeeperCompleteTask", {"name": "clean windows"})
    speech = _speech(resp).lower()
    assert "more than one" in speech
    assert "upstairs windows" in speech and "downstairs windows" in speech

    # Nothing was completed, so the captured-origin marker is unchanged.
    time.sleep(1)
    after = get_state(ha, "input_text.hk_last_completed_origin")
    assert (after["state"] if after else None) == before_val


def test_synced_problem_task_rejected_via_intent(ha):
    task = _synced_task(ha)
    assert task is not None, "expected a synced task for the problem binary sensor"
    resp = _handle(ha, "HomeKeeperCompleteTask", {"name": task["name"]})
    speech = _speech(resp).lower()
    assert "can't be cleared" in speech or "originating integration" in speech


def test_list_due_tasks_via_intent(ha):
    # A floating task last done long ago is overdue, so it must show up as due.
    _add_task(ha, "Descale the kettle", last_completed="2020-01-01T09:00:00-05:00")
    resp = _handle(ha, "HomeKeeperListDueTasks", {})
    speech = _speech(resp).lower()
    assert "due" in speech
    assert "descale the kettle" in speech


def test_intents_survive_entry_reload(ha):
    task_id = _add_task(ha, "Water the ferns")
    # set_options awaits its own entry reload, which re-runs async_setup_entry and
    # re-registers the intents. Firing afterwards proves registration is reload-safe.
    call_service(ha, "home_keeper", "set_options", {"sync_problem_sensors": True})
    resp = _handle(ha, "HomeKeeperCompleteTask", {"name": "water the ferns"})
    assert "completed" in _speech(resp).lower()
    assert _get_task(ha, task_id)["last_completed"] is not None
