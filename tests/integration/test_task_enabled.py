"""Integration tests: switching a task off and on through ``home_keeper.update_task``.

``enabled`` is a stored field every schedule surface already honoured, and nothing a
user could reach ever wrote it (issue #344). It ships as an ordinary field on
``add_task`` and ``update_task``, so an automation can follow a helper: a pool's tasks
go off when the pool closes for the winter and come back when it opens.

Two claims live at this level and cannot be checked anywhere else:

1. **The per-task entity set follows the field.** ``coordinator.entity_set_key``
   includes ``enabled``, and ``handle_update_task`` reloads the config entry when that
   key moves. Whether the reload really removes and restores the entities is a Home
   Assistant entity-registry contract, so a unit test that mocks the registry cannot
   see it — the same trap as #183.

2. **The to-do list drops the task and takes it back.** ``todo.py`` filters on the
   field, and the todo entity is Home Assistant's, not ours.

The due date is deliberately *not* touched by either direction. That is the whole
difference from an active season, which clamps the date forward to the next window.
"""

import time

from conftest import call_service, list_states
from ha_registry import entity_registry as _entity_registry

DEVICE_ID = "pool_toggle_fake_device_344"


def _unique_ids(ha) -> set[str]:
    return {e["unique_id"] for e in _entity_registry(ha) if e.get("unique_id")}


def _wait_for_uids(ha, uids: set[str], *, present: bool, timeout: int = 25) -> set[str]:
    """Poll until every id in *uids* is present (or absent), returning what is wrong."""
    deadline = time.monotonic() + timeout
    wrong = set(uids)
    while time.monotonic() < deadline:
        current = _unique_ids(ha)
        wrong = {u for u in uids if (u in current) is not present}
        if not wrong:
            break
        time.sleep(1)
    return wrong


def _todo_entity_id(ha) -> str:
    for s in list_states(ha):
        if s["entity_id"].startswith("todo.") and "home_keeper" in s["entity_id"]:
            return s["entity_id"]
    raise AssertionError("Home Keeper's todo entity should exist")


def _todo_names(ha, entity_id: str) -> list[str]:
    resp = call_service(
        ha,
        "todo",
        "get_items",
        {"entity_id": entity_id},
        return_response=True,
    )
    body = resp.get("service_response", resp)
    items = body.get(entity_id, {}).get("items", [])
    return [i.get("summary", "") for i in items]


def _wait_for_todo(ha, entity_id: str, name: str, *, present: bool, timeout: int = 25):
    deadline = time.monotonic() + timeout
    seen: list[str] = []
    while time.monotonic() < deadline:
        seen = _todo_names(ha, entity_id)
        if (name in seen) is present:
            return seen
        time.sleep(1)
    return seen


def test_switching_a_task_off_and_on_moves_its_entities_and_keeps_its_date(ha):
    """The whole round trip, on a device-attached task so the entity set is in play."""
    resp = call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Backwash the pool filter",
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "weeks",
            "device_id": DEVICE_ID,
        },
        return_response=True,
    )
    task_id = resp.get("service_response", resp)["task_id"]
    uids = {
        f"home_keeper_{task_id}_done",
        f"home_keeper_{task_id}_next_due",
        f"home_keeper_{task_id}_overdue",
    }

    try:
        missing = _wait_for_uids(ha, uids, present=True)
        assert not missing, f"a live device-attached task owns all three: {missing}"

        todo = _todo_entity_id(ha)
        names = _wait_for_todo(ha, todo, "Backwash the pool filter", present=True)
        assert "Backwash the pool filter" in names, names

        # The pool closes. One service call, exactly what an automation on an
        # input_boolean would send.
        call_service(
            ha,
            "home_keeper",
            "update_task",
            {"task_id": task_id, "enabled": False},
        )

        stale = _wait_for_uids(ha, uids, present=False)
        assert not stale, f"a switched-off task keeps no per-task entities: {stale}"
        names = _wait_for_todo(ha, todo, "Backwash the pool filter", present=False)
        assert "Backwash the pool filter" not in names, names

        # The task itself is still there, with its schedule and its date intact.
        listed = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
        tasks = listed.get("service_response", listed)["tasks"]
        stored = next(t for t in tasks if t["id"] == task_id)
        assert stored["enabled"] is False
        assert stored["interval"] == 2
        frozen_due = stored["next_due"]
        assert frozen_due, "switching a task off must not clear its due date"

        # The pool opens again.
        call_service(
            ha,
            "home_keeper",
            "update_task",
            {"task_id": task_id, "enabled": True},
        )

        missing = _wait_for_uids(ha, uids, present=True)
        assert not missing, f"switching a task on restores its entities: {missing}"
        names = _wait_for_todo(ha, todo, "Backwash the pool filter", present=True)
        assert "Backwash the pool filter" in names, names

        listed = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
        tasks = listed.get("service_response", listed)["tasks"]
        stored = next(t for t in tasks if t["id"] == task_id)
        assert stored["enabled"] is True
        # The date did not move in either direction. An automation that wants the
        # clean re-entry an active season gives pairs this with set_due_today.
        assert stored["next_due"] == frozen_due

    finally:
        try:
            call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})
        except Exception:
            pass


def test_a_task_can_be_created_switched_off(ha):
    """``add_task`` takes the field too, so an import or a script can seed one off."""
    resp = call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Winterize the pool heater",
            "recurrence_type": "floating",
            "interval": 12,
            "unit": "months",
            "enabled": False,
        },
        return_response=True,
    )
    task_id = resp.get("service_response", resp)["task_id"]
    try:
        listed = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
        tasks = listed.get("service_response", listed)["tasks"]
        stored = next(t for t in tasks if t["id"] == task_id)
        assert stored["enabled"] is False

        todo = _todo_entity_id(ha)
        names = _wait_for_todo(ha, todo, "Winterize the pool heater", present=False)
        assert "Winterize the pool heater" not in names, names
    finally:
        try:
            call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})
        except Exception:
            pass


def test_an_edit_that_sends_no_enabled_leaves_a_switched_off_task_off(ha):
    """The panel's task form sends no ``enabled``, and must not switch one back on.

    Every other field on ``update_task`` is only-when-sent. If this one were not, a
    user opening the form on a task an automation had switched off — to fix a typo in
    its name — would switch it back on by pressing Save.
    """
    resp = call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Test the pool chemicals",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "weeks",
            "enabled": False,
        },
        return_response=True,
    )
    task_id = resp.get("service_response", resp)["task_id"]
    try:
        call_service(
            ha,
            "home_keeper",
            "update_task",
            {"task_id": task_id, "name": "Test the pool chemistry"},
        )
        listed = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
        tasks = listed.get("service_response", listed)["tasks"]
        stored = next(t for t in tasks if t["id"] == task_id)
        assert stored["name"] == "Test the pool chemistry"
        assert stored["enabled"] is False
    finally:
        try:
            call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})
        except Exception:
            pass
