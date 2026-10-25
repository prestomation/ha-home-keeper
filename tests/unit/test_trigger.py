"""Unit tests for ``trigger.py``, the Home Keeper triggers, on a real Home Assistant.

The suite loads the real ``trigger.py`` under the synthetic ``hk`` package. A fake
hass gives a bus that keeps the listeners, so a test fires a bus event and reads
what the trigger ran. The registries and Home Assistant's target helper are
replaced on the loaded module, so each test sets what a target resolves to. The
Docker integration tests cover the real registries.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("homeassistant")
vol = pytest.importorskip("voluptuous")

from homeassistant.const import __version__ as HA_VERSION  # noqa: E402

# The trigger platform needs the Home Assistant that Home Keeper supports
# (ci/oldest-ha.env). On Python 3.12, pip resolves an older Home Assistant that has
# no such API, so this module skips there. The Docker tiers test the real platform.
_OLDEST = (2026, 1)
if tuple(int(part) for part in HA_VERSION.split(".")[:2]) < _OLDEST:
    pytest.skip(
        f"Home Assistant {HA_VERSION} is older than {_OLDEST}",
        allow_module_level=True,
    )

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)


def _load_trigger() -> types.ModuleType:
    if "hk.trigger" in sys.modules:
        return sys.modules["hk.trigger"]
    spec = importlib.util.spec_from_file_location(
        "hk.trigger", str(_COMPONENT_DIR / "trigger.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hk.trigger"] = module
    spec.loader.exec_module(module)
    return module


trigger = _load_trigger()
api_surface = sys.modules["hk.api_surface"]

from homeassistant.helpers.trigger import TriggerConfig  # noqa: E402

TASK = "3f1c2d4e5a6b4c7d8e9f0a1b2c3d4e5f"


class FakeBus:
    def __init__(self) -> None:
        self.listeners: dict[str, list] = {}

    def async_listen(self, name, handler):
        self.listeners.setdefault(name, []).append(handler)

        def remove() -> None:
            self.listeners[name].remove(handler)

        return remove

    def fire(self, name: str, data: dict) -> types.SimpleNamespace:
        event = types.SimpleNamespace(event_type=name, data=data, context="ctx")
        for handler in list(self.listeners.get(name, [])):
            handler(event)
        return event


def _attach(key: str, target: dict | None = None):
    """Attach the trigger *key*. Return the bus, the runs and the remover."""
    hass = types.SimpleNamespace(bus=FakeBus())
    cls = trigger.TRIGGER_CLASSES[key]
    instance = cls(hass, TriggerConfig(key=f"home_keeper.{key}", target=target))
    runs: list[tuple] = []

    def run_action(payload, description, context=None):
        runs.append((payload, description, context))

    remove = asyncio.run(instance.async_attach_runner(run_action))
    return hass.bus, runs, remove


@pytest.fixture
def resolved(monkeypatch):
    """Set what each target resolves to, for the tests that attach a trigger."""
    holder = {"refs": make_refs()}

    def fake_resolve(hass, target):
        holder["target"] = target
        return holder["refs"]

    monkeypatch.setattr(trigger, "resolve_target", fake_resolve)
    return holder


def make_refs(**kwargs):
    targets = sys.modules["hk.trigger_targets"]
    return targets.TargetRefs(**kwargs)


def test_each_model_trigger_is_offered() -> None:
    triggers = asyncio.run(trigger.async_get_triggers(None))
    assert list(triggers) == [spec.key for spec in api_surface.TRIGGERS]
    for key, cls in triggers.items():
        assert cls.spec.key == key
        assert issubclass(cls, trigger.HomeKeeperTrigger)
    assert triggers["task_overdue"].__name__ == "TaskOverdueTrigger"


def test_a_targeted_trigger_requires_a_target() -> None:
    cls = trigger.TRIGGER_CLASSES["task_completed"]
    config = asyncio.run(
        cls.async_validate_config(None, {"target": {"device_id": "dev1"}})
    )
    assert config == {"target": {"device_id": ["dev1"]}, "options": {}}
    with pytest.raises(vol.Invalid):
        asyncio.run(cls.async_validate_config(None, {}))


def test_an_untargeted_trigger_takes_no_target() -> None:
    cls = trigger.TRIGGER_CLASSES["data_exported"]
    assert asyncio.run(cls.async_validate_config(None, {})) == {"options": {}}
    with pytest.raises(vol.Invalid):
        asyncio.run(cls.async_validate_config(None, {"target": {"device_id": "dev1"}}))


def test_trigger_listens_on_its_bus_event_only(resolved) -> None:
    bus, _runs, remove = _attach("task_overdue", {"device_id": ["dev1"]})
    assert list(bus.listeners) == ["home_keeper_task_overdue"]
    remove()
    assert bus.listeners["home_keeper_task_overdue"] == []


def test_trigger_runs_with_the_bus_event_when_the_task_is_in_the_target(
    resolved,
) -> None:
    resolved["refs"] = make_refs(task_ids=frozenset({TASK}))
    bus, runs, _ = _attach("task_completed", {"entity_id": ["binary_sensor.x"]})
    event = bus.fire("home_keeper_task_completed", {"task_id": TASK})
    assert runs == [({"event": event}, "event 'home_keeper_task_completed'", "ctx")]
    assert resolved["target"] == {"entity_id": ["binary_sensor.x"]}


def test_trigger_skips_an_event_outside_the_target(resolved) -> None:
    resolved["refs"] = make_refs(task_ids=frozenset({TASK}))
    bus, runs, _ = _attach("task_completed", {"entity_id": ["binary_sensor.x"]})
    bus.fire("home_keeper_task_completed", {"task_id": "other", "device_id": None})
    assert runs == []


def test_part_trigger_uses_the_stock_rule(resolved) -> None:
    resolved["refs"] = make_refs(part_keys=frozenset({("a1", "p1")}))
    bus, runs, _ = _attach("part_low_stock", {"device_id": ["dev1"]})
    bus.fire("home_keeper_part_low_stock", {"asset_id": "a1", "part_id": "p2"})
    bus.fire("home_keeper_part_low_stock", {"asset_id": "a1", "part_id": "p1"})
    assert len(runs) == 1


def test_untargeted_trigger_runs_for_each_event(resolved) -> None:
    bus, runs, _ = _attach("companion_connected")
    bus.fire("home_keeper_companion_connected", {"domain": "x"})
    assert len(runs) == 1
    assert "target" not in resolved


def test_trigger_resolves_the_target_again_for_each_event(resolved) -> None:
    bus, runs, _ = _attach("task_overdue", {"device_id": ["dev1"]})
    resolved["refs"] = make_refs()
    bus.fire("home_keeper_task_overdue", {"task_id": TASK})
    resolved["refs"] = make_refs(device_ids=frozenset({"dev1"}))
    bus.fire("home_keeper_task_overdue", {"task_id": TASK, "device_id": "dev1"})
    assert len(runs) == 1


# ── resolve_target ───────────────────────────────────────────────────────────


class FakeRegistry:
    def __init__(self, entries: dict) -> None:
        self._entries = entries

    def async_get(self, entity_id):
        return self._entries.get(entity_id)


def _entry(platform: str, unique_id: str, device_id: str | None):
    return types.SimpleNamespace(
        platform=platform, unique_id=unique_id, device_id=device_id
    )


def test_resolve_target_reads_home_keeper_entities_and_the_named_places(
    monkeypatch,
) -> None:
    from homeassistant.helpers.target import SelectedEntities

    selected = SelectedEntities(
        referenced={"binary_sensor.filter_overdue", "light.kitchen"},
        indirectly_referenced={"sensor.service_tasks", "number.part_stock"},
        referenced_devices={"dev1"},
        referenced_areas={"garage"},
    )
    calls = {}

    def fake_extract(hass, selection, expand_group=True, **kwargs):
        calls["selection"] = selection
        calls["expand_group"] = expand_group
        return selected

    registry = FakeRegistry(
        {
            "binary_sensor.filter_overdue": _entry(
                "home_keeper", f"home_keeper_{TASK}_overdue", "dev_self"
            ),
            "light.kitchen": _entry("hue", f"home_keeper_{TASK}x_overdue", "dev2"),
            "sensor.service_tasks": _entry(
                "home_keeper", "home_keeper_tasks", "dev_other"
            ),
            "number.part_stock": _entry(
                "home_keeper", "home_keeper_asset_a1_part_p1_stock", "dev1"
            ),
        }
    )
    monkeypatch.setattr(
        trigger.target_helpers, "async_extract_referenced_entity_ids", fake_extract
    )
    monkeypatch.setattr(trigger.er, "async_get", lambda hass: registry)
    monkeypatch.setattr(trigger.dr, "async_get", lambda hass: "devreg")
    monkeypatch.setattr(
        trigger,
        "find_devices",
        lambda reg, identifiers: [types.SimpleNamespace(id="dev_service")],
    )

    refs = trigger.resolve_target(None, {"label_id": ["outdoor"]})
    assert calls["expand_group"] is False
    assert calls["selection"].label_ids == {"outdoor"}
    assert refs.task_ids == frozenset({TASK})
    assert refs.part_keys == frozenset({("a1", "p1")})
    assert refs.device_ids == frozenset({"dev1"})
    assert refs.area_ids == frozenset({"garage"})
    assert refs.label_ids == frozenset({"outdoor"})
    assert not refs.everything


def test_resolve_target_sees_the_service_device(monkeypatch) -> None:
    from homeassistant.helpers.target import SelectedEntities

    selected = SelectedEntities(referenced={"todo.tasks"})
    registry = FakeRegistry(
        {"todo.tasks": _entry("home_keeper", "home_keeper_tasks", "dev_service")}
    )
    monkeypatch.setattr(
        trigger.target_helpers,
        "async_extract_referenced_entity_ids",
        lambda hass, selection, expand_group=True: selected,
    )
    monkeypatch.setattr(trigger.er, "async_get", lambda hass: registry)
    monkeypatch.setattr(trigger.dr, "async_get", lambda hass: "devreg")
    seen = {}

    def fake_find(reg, identifiers):
        seen["identifiers"] = identifiers
        return [types.SimpleNamespace(id="dev_service")]

    monkeypatch.setattr(trigger, "find_devices", fake_find)
    assert trigger.resolve_target(None, {"entity_id": ["todo.tasks"]}).everything
    assert seen["identifiers"] == {("home_keeper", "service")}

    monkeypatch.setattr(trigger, "find_devices", lambda reg, identifiers: [])
    assert not trigger.resolve_target(None, {"entity_id": ["todo.tasks"]}).everything
