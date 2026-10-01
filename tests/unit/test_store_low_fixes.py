"""Store rules behind 2 low findings.

* B03-5: a skip entry keeps only the skip fields. ``cost`` and ``photo`` belong to
  a completion, and ``update_skip`` cannot clear them from a skip.
* B02-8: ``set_sensor_baseline`` rejects NaN and infinity, as ``models`` does for
  every other stored number.

The harness is ``test_store_consumable.py``'s: a fake ``Store`` and a fake ``hass``.
"""

from __future__ import annotations

import math

import pytest
from asserts import raises_exactly
from test_store_consumable import (  # noqa: F401
    TaskValidationError,
    _run,
    _task,
    store,
)

EVENT_TASK_UPDATED = "home_keeper_task_updated"


# ── B03-5 ────────────────────────────────────────────────────────────────────
def test_b03_5_a_skip_keeps_only_the_skip_fields(store):  # noqa: F811
    task = _task(store)
    updated = _run(
        store.skip_task(
            task["id"],
            metadata={
                "note": "away",
                "who": "Sam",
                "cost": 50,
                "photo": "https://example.com/y.jpg",
            },
        )
    )
    entry = updated["skips"][-1]
    assert entry["note"] == "away"
    assert entry["who"] == "Sam"
    assert "cost" not in entry
    assert "photo" not in entry


def test_b03_5_a_skip_with_only_completion_fields_records_no_metadata(store):  # noqa: F811
    task = _task(store)
    updated = _run(store.skip_task(task["id"], metadata={"cost": 12.5}))
    assert set(updated["skips"][-1]) == {"ts"}


# ── B02-8 ────────────────────────────────────────────────────────────────────
def _usage_task(store):  # noqa: F811
    return _task(
        store,
        recurrence_type="sensor",
        sensor={
            "mode": "usage",
            "entity_id": "sensor.odometer",
            "target": 5000,
            "baseline": 25000,
        },
    )


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_b02_8_a_non_finite_baseline_is_rejected(store, value):  # noqa: F811
    task = _usage_task(store)
    saves = store._store.saves
    with raises_exactly(TaskValidationError, "sensor.baseline must be a finite number"):
        _run(store.set_sensor_baseline(task["id"], value, silent=False))
    assert store._tasks[task["id"]]["sensor"]["baseline"] == 25000
    assert store._store.saves == saves
    assert store._hass.bus.of(EVENT_TASK_UPDATED) == []


def test_b02_8_a_finite_baseline_is_stored(store):  # noqa: F811
    task = _usage_task(store)
    _run(store.set_sensor_baseline(task["id"], 30000.0, silent=False))
    assert store._tasks[task["id"]]["sensor"]["baseline"] == 30000.0
    assert len(store._hass.bus.of(EVENT_TASK_UPDATED)) == 1


def test_b02_8_an_unknown_task_is_still_a_key_error(store):  # noqa: F811
    with pytest.raises(KeyError):
        _run(store.set_sensor_baseline("missing", math.nan))
