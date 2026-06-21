"""Unit tests for sensor-based recurrence in the pure engine.

A sensor task behaves like a triggered task at the recurrence layer: its
``next_due`` is its state (``None`` dormant / a timestamp armed), arming reads as
due-now, completing clears it to dormant (the meter reset happens in the HA-aware
store), and editing history never re-arms it.
"""

from datetime import datetime, timedelta, timezone

import hk_recurrence as r

TZ = timezone(timedelta(hours=-4))


def dt(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def _sensor(**over):
    task = {
        "recurrence_type": "sensor",
        "sensor": {"entity_id": "sensor.x", "mode": "usage", "target": 100},
        "completions": [],
    }
    task.update(over)
    return task


def test_compute_next_due_arms_to_now():
    now = dt(2026, 6, 16, 10)
    assert r.compute_next_due(_sensor(), now=now) == now


def test_apply_completion_goes_dormant_and_records_history():
    now = dt(2026, 6, 16, 10)
    when = dt(2026, 6, 16, 9)
    task = _sensor(next_due=now.isoformat(), last_completed=None)
    out = r.apply_completion(task, when, now=now)
    assert out["next_due"] is None
    assert out["completions"] == [{"ts": when.isoformat()}]
    assert out["last_completed"] == when.isoformat()


def test_remove_completion_does_not_rearm():
    now = dt(2026, 6, 16, 10)
    task = _sensor(
        next_due=None,
        last_completed=dt(2026, 1, 1).isoformat(),
        completions=[{"ts": dt(2026, 1, 1).isoformat()}],
    )
    out = r.remove_completion(task, dt(2026, 1, 1).isoformat(), now=now)
    assert out["next_due"] is None
    assert out["completions"] == []


def test_armed_sensor_is_overdue():
    now = dt(2026, 6, 16, 10)
    assert r.is_overdue(_sensor(next_due=now.isoformat()), now=now) is True
    assert r.is_overdue(_sensor(next_due=None), now=now) is False
