"""Unit tests for one-off (do-once) recurrence.

A one-off task carries its own ``due`` datetime. ``compute_next_due`` reads that
date back (arming); ``apply_completion`` clears ``next_due`` to ``None`` (dormant,
permanently complete) while recording the completion; undoing the (final)
completion via ``remove_completion`` re-arms it to ``due``. The auto-delete
retention helper ``one_off_expired`` decides when a completed one-off is eligible
for cleanup.
"""

from datetime import datetime, timedelta, timezone

import hk_recurrence as r

TZ = timezone(timedelta(hours=-4))


def dt(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def _one_off(**over):
    task = {"recurrence_type": "one-off", "completions": []}
    task.update(over)
    return task


def test_compute_next_due_returns_due_date():
    now = dt(2026, 6, 16, 10)
    due = dt(2026, 7, 1, 8)
    assert r.compute_next_due(_one_off(due=due.isoformat()), now=now) == due


def test_apply_completion_goes_dormant_and_records_history():
    now = dt(2026, 7, 1, 10)
    when = dt(2026, 7, 1, 9)
    task = _one_off(due=dt(2026, 7, 1, 8).isoformat(), last_completed=None)
    out = r.apply_completion(task, when, now=now)
    # Permanently complete: no due date at all (does not reschedule).
    assert out["next_due"] is None
    # The completion is recorded (cadence / history retained).
    assert out["completions"] == [{"ts": when.isoformat()}]
    assert out["last_completed"] == when.isoformat()


def test_apply_completion_records_metadata():
    now = dt(2026, 7, 1, 10)
    task = _one_off(due=dt(2026, 7, 1, 8).isoformat())
    out = r.apply_completion(task, now, now=now, metadata={"cost": 12.5})
    assert out["next_due"] is None
    assert out["completions"] == [{"ts": now.isoformat(), "cost": 12.5}]


def test_dormant_one_off_is_not_overdue_or_due_soon():
    now = dt(2026, 7, 2, 10)
    dormant = _one_off(due=dt(2026, 7, 1, 8).isoformat(), next_due=None)
    assert r.is_overdue(dormant, now=now) is False
    assert r.is_due_soon(dormant, timedelta(days=3), now=now) is False


def test_armed_one_off_is_overdue_when_due_passes():
    now = dt(2026, 7, 1, 10)
    armed = _one_off(
        due=dt(2026, 7, 1, 8).isoformat(), next_due=dt(2026, 7, 1, 8).isoformat()
    )
    assert r.is_overdue(armed, now=now) is True


def test_remove_final_completion_rearms_to_due():
    # Undoing the only completion of a one-off brings it back to its due date.
    now = dt(2026, 7, 5, 10)
    due = dt(2026, 7, 1, 8)
    completed_at = dt(2026, 7, 1, 9)
    task = _one_off(
        due=due.isoformat(),
        next_due=None,
        last_completed=completed_at.isoformat(),
        completions=[{"ts": completed_at.isoformat()}],
    )
    out = r.remove_completion(task, completed_at.isoformat(), now=now)
    assert out["next_due"] == due.isoformat()
    assert out["last_completed"] is None
    assert out["completions"] == []


def test_remove_one_of_several_completions_stays_dormant():
    # An edge case: a one-off that somehow has more than one completion stays
    # dormant while any completion remains (only the final undo re-arms it).
    now = dt(2026, 7, 5, 10)
    due = dt(2026, 7, 1, 8)
    first = dt(2026, 7, 1, 9)
    second = dt(2026, 7, 2, 9)
    task = _one_off(
        due=due.isoformat(),
        next_due=None,
        last_completed=second.isoformat(),
        completions=[{"ts": first.isoformat()}, {"ts": second.isoformat()}],
    )
    out = r.remove_completion(task, second.isoformat(), now=now)
    assert out["next_due"] is None
    assert out["last_completed"] == first.isoformat()


def test_one_off_expired_respects_retention_window():
    completed_at = dt(2026, 7, 1, 9)
    task = _one_off(
        due=dt(2026, 7, 1, 8).isoformat(),
        next_due=None,
        last_completed=completed_at.isoformat(),
    )
    # Within the window -> not expired.
    assert r.one_off_expired(task, 30, now=completed_at + timedelta(days=29)) is False
    # On/after the boundary -> expired.
    assert r.one_off_expired(task, 30, now=completed_at + timedelta(days=30)) is True
    assert r.one_off_expired(task, 30, now=completed_at + timedelta(days=31)) is True


def test_one_off_expired_keep_forever_default():
    completed_at = dt(2020, 1, 1)
    task = _one_off(
        due=dt(2020, 1, 1).isoformat(),
        next_due=None,
        last_completed=completed_at.isoformat(),
    )
    # Retention 0 (the default) never purges, no matter how old.
    assert r.one_off_expired(task, 0, now=dt(2030, 1, 1)) is False


def test_one_off_expired_ignores_uncompleted_and_other_kinds():
    now = dt(2026, 8, 1)
    # An armed (uncompleted) one-off is never purged.
    armed = _one_off(
        due=dt(2026, 7, 1).isoformat(), next_due=dt(2026, 7, 1).isoformat()
    )
    assert r.one_off_expired(armed, 30, now=now) is False
    # Other recurrence kinds are never purged even when dormant.
    triggered = {
        "recurrence_type": "triggered",
        "next_due": None,
        "last_completed": dt(2026, 1, 1).isoformat(),
        "completions": [],
    }
    assert r.one_off_expired(triggered, 30, now=now) is False
