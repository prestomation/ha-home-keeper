"""Unit tests for the to-do entity's dormancy projection (``todo.py``).

The to-do entity is a thin projection over the task store, but it imports Home
Assistant (``TodoItem``/``CoordinatorEntity``/``dt_util``). Like ``test_calendar.py``
we load ``todo.py`` under the synthetic ``hk`` package used by the other pure unit
tests (see ``tests/conftest.py``), stubbing only the HA symbols it references, and
drive it against an in-memory coordinator/store. The real store/entity wiring is
exercised by the integration suite.

What's pinned here is the dormancy rule (#221): a task with no ``next_due`` whose
kind goes dormant — a completed do-once task, an unarmed triggered/sensor task — is
off the list entirely, because the entity only ever emits ``NEEDS_ACTION`` items and
an undated one can never be cleared.
"""

from __future__ import annotations

import asyncio
import enum
import importlib.util
import sys
import types
import typing
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)

TZ = timezone(timedelta(hours=-4))
DUE = datetime(2026, 7, 15, 9, 0, tzinfo=TZ)


def _real_ha_present() -> bool:
    """True only when the *real* Home Assistant package is installed.

    A hand-built stub ``homeassistant`` module (e.g. from ``test_calendar.py``) has
    no ``__file__``; the real package does. This distinguishes them so we fill gaps
    over a stub tree but never shadow real submodules.
    """
    mod = sys.modules.get("homeassistant")
    if mod is None:
        try:  # pragma: no cover - depends on environment
            import homeassistant as mod  # type: ignore[no-redef]
        except ImportError:
            return False
    return getattr(mod, "__file__", None) is not None


def _install_ha_stubs() -> None:
    """Additively register the HA symbols ``todo.py`` imports.

    Idempotent and non-clobbering, like ``test_coordinator_purge.py``: the other
    pure-unit suites install their own partial ``homeassistant`` stub trees, so we
    only *fill gaps* rather than early-return or overwrite — otherwise load order
    between the suites would matter.
    """
    if _real_ha_present():  # pragma: no cover - real HA env
        return

    def _mod(name: str) -> types.ModuleType:
        existing = sys.modules.get(name)
        if existing is not None:
            return existing
        m = types.ModuleType(name)
        sys.modules[name] = m
        return m

    ha = _mod("homeassistant")
    components = _mod("homeassistant.components")
    ha.components = components

    comp_todo = _mod("homeassistant.components.todo")
    if not hasattr(comp_todo, "TodoItem"):

        class TodoItem:
            def __init__(
                self,
                *,
                uid=None,
                summary=None,
                status=None,
                due=None,
                description=None,
            ) -> None:
                self.uid = uid
                self.summary = summary
                self.status = status
                self.due = due
                self.description = description

        class TodoItemStatus(enum.Enum):
            NEEDS_ACTION = "needs_action"
            COMPLETED = "completed"

        class TodoListEntity:
            pass

        class TodoListEntityFeature(enum.IntFlag):
            CREATE_TODO_ITEM = 1
            DELETE_TODO_ITEM = 2
            UPDATE_TODO_ITEM = 4

        comp_todo.TodoItem = TodoItem
        comp_todo.TodoItemStatus = TodoItemStatus
        comp_todo.TodoListEntity = TodoListEntity
        comp_todo.TodoListEntityFeature = TodoListEntityFeature
    components.todo = comp_todo

    config_entries = _mod("homeassistant.config_entries")
    if not hasattr(config_entries, "ConfigEntry"):
        config_entries.ConfigEntry = type("ConfigEntry", (), {})

    core = _mod("homeassistant.core")
    if not hasattr(core, "HomeAssistant"):
        core.HomeAssistant = type("HomeAssistant", (), {})

    exceptions = _mod("homeassistant.exceptions")
    if not hasattr(exceptions, "HomeAssistantError"):

        class HomeAssistantError(Exception):
            def __init__(
                self,
                *args,
                translation_domain=None,
                translation_key=None,
                translation_placeholders=None,
            ) -> None:
                super().__init__(*args)
                self.translation_domain = translation_domain
                self.translation_key = translation_key
                self.translation_placeholders = translation_placeholders

        exceptions.HomeAssistantError = HomeAssistantError

    helpers = _mod("homeassistant.helpers")
    entity_platform = _mod("homeassistant.helpers.entity_platform")
    if not hasattr(entity_platform, "AddEntitiesCallback"):
        entity_platform.AddEntitiesCallback = object
    helpers.entity_platform = entity_platform

    update_coordinator = _mod("homeassistant.helpers.update_coordinator")
    if not hasattr(update_coordinator, "CoordinatorEntity"):
        _T = typing.TypeVar("_T")

        class CoordinatorEntity(typing.Generic[_T]):
            def __init__(self, coordinator) -> None:
                self.coordinator = coordinator

        update_coordinator.CoordinatorEntity = CoordinatorEntity

    util = _mod("homeassistant.util")
    dt_mod = _mod("homeassistant.util.dt")
    if not hasattr(dt_mod, "parse_datetime"):

        def parse_datetime(value):
            if not value:
                return None
            try:
                return datetime.fromisoformat(value)
            except (TypeError, ValueError):
                return None

        dt_mod.parse_datetime = parse_datetime
    # Guarded separately from ``parse_datetime``: ``test_calendar.py`` installs its own
    # ``homeassistant.util.dt`` carrying only ``parse_datetime``/``now``, so folding
    # these into that branch would make load order between the suites matter.
    if not hasattr(dt_mod, "DEFAULT_TIME_ZONE"):
        dt_mod.DEFAULT_TIME_ZONE = UTC
    if not hasattr(dt_mod, "as_local"):

        def as_local(value):
            # Reads the module global at call time, like HA's own implementation, so a
            # test can point "local" somewhere by monkeypatching DEFAULT_TIME_ZONE.
            return value.astimezone(dt_mod.DEFAULT_TIME_ZONE)

        dt_mod.as_local = as_local
    util.dt = dt_mod


def _load_todo() -> types.ModuleType:
    """Load ``todo.py`` as ``hk.todo`` so its relative imports resolve."""
    if "hk.todo" in sys.modules:
        return sys.modules["hk.todo"]
    _install_ha_stubs()
    # ``from .coordinator import HomeKeeperCoordinator`` — the real module pulls in
    # HA/store; the entity only needs the name for typing, so stub it if no other
    # suite has already registered one (test_coordinator_purge.py loads the real one).
    if "hk.coordinator" not in sys.modules:
        coord = types.ModuleType("hk.coordinator")
        coord.HomeKeeperCoordinator = type("HomeKeeperCoordinator", (), {})
        sys.modules["hk.coordinator"] = coord
    spec = importlib.util.spec_from_file_location(
        "hk.todo", str(_COMPONENT_DIR / "todo.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hk.todo"] = module
    spec.loader.exec_module(module)
    return module


todo = _load_todo()
TodoItem = sys.modules["homeassistant.components.todo"].TodoItem
TodoItemStatus = sys.modules["homeassistant.components.todo"].TodoItemStatus
HomeAssistantError = sys.modules["homeassistant.exceptions"].HomeAssistantError


class FakeStore:
    """The slice of ``store.py`` the entity touches, recording what it was asked."""

    def __init__(self, tasks: dict) -> None:
        self._tasks = tasks
        self.completed: list[str] = []
        self.updated: list[tuple[str, dict]] = []
        self.raise_on_complete: Exception | None = None
        self.raise_on_update: Exception | None = None

    def get_task(self, task_id: str):
        return self._tasks.get(task_id)

    async def complete_task(self, task_id: str):
        # The real store raises KeyError for an unknown id *before* recording
        # anything (store.complete_task), so mirror that order here.
        if task_id not in self._tasks:
            raise KeyError(task_id)
        if self.raise_on_complete is not None:
            raise self.raise_on_complete
        self.completed.append(task_id)
        return self._tasks[task_id]

    async def update_task(self, task_id: str, updates: dict):
        if self.raise_on_update is not None:
            raise self.raise_on_update
        self.updated.append((task_id, updates))
        return self._tasks[task_id]


def _entity(*tasks: dict):
    """Build a to-do entity over an in-memory coordinator/store (no __init__)."""
    by_id = {task["id"]: task for task in tasks}
    entity = object.__new__(todo.HomeKeeperTodoListEntity)
    store = FakeStore(by_id)
    calls: list[str] = []

    def _record(marker: str):
        async def _call():
            calls.append(marker)

        return _call

    entity.coordinator = types.SimpleNamespace(
        data=by_id,
        store=store,
        async_settle_buy_tasks=_record("settle"),
        async_request_refresh=_record("refresh"),
    )
    return entity, store, calls


def _task(task_id: str, rec_type: str, **over) -> dict:
    task = {
        "id": task_id,
        "name": f"Task {task_id}",
        "recurrence_type": rec_type,
        "next_due": None,
        "enabled": True,
    }
    task.update(over)
    return task


def _uids(entity) -> list[str]:
    return [item.uid for item in entity.todo_items]


# --- todo_items: the dormancy projection ------------------------------------


def test_completed_one_off_is_dropped() -> None:
    """#221: a do-once task that's done is dormant, so it leaves the list."""
    entity, _store, _calls = _entity(
        _task("done", "one-off", last_completed="2026-06-16T10:00:00-04:00")
    )
    assert _uids(entity) == []


def test_armed_one_off_is_listed_with_its_due_date() -> None:
    entity, _store, _calls = _entity(
        _task(
            "armed",
            "one-off",
            name="Renew passport",
            next_due=DUE.isoformat(),
            notes="bring photos",
        )
    )
    (item,) = entity.todo_items
    assert item.uid == "armed"
    assert item.summary == "Renew passport"
    assert item.status is TodoItemStatus.NEEDS_ACTION
    assert item.due == date(2026, 7, 15)
    assert item.description == "bring photos"


# --- todo_items: the due date is a *local* calendar date (#250) ---------------


def test_due_date_is_taken_in_home_assistants_timezone(monkeypatch) -> None:
    """#250: a ``+00:00`` next_due at local midnight showed the previous day.

    The reporter's own numbers, on Europe/London in BST. Their task's last completion
    was entered through the panel's date picker, which sends local midnight expressed
    in UTC, so ``next_due`` landed on ``+00:00``. Taking ``.date()`` in that offset
    read the 26th while the panel and ``list_tasks`` both read the 27th.
    """
    monkeypatch.setattr(todo.dt_util, "DEFAULT_TIME_ZONE", timezone(timedelta(hours=1)))
    entity, _store, _calls = _entity(
        _task("vacuum", "floating", next_due="2026-08-26T23:00:00+00:00")
    )
    (item,) = entity.todo_items
    assert item.due == date(2026, 8, 27)


def test_due_date_shifts_back_when_local_trails_the_stored_offset(monkeypatch) -> None:
    """The opposite direction, so the conversion cannot pass by doing nothing.

    ``2026-07-15T01:00:00+01:00`` is 2026-07-14 20:00 in a UTC-4 zone, so the local
    date is the 14th even though the stored string opens with the 15th. A fix that
    only ever moved dates forward, or that read the stored offset again, fails here.
    """
    monkeypatch.setattr(
        todo.dt_util, "DEFAULT_TIME_ZONE", timezone(timedelta(hours=-4))
    )
    entity, _store, _calls = _entity(
        _task("filter", "floating", next_due="2026-07-15T01:00:00+01:00")
    )
    (item,) = entity.todo_items
    assert item.due == date(2026, 7, 14)


def test_due_date_is_unchanged_when_the_offset_already_matches_local(
    monkeypatch,
) -> None:
    """A next_due already written in the local offset keeps its date.

    This is the majority case — a completion made "now" is stored with HA's own
    offset — and it is why the bug hid for so long: those tasks were always right.
    """
    monkeypatch.setattr(todo.dt_util, "DEFAULT_TIME_ZONE", timezone(timedelta(hours=1)))
    entity, _store, _calls = _entity(
        _task("live", "floating", next_due="2026-08-27T00:00:00+01:00")
    )
    (item,) = entity.todo_items
    assert item.due == date(2026, 8, 27)


def test_skipped_one_off_is_dropped() -> None:
    """A skipped do-once task is dormant too — no last_completed, still gone."""
    entity, _store, _calls = _entity(_task("skipped", "one-off"))
    assert _uids(entity) == []


def test_recurring_task_stays_listed_after_a_completion() -> None:
    """The skip keys on dormancy, not on "has been completed"."""
    entity, _store, _calls = _entity(
        _task(
            "float",
            "floating",
            next_due=DUE.isoformat(),
            last_completed="2026-06-16T10:00:00-04:00",
        )
    )
    assert _uids(entity) == ["float"]


def test_undated_recurring_task_stays_listed() -> None:
    """Only the dormant *kinds* are dropped: a floating task with no next_due is
    malformed data, and hiding it would make it unreachable from the card."""
    entity, _store, _calls = _entity(_task("float", "floating"))
    assert _uids(entity) == ["float"]


def test_disabled_task_is_dropped() -> None:
    entity, _store, _calls = _entity(
        _task("off", "floating", next_due=DUE.isoformat(), enabled=False)
    )
    assert _uids(entity) == []


@pytest.mark.parametrize("rec_type", ["triggered", "sensor"])
def test_dormant_triggered_and_sensor_stay_dropped(rec_type: str) -> None:
    entity, _store, _calls = _entity(_task("dormant", rec_type))
    assert _uids(entity) == []


@pytest.mark.parametrize("rec_type", ["triggered", "sensor"])
def test_armed_triggered_and_sensor_are_listed(rec_type: str) -> None:
    entity, _store, _calls = _entity(_task("armed", rec_type, next_due=DUE.isoformat()))
    assert _uids(entity) == ["armed"]


# --- async_update_todo_item: completion routing ------------------------------


def test_completing_an_already_completed_one_off_is_ignored() -> None:
    """A second check-off must not duplicate the record of work done once (#221)."""
    task = _task("done", "one-off", last_completed="2026-06-16T10:00:00-04:00")
    entity, store, calls = _entity(task)
    asyncio.run(
        entity.async_update_todo_item(
            TodoItem(uid="done", summary=task["name"], status=TodoItemStatus.COMPLETED)
        )
    )
    assert store.completed == []
    assert calls == []


def test_completing_an_armed_one_off_completes_it() -> None:
    task = _task("armed", "one-off", next_due=DUE.isoformat())
    entity, store, calls = _entity(task)
    asyncio.run(
        entity.async_update_todo_item(
            TodoItem(uid="armed", summary=task["name"], status=TodoItemStatus.COMPLETED)
        )
    )
    assert store.completed == ["armed"]
    assert calls == ["settle"]


def test_completing_a_skipped_one_off_still_completes_it() -> None:
    """Dormant but never completed: the guard is about duplicates, not dormancy."""
    task = _task("skipped", "one-off")
    entity, store, _calls = _entity(task)
    asyncio.run(
        entity.async_update_todo_item(
            TodoItem(
                uid="skipped", summary=task["name"], status=TodoItemStatus.COMPLETED
            )
        )
    )
    assert store.completed == ["skipped"]


def test_completing_a_recurring_task_still_completes_it() -> None:
    task = _task(
        "float",
        "floating",
        next_due=DUE.isoformat(),
        last_completed="2026-06-16T10:00:00-04:00",
    )
    entity, store, _calls = _entity(task)
    asyncio.run(
        entity.async_update_todo_item(
            TodoItem(uid="float", summary=task["name"], status=TodoItemStatus.COMPLETED)
        )
    )
    assert store.completed == ["float"]


def test_completing_an_unknown_uid_still_reaches_the_store() -> None:
    """Hoisting the get_task lookup must not swallow an unknown id.

    ``task`` is now bound before the COMPLETED branch, so ``None`` has to keep
    falling through to the store — which raises, as it did before the hoist.
    """
    entity, store, calls = _entity(_task("float", "floating", next_due=DUE.isoformat()))
    with pytest.raises(KeyError):
        asyncio.run(
            entity.async_update_todo_item(
                TodoItem(uid="ghost", summary="x", status=TodoItemStatus.COMPLETED)
            )
        )
    assert store.completed == []
    assert calls == []


def test_item_without_a_uid_is_ignored() -> None:
    entity, store, calls = _entity(_task("float", "floating", next_due=DUE.isoformat()))
    asyncio.run(
        entity.async_update_todo_item(
            TodoItem(uid=None, summary="x", status=TodoItemStatus.COMPLETED)
        )
    )
    assert store.completed == []
    assert store.updated == []
    assert calls == []


def test_completion_rejected_by_the_store_surfaces_as_ha_error() -> None:
    """A problem-synced task is rejected by the store; the card shows the reason."""
    task = _task("synced", "triggered", next_due=DUE.isoformat())
    entity, store, _calls = _entity(task)
    store.raise_on_complete = todo.TaskValidationError("clear the problem first")
    with pytest.raises(HomeAssistantError):
        asyncio.run(
            entity.async_update_todo_item(
                TodoItem(
                    uid="synced", summary=task["name"], status=TodoItemStatus.COMPLETED
                )
            )
        )


# --- async_update_todo_item: rename/notes path -------------------------------


def test_renaming_an_item_persists_and_refreshes() -> None:
    """The hoisted get_task lookup must leave the NEEDS_ACTION branch intact."""
    task = _task("float", "floating", next_due=DUE.isoformat(), notes="old")
    entity, store, calls = _entity(task)
    asyncio.run(
        entity.async_update_todo_item(
            TodoItem(
                uid="float",
                summary="New name",
                description="new",
                status=TodoItemStatus.NEEDS_ACTION,
            )
        )
    )
    assert store.updated == [("float", {"name": "New name", "notes": "new"})]
    assert calls == ["refresh"]


def test_unchanged_item_writes_nothing() -> None:
    task = _task("float", "floating", next_due=DUE.isoformat(), notes="keep")
    entity, store, calls = _entity(task)
    asyncio.run(
        entity.async_update_todo_item(
            TodoItem(
                uid="float",
                summary=task["name"],
                description="keep",
                status=TodoItemStatus.NEEDS_ACTION,
            )
        )
    )
    assert store.updated == []
    assert calls == []


def test_unknown_uid_on_the_rename_path_is_ignored() -> None:
    entity, store, calls = _entity(_task("float", "floating", next_due=DUE.isoformat()))
    asyncio.run(
        entity.async_update_todo_item(
            TodoItem(uid="ghost", summary="x", status=TodoItemStatus.NEEDS_ACTION)
        )
    )
    assert store.updated == []
    assert calls == []
