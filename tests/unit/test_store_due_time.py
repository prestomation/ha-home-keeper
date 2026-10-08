"""The store side of the set due time for floating tasks (#438).

The pure rules are in ``test_recurrence_due_time.py``. This file checks that the store
passes the set due time on: to a completion, a skip and a snooze, and to the stored
dates when setup applies the option. It uses the fake ``Store`` and ``hass`` of
``test_store_consumable.py``.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest
from test_store_consumable import NOW, TZ, _FakeHass, _FakeStore, _run, store_mod

EIGHT = time(8, 0)
UPDATED = "home_keeper_task_updated"


@pytest.fixture
def store():
    """A store with no records, its ``Store`` replaced by the fake."""
    prior = store_mod.Store
    store_mod.Store = _FakeStore
    try:
        yield store_mod.HomeKeeperStore(_FakeHass())
    finally:
        store_mod.Store = prior


def at(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def _floating(store, **extra):
    data = {"name": "Furnace filter", "interval": 90, "unit": "days", **extra}
    return _run(store.add_task(data))


def test_apply_due_time_moves_future_floating_dates_once(store):
    task = _floating(store, last_completed=at(2026, 6, 1, 22, 42).isoformat())
    assert task["next_due"] == at(2026, 8, 30, 22, 42).isoformat()
    saves = store._store.saves

    _run(store.async_apply_due_time(EIGHT))

    assert store._tasks[task["id"]]["next_due"] == at(2026, 8, 30, 8).isoformat()
    assert store._store.saves == saves + 1
    assert [e["changed_fields"] for e in store._hass.bus.of(UPDATED)] == [["next_due"]]

    # A second apply finds nothing to move: no save, no event.
    _run(store.async_apply_due_time(EIGHT))
    assert store._store.saves == saves + 1
    assert len(store._hass.bus.of(UPDATED)) == 1


def test_apply_completion_mode_moves_nothing(store):
    task = _floating(store, last_completed=at(2026, 6, 1, 22, 42).isoformat())
    saves = store._store.saves
    _run(store.async_apply_due_time(None))
    assert store._tasks[task["id"]]["next_due"] == at(2026, 8, 30, 22, 42).isoformat()
    assert store._store.saves == saves


def test_new_task_is_due_now_and_a_seeded_task_snaps(store):
    _run(store.async_apply_due_time(EIGHT))
    assert _floating(store)["next_due"] == NOW.isoformat()
    seeded = _floating(store, last_completed=at(2026, 6, 1, 22, 42).isoformat())
    assert seeded["next_due"] == at(2026, 8, 30, 8).isoformat()


def test_completion_and_skip_use_the_set_due_time(store):
    _run(store.async_apply_due_time(EIGHT))
    task = _floating(store)
    done = _run(store.complete_task(task["id"]))
    assert done["next_due"] == (NOW + timedelta(days=90)).replace(hour=8).isoformat()
    skipped = _run(store.skip_task(task["id"]))
    assert skipped["next_due"] == done["next_due"]


def test_snooze_rounds_up_to_the_set_due_time(store):
    _run(store.async_apply_due_time(EIGHT))
    task = _floating(store)
    snoozed = _run(store.snooze_task(task["id"], at(2026, 6, 13, 22)))
    assert snoozed["next_due"] == at(2026, 6, 14, 8).isoformat()
    snoozed = _run(store.snooze_task(task["id"], at(2026, 6, 20, 6)))
    assert snoozed["next_due"] == at(2026, 6, 20, 8).isoformat()


def test_snooze_of_a_fixed_task_keeps_its_time(store):
    _run(store.async_apply_due_time(EIGHT))
    task = _run(
        store.add_task(
            {
                "name": "Bins",
                "recurrence_type": "fixed",
                "freq": "WEEKLY",
                "interval": 1,
                "anchor": at(2026, 6, 1, 19).isoformat(),
            }
        )
    )
    snoozed = _run(store.snooze_task(task["id"], at(2026, 6, 20, 22)))
    assert snoozed["next_due"] == at(2026, 6, 20, 22).isoformat()


def test_due_today_stays_now(store):
    _run(store.async_apply_due_time(EIGHT))
    task = _floating(store, last_completed=at(2026, 6, 1, 22, 42).isoformat())
    moved = _run(store.set_due_today(task["id"]))
    assert moved["next_due"] == NOW.isoformat()
