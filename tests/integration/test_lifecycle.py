"""Integration tests against a real Home Assistant Docker container.

Verifies the seeded Home Keeper tasks produce the expected native entities, that
device-attached tasks get per-task device-page entities, and that completing /
adding tasks flows through the recurrence engine and updates entities.
"""

from conftest import call_service, get_state, list_states, poll_state


def test_todo_entity_exists_with_seeded_tasks(ha):
    state = get_state(ha, "todo.home_keeper_tasks")
    assert state is not None
    # State is the count of incomplete items; 4 seeded tasks are enabled.
    assert int(state["state"]) >= 1


def test_calendar_entity_exists(ha):
    assert get_state(ha, "calendar.home_keeper_upcoming_tasks") is not None


def test_device_attached_task_creates_per_task_entities(ha):
    states = list_states(ha)
    ids = [s["entity_id"] for s in states]
    # The seeded "water filter" task has a device_id, so it gets button + sensor +
    # binary_sensor entities.
    assert any(eid.startswith("button.") and "water_filter" in eid or
               eid == "button.replace_water_filter_mark_done" for eid in ids) or \
        any("mark_done" in eid for eid in ids)
    assert any("next_due" in eid for eid in ids)
    assert any("overdue" in eid for eid in ids)


def test_overdue_binary_sensor_is_on_for_overdue_task(ha):
    states = list_states(ha)
    overdue = [s for s in states if s["entity_id"].endswith("_overdue") or "overdue" in s["entity_id"]]
    assert overdue, "expected at least one overdue binary_sensor"
    # The seeded water filter is overdue.
    assert any(s["state"] == "on" for s in overdue)


def test_add_task_service_creates_task(ha):
    before = int(get_state(ha, "todo.home_keeper_tasks")["state"])
    call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Test clean gutters",
            "recurrence_type": "floating",
            "interval": 6,
            "unit": "months",
        },
    )
    poll_state(
        ha,
        "todo.home_keeper_tasks",
        lambda s: int(s) >= before + 1,
    )


def test_list_tasks_service_returns_response(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    # HA wraps service responses under "service_response".
    payload = resp.get("service_response", resp)
    assert "tasks" in payload
    assert isinstance(payload["tasks"], list)
    names = [t["name"] for t in payload["tasks"]]
    assert "Take medicine" in names
