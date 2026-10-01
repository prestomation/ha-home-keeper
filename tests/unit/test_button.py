"""Unit tests for the device-page mark-done button (``button.py``).

Like ``test_todo.py``, this loads the real ``button.py`` (and ``entity.py``) under
the synthetic ``hk`` package over the shared HA stub tree, and drives the press
against an in-memory store. Which tasks get a button at all is the pure
``task_entities.has_mark_done_button``, tested in ``test_task_entities.py``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest
from ha_stubs import install_ha_stubs

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)


def _load(name: str) -> types.ModuleType:
    if f"hk.{name}" in sys.modules:
        return sys.modules[f"hk.{name}"]
    spec = importlib.util.spec_from_file_location(
        f"hk.{name}", str(_COMPONENT_DIR / f"{name}.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"hk.{name}"] = module
    spec.loader.exec_module(module)
    return module


def _load_button() -> types.ModuleType:
    install_ha_stubs()
    if "hk.coordinator" not in sys.modules:
        coord = types.ModuleType("hk.coordinator")
        coord.HomeKeeperCoordinator = type("HomeKeeperCoordinator", (), {})
        sys.modules["hk.coordinator"] = coord
    _load("entity")
    return _load("button")


button = _load_button()
HomeAssistantError = sys.modules["homeassistant.exceptions"].HomeAssistantError


class FakeStore:
    def __init__(self, tasks: dict, raise_on_complete: Exception | None = None):
        self._tasks = tasks
        self.completed: list[str] = []
        self.raise_on_complete = raise_on_complete

    def get_task(self, task_id: str):
        return self._tasks.get(task_id)

    async def complete_task(self, task_id: str):
        if task_id not in self._tasks:
            raise KeyError(task_id)
        if self.raise_on_complete is not None:
            raise self.raise_on_complete
        self.completed.append(task_id)
        return self._tasks[task_id]


def _button(task_id: str, *tasks: dict, raise_on_complete=None):
    store = FakeStore({t["id"]: t for t in tasks}, raise_on_complete)
    calls: list[str] = []

    async def _settle():
        calls.append("settle")

    entity = object.__new__(button.HomeKeeperMarkDoneButton)
    entity._task_id = task_id
    entity.coordinator = types.SimpleNamespace(
        store=store, async_settle_buy_tasks=_settle
    )
    return entity, store, calls


def _task(task_id: str, rec_type: str = "floating", **over) -> dict:
    return {
        "id": task_id,
        "name": f"Task {task_id}",
        "recurrence_type": rec_type,
        "next_due": "2026-07-15T09:00:00+00:00",
        "device_id": "d1",
        "enabled": True,
        **over,
    }


def test_press_completes_the_task_and_settles() -> None:
    entity, store, calls = _button("t1", _task("t1"))
    asyncio.run(entity.async_press())
    assert store.completed == ["t1"]
    assert calls == ["settle"]


def test_b15_4_press_on_a_completed_one_off_is_ignored() -> None:
    task = _task(
        "t1", "one-off", next_due=None, last_completed="2026-06-16T10:00:00+00:00"
    )
    entity, store, calls = _button("t1", task)
    asyncio.run(entity.async_press())
    assert store.completed == []
    assert calls == []


def test_b15_4_press_on_an_armed_one_off_completes_it() -> None:
    entity, store, calls = _button("t1", _task("t1", "one-off"))
    asyncio.run(entity.async_press())
    assert store.completed == ["t1"]
    assert calls == ["settle"]


def test_b15_2_store_refusal_is_a_translated_error() -> None:
    err = button.TaskValidationError("scan the tag")
    entity, _store, calls = _button("t1", _task("t1"), raise_on_complete=err)
    with pytest.raises(HomeAssistantError) as caught:
        asyncio.run(entity.async_press())
    assert caught.value.translation_domain == "home_keeper"
    assert caught.value.translation_key == "complete_failed"
    assert caught.value.translation_placeholders == {"error": "scan the tag"}
    assert caught.value.__cause__ is err
    assert calls == []


def test_b15_2_deleted_task_is_a_translated_error() -> None:
    entity, _store, calls = _button("gone", _task("t1"))
    with pytest.raises(HomeAssistantError) as caught:
        asyncio.run(entity.async_press())
    assert caught.value.translation_domain == "home_keeper"
    assert caught.value.translation_key == "task_not_found"
    assert caught.value.translation_placeholders == {"task_id": "gone"}
    assert calls == []
