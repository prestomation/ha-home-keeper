"""Unit tests for the pure overdue / due-soon edge detector.

These exercise the fire-once-per-crossing semantics with an injected ``now`` (no HA
runtime): a task announces due-soon then overdue against the same ``next_due`` exactly
once each, re-arms when its schedule moves, and never fires while dormant or disabled.
"""

from datetime import datetime, timedelta, timezone

import hk_transitions as t
from hk_const import EVENT_TASK_DUE_SOON, EVENT_TASK_OVERDUE

TZ = timezone.utc
NOW = datetime(2026, 6, 18, 12, 0, tzinfo=TZ)


def _task(tid="t1", *, next_due, enabled=True, recurrence_type="floating"):
    return {
        "id": tid,
        "name": "Task",
        "next_due": next_due.isoformat() if next_due else None,
        "enabled": enabled,
        "recurrence_type": recurrence_type,
    }


def _names(fired):
    return [name for name, _ in fired]


def test_overdue_fires_once_and_not_again():
    task = _task(next_due=NOW - timedelta(days=2))
    tasks = {"t1": task}

    fired, state = t.detect_transitions({}, tasks, now=NOW)
    assert _names(fired) == [EVENT_TASK_OVERDUE]
    assert fired[0][1]["days_overdue"] == 2
    assert state["t1"]["overdue_fired"] is True

    # Still overdue next cycle, same next_due -> no repeat.
    fired2, state2 = t.detect_transitions(state, tasks, now=NOW + timedelta(hours=1))
    assert fired2 == []
    assert state2["t1"]["overdue_fired"] is True


def test_due_soon_then_overdue_both_fire_once_for_one_next_due():
    next_due = NOW + timedelta(days=1)  # within the 3-day window, not yet overdue
    tasks = {"t1": _task(next_due=next_due)}

    fired, state = t.detect_transitions({}, tasks, now=NOW)
    assert _names(fired) == [EVENT_TASK_DUE_SOON]
    assert fired[0][1]["due_in_hours"] == 24.0

    # Time passes to just after the due date — overdue fires, due-soon does not repeat.
    later = next_due + timedelta(minutes=5)
    fired2, state2 = t.detect_transitions(state, tasks, now=later)
    assert _names(fired2) == [EVENT_TASK_OVERDUE]
    assert state2["t1"] == {
        "next_due": tasks["t1"]["next_due"],
        "due_soon_fired": True,
        "overdue_fired": True,
    }


def test_reschedule_rearms_announcements():
    task = _task(next_due=NOW - timedelta(days=1))
    fired, state = t.detect_transitions({}, {"t1": task}, now=NOW)
    assert _names(fired) == [EVENT_TASK_OVERDUE]

    # Completed/rescheduled: next_due moves into the future -> flags reset, nothing
    # fires now, and a later crossing fires again.
    rescheduled = _task(next_due=NOW + timedelta(days=30))
    fired2, state2 = t.detect_transitions(state, {"t1": rescheduled}, now=NOW)
    assert fired2 == []
    assert state2["t1"]["overdue_fired"] is False


def test_dormant_and_disabled_never_fire():
    dormant = _task("d", next_due=None, recurrence_type="triggered")
    disabled = _task("x", next_due=NOW - timedelta(days=5), enabled=False)
    fired, state = t.detect_transitions({}, {"d": dormant, "x": disabled}, now=NOW)
    assert fired == []
    # Tracked but quiet: both carry state so re-arm/re-enable starts fresh.
    assert set(state) == {"d", "x"}


def test_triggered_task_fires_overdue_on_arm():
    dormant = _task("d", next_due=None, recurrence_type="triggered")
    _, state = t.detect_transitions({}, {"d": dormant}, now=NOW)

    armed = _task("d", next_due=NOW, recurrence_type="triggered")
    fired, state2 = t.detect_transitions(state, {"d": armed}, now=NOW)
    assert _names(fired) == [EVENT_TASK_OVERDUE]


def test_deleted_task_drops_out_of_state():
    task = _task(next_due=NOW - timedelta(days=1))
    _, state = t.detect_transitions({}, {"t1": task}, now=NOW)
    assert "t1" in state
    fired, state2 = t.detect_transitions(state, {}, now=NOW)
    assert fired == [] and state2 == {}
