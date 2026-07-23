"""Integration tests against a real Home Assistant Docker container.

Verifies the seeded Home Keeper tasks produce the expected native entities, that
device-attached tasks get per-task device-page entities, and that completing /
adding tasks flows through the recurrence engine and updates entities.
"""

import json
import time

import websockets.sync.client
from conftest import HA_URL, call_service, get_state, list_states, poll_state

_WS_URL = HA_URL.replace("http://", "ws://") + "/api/websocket"


def _list_tasks(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def test_todo_entity_exists_with_seeded_tasks(ha):
    state = get_state(ha, "todo.home_keeper_tasks")
    assert state is not None
    # State is the count of incomplete items; 4 seeded tasks are enabled.
    assert int(state["state"]) >= 1


def test_calendar_entity_exists(ha):
    state = get_state(ha, "calendar.home_keeper_upcoming_tasks")
    assert state is not None
    # Regression: a wear part's date-only last_replaced used to produce a tz-naive
    # next_due, which crashed the calendar's state computation -> "unavailable".
    assert state["state"] != "unavailable"


def test_wear_part_next_due_sensor_is_timezone_aware(ha):
    # The seeded water heater's anode rod is a wear item. Its derived next-due
    # timestamp sensor must report an aware datetime (not "unavailable" from a
    # naive-vs-aware comparison crash).
    sensor = next(
        (
            s
            for s in list_states(ha)
            if s["entity_id"].startswith("sensor.")
            and "anode_rod" in s["entity_id"]
            and s["entity_id"].endswith("_next_due")
        ),
        None,
    )
    assert sensor is not None, "expected a next-due sensor for the anode rod wear part"
    assert sensor["state"] not in ("unavailable", "unknown"), sensor["state"]
    # A timestamp device_class state is an aware ISO datetime; parsing must yield tz.
    from datetime import datetime

    assert datetime.fromisoformat(sensor["state"]).tzinfo is not None


def test_device_attached_task_creates_per_task_entities(ha):
    states = list_states(ha)
    ids = [s["entity_id"] for s in states]
    # The seeded "water filter" task has a device_id, so it gets button + sensor +
    # binary_sensor entities.
    assert any(
        (eid.startswith("button.") and "water_filter" in eid)
        or eid == "button.replace_water_filter_mark_done"
        for eid in ids
    ) or any("mark_done" in eid for eid in ids)
    assert any("next_due" in eid for eid in ids)
    assert any("overdue" in eid for eid in ids)


def test_overdue_binary_sensor_is_on_for_overdue_task(ha):
    states = list_states(ha)
    overdue = [
        s
        for s in states
        if s["entity_id"].endswith("_overdue") or "overdue" in s["entity_id"]
    ]
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


def test_add_fixed_task_with_naive_anchor_does_not_crash(ha):
    # Mirrors what the panel's datetime-local input sends (no timezone). The
    # backend must normalize it so recurrence math doesn't raise.
    before = int(get_state(ha, "todo.home_keeper_tasks")["state"])
    call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Test water the plants",
            "recurrence_type": "fixed",
            "interval": 1,
            "freq": "DAILY",
            "anchor": "2026-01-01T07:30",
        },
    )
    poll_state(ha, "todo.home_keeper_tasks", lambda s: int(s) >= before + 1)


def test_list_tasks_service_returns_response(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    # HA wraps service responses under "service_response".
    payload = resp.get("service_response", resp)
    assert "tasks" in payload
    assert isinstance(payload["tasks"], list)
    names = [t["name"] for t in payload["tasks"]]
    assert "Take medicine" in names


def test_add_task_accepts_and_round_trips_opaque_source(ha):
    # A contributing integration tags its task with a domain-namespaced source dict;
    # Home Keeper must accept it on the service and store it verbatim (see
    # docs/INTEGRATING.md).
    source = {
        "pawsistant": {
            "dog_id": "buddy",
            "event_type": "medicine",
            "schedule_id": "sched-1",
        }
    }
    call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Cross-integration medicine",
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "weeks",
            "source": source,
        },
    )
    match = next(
        (t for t in _list_tasks(ha) if t.get("name") == "Cross-integration medicine"),
        None,
    )
    assert match is not None
    assert match["source"] == source


def test_complete_task_fires_event_with_source_and_origin(ha):
    # Completing a task fires home_keeper_task_completed carrying the opaque source and
    # the caller's origin; an automation mirrors them into input_text helpers so we can
    # assert over REST. This is what makes two-way sync ("the same button") possible.
    origin = "pawsistant-itest"
    source = {"pawsistant": {"schedule_id": "evt-sched"}}
    call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Event payload probe",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "days",
            "source": source,
        },
    )
    task_id = next(
        t["id"] for t in _list_tasks(ha) if t["name"] == "Event payload probe"
    )

    call_service(
        ha, "home_keeper", "complete_task", {"task_id": task_id, "origin": origin}
    )

    # The capture automation records the last completion's origin/source.
    poll_state(
        ha,
        "input_text.hk_last_completed_origin",
        lambda s: s == origin,
    )
    captured_source = get_state(ha, "input_text.hk_last_completed_source")["state"]
    assert "pawsistant" in captured_source and "evt-sched" in captured_source


def test_complete_task_without_origin_reports_none(ha):
    # A manual / Home-Keeper-UI completion passes no origin; the event's origin is null
    # so listeners treat it as "not mine" and mirror it.
    task_id = next(t["id"] for t in _list_tasks(ha) if t["name"] == "Take medicine")
    call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
    poll_state(ha, "input_text.hk_last_completed_origin", lambda s: s == "none")


def _ws_call(ha, payload):
    """Send one Home Keeper websocket command and return its result payload."""
    token = ha.headers["Authorization"].split(" ", 1)[1]
    with websockets.sync.client.connect(_WS_URL) as ws:
        msg = json.loads(ws.recv())
        assert msg["type"] == "auth_required"
        ws.send(json.dumps({"type": "auth", "access_token": token}))
        msg = json.loads(ws.recv())
        assert msg["type"] == "auth_ok", f"auth failed: {msg}"
        ws.send(json.dumps({"id": 1, **payload}))
        msg = json.loads(ws.recv())
        return msg


def test_complete_task_websocket_completed_at_persists(ha):
    # Regression: ws_complete_task used to drop completed_at entirely even though
    # the service and store already supported back-dating (issue #143 gap). This
    # exercises the websocket command directly (not the service) to cover the fix.
    call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "WS back-date probe",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "days",
        },
    )
    task_id = next(
        t["id"] for t in _list_tasks(ha) if t["name"] == "WS back-date probe"
    )
    try:
        back_dated = "2026-01-05T09:00:00-04:00"
        result = _ws_call(
            ha,
            {
                "type": "home_keeper/complete_task",
                "task_id": task_id,
                "completed_at": back_dated,
            },
        )
        assert result["success"], result
        assert result["result"]["task"]["last_completed"] == back_dated
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})


def test_move_completion_websocket_command_persists(ha):
    old_ts = "2026-01-01T09:00:00-04:00"
    new_ts = "2026-01-12T09:00:00-04:00"
    call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "WS move completion probe",
            "recurrence_type": "floating",
            "interval": 30,
            "unit": "days",
            "last_completed": old_ts,
        },
    )
    task_id = next(
        t["id"] for t in _list_tasks(ha) if t["name"] == "WS move completion probe"
    )
    try:
        result = _ws_call(
            ha,
            {
                "type": "home_keeper/move_completion",
                "task_id": task_id,
                "old_ts": old_ts,
                "new_ts": new_ts,
            },
        )
        assert result["success"], result
        assert result["result"]["task"]["completions"] == [{"ts": new_ts}]
        assert result["result"]["task"]["last_completed"] == new_ts
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})


def test_move_completion_service_fires_uncompleted_then_completed(ha):
    # Modeled as "undo, then redo at the new time": both events fire so existing
    # automations/integrations that already react to completions/uncompletions see
    # the move without a new event type to learn (issue #143).
    old_ts = "2026-01-01T09:00:00-04:00"
    new_ts = "2026-01-10T09:00:00-04:00"
    call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Move completion probe",
            "recurrence_type": "floating",
            "interval": 30,
            "unit": "days",
            "last_completed": old_ts,
        },
    )
    task_id = next(
        t["id"] for t in _list_tasks(ha) if t["name"] == "Move completion probe"
    )
    try:
        seeded = next(t for t in _list_tasks(ha) if t["id"] == task_id)
        assert seeded["completions"] == [{"ts": old_ts}]

        call_service(
            ha,
            "home_keeper",
            "move_completion",
            {"task_id": task_id, "old_ts": old_ts, "new_completed_at": new_ts},
        )

        # task_uncompleted fired first, carrying the old ts as an extra.
        poll_state(ha, "input_text.hk_last_uncompleted_ts", lambda s: s == old_ts)
        # task_completed fired second, with no caller-supplied origin.
        poll_state(ha, "input_text.hk_last_completed_origin", lambda s: s == "none")

        moved = next(t for t in _list_tasks(ha) if t["id"] == task_id)
        assert moved["completions"] == [{"ts": new_ts}]
        assert moved["last_completed"] == new_ts
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})


def test_move_completion_unknown_ts_rejected(ha):
    call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Move completion missing ts probe",
            "recurrence_type": "floating",
            "interval": 30,
            "unit": "days",
        },
    )
    task_id = next(
        t["id"]
        for t in _list_tasks(ha)
        if t["name"] == "Move completion missing ts probe"
    )
    try:
        r = ha.post(
            f"{HA_URL}/api/services/home_keeper/move_completion",
            json={
                "task_id": task_id,
                "old_ts": "2000-01-01T00:00:00+00:00",
                "new_completed_at": "2026-01-01T00:00:00+00:00",
            },
        )
        assert r.status_code >= 400, "expected rejection for an unknown old_ts"
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})


def _find_button_by_name(ha, name_substr):
    """Return (entity_id, friendly_name) of a button whose name contains a substring."""
    for s in list_states(ha):
        if not s["entity_id"].startswith("button."):
            continue
        fn = s.get("attributes", {}).get("friendly_name", "")
        if name_substr in fn:
            return s["entity_id"], fn
    return None, None


def test_renaming_task_updates_device_entity_name(ha):
    # Regression: HA caches an entity's computed name, and a plain coordinator
    # refresh leaves it stale. A task rename must reload the entry so the
    # device-page entity (and the self-owned device) pick up the new name.
    resp = call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Rename probe original",
            "recurrence_type": "floating",
            "interval": 3,
            "unit": "months",
            # Any device_id gives the task per-task entities; an unknown one lands
            # them on a self-owned device named after the task.
            "device_id": "rename_probe_fake_device",
        },
        return_response=True,
    )
    task_id = resp.get("service_response", resp)["task_id"]
    try:
        eid = None
        for _ in range(20):
            eid, _before = _find_button_by_name(ha, "Rename probe original")
            if eid:
                break
            time.sleep(1)
        assert eid, "expected a mark-done button for the new device-attached task"

        call_service(
            ha,
            "home_keeper",
            "update_task",
            {"task_id": task_id, "name": "Rename probe renamed"},
        )

        # The entity id is stable (keyed by unique_id); only its name changes.
        after = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = get_state(ha, eid)
            after = (state or {}).get("attributes", {}).get("friendly_name", "")
            if "renamed" in after:
                break
            time.sleep(1)
        assert after and "Rename probe renamed" in after, (
            f"device entity name did not update after rename: {after!r}"
        )
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})
