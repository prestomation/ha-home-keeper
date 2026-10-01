"""The count sensor counts once per state write (X08-4).

``sensor.py`` needs Home Assistant's real ``sensor`` component, so this suite skips
when Home Assistant is not installed. Its HA-bound siblings are doubles, present only
while the module body runs, the same way ``test_todo_list_sync.py`` loads its module.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("homeassistant.components.sensor")

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)


@contextlib.contextmanager
def _borrowed(modules: dict[str, types.ModuleType]) -> Iterator[None]:
    saved = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        yield
    finally:
        for name, prior in saved.items():
            if prior is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior


def _fake(name: str, **attrs: object) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def _load_sensor() -> types.ModuleType:
    from homeassistant.helpers.update_coordinator import CoordinatorEntity

    doubles = {
        "hk.coordinator": _fake(
            "hk.coordinator", HomeKeeperCoordinator=type("C", (), {})
        ),
        "hk.devices": _fake("hk.devices", service_device_info=lambda: None),
        "hk.entity": _fake(
            "hk.entity",
            HomeKeeperTaskEntity=CoordinatorEntity,
            prune_registry_entries=lambda *a: None,
        ),
        "hk.options": _fake("hk.options", current_options=lambda entry: {}),
        "hk.sensor_watcher": _fake("hk.sensor_watcher", read_sensor_value=None),
        "hk.notifier": _fake(
            "hk.notifier", effective_filter_tasks=lambda hass, tasks: tasks
        ),
    }
    spec = importlib.util.spec_from_file_location(
        "hk.sensor_x08_4", str(_COMPONENT_DIR / "sensor.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    hk = sys.modules["hk"]
    saved_notifier = getattr(hk, "notifier", None)
    with _borrowed(doubles):
        # ``from . import notifier`` reads the package attribute first.
        hk.notifier = doubles["hk.notifier"]
        try:
            spec.loader.exec_module(module)
        finally:
            if saved_notifier is None:
                del hk.notifier
            else:
                hk.notifier = saved_notifier
    return module


sensor = _load_sensor()


def _count_sensor():
    entity = object.__new__(sensor.HomeKeeperTaskCountSensor)
    calls: list[int] = []

    def _counts() -> dict:
        calls.append(1)
        return {"state": 3, "total": 7, "next_task_id": "t1"}

    entity._counts = _counts
    entity.async_write_ha_state = lambda: None
    return entity, calls


def test_x08_4_coordinator_update_counts_once_for_state_and_attributes() -> None:
    entity, calls = _count_sensor()
    entity._handle_coordinator_update()
    assert entity.native_value == 3
    assert entity.extra_state_attributes == {"total": 7, "next_task_id": "t1"}
    assert entity.native_value == 3
    assert len(calls) == 1


def test_x08_4_the_first_write_has_counts() -> None:
    entity, calls = _count_sensor()
    entity.coordinator = types.SimpleNamespace(
        async_add_listener=lambda *a, **k: lambda: None
    )
    entity.coordinator_context = None
    entity.async_on_remove = lambda func: None
    asyncio.run(entity.async_added_to_hass())
    assert entity.native_value == 3
    assert entity.extra_state_attributes == {"total": 7, "next_task_id": "t1"}
    assert len(calls) == 1
