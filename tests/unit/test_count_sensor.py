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
from datetime import timedelta
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


# ── a live profile filter (#467) ─────────────────────────────────────────────
def _profile_sensor(monkeypatch, stored_profiles: list[dict]) -> object:
    entity = sensor.HomeKeeperTaskCountSensor(
        types.SimpleNamespace(entry="the-entry"),
        unique_id="home_keeper_profile_p1_tasks",
        translation_key="profile_tasks",
        placeholders={"profile": "Chores"},
        task_filter={"status": "overdue"},
        profile_id="p1",
    )
    monkeypatch.setattr(
        sensor,
        "current_options",
        lambda entry: {"profiles": stored_profiles} if entry == "the-entry" else {},
    )
    return entity


def test_a_profile_count_reads_the_filter_the_options_hold_now(monkeypatch) -> None:
    """An options change that keeps the profiles does not reload the entry."""
    entity = _profile_sensor(
        monkeypatch,
        [
            {"id": "p0", "filter": {"status": "due_soon"}},
            {"id": "p1", "filter": {"status": "all"}},
        ],
    )
    assert entity._task_filter() == {"status": "all"}


def test_a_profile_count_keeps_its_filter_when_the_profile_is_gone(monkeypatch) -> None:
    """Between the save and the reload that removes the sensor."""
    entity = _profile_sensor(monkeypatch, [{"id": "p0", "filter": {"status": "all"}}])
    assert entity._task_filter() == {"status": "overdue"}


def test_the_all_tasks_count_has_no_profile(monkeypatch) -> None:
    entity = sensor.HomeKeeperTaskCountSensor(
        types.SimpleNamespace(entry="the-entry"),
        unique_id="home_keeper_tasks",
        translation_key="all_tasks",
        placeholders={},
        task_filter={"status": "overdue"},
    )
    monkeypatch.setattr(
        sensor, "current_options", lambda entry: pytest.fail("no options read")
    )
    assert entity._task_filter() == {"status": "overdue"}


# ── cost sensors (#460) ──────────────────────────────────────────────────────


def _coordinator(tasks: dict, assets: list) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        data=tasks, store=types.SimpleNamespace(list_assets=lambda: assets)
    )


def _ago(days: float) -> str:
    from homeassistant.util import dt as dt_util

    return (dt_util.now() - timedelta(days=days)).isoformat()


_COST_TASKS = {
    "a": {
        "id": "a",
        "name": "Fix shower",
        "completions": [{"ts": _ago(5), "cost": 3.19}, {"ts": _ago(45), "cost": 20}],
    }
}
_COST_ASSETS = [
    {
        "id": "heater",
        "cost": 900,
        "task_history": [
            {"task_id": "gone", "completions": [{"ts": _ago(400), "cost": 50}]}
        ],
    },
    {"id": "fridge", "cost": 1200.5},
    {"id": "lamp"},
]


def _written(entity) -> None:
    entity.async_write_ha_state = lambda: None
    entity._handle_coordinator_update()


def test_spend_window_sensor() -> None:
    entity = sensor.HomeKeeperSpendSensor(
        _coordinator(_COST_TASKS, _COST_ASSETS), days=30
    )
    _written(entity)
    assert entity.unique_id == "home_keeper_spend_30d"
    assert entity.translation_key == "spend_window"
    assert entity.translation_placeholders == {"days": "30"}
    assert entity.state_class is None
    assert entity.device_class == "monetary"
    assert entity.native_value == 3.19
    assert entity.extra_state_attributes["count"] == 1
    assert set(entity.extra_state_attributes) == {"count"}


def test_spend_all_time_sensor_counts_archived_history() -> None:
    entity = sensor.HomeKeeperSpendSensor(
        _coordinator(_COST_TASKS, _COST_ASSETS), days=None
    )
    _written(entity)
    assert entity.unique_id == "home_keeper_spend_all"
    assert entity.translation_key == "spend_all"
    assert entity.state_class == "total"
    assert entity.native_value == 73.19
    oldest = _COST_ASSETS[0]["task_history"][0]["completions"][0]["ts"]
    assert entity.extra_state_attributes == {"count": 3, "first": oldest}


def test_purchase_sensor() -> None:
    entity = sensor.HomeKeeperPurchaseSensor(_coordinator({}, _COST_ASSETS))
    _written(entity)
    assert entity.unique_id == "home_keeper_purchases"
    assert entity.translation_key == "purchases_total"
    assert entity.state_class == "total"
    assert entity.native_value == 2100.5
    assert entity.extra_state_attributes == {"count": 2}


def test_cost_sensor_unit_is_the_currency() -> None:
    entity = sensor.HomeKeeperPurchaseSensor(_coordinator({}, []))
    entity.hass = types.SimpleNamespace(config=types.SimpleNamespace(currency="EUR"))
    assert entity.native_unit_of_measurement == "EUR"
    entity.hass.config.currency = ""
    assert entity.native_unit_of_measurement is None


def test_cost_entities_follow_the_windows() -> None:
    entities, live = sensor._cost_entities(_coordinator({}, []), object())
    assert [e.unique_id for e in entities] == [
        "home_keeper_spend_30d",
        "home_keeper_spend_60d",
        "home_keeper_spend_all",
        "home_keeper_purchases",
    ]
    assert live == {e.unique_id for e in entities}
