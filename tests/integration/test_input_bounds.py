"""Input limits on the service and on the websocket command, in a real Home Assistant.

Each case is a task field over its limit. The ``home_keeper.add_task`` service and the
``home_keeper/add_task`` websocket command refuse the same cases, and no task is
stored. ``home_keeper.snooze_task`` refuses an ``hours`` value over 1 year, where the
date math overflowed before.
"""

from __future__ import annotations

import uuid

import pytest
from conftest import HA_URL, call_service
from ha_registry import ws_send

_LONG_URL = "https://example.com/" + "a" * 2029

# (label, field, value): each value is over the limit of its field.
BAD_FIELDS = [
    ("snooze hours", "snooze_hours", 10**9),
    (
        "season windows",
        "active_season",
        [
            {"start": f"{(n % 12) + 1:02d}-01", "end": f"{(n % 12) + 1:02d}-10"}
            for n in range(13)
        ],
    ),
    ("device id list", "device_id", ["a"]),
    ("area id object", "area_id", {"id": "a"}),
    ("chip url", "task_chips", [{"label": "Manual", "url": _LONG_URL}]),
]


# The fields that pass the service schema and that the store refuses. The others are
# refused by the service schema.
_STORE_CHECKED = {"task_chips"}


def _token(ha) -> str:
    return ha.headers["Authorization"].split(" ", 1)[1]


def _task_named(ha, name):
    msg = ws_send(_token(ha), {"type": "home_keeper/get_tasks"})
    return next((t for t in msg["result"]["tasks"] if t.get("name") == name), None)


def _cleanup(ha, name):
    task = _task_named(ha, name)
    if task is not None:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task["id"]})
    return task


@pytest.mark.parametrize(
    ("label", "field", "value"), BAD_FIELDS, ids=[c[0] for c in BAD_FIELDS]
)
def test_the_add_task_service_refuses_a_field_over_its_limit(ha, label, field, value):
    name = f"Bound service {label} {uuid.uuid4().hex[:8]}"
    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/add_task",
        json={"name": name, "interval": 1, "unit": "days", field: value},
    )
    stored = _cleanup(ha, name)
    assert stored is None
    if field in _STORE_CHECKED:
        # The store raises ServiceValidationError. Home Assistant 2026.1 answers it
        # with 500 and no message over REST; later releases answer 400 with the text.
        assert r.status_code in (400, 500), r.text
        if r.status_code == 400:
            assert field in r.text, r.text
    else:
        # The service schema refuses the value, with a bare 400 on every version.
        # The websocket test below runs the same schema and checks the message.
        assert r.status_code == 400, r.text


@pytest.mark.parametrize(
    ("label", "field", "value"), BAD_FIELDS, ids=[c[0] for c in BAD_FIELDS]
)
def test_the_add_task_websocket_command_refuses_a_field_over_its_limit(
    ha, label, field, value
):
    name = f"Bound ws {label} {uuid.uuid4().hex[:8]}"
    msg = ws_send(
        _token(ha),
        {
            "type": "home_keeper/add_task",
            "task": {"name": name, "interval": 1, "unit": "days", field: value},
        },
    )
    stored = _cleanup(ha, name)
    assert not msg.get("success"), msg
    assert field in msg["error"]["message"], msg
    assert stored is None


def test_snooze_task_refuses_hours_over_1_year(ha):
    name = f"Bound snooze {uuid.uuid4().hex[:8]}"
    call_service(
        ha, "home_keeper", "add_task", {"name": name, "interval": 1, "unit": "days"}
    )
    task = _task_named(ha, name)
    try:
        r = ha.post(
            f"{HA_URL}/api/services/home_keeper/snooze_task",
            json={"task_id": task["id"], "hours": 10**12},
        )
        assert r.status_code == 400, r.text
        ok = ha.post(
            f"{HA_URL}/api/services/home_keeper/snooze_task",
            json={"task_id": task["id"], "hours": 8760},
        )
        assert ok.status_code == 200, ok.text
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task["id"]})


def test_the_update_task_service_clears_a_real_area_with_null(ha):
    # The panel sends ``device_id: null`` and ``area_id: null`` to clear the links.
    # ``devices.area_exists`` reads null as "no area", so the service accepts it.
    token = _token(ha)
    area = ws_send(
        token,
        {
            "type": "config/area_registry/create",
            "name": f"Bound {uuid.uuid4().hex[:8]}",
        },
    )
    assert area.get("success"), area
    area_id = area["result"]["area_id"]
    name = f"Bound null links {uuid.uuid4().hex[:8]}"
    try:
        call_service(
            ha,
            "home_keeper",
            "add_task",
            {"name": name, "interval": 1, "unit": "days", "area_id": area_id},
        )
        task = _task_named(ha, name)
        assert task["area_id"] == area_id
        r = ha.post(
            f"{HA_URL}/api/services/home_keeper/update_task",
            json={"task_id": task["id"], "device_id": None, "area_id": None},
        )
        assert r.status_code == 200, r.text
        cleared = _task_named(ha, name)
        assert cleared["area_id"] is None
        assert cleared["device_id"] is None
    finally:
        _cleanup(ha, name)
        ws_send(token, {"type": "config/area_registry/delete", "area_id": area_id})
