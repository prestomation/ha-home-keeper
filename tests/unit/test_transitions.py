"""Unit tests for the pure overdue / due-soon edge detector.

These exercise the fire-once-per-crossing semantics with an injected ``now`` (no HA
runtime): a task announces due-soon then overdue against the same ``next_due`` exactly
once each, re-arms when its schedule moves, and never fires while dormant or disabled.
"""

from datetime import UTC, datetime, timedelta

import hk_transitions as t
from hk_const import EVENT_TASK_DUE_SOON, EVENT_TASK_OVERDUE

TZ = UTC
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


def test_preserved_baseline_fires_pending_transition_after_reload():
    # Regression (coordinator reload handoff): a task tracked as due-soon-but-not-yet-
    # overdue crosses next_due while the entry is reloading. As long as the prior edge
    # state is *preserved* (the coordinator seeds it from the process-lifetime store on
    # reload rather than baselining a fresh empty map), the overdue fires on the first
    # refresh after the reload instead of being silently swallowed.
    due = NOW + timedelta(hours=1)
    task_soon = _task(next_due=due)
    fired, state = t.detect_transitions({}, {"t1": task_soon}, now=NOW)
    assert _names(fired) == [EVENT_TASK_DUE_SOON]  # due-soon announced, overdue pending

    # Reload happens; the same (preserved) state is carried into the new coordinator.
    # An hour later the task is overdue against the same next_due -> overdue fires.
    later = due + timedelta(minutes=1)
    fired2, _ = t.detect_transitions(state, {"t1": task_soon}, now=later)
    assert _names(fired2) == [EVENT_TASK_OVERDUE]


def test_dormant_and_disabled_never_fire():
    dormant = _task("d", next_due=None, recurrence_type="triggered")
    disabled = _task("x", next_due=NOW - timedelta(days=5), enabled=False)
    fired, state = t.detect_transitions({}, {"d": dormant, "x": disabled}, now=NOW)
    assert fired == []
    # Tracked but quiet: both carry state so re-arm/re-enable starts fresh.
    assert set(state) == {"d", "x"}


def test_one_off_armed_fires_overdue_then_completed_goes_quiet():
    # An armed one-off announces overdue once; once completed (next_due -> None) it
    # is dormant and never fires again.
    armed = _task("o", next_due=NOW - timedelta(days=1), recurrence_type="one-off")
    fired, state = t.detect_transitions({}, {"o": armed}, now=NOW)
    assert _names(fired) == [EVENT_TASK_OVERDUE]

    completed = _task("o", next_due=None, recurrence_type="one-off")
    fired2, _state2 = t.detect_transitions(state, {"o": completed}, now=NOW)
    assert fired2 == []


def test_triggered_task_fires_overdue_on_arm():
    dormant = _task("d", next_due=None, recurrence_type="triggered")
    _, state = t.detect_transitions({}, {"d": dormant}, now=NOW)

    armed = _task("d", next_due=NOW, recurrence_type="triggered")
    fired, _state2 = t.detect_transitions(state, {"d": armed}, now=NOW)
    assert _names(fired) == [EVENT_TASK_OVERDUE]


def test_deleted_task_drops_out_of_state():
    task = _task(next_due=NOW - timedelta(days=1))
    _, state = t.detect_transitions({}, {"t1": task}, now=NOW)
    assert "t1" in state
    fired, state2 = t.detect_transitions(state, {}, now=NOW)
    assert fired == [] and state2 == {}


# ── auto_crossings (B16-6) ─────────────────────────────────────────────────────


def test_b16_6_a_snooze_of_an_overdue_task_sends_no_due_soon_push():
    overdue = _task(next_due=NOW - timedelta(days=1))
    _, state = t.detect_transitions({}, {"t1": overdue}, now=NOW)
    snoozed = _task(next_due=NOW + timedelta(hours=24))
    fired, _ = t.detect_transitions(state, {"t1": snoozed}, now=NOW)
    # The event still fires, but it sends no automatic notification.
    assert _names(fired) == [EVENT_TASK_DUE_SOON]
    assert t.auto_crossings(state, fired) == []


def test_b16_6_completing_a_due_soon_task_sends_no_due_soon_push():
    due_soon = _task(next_due=NOW + timedelta(days=1))
    _, state = t.detect_transitions({}, {"t1": due_soon}, now=NOW)
    assert state["t1"]["overdue_fired"] is False
    completed = _task(next_due=NOW + timedelta(days=2))
    fired, _ = t.detect_transitions(state, {"t1": completed}, now=NOW)
    assert _names(fired) == [EVENT_TASK_DUE_SOON]
    assert t.auto_crossings(state, fired) == []


def test_b16_6_a_time_crossing_still_sends():
    later = _task(next_due=NOW + timedelta(days=5))
    _, state = t.detect_transitions({}, {"t1": later}, now=NOW)
    fired, _ = t.detect_transitions(state, {"t1": later}, now=NOW + timedelta(days=3))
    assert t.auto_crossings(state, fired) == [("due_soon", "t1")]
    # A new task has no prior state, so it sends too.
    new = _task(next_due=NOW + timedelta(days=1))
    fired, _ = t.detect_transitions({}, {"t1": new}, now=NOW)
    assert t.auto_crossings({}, fired) == [("due_soon", "t1")]


def test_b16_6_overdue_after_a_snooze_still_sends():
    overdue = _task(next_due=NOW - timedelta(days=1))
    _, state = t.detect_transitions({}, {"t1": overdue}, now=NOW)
    moved = _task(next_due=NOW - timedelta(hours=1))
    fired, _ = t.detect_transitions(state, {"t1": moved}, now=NOW)
    assert _names(fired) == [EVENT_TASK_OVERDUE]
    assert t.auto_crossings(state, fired) == [("overdue", "t1")]


def test_b16_6_auto_crossings_skips_other_events_and_a_missing_task_id():
    fired = [
        ("home_keeper_task_completed", {"task_id": "t1"}),
        (EVENT_TASK_OVERDUE, {}),
        (EVENT_TASK_OVERDUE, {"task_id": ""}),
        (EVENT_TASK_OVERDUE, {"task_id": "t2"}),
    ]
    assert t.auto_crossings({}, fired) == [("overdue", "t2")]
    assert (
        t.auto_crossings(
            {"t2": {"due_soon_fired": True}}, [(EVENT_TASK_DUE_SOON, {"task_id": "t2"})]
        )
        == []
    )
    assert t.auto_crossings(
        {"t2": {"due_soon_fired": False, "overdue_fired": False}},
        [(EVENT_TASK_DUE_SOON, {"task_id": "t2"})],
    ) == [("due_soon", "t2")]
    # A held-back due_soon does not stop the events after it.
    held_back_then_overdue = [
        (EVENT_TASK_DUE_SOON, {"task_id": "t2"}),
        (EVENT_TASK_OVERDUE, {"task_id": "t3"}),
    ]
    assert t.auto_crossings(
        {"t2": {"overdue_fired": True}}, held_back_then_overdue
    ) == [("overdue", "t3")]
