"""A stored task with a device id or an area id that is not text still loads.

An older release stored the task fields of the websocket commands without a schema,
so a stored ``device_id`` or ``area_id`` can be a list or a dict. The device
registry raises ``TypeError`` on such a value, and platform setup then failed until
the task was deleted. ``models.drop_malformed_link_ids`` removes the value, and
``store.load`` runs it with the other load-time shims. This drives the real store
over the fake ``Store`` and ``hass`` of ``test_store_consumable.py``.
"""

from __future__ import annotations

import asyncio
import logging

import hk_models as m
import pytest
from test_store_consumable import _FakeHass, _FakeStore, store_mod


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("device_id", ["a"]),
        ("device_id", {"id": "a"}),
        ("device_id", 7),
        ("area_id", ["kitchen"]),
        ("area_id", {"id": "kitchen"}),
        ("area_id", True),
    ],
)
def test_a_value_that_is_not_text_is_removed(field, value):
    task = {"id": "t1", "name": "Filter", field: value}
    assert m.drop_malformed_link_ids(task) == [field]
    assert task[field] is None


def test_both_fields_are_reported_in_order():
    task = {"id": "t1", "device_id": ["a"], "area_id": ["b"]}
    assert m.drop_malformed_link_ids(task) == ["device_id", "area_id"]
    assert task == {"id": "t1", "device_id": None, "area_id": None}


@pytest.mark.parametrize("value", ["dev1", "", None])
def test_text_and_none_stay(value):
    task = {"id": "t1", "device_id": value, "area_id": value}
    assert m.drop_malformed_link_ids(task) == []
    assert task == {"id": "t1", "device_id": value, "area_id": value}


def test_a_task_without_the_fields_is_unchanged():
    task = {"id": "t1", "name": "Filter"}
    assert m.drop_malformed_link_ids(task) == []
    assert task == {"id": "t1", "name": "Filter"}


@pytest.fixture
def store():
    prior = store_mod.Store
    store_mod.Store = _FakeStore
    try:
        yield store_mod.HomeKeeperStore(_FakeHass())
    finally:
        store_mod.Store = prior


def _document() -> dict:
    return {
        "tasks": {
            "bad": {"id": "bad", "name": "Bad", "device_id": ["a"], "area_id": ["b"]},
            "good": {"id": "good", "name": "Good", "device_id": "dev1"},
        }
    }


def test_load_removes_the_value_and_logs_it(store, caplog):
    store._store.data = _document()
    with caplog.at_level(logging.WARNING):
        asyncio.run(store.load())
    assert store._tasks["bad"]["device_id"] is None
    assert store._tasks["bad"]["area_id"] is None
    assert store._tasks["good"]["device_id"] == "dev1"
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == [
        "Task bad (Bad) has a stored device_id that is not text. The value is removed",
        "Task bad (Bad) has a stored area_id that is not text. The value is removed",
    ]
    assert store._store.saves == 1, "the cleaned document is saved once"
    asyncio.run(store.load())
    assert store._store.saves == 1, "a clean document is not saved again"


def test_a_device_repoint_runs_after_the_load(store):
    # The split-device heal runs this at setup. It raised TypeError on a list.
    store._store.data = _document()
    asyncio.run(store.load())
    moved = asyncio.run(store.async_repoint_device_ids({"dev1": "dev2"}))
    assert moved == 1
    assert store._tasks["good"]["device_id"] == "dev2"
    assert store._tasks["bad"]["device_id"] is None
