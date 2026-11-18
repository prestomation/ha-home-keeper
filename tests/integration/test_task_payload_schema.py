"""The websocket task commands and the task services check a payload with 1 schema.

``home_keeper/add_task`` and ``home_keeper/update_task`` validate their task fields
with ``ADD_TASK_SCHEMA`` and ``UPDATE_TASK_SCHEMA``, the schemas of the
``home_keeper.add_task`` and ``home_keeper.update_task`` services. Each case in
``BAD_FIELDS`` runs against all 4 surfaces, so a surface that accepts a case
that another surface rejects fails here.
"""

from __future__ import annotations

import uuid

import pytest
from conftest import HA_URL, call_service
from ha_registry import ws_send

# Each case is a set of task fields that every task surface rejects. A case is
# merged over a valid task, so only the named field is wrong.
BAD_FIELDS = [
    pytest.param({"device_id": ["a"]}, id="device_id-list"),
    pytest.param({"device_id": {"id": "a"}}, id="device_id-dict"),
    pytest.param({"area_id": ["kitchen"]}, id="area_id-list"),
    pytest.param({"area_id": {"id": "kitchen"}}, id="area_id-dict"),
    pytest.param({"name": ["x"]}, id="name-list"),
    pytest.param({"interval": 0}, id="interval-zero"),
    pytest.param({"labels": [["a"]]}, id="labels-nested-list"),
    pytest.param({"tag_id": ["t"]}, id="tag_id-list"),
    pytest.param({"card_links": [{"asset_id": "a"}]}, id="card_link-no-entry"),
    pytest.param({"unknown_field": 1}, id="unknown-field"),
]

_VALID = {"recurrence_type": "floating", "interval": 3, "unit": "months"}


def _token(ha) -> str:
    return ha.headers["Authorization"].split(" ", 1)[1]


def _name() -> str:
    return f"Schema probe {uuid.uuid4().hex[:8]}"


def _tasks(ha) -> list[dict]:
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def _task_named(ha, name: str) -> dict | None:
    return next((t for t in _tasks(ha) if t["name"] == name), None)


def _delete(ha, task_id: str) -> None:
    call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})


@pytest.fixture
def stored_task(ha):
    """A valid task to update, deleted after the test."""
    name = _name()
    call_service(ha, "home_keeper", "add_task", {"name": name, **_VALID})
    task = _task_named(ha, name)
    assert task is not None
    yield task
    _delete(ha, task["id"])


@pytest.mark.parametrize("bad", BAD_FIELDS)
def test_websocket_add_task_rejects_the_case(ha, bad):
    name = _name()
    msg = ws_send(
        _token(ha),
        {"type": "home_keeper/add_task", "task": {"name": name, **_VALID, **bad}},
    )
    created = _task_named(ha, name)
    if created is not None:
        _delete(ha, created["id"])
    assert not msg.get("success"), f"websocket add_task stored {bad}: {msg}"
    assert msg["error"]["code"] == "invalid_format", msg
    assert created is None


@pytest.mark.parametrize("bad", BAD_FIELDS)
def test_service_add_task_rejects_the_case(ha, bad):
    name = _name()
    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/add_task",
        json={"name": name, **_VALID, **bad},
    )
    created = _task_named(ha, name)
    if created is not None:
        _delete(ha, created["id"])
    assert r.status_code == 400, f"service add_task stored {bad}: {r.text}"
    assert created is None


@pytest.mark.parametrize("bad", BAD_FIELDS)
def test_websocket_update_task_rejects_the_case(ha, stored_task, bad):
    msg = ws_send(
        _token(ha),
        {
            "type": "home_keeper/update_task",
            "task_id": stored_task["id"],
            "updates": bad,
        },
    )
    assert not msg.get("success"), f"websocket update_task stored {bad}: {msg}"
    assert msg["error"]["code"] == "invalid_format", msg
    assert _task_named(ha, stored_task["name"]) == stored_task


@pytest.mark.parametrize("bad", BAD_FIELDS)
def test_service_update_task_rejects_the_case(ha, stored_task, bad):
    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/update_task",
        json={"task_id": stored_task["id"], **bad},
    )
    assert r.status_code == 400, f"service update_task stored {bad}: {r.text}"
    assert _task_named(ha, stored_task["name"]) == stored_task


# The fields the panel form sends to clear a device and an area.
_CLEARED_LINKS = {"device_id": None, "area_id": None}


def test_websocket_add_task_accepts_cleared_links(ha):
    name = _name()
    msg = ws_send(
        _token(ha),
        {
            "type": "home_keeper/add_task",
            "task": {"name": name, **_VALID, **_CLEARED_LINKS},
        },
    )
    assert msg.get("success"), msg
    task = msg["result"]["task"]
    _delete(ha, task["id"])
    assert task["device_id"] is None
    assert task["area_id"] is None


def test_service_add_task_accepts_cleared_links(ha):
    name = _name()
    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/add_task?return_response",
        json={"name": name, **_VALID, **_CLEARED_LINKS},
    )
    created = _task_named(ha, name)
    if created is not None:
        _delete(ha, created["id"])
    assert r.status_code == 200, r.text
    assert created is not None
    assert created["device_id"] is None
    assert created["area_id"] is None


def test_websocket_update_task_returns_the_coerced_values(ha, stored_task):
    # The schema output is what the store gets: the interval text becomes a number.
    msg = ws_send(
        _token(ha),
        {
            "type": "home_keeper/update_task",
            "task_id": stored_task["id"],
            "updates": {"interval": "5", **_CLEARED_LINKS},
        },
    )
    assert msg.get("success"), msg
    assert msg["result"]["task"]["interval"] == 5
    assert _task_named(ha, stored_task["name"])["interval"] == 5


def test_service_update_task_clears_the_links(ha, stored_task):
    call_service(
        ha,
        "home_keeper",
        "update_task",
        {"task_id": stored_task["id"], **_CLEARED_LINKS},
    )
    task = _task_named(ha, stored_task["name"])
    assert task["device_id"] is None
    assert task["area_id"] is None
