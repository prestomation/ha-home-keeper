"""The store follows an entity id rename into the sensor bindings (X10-1).

Home Assistant does not rewrite integration storage when a user renames an entity
id. The sensor watcher hears the rename and calls
``HomeKeeperStore.async_repoint_sensor_entity``. This drives the real store over the
fake ``Store`` and ``hass`` of ``test_store_consumable.py``.
"""

from __future__ import annotations

import asyncio
import sys

import pytest
from test_store_consumable import _FakeHass, _FakeStore, store_mod

OLD = "sensor.car_odometer"
NEW = "sensor.tesla_odometer"


@pytest.fixture
def store():
    prior = store_mod.Store
    store_mod.Store = _FakeStore
    try:
        yield store_mod.HomeKeeperStore(_FakeHass())
    finally:
        store_mod.Store = prior


def _sensor_task(store, entity_id, **overrides):
    models = sys.modules["hk.models"]
    task = models.build_task(
        {
            "name": "Oil change",
            "recurrence_type": "sensor",
            "sensor": {"entity_id": entity_id, "mode": "usage", "target": 10000},
            **overrides,
        },
        now=store_mod.dt_util.now(),
    )
    store._tasks[task["id"]] = task
    return task


def test_x10_1_a_rename_rewrites_every_bound_task_once(store):
    bound = _sensor_task(store, OLD)
    disabled = _sensor_task(store, OLD, enabled=False)
    other = _sensor_task(store, "sensor.other")

    changed = asyncio.run(store.async_repoint_sensor_entity(OLD, NEW))

    assert sorted(changed) == sorted([bound["id"], disabled["id"]])
    assert store._tasks[bound["id"]]["sensor"] == {
        "entity_id": NEW,
        "mode": "usage",
        "target": 10000.0,
    }
    assert store._tasks[disabled["id"]]["sensor"]["entity_id"] == NEW
    assert store._tasks[other["id"]]["sensor"]["entity_id"] == "sensor.other"
    # One write for the batch, and the normal updated event per task.
    assert store._store.saves == 1
    events = store._hass.bus.of(store_mod.EVENT_TASK_UPDATED)
    assert sorted(e["task_id"] for e in events) == sorted(changed)
    assert all(e["changed_fields"] == ["sensor"] for e in events)


@pytest.mark.parametrize(
    ("old", "new"), [("sensor.nothing", NEW), (OLD, OLD), ("", NEW), (OLD, "")]
)
def test_x10_1_nothing_to_rewrite_writes_nothing(store, old, new):
    _sensor_task(store, OLD)

    assert asyncio.run(store.async_repoint_sensor_entity(old, new)) == []
    assert store._store.saves == 0
    assert store._hass.bus.fired == []
