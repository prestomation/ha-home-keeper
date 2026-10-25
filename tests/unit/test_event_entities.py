"""Unit tests for the global event entity (``event.py``) and its ``api_surface`` model.

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


# ── The model ────────────────────────────────────────────────────────────────


def test_event_type_is_the_bus_name_without_the_domain() -> None:
    assert api_surface.event_entity_type("home_keeper_task_completed") == (
        "task_completed"
    )


def test_every_mirrored_event_type_has_a_label_in_every_language() -> None:
    """A new fired event with a payload needs a label, or the editor shows a raw key."""
    import json

    want = set(api_surface.event_entity_events())
    files = [
        _COMPONENT_DIR / "strings.json",
        *_COMPONENT_DIR.glob("translations/*.json"),
    ]
    assert len(files) == 17
    for path in files:
        events = json.loads(path.read_text(encoding="utf-8"))["entity"]["event"]
        assert set(events) == {"home_keeper_events"}, path.name
        state = events["home_keeper_events"]["state_attributes"]["event_type"]
        have = set(state["state"])
        assert have == want, (path.name, sorted(want ^ have))


def test_global_entity_mirrors_every_fired_event_with_a_payload() -> None:
    expected = {
        spec.name
        for spec in api_surface.EVENTS
        if spec.direction == "fired" and spec.payload != "none"
    }
    assert set(event.GLOBAL_EVENTS.values()) == expected
    assert "home_keeper_register_companions" not in expected
    assert "home_keeper_companion_connected" in expected


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
    entity = event.HomeKeeperGlobalEventEntity()
    entity._events = {"task_completed": "home_keeper_task_completed"}
    entity._attr_event_types = ["task_completed"]
    _added(entity)
    entity._async_handle_event(
        types.SimpleNamespace(event_type="home_keeper_task_overdue", data={})
    )
    assert not hasattr(entity, "last_event_type")


def test_global_entity_keeps_short_fields_and_drops_large_ones() -> None:
    entity = event.HomeKeeperGlobalEventEntity()
    bus = _added(entity)
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


def test_setup_adds_the_global_entity_and_prunes_old_device_entities(
    monkeypatch,
) -> None:
    seen = {}

    def fake_prune(hass, entry, domain, keep):
        seen["domain"] = domain
        seen["keep"] = keep

    monkeypatch.setattr(event, "prune_registry_entries", fake_prune)
    added = []
    entry = types.SimpleNamespace(runtime_data=None)
    asyncio.run(event.async_setup_entry(None, entry, added.extend))

    assert [type(e).__name__ for e in added] == ["HomeKeeperGlobalEventEntity"]
    keep = seen["keep"]
    assert seen["domain"] == "event"
    assert keep("home_keeper_events") is True
    assert keep("home_keeper_device_heater_events") is False
    assert keep("home_keeper_device_x") is False
    assert keep("something_else") is None
