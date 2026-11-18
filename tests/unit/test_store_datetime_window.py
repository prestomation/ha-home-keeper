"""The store refuses a datetime outside the window, and clamps a stored one on load.

The window is ``recurrence.DATETIME_MIN`` to ``recurrence.DATETIME_MAX`` (see
``test_datetime_window.py``). The harness is ``test_store_consumable.py``'s.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta, timezone

import pytest
from test_store_consumable import NOW, TZ, _FakeHass, _FakeStore, _run, store_mod

models = sys.modules["hk.models"]
recurrence = sys.modules["hk.recurrence"]
TaskValidationError = models.TaskValidationError

FAR = [
    datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone(timedelta(hours=-12))),
    datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=14))),
    datetime(2200, 1, 1, tzinfo=UTC),
    datetime(1899, 12, 31, tzinfo=UTC),
]
TOP = (recurrence.DATETIME_MAX - timedelta(seconds=1)).isoformat()


@pytest.fixture
def store():
    prior = store_mod.Store
    store_mod.Store = _FakeStore
    try:
        yield store_mod.HomeKeeperStore(_FakeHass())
    finally:
        store_mod.Store = prior


def _floating(store) -> dict:
    task = models.build_task({"name": "Filter", "interval": 1, "unit": "days"}, now=NOW)
    store._tasks[task["id"]] = task
    return task


def _fixed(store) -> dict:
    task = models.build_task(
        {
            "name": "Bins",
            "rrule": "FREQ=WEEKLY;BYDAY=TU,FR",
            "anchor": datetime(2026, 6, 9, 7, tzinfo=TZ).isoformat(),
        },
        now=NOW,
    )
    store._tasks[task["id"]] = task
    return task


@pytest.mark.parametrize("when", FAR)
def test_complete_task_refuses_a_completed_at_outside_the_window(store, when):
    task = _floating(store)
    with pytest.raises(TaskValidationError, match="completed_at must be between"):
        _run(store.complete_task(task["id"], when))
    assert store._tasks[task["id"]] == task
    assert store._store.saves == 0


def test_complete_task_keeps_a_completed_at_inside_the_window(store):
    task = _floating(store)
    when = datetime(1900, 1, 1, tzinfo=UTC)
    updated = _run(store.complete_task(task["id"], when))
    assert updated["completions"][-1]["ts"] == when.isoformat()


@pytest.mark.parametrize("until", FAR)
def test_snooze_task_refuses_an_until_outside_the_window(store, until):
    task = _floating(store)
    with pytest.raises(TaskValidationError, match="until must be between"):
        _run(store.snooze_task(task["id"], until))
    assert store._store.saves == 0


@pytest.mark.parametrize("to", FAR)
def test_move_occurrence_refuses_a_to_outside_the_window(store, to):
    task = _fixed(store)
    occurrence = datetime(2026, 6, 16, 7, tzinfo=TZ)
    with pytest.raises(TaskValidationError, match="to must be between"):
        _run(store.move_occurrence(task["id"], occurrence, to))
    assert store._store.saves == 0


@pytest.mark.parametrize("new", FAR)
def test_move_completion_refuses_a_new_ts_outside_the_window(store, new):
    task = _floating(store)
    done = _run(store.complete_task(task["id"], NOW))
    saves = store._store.saves
    with pytest.raises(TaskValidationError, match="new_completed_at must be between"):
        _run(
            store.move_completion(
                task["id"], done["completions"][-1]["ts"], new.isoformat()
            )
        )
    assert store._store.saves == saves


@pytest.mark.parametrize("new", FAR)
def test_move_skip_refuses_a_new_ts_outside_the_window(store, new):
    task = _floating(store)
    skipped = _run(store.skip_task(task["id"]))
    saves = store._store.saves
    with pytest.raises(TaskValidationError, match="new_ts must be between"):
        _run(store.move_skip(task["id"], skipped["skips"][-1]["ts"], new.isoformat()))
    assert store._store.saves == saves


def test_load_clamps_a_stored_datetime_outside_the_window(store):
    task = models.build_task(
        {"name": "x", "recurrence_type": "one-off", "due": NOW.isoformat()}, now=NOW
    )
    task["next_due"] = None
    task["last_completed"] = "9999-12-31T00:00:00+00:00"
    task["completions"] = [{"ts": "9999-12-31T00:00:00+00:00"}]
    store._store.data = {"tasks": {task["id"]: task}}
    _run(store.load())
    loaded = store.get_task(task["id"])
    assert loaded["last_completed"] == TOP
    assert loaded["completions"] == [{"ts": TOP}]
    # The clamped values are saved, so the warning does not come back on each load.
    assert store._store.saves == 1
    assert store._store.data["tasks"][task["id"]]["last_completed"] == TOP
    # The one-off purge reads the clamped value without an overflow.
    assert recurrence.one_off_expired(loaded, 30, now=NOW) is False
