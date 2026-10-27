"""The transition events of ``HomeKeeperCoordinator._async_update_data``.

The coordinator builds an overdue or due-soon event in ``transitions`` and adds the
entity id of the Home Keeper to-do list. The logbook matches the event to the to-do
list by that key, so without it the row does not show on the list.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from test_coordinator_purge import NOW, coordinator


class _FakeBus:
    def __init__(self) -> None:
        self.fired: list[tuple[str, dict[str, Any]]] = []

    def async_fire(self, event_type: str, data: dict[str, Any]) -> None:
        self.fired.append((event_type, data))


class _FakeStore:
    todo_entity_id = "todo.home_keeper_tasks"

    def __init__(self, tasks: dict[str, dict[str, Any]]) -> None:
        self._tasks = tasks

    async def settle_use_tasks(self) -> None:
        return None

    def get_tasks(self) -> dict[str, dict[str, Any]]:
        return self._tasks


def _overdue_task() -> dict[str, Any]:
    return {
        "id": "t1",
        "name": "Filter",
        "enabled": True,
        "recurrence_type": "floating",
        "next_due": (NOW - timedelta(days=2)).isoformat(),
    }


def _run(coord: Any) -> None:
    asyncio.run(coord._async_update_data())


def _make() -> Any:
    coord = object.__new__(coordinator.HomeKeeperCoordinator)
    coord.hass = SimpleNamespace(bus=_FakeBus())
    coord.store = _FakeStore({"t1": _overdue_task()})
    coord.sensor_watcher = None
    coord.shopping_sync = None
    coord.todo_list_sync = None
    coord._edge_state = {}
    coord._events_enabled = True
    coord._had_prior_edge_state = True

    async def _no_purge() -> None:
        return None

    coord._purge_expired_one_offs = _no_purge
    coord._persist_edge_state = lambda: None
    return coord


def test_a_transition_event_carries_the_to_do_entity_id() -> None:
    coord = _make()
    _run(coord)
    fired = coord.hass.bus.fired
    assert [name for name, _ in fired] == ["home_keeper_task_overdue"]
    assert fired[0][1]["entity_id"] == "todo.home_keeper_tasks"
    assert fired[0][1]["task_id"] == "t1"
