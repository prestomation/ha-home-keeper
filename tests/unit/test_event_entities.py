"""Unit tests for the event entities (``event.py``) and their model in ``api_surface``.

The suite loads the real ``event.py`` under the synthetic ``hk`` package over the
shared HA stub tree, as ``test_button.py`` does. The bus is a fake that keeps the
listeners, so a test fires an event at the entity and reads what it recorded.
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


def _load_event() -> types.ModuleType:
    install_ha_stubs()
    if "hk.coordinator" not in sys.modules:
        coord = types.ModuleType("hk.coordinator")
        coord.HomeKeeperCoordinator = type("HomeKeeperCoordinator", (), {})
        sys.modules["hk.coordinator"] = coord
    _load("entity")
    return _load("event")


event = _load_event()
api_surface = sys.modules["hk.api_surface"]


class FakeBus:
    def __init__(self) -> None:
        self.listeners: dict[str, list] = {}

    def async_listen(self, name, handler):
        self.listeners.setdefault(name, []).append(handler)

        def remove() -> None:
            self.listeners[name].remove(handler)

        return remove

    def fire(self, name: str, data: dict) -> None:
        for handler in list(self.listeners.get(name, [])):
            handler(types.SimpleNamespace(event_type=name, data=data))


@pytest.fixture(autouse=True)
def _no_restore(monkeypatch) -> None:
    """Skip the base class setup, which restores the last state from a real hass.

    The suite runs on the stub tree and on a real Home Assistant install, so it
    replaces the base hooks it calls instead of depending on either one.
    """

    async def noop(self) -> None:
        return None

    monkeypatch.setattr(event.EventEntity, "async_added_to_hass", noop)


def _added(entity) -> FakeBus:
    """Add *entity* to a fake hass, and record what it triggers and writes."""
    bus = FakeBus()
    entity.hass = types.SimpleNamespace(bus=bus)
    entity.writes = 0
    entity.removers = []

    def write() -> None:
        entity.writes += 1

    def trigger(event_type, event_attributes=None) -> None:
        entity.last_event_type = event_type
        entity.last_event_attributes = event_attributes

    entity.async_write_ha_state = write
    entity.async_on_remove = entity.removers.append
    entity._trigger_event = trigger
    asyncio.run(entity.async_added_to_hass())
    return bus


def _device(device_id: str):
    return types.SimpleNamespace(id=device_id)


# ── The model ────────────────────────────────────────────────────────────────


def test_event_type_is_the_bus_name_without_the_domain() -> None:
    assert api_surface.event_entity_type("home_keeper_task_completed") == (
        "task_completed"
    )


def test_global_entity_mirrors_every_fired_event_with_a_payload() -> None:
    expected = {
        spec.name
        for spec in api_surface.EVENTS
        if spec.direction == "fired" and spec.payload != "none"
    }
    assert set(event.GLOBAL_EVENTS.values()) == expected
    assert "home_keeper_register_companions" not in expected
    assert "home_keeper_companion_connected" in expected


def test_device_entity_mirrors_only_events_with_a_device_id() -> None:
    payloads = {spec.name: spec.payload for spec in api_surface.EVENTS}
    assert event.DEVICE_EVENTS
    assert {payloads[name] for name in event.DEVICE_EVENTS.values()} == {
        "task",
        "stock",
        "asset",
    }
    for payload in api_surface.EVENT_ENTITY_DEVICE_PAYLOADS:
        keys = {f.name for f in api_surface.PAYLOAD_SPINES[payload]}
        assert "device_id" in keys, payload
    assert set(event.DEVICE_EVENTS) < set(event.GLOBAL_EVENTS)


def test_dropped_fields_are_real_payload_keys_with_a_reason() -> None:
    keys = {f.name for spine in api_surface.PAYLOAD_SPINES.values() for f in spine}
    keys |= {f.name for spec in api_surface.EVENTS for f in spec.extra}
    for name, reason in api_surface.EVENT_ENTITY_DROPPED_FIELDS.items():
        assert name in keys, name
        assert reason.strip(), name


# The declared types a kept payload field may have: values that stay small.
_SMALL_TYPES = frozenset(
    {"bool", "int", "float", "str", "str | None", "int | None", "float | None"}
    | {"list[str]"}
)


def test_kept_payload_fields_hold_only_small_values() -> None:
    """A payload key that an event entity keeps has a known small type.

    The recorder keeps each event's attributes. A new payload field must have a
    type in ``_SMALL_TYPES``, or go in ``EVENT_ENTITY_DROPPED_FIELDS`` with a
    reason. A field with no type, or a type such as ``dict``, ``list[dict]`` or
    ``Any``, fails this test until someone makes that choice.
    """
    fields = [f for spine in api_surface.PAYLOAD_SPINES.values() for f in spine]
    fields += [f for spec in api_surface.EVENTS for f in spec.extra]
    dropped = api_surface.EVENT_ENTITY_DROPPED_FIELDS
    # Dropped by key name, the same way ``event.event_attributes`` drops them.
    unsafe = sorted(
        {
            f"{f.name}: {f.type!r}"
            for f in fields
            if f.name not in dropped and f.type.strip() not in _SMALL_TYPES
        }
    )
    assert unsafe == [], {
        "kept_fields_without_a_small_type": unsafe,
        "fix": "add each one to api_surface.EVENT_ENTITY_DROPPED_FIELDS with a "
        "reason, or give it a small type",
    }


def test_event_attributes_drop_the_large_keys_only() -> None:
    data = {
        "task_id": "t1",
        "name": "Filter",
        "device_id": "d1",
        "source": {"big": True},
        "managed_by": None,
        "task_chips": [],
        "active_season": None,
        "note": "long text",
        "photo": "/x.jpg",
        "cost": 4.5,
    }
    assert event.event_attributes(data) == {
        "task_id": "t1",
        "name": "Filter",
        "device_id": "d1",
        "cost": 4.5,
    }


# ── The entities ─────────────────────────────────────────────────────────────


def test_device_entity_records_an_event_for_its_device() -> None:
    entity = event.HomeKeeperDeviceEventEntity(_device("dev1"))
    bus = _added(entity)
    assert entity._attr_unique_id == "home_keeper_device_dev1_events"
    assert entity.device_entry.id == "dev1"
    assert entity._attr_translation_key == "device_events"
    assert entity._attr_event_types == list(event.DEVICE_EVENTS)

    bus.fire(
        "home_keeper_task_completed",
        {"task_id": "t1", "device_id": "dev1", "note": "x", "origin": "button"},
    )
    assert entity.last_event_type == "task_completed"
    assert entity.last_event_attributes == {
        "task_id": "t1",
        "device_id": "dev1",
        "origin": "button",
    }
    assert entity.writes == 1


def test_device_entity_ignores_another_device_and_no_device() -> None:
    entity = event.HomeKeeperDeviceEventEntity(_device("dev1"))
    bus = _added(entity)
    bus.fire("home_keeper_task_overdue", {"task_id": "t1", "device_id": "dev2"})
    bus.fire("home_keeper_task_overdue", {"task_id": "t2", "device_id": None})
    assert not hasattr(entity, "last_event_type")
    assert entity.writes == 0


def test_appliance_with_no_device_yet_reaches_only_the_global_entity() -> None:
    """A virtual appliance's device_id is None until its device exists."""
    device = event.HomeKeeperDeviceEventEntity(_device("dev1"))
    glob = event.HomeKeeperGlobalEventEntity()
    device_bus = _added(device)
    global_bus = _added(glob)
    data = {"asset_id": "a1", "asset_name": "Heater", "device_id": None}
    device_bus.fire("home_keeper_asset_created", data)
    global_bus.fire("home_keeper_asset_created", data)
    assert device.writes == 0
    assert glob.last_event_type == "asset_created"


def test_device_entity_gets_part_and_appliance_events() -> None:
    entity = event.HomeKeeperDeviceEventEntity(_device("dev1"))
    bus = _added(entity)
    bus.fire("home_keeper_part_low_stock", {"part_id": "p1", "device_id": "dev1"})
    assert entity.last_event_type == "part_low_stock"
    bus.fire("home_keeper_asset_archived", {"asset_id": "a1", "device_id": "dev1"})
    assert entity.last_event_type == "asset_archived"
    assert entity.writes == 2


def test_device_entity_does_not_listen_for_companion_events() -> None:
    entity = event.HomeKeeperDeviceEventEntity(_device("dev1"))
    bus = _added(entity)
    assert "home_keeper_companion_connected" not in bus.listeners
    assert "home_keeper_task_completed" in bus.listeners


def test_global_entity_records_every_event() -> None:
    entity = event.HomeKeeperGlobalEventEntity()
    bus = _added(entity)
    assert entity._attr_unique_id == "home_keeper_events"
    assert entity._attr_translation_key == "home_keeper_events"
    assert entity._attr_device_info is not None
    bus.fire("home_keeper_task_created", {"task_id": "t1", "device_id": None})
    assert entity.last_event_type == "task_created"
    bus.fire("home_keeper_companion_connected", {"domain": "x", "name": "X"})
    assert entity.last_event_type == "companion_connected"
    assert entity.last_event_attributes == {"domain": "x", "name": "X"}
    assert entity.writes == 2


def test_listeners_are_removed_with_the_entity() -> None:
    entity = event.HomeKeeperGlobalEventEntity()
    bus = _added(entity)
    assert len(entity.removers) == len(event.GLOBAL_EVENTS)
    for remove in entity.removers:
        remove()
    assert not any(bus.listeners.values())


def test_unknown_event_type_is_ignored() -> None:
    entity = event.HomeKeeperDeviceEventEntity(_device("dev1"))
    entity._events = {"task_completed": "home_keeper_task_completed"}
    entity._attr_event_types = ["task_completed"]
    _added(entity)
    entity._async_handle_event(
        types.SimpleNamespace(
            event_type="home_keeper_task_overdue", data={"device_id": "dev1"}
        )
    )
    assert not hasattr(entity, "last_event_type")


# ── Which devices get an entity ──────────────────────────────────────────────


class FakeCoordinator:
    def __init__(self, tasks, assets, known) -> None:
        self.data = {task["id"]: task for task in tasks}
        self.store = types.SimpleNamespace(list_assets=lambda: assets)
        self._known = known

    def device_attached_task_ids(self):
        return [
            tid
            for tid, task in self.data.items()
            if task.get("device_id") and task.get("enabled", True)
        ]

    def device_entry_for_device_id(self, device_id):
        return _device(device_id) if device_id in self._known else None


def test_event_devices_from_tasks_and_appliances() -> None:
    coordinator = FakeCoordinator(
        tasks=[
            {"id": "t1", "device_id": "thermostat"},
            {"id": "t2", "device_id": "thermostat"},
            {"id": "t3", "device_id": "gone"},
            {"id": "t4", "device_id": "off", "enabled": False},
            {"id": "t5", "device_id": None},
        ],
        assets=[
            {"id": "a1", "device_id": "heater"},
            {"id": "a2", "device_id": "thermostat"},
            {"id": "a3", "device_id": None},
        ],
        known={"thermostat", "heater", "off"},
    )
    ids = [device.id for device in event.event_devices(coordinator)]
    assert ids == ["thermostat", "heater"]


def test_setup_prunes_stale_device_entities_only(monkeypatch) -> None:
    coordinator = FakeCoordinator(
        tasks=[{"id": "t1", "device_id": "heater"}], assets=[], known={"heater"}
    )
    seen = {}

    def fake_prune(hass, entry, domain, keep):
        seen["domain"] = domain
        seen["keep"] = keep

    monkeypatch.setattr(event, "prune_registry_entries", fake_prune)
    added = []
    entry = types.SimpleNamespace(runtime_data=coordinator)
    asyncio.run(event.async_setup_entry(None, entry, added.extend))

    assert [type(e).__name__ for e in added] == [
        "HomeKeeperGlobalEventEntity",
        "HomeKeeperDeviceEventEntity",
    ]
    keep = seen["keep"]
    assert seen["domain"] == "event"
    assert keep("home_keeper_events") is True
    assert keep("home_keeper_device_heater_events") is True
    assert keep("home_keeper_device_old_events") is False
    assert keep("home_keeper_device_heater") is None
    assert keep("something_else") is None
