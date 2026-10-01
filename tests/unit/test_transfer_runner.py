"""The Home Assistant half of import and export: ``transfer_runner.py``.

``transfer.py`` decides what an import does and is tested on its own. This suite
drives the runner that the service and its websocket twin share, with fakes for the
registries and the store, for two things only the runner can get wrong:

* **B04-1.** The runner read ``.id`` off each item of ``DeviceRegistry.devices``.
  Before Home Assistant 2026.9 those items are id strings, so every import and every
  dry run failed. From 2026.9 the collection lists main devices only, so a child
  device read as not on this install.
* **B03-3.** PyYAML is pure Python here, so reading or writing a large document
  takes seconds. The runner must do that work in the executor, off the event loop.

The module is loaded under the synthetic ``hk`` package, the same way
``notifier_harness`` loads ``notifier.py``. Its two HA-importing siblings
(``devices``, ``coordinator``) are faked only while it loads, so the fakes do not
leak into the suites that load the real ones.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import threading
import types
from collections import UserDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import hk_transfer as tr
import pytest
from ha_stubs import install_ha_stubs

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)
TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)


def _load_runner() -> types.ModuleType:
    install_ha_stubs()
    fake_devices = types.ModuleType("hk.devices")
    fake_devices.area_names = lambda hass: {}

    async def _reconcile(hass, entry, store):  # pragma: no cover - dry runs only
        return None

    fake_devices.async_reconcile_assets = _reconcile
    fake_coordinator = types.ModuleType("hk.coordinator")
    fake_coordinator.HomeKeeperCoordinator = object
    saved = {name: sys.modules.get(name) for name in ("hk.devices", "hk.coordinator")}
    sys.modules["hk.devices"] = fake_devices
    sys.modules["hk.coordinator"] = fake_coordinator
    # ``from . import devices`` reads the attribute on the package first. Another
    # suite that loaded the real ``hk.devices`` leaves it there, so set it too.
    package = sys.modules["hk"]
    saved_attr = getattr(package, "devices", None)
    package.devices = fake_devices
    try:
        spec = importlib.util.spec_from_file_location(
            "hk.transfer_runner", str(_COMPONENT_DIR / "transfer_runner.py")
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        if saved_attr is None:
            del package.devices
        else:
            package.devices = saved_attr
    module.dt_util = types.SimpleNamespace(now=lambda: NOW)
    module.ar = types.SimpleNamespace(
        async_get=lambda hass: types.SimpleNamespace(async_list_areas=lambda: [])
    )
    return module


runner = _load_runner()


class _Device:
    def __init__(self, device_id: str) -> None:
        self.id = device_id


class _DeviceItems(UserDict):
    """The pre-2026.9 ``devices``: a ``UserDict`` keyed by id, so it iterates ids."""


class _OldRegistry:
    def __init__(self, *devices: _Device) -> None:
        self.devices = _DeviceItems({d.id: d for d in devices})

    def async_get(self, device_id):
        return self.devices.get(device_id)


class _NewRegistry:
    """2026.9: ``devices`` lists main devices; ``async_get`` answers a child too."""

    def __init__(self, main: list[_Device], children: list[_Device]) -> None:
        self.devices = list(main)
        self._by_id = {d.id: d for d in [*main, *children]}

    def async_get(self, device_id):
        return self._by_id.get(device_id)


class _Store:
    def __init__(self, tasks=None, assets=None) -> None:
        self._tasks = tasks or {}
        self._assets = assets or {}

    def get_tasks(self):
        return self._tasks

    def get_assets(self):
        return self._assets

    def list_tasks(self):
        return list(self._tasks.values())

    def list_assets(self):
        return list(self._assets.values())


class _Hass:
    async def async_add_executor_job(self, func, *args):
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)


def _coord(store: _Store | None = None) -> Any:
    return types.SimpleNamespace(
        store=store or _Store(), entry=types.SimpleNamespace(entry_id="e")
    )


def _dry_run(registry, document) -> dict:
    runner.dr = types.SimpleNamespace(async_get=lambda hass: registry)
    data = {"document": document, "dry_run": True}
    return asyncio.run(runner.async_import_document(_Hass(), _coord(), data))


def _tasks_on(*device_ids: str) -> dict:
    return {
        "home_keeper": {"format": 1},
        "tasks": [
            {"name": f"Task {i}", "device_id": device_id}
            for i, device_id in enumerate(device_ids)
        ],
    }


def _device_warnings(report: dict) -> list[str]:
    return [p["path"] for p in report["problems"] if p["path"].endswith("device_id")]


def test_b04_1_a_dry_run_works_on_the_pre_2026_9_registry():
    report = _dry_run(_OldRegistry(_Device("dev-a")), _tasks_on("dev-a", "dev-gone"))
    assert report["ok"] is True
    assert report["dry_run"] is True
    assert _device_warnings(report) == ["tasks[1].device_id"]


def test_b04_1_a_task_on_a_child_device_keeps_its_device():
    registry = _NewRegistry([_Device("dev-a")], [_Device("dev-child")])
    report = _dry_run(registry, _tasks_on("dev-a", "dev-child", "dev-gone"))
    assert report["ok"] is True
    assert _device_warnings(report) == ["tasks[2].device_id"]


def test_b03_3_the_import_reads_its_text_off_the_event_loop(monkeypatch):
    threads: list[int] = []
    original = tr.parse_document

    def spy(text):
        threads.append(threading.get_ident())
        return original(text)

    monkeypatch.setattr(tr, "parse_document", spy)
    loop_thread: list[int] = []

    async def run():
        loop_thread.append(threading.get_ident())
        runner.dr = types.SimpleNamespace(async_get=lambda hass: _OldRegistry())
        data = {"document": "home_keeper: {format: 1}\ntasks: []\n", "dry_run": True}
        return await runner.async_import_document(_Hass(), _coord(), data)

    report = asyncio.run(run())
    assert report["ok"] is True
    assert len(threads) == 1
    assert threads[0] != loop_thread[0]


@pytest.mark.parametrize("dry_run", [True, False])
def test_b03_3_a_syntax_error_from_the_executor_is_a_problem_row(dry_run):
    runner.dr = types.SimpleNamespace(async_get=lambda hass: _OldRegistry())
    data = {"document": "tasks: [\n", "dry_run": dry_run}
    report = asyncio.run(runner.async_import_document(_Hass(), _coord(), data))
    assert report["ok"] is False
    assert report["dry_run"] is dry_run
    (problem,) = report["problems"]
    assert problem["path"].startswith("line ")
    assert problem["message"].startswith("this file is not valid YAML")


def test_b03_3_the_export_writes_its_yaml_off_the_event_loop(monkeypatch):
    calls: list[tuple[int, Any]] = []
    original = tr.document_to_yaml

    def spy(document):
        calls.append((threading.get_ident(), document))
        return original(document)

    monkeypatch.setattr(tr, "document_to_yaml", spy)
    task = tr.models.build_task({"name": "Furnace filter"}, now=NOW)
    store = _Store(tasks={task["id"]: task})
    loop_thread: list[int] = []

    async def run():
        loop_thread.append(threading.get_ident())
        return await runner.async_export_document(_Hass(), _coord(store), {})

    result = asyncio.run(run())
    ((thread, handed),) = calls
    assert thread != loop_thread[0]
    # The executor gets its own copy, and the text says what the document says.
    assert handed == result["document"]
    assert handed is not result["document"]
    assert tr.parse_document(result["yaml"]) == result["document"]
