"""``store.move_occurrence`` and the load-time conversion of legacy fixed tasks.

Uses the fake ``Store`` and ``hass`` from ``test_store_consumable.py``: these paths
touch nothing beyond the storage document and the bus.
"""

from __future__ import annotations

import sys
from datetime import datetime

import pytest
from test_store_consumable import NOW, TZ, _FakeHass, _FakeStore, _run, store_mod

models = sys.modules["hk.models"]
const = sys.modules["hk.const"]
TaskValidationError = models.TaskValidationError


def dt(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


@pytest.fixture
def store():
    prior = store_mod.Store
    store_mod.Store = _FakeStore
    try:
        yield store_mod.HomeKeeperStore(_FakeHass())
    finally:
        store_mod.Store = prior


def _bins(store) -> dict:
    # NOW is Saturday 2026-06-13 10:00. Tue/Fri at 07:00 from the week before.
    task = models.build_task(
        {
            "name": "Take trash out",
            "rrule": "FREQ=WEEKLY;BYDAY=TU,FR",
            "anchor": dt(2026, 6, 9, 7).isoformat(),
        },
        now=NOW,
    )
    store._tasks[task["id"]] = task
    return task


def test_a_move_is_saved_and_announced(store):
    task = _bins(store)
    assert task["next_due"] == dt(2026, 6, 16, 7).isoformat()

    moved = _run(
        store.move_occurrence(
            task["id"], dt(2026, 6, 19, 7), dt(2026, 6, 20, 8), origin="city"
        )
    )

    assert moved["moved_occurrences"] == [
        {"from": dt(2026, 6, 19, 7).isoformat(), "to": dt(2026, 6, 20, 8).isoformat()}
    ]
    assert store._store.saves == 1
    (payload,) = store._hass.bus.of(const.EVENT_TASK_OCCURRENCE_MOVED)
    assert payload["task_id"] == task["id"]
    assert payload["occurrence"] == dt(2026, 6, 19, 7).isoformat()
    assert payload["to"] == dt(2026, 6, 20, 8).isoformat()
    assert payload["previous_to"] is None
    assert payload["origin"] == "city"


def test_a_second_move_reports_where_the_date_was(store):
    task = _bins(store)
    _run(store.move_occurrence(task["id"], dt(2026, 6, 19, 7), dt(2026, 6, 20, 8)))
    _run(store.move_occurrence(task["id"], dt(2026, 6, 20, 8), dt(2026, 6, 21, 8)))
    last = store._hass.bus.of(const.EVENT_TASK_OCCURRENCE_MOVED)[-1]
    assert last["occurrence"] == dt(2026, 6, 19, 7).isoformat()
    assert last["previous_to"] == dt(2026, 6, 20, 8).isoformat()
    assert last["to"] == dt(2026, 6, 21, 8).isoformat()


def test_an_undo_reports_the_date_back_on_its_own_time(store):
    task = _bins(store)
    _run(store.move_occurrence(task["id"], dt(2026, 6, 19, 7), dt(2026, 6, 20, 8)))
    undone = _run(
        store.move_occurrence(task["id"], dt(2026, 6, 19, 7), dt(2026, 6, 19, 7))
    )
    assert undone["moved_occurrences"] == []
    last = store._hass.bus.of(const.EVENT_TASK_OCCURRENCE_MOVED)[-1]
    assert last["to"] == last["occurrence"]


def test_a_naive_new_time_is_reported_with_a_zone(store):
    task = _bins(store)
    _run(
        store.move_occurrence(task["id"], dt(2026, 6, 19, 7), datetime(2026, 6, 20, 8))
    )
    (payload,) = store._hass.bus.of(const.EVENT_TASK_OCCURRENCE_MOVED)
    assert payload["to"] == dt(2026, 6, 20, 8).isoformat()


def test_an_unknown_task_raises_key_error(store):
    with pytest.raises(KeyError):
        _run(store.move_occurrence("nope", NOW, NOW))


def test_a_task_of_another_kind_is_refused(store):
    task = models.build_task(
        {"name": "Filter", "interval": 1, "unit": "months"}, now=NOW
    )
    store._tasks[task["id"]] = task
    with pytest.raises(TaskValidationError, match="fixed schedule"):
        _run(store.move_occurrence(task["id"], NOW, NOW))
    assert store._hass.bus.fired == []


def test_an_engine_refusal_becomes_a_validation_error(store):
    task = _bins(store)
    with pytest.raises(TaskValidationError, match="not a date of this schedule"):
        _run(store.move_occurrence(task["id"], dt(2026, 6, 18, 7), dt(2026, 6, 20, 8)))
    assert store._store.saves == 0
    assert store._hass.bus.fired == []


def test_load_converts_a_legacy_fixed_task_and_saves_once(store):
    store._store.data = {
        "tasks": {
            "t1": {
                "id": "t1",
                "name": "Rent",
                "recurrence_type": "fixed",
                "freq": "MONTHLY",
                "interval": 1,
                "anchor": "2026-01-31T09:00:00-04:00",
                "next_due": "2026-06-30T09:00:00-04:00",
            },
            "t2": {
                "id": "t2",
                "name": "Filter",
                "recurrence_type": "floating",
                "interval": 1,
                "unit": "months",
            },
        }
    }
    _run(store.load())
    rent = store._tasks["t1"]
    assert rent["rrule"] == "FREQ=MONTHLY;INTERVAL=1"
    assert rent["moved_occurrences"] == []
    assert "freq" not in rent and "interval" not in rent
    assert store._tasks["t2"]["interval"] == 1
    assert store._store.saves == 1

    # A second load has nothing to convert.
    _run(store.load())
    assert store._store.saves == 1
