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
    assert r.status_code == 400, r.text
    assert stored is None


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
