"""``HomeKeeperCoordinator.async_apply_options`` — a live options change (#467).

An options change reloaded the whole entry. Home Assistant then wrote ``unavailable``
for each Home Keeper entity and wrote each state again, so 1 change put many rows in
the logbook. Now the coordinator applies a change that keeps the entity set to the
running entry, and reloads only when ``options.reload_needed`` says so.

The coordinator loads over the HA stubs the same way ``test_coordinator_purge.py``
loads it, and runs against fake syncs and a fake store.
"""

from __future__ import annotations

import asyncio
from datetime import time
from typing import Any

import hk_const as const  # type: ignore[import-not-found]
import hk_options as real_options  # type: ignore[import-not-found]
import pytest
from test_coordinator_purge import coordinator


class _FakeConfigEntries:
    def __init__(self) -> None:
        self.reloaded: list[str] = []

    async def async_reload(self, entry_id: str) -> None:
        self.reloaded.append(entry_id)


class _FakeHass:
    def __init__(self) -> None:
        self.config_entries = _FakeConfigEntries()


class _FakeEntry:
    def __init__(self, options: dict[str, Any]) -> None:
        self.entry_id = "entry-1"
        self.options = options
        self.state = coordinator.ConfigEntryState.LOADED


class _FakeStore:
    def __init__(self) -> None:
        self.due_times: list[time | None] = []

    async def async_apply_due_time(self, due_time: time | None) -> None:
        self.due_times.append(due_time)


class _FakeSync:
    """A sync whose ``async_apply_options`` records each call."""

    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.calls = 0
        self._result = result
        self._error = error

    async def async_apply_options(self) -> Any:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._result


def _doc(**updates: Any) -> dict[str, Any]:
    return real_options._normalize(updates, real_options._empty_options())


def _make(old: dict[str, Any], new: dict[str, Any], *, problem_result: bool = False):
    coord = object.__new__(coordinator.HomeKeeperCoordinator)
    coord.config_entry = _FakeEntry(new)
    coord.config_entry.runtime_data = coord
    coord.hass = _FakeHass()
    coord.store = _FakeStore()
    coord.problem_sync = _FakeSync(problem_result)
    coord.shopping_sync = _FakeSync()
    coord.todo_list_sync = _FakeSync()
    coord.applied_options = old
    coord._options_lock = asyncio.Lock()
    refreshes: list[bool] = []

    async def _refresh() -> None:
        refreshes.append(True)

    coord.async_request_refresh = _refresh
    coord.refreshes = refreshes
    return coord


def _apply(coord: Any) -> None:
    asyncio.run(coord.async_apply_options())


def test_no_change_does_nothing() -> None:
    """The listener also fires for a title or data change: no refresh, no reload."""
    coord = _make(_doc(), _doc())
    _apply(coord)
    assert coord.hass.config_entries.reloaded == []
    assert coord.refreshes == []


def test_a_live_change_refreshes_and_does_not_reload() -> None:
    new = _doc(allow_snooze=False)
    coord = _make(_doc(), new)
    _apply(coord)
    assert coord.hass.config_entries.reloaded == []
    assert coord.refreshes == [True]
    assert coord.applied_options == new
    # No step for a value that is read live.
    assert coord.problem_sync.calls == 0
    assert coord.shopping_sync.calls == 0
    assert coord.todo_list_sync.calls == 0
    assert coord.store.due_times == []


def test_a_change_to_the_entity_set_reloads() -> None:
    coord = _make(_doc(), _doc(cost_windows=[7, 30, 60]))
    _apply(coord)
    assert coord.hass.config_entries.reloaded == ["entry-1"]
    assert coord.refreshes == []
    assert coord.problem_sync.calls == 0


def test_a_new_due_time_moves_the_store_dates() -> None:
    new = _doc(due_time_mode=const.DUE_TIME_MODE_SET_TIME, due_time="09:30")
    coord = _make(_doc(), new)
    _apply(coord)
    assert coord.store.due_times == [time(9, 30)]
    assert coord.hass.config_entries.reloaded == []


def test_a_shopping_change_retargets_the_shopping_sync_only() -> None:
    coord = _make(_doc(), _doc(shopping_list_entity="todo.shopping"))
    _apply(coord)
    assert coord.shopping_sync.calls == 1
    assert coord.todo_list_sync.calls == 0
    assert coord.problem_sync.calls == 0


def test_a_profile_filter_edit_retargets_the_todo_list_sync() -> None:
    profile = {"id": "p1", "name": "Chores", "filter": {"status": "overdue"}}
    old = _doc(profiles=[profile])
    new = _doc(profiles=[{**profile, "filter": {"status": "all"}}])
    coord = _make(old, new)
    _apply(coord)
    assert coord.todo_list_sync.calls == 1
    assert coord.shopping_sync.calls == 0
    assert coord.hass.config_entries.reloaded == []


def test_a_problem_change_that_keeps_the_entity_set_is_live() -> None:
    coord = _make(_doc(), _doc(problem_sensor_exclude_areas=["kitchen"]))
    _apply(coord)
    assert coord.problem_sync.calls == 1
    assert coord.hass.config_entries.reloaded == []
    assert coord.refreshes == [True]


def test_a_problem_change_that_changes_the_entity_set_reloads() -> None:
    """A synced task with entities came or went: only the platforms make them."""
    new = _doc(sync_problem_sensors=True)
    coord = _make(_doc(), new, problem_result=True)
    _apply(coord)
    assert coord.problem_sync.calls == 1
    assert coord.hass.config_entries.reloaded == ["entry-1"]
    assert coord.refreshes == []


def test_a_live_step_that_raises_falls_back_to_a_reload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    coord = _make(_doc(), _doc(shopping_list_entity="todo.shopping"))
    coord.shopping_sync = _FakeSync(error=RuntimeError("boom"))
    old = coord.applied_options
    _apply(coord)
    assert coord.hass.config_entries.reloaded == ["entry-1"]
    assert coord.refreshes == []
    assert coord.applied_options is old  # the snapshot did not move
    assert "without a reload" in caplog.text


def test_a_missing_sync_is_skipped() -> None:
    """Setup attaches the syncs after the first refresh."""
    coord = _make(_doc(), _doc(shopping_list_entity="todo.shopping", profiles=[]))
    coord.shopping_sync = None
    coord.problem_sync = None
    coord.todo_list_sync = None
    _apply(coord)
    assert coord.hass.config_entries.reloaded == []
    assert coord.refreshes == [True]


def test_a_second_change_compares_with_the_first() -> None:
    """The snapshot moves on each live apply, so the next change compares with it."""
    first = _doc(allow_skip=False)
    coord = _make(_doc(), first)
    _apply(coord)
    coord.config_entry.options = first
    _apply(coord)
    assert coord.refreshes == [True]


# ── an entry that is not loaded, or a coordinator that is stale ─────────────────
def test_a_coordinator_of_an_entry_that_is_not_loaded_reloads() -> None:
    """A failed setup keeps ``runtime_data``, and an unload runs first and drops it.

    Its syncs and store are closed, so a live step would act on dead objects. The
    reload sets the entry up with the new options, as before #467.
    """
    coord = _make(_doc(), _doc(allow_snooze=False))
    # Any state that is not LOADED. The HA stub of the bare unit lane (and of the
    # mutation lane) has only ``LOADED``, so the test names no other member.
    coord.config_entry.state = "setup_error"
    _apply(coord)
    assert coord.hass.config_entries.reloaded == ["entry-1"]
    assert coord.refreshes == []


def test_a_coordinator_that_a_reload_replaced_reloads() -> None:
    coord = _make(_doc(), _doc(allow_snooze=False))
    coord.config_entry.runtime_data = object()
    _apply(coord)
    assert coord.hass.config_entries.reloaded == ["entry-1"]
    assert coord.refreshes == []


def test_the_listener_applies_through_the_loaded_coordinator() -> None:
    coord = _make(_doc(), _doc(allow_snooze=False))
    asyncio.run(coordinator.async_apply_entry_options(coord.hass, coord.config_entry))
    assert coord.refreshes == [True]
    assert coord.hass.config_entries.reloaded == []


def test_the_listener_reloads_an_entry_with_no_coordinator() -> None:
    """The update listener runs as a task, so the entry can unload before it runs.

    The unload deletes ``runtime_data``. A reload keeps the change, where a bare
    ``entry.runtime_data`` raised ``AttributeError``.
    """
    hass, entry = _FakeHass(), _FakeEntry(_doc(allow_snooze=False))
    asyncio.run(coordinator.async_apply_entry_options(hass, entry))
    assert hass.config_entries.reloaded == ["entry-1"]
