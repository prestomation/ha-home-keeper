"""Unit tests for triggered (condition-driven) recurrence.

A triggered task has no schedule: its ``next_due`` is its state — ``None`` means
dormant (invisible to every time surface), a timestamp means armed/due-now.
Arming (``compute_next_due``) yields now; completing (``apply_completion``) clears
it back to dormant while still recording the completion in history.
"""

from datetime import datetime, timedelta, timezone

import hk_recurrence as r

TZ = timezone(timedelta(hours=-4))


def dt(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def _triggered(**over):
    task = {"recurrence_type": "triggered", "completions": []}
    task.update(over)
    return task


def test_compute_next_due_arms_to_now():
    now = dt(2026, 6, 16, 10)
    assert r.compute_next_due(_triggered(), now=now) == now


def test_apply_completion_goes_dormant_and_records_history():
    now = dt(2026, 6, 16, 10)
    when = dt(2026, 6, 16, 9)
    task = _triggered(next_due=now.isoformat(), last_completed=None)
    out = r.apply_completion(task, when, now=now)
    # Dormant: no due date at all (clears, does not reschedule).
    assert out["next_due"] is None
    # But the completion is recorded so cadence accumulates on the task.
    assert out["completions"] == [{"ts": when.isoformat()}]
    assert out["last_completed"] == when.isoformat()


def test_dormant_triggered_is_not_overdue_or_due_soon():
    now = dt(2026, 6, 16, 10)
    dormant = _triggered(next_due=None)
    assert r.is_overdue(dormant, now=now) is False
    assert r.is_due_soon(dormant, timedelta(days=3), now=now) is False


def test_armed_triggered_is_overdue_immediately():
    now = dt(2026, 6, 16, 10)
    armed = _triggered(next_due=now.isoformat())
    assert r.is_overdue(armed, now=now) is True


def test_arm_complete_arm_cycle_preserves_history():
    # The battery lifecycle: low -> replaced -> low again. History keeps growing.
    now = dt(2026, 6, 16, 10)
    task = _triggered(next_due=r.compute_next_due(_triggered(), now=now).isoformat())

    r.apply_completion(task, dt(2026, 6, 16), now=now)
    assert task["next_due"] is None  # dormant after first replacement

    # Re-arm a year later (battery low again).
    later = dt(2027, 6, 1, 10)
    task["next_due"] = r.compute_next_due(task, now=later).isoformat()
    assert task["next_due"] == later.isoformat()

    r.apply_completion(task, dt(2027, 6, 1), now=later)
    assert task["next_due"] is None
    assert len(task["completions"]) == 2  # both replacements retained


def test_remove_completion_leaves_dormant_triggered_dormant():
    # Regression: editing the replacement history of a dormant triggered task must
    # not re-arm it (next_due stays None).
    now = dt(2026, 6, 16, 10)
    task = _triggered(
        next_due=None,
        last_completed=dt(2026, 1, 1).isoformat(),
        completions=[{"ts": dt(2026, 1, 1).isoformat()}],
    )
    out = r.remove_completion(task, dt(2026, 1, 1).isoformat(), now=now)
    assert out["next_due"] is None
    assert out["completions"] == []


def test_remove_completion_keeps_armed_triggered_armed():
    # And removing a past completion from an armed triggered task keeps it armed.
    now = dt(2026, 6, 16, 10)
    armed_at = dt(2026, 6, 16).isoformat()
    task = _triggered(
        next_due=armed_at,
        last_completed=dt(2025, 1, 1).isoformat(),
        completions=[{"ts": dt(2025, 1, 1).isoformat()}],
    )
    out = r.remove_completion(task, dt(2025, 1, 1).isoformat(), now=now)
    assert out["next_due"] == armed_at  # still armed
