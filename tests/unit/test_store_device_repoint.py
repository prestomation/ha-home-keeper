"""The store fires an updated event for each record that a device repoint moves.

``devices.async_reconcile_assets`` (a re-created or recovered appliance device) and
``devices.async_heal_split_device_ids`` (the Home Assistant 2026.8 split) move the
device ids through ``HomeKeeperStore.async_repoint_device_ids`` and
``async_repoint_asset_device_ids``. Every state change fires an event from the store,
so an automation sees each moved task and appliance. This drives the real store over
the fake ``Store`` and ``hass`` of ``test_store_consumable.py``.
"""

from __future__ import annotations

import asyncio

import pytest
from test_store_consumable import _FakeHass, _FakeStore, store_mod


@pytest.fixture
def store():
    prior = store_mod.Store
    store_mod.Store = _FakeStore
    try:
        yield store_mod.HomeKeeperStore(_FakeHass())
    finally:
        store_mod.Store = prior


def test_each_moved_task_fires_one_updated_event(store):
    store._tasks = {
        "t1": {"id": "t1", "name": "A", "device_id": "dev_old"},
        "t2": {
            "id": "t2",
            "name": "B",
            "device_id": None,
            "source": {"glue": {"device_id": "dev_old"}},
        },
        "t3": {"id": "t3", "name": "C", "device_id": "dev_other"},
    }

    changed = asyncio.run(store.async_repoint_device_ids({"dev_old": "dev_new"}))

    assert changed == 2
    assert store._store.saves == 1
    events = store._hass.bus.of(store_mod.EVENT_TASK_UPDATED)
    assert [(e["task_id"], e["changed_fields"]) for e in events] == [
        ("t1", ["device_id"]),
        ("t2", ["source"]),
    ]
    assert events[0]["device_id"] == "dev_new"


def test_a_task_with_both_ids_fires_once(store):
    store._tasks = {
        "t1": {
            "id": "t1",
            "name": "A",
            "device_id": "dev_old",
            "source": {"glue": {"device_id": "dev_old"}},
        }
    }
    asyncio.run(store.async_repoint_device_ids({"dev_old": "dev_new"}))
    (event,) = store._hass.bus.of(store_mod.EVENT_TASK_UPDATED)
    assert event["changed_fields"] == ["device_id", "source"]


def test_each_moved_appliance_fires_one_updated_event(store):
    store._assets = {
        "a1": {"id": "a1", "name": "Boiler", "device_id": "dev_old"},
        "a2": {
            "id": "a2",
            "name": "Pump",
            "device_id": "dev_pump",
            "related_device_ids": ["dev_old", "dev_x"],
        },
        "a3": {"id": "a3", "name": "Fan", "device_id": "dev_fan"},
    }

    changed = asyncio.run(store.async_repoint_asset_device_ids({"dev_old": "dev_new"}))

    assert changed == 2
    assert store._assets["a2"]["related_device_ids"] == ["dev_new", "dev_x"]
    events = store._hass.bus.of(store_mod.EVENT_ASSET_UPDATED)
    assert [(e["asset_id"], e["changed_fields"]) for e in events] == [
        ("a1", ["device_id"]),
        ("a2", ["related_device_ids"]),
    ]


def test_a_repoint_that_moves_nothing_fires_nothing(store):
    store._tasks = {"t1": {"id": "t1", "name": "A", "device_id": "dev_x"}}
    store._assets = {"a1": {"id": "a1", "name": "B", "device_id": "dev_x"}}
    assert asyncio.run(store.async_repoint_device_ids({"dev_old": "dev_new"})) == 0
    assert asyncio.run(store.async_repoint_asset_device_ids({"dev_old": "n"})) == 0
    assert store._store.saves == 0
    assert store._hass.bus.fired == []
