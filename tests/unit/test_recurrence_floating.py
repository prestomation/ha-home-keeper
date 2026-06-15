"""Unit tests for floating recurrence (reset-from-completion)."""

from datetime import datetime, timedelta, timezone

import hk_recurrence as r

TZ = timezone(timedelta(hours=-4))


def dt(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def test_add_interval_days_weeks():
    assert r.add_interval(dt(2026, 1, 1), 3, "days") == dt(2026, 1, 4)
    assert r.add_interval(dt(2026, 1, 1), 2, "weeks") == dt(2026, 1, 15)


def test_add_months_end_of_month_clamp():
    # Jan 31 + 1 month -> Feb 28 in a non-leap year.
    assert r.add_months(dt(2026, 1, 31, 8), 1) == dt(2026, 2, 28, 8)
    # Leap year keeps Feb 29.
    assert r.add_months(dt(2024, 1, 31), 1) == dt(2024, 2, 29)
    # Crossing a year boundary.
    assert r.add_months(dt(2026, 12, 15), 1) == dt(2027, 1, 15)


def test_add_months_handles_negative_across_year_boundary():
    # Floor division + non-negative modulo handle negatives correctly.
    assert r.add_months(dt(2026, 1, 15), -2) == dt(2025, 11, 15)
    assert r.add_months(dt(2026, 1, 15), -1) == dt(2025, 12, 15)
    assert r.add_months(dt(2026, 3, 31), -1) == dt(2026, 2, 28)


def test_add_interval_rejects_bad_input():
    import pytest

    with pytest.raises(ValueError):
        r.add_interval(dt(2026, 1, 1), 0, "days")
    with pytest.raises(ValueError):
        r.add_interval(dt(2026, 1, 1), 1, "fortnights")


def test_floating_next_due_from_last_completed():
    last = dt(2026, 6, 1, 9)
    nd = r.compute_floating_next_due(last, 1, "months", now=dt(2026, 6, 1))
    assert nd == dt(2026, 7, 1, 9)


def test_floating_next_due_is_now_when_never_completed():
    # A never-completed floating task is due immediately, not a full interval out.
    nd = r.compute_floating_next_due(None, 30, "days", now=dt(2026, 6, 13))
    assert nd == dt(2026, 6, 13)


def test_apply_completion_resets_clock_from_completion():
    now = dt(2026, 6, 13, 10)
    task = {
        "recurrence_type": "floating",
        "interval": 1,
        "unit": "months",
        "completions": [],
    }
    r.apply_completion(task, now, now=now)
    assert task["last_completed"] == now.isoformat()
    assert task["next_due"] == dt(2026, 7, 13, 10).isoformat()
    assert len(task["completions"]) == 1


def test_overdue_and_due_soon():
    now = dt(2026, 6, 13, 12)
    overdue = {"next_due": dt(2026, 6, 1).isoformat()}
    soon = {"next_due": dt(2026, 6, 14).isoformat()}
    later = {"next_due": dt(2026, 7, 1).isoformat()}
    assert r.is_overdue(overdue, now=now) is True
    assert r.is_overdue(soon, now=now) is False
    assert r.is_due_soon(soon, timedelta(days=3), now=now) is True
    assert r.is_due_soon(later, timedelta(days=3), now=now) is False


def test_remove_completion_rewinds_to_prior():
    now = dt(2026, 6, 13, 10)
    task = {
        "recurrence_type": "floating",
        "interval": 1,
        "unit": "months",
        "created": dt(2026, 1, 1, 9).isoformat(),
        "last_completed": dt(2026, 6, 1, 9).isoformat(),
        "next_due": dt(2026, 7, 1, 9).isoformat(),
        "completions": [
            {"ts": dt(2026, 5, 1, 9).isoformat()},
            {"ts": dt(2026, 6, 1, 9).isoformat()},
        ],
    }
    r.remove_completion(task, dt(2026, 6, 1, 9).isoformat(), now=now)
    # The accidental latest completion is gone; clock rewinds to the prior one.
    assert task["completions"] == [{"ts": dt(2026, 5, 1, 9).isoformat()}]
    assert task["last_completed"] == dt(2026, 5, 1, 9).isoformat()
    assert task["next_due"] == dt(2026, 6, 1, 9).isoformat()


def test_remove_only_completion_clears_last_completed():
    now = dt(2026, 6, 13)
    task = {
        "recurrence_type": "floating",
        "interval": 30,
        "unit": "days",
        "created": dt(2026, 1, 1).isoformat(),
        "last_completed": dt(2026, 6, 1).isoformat(),
        "next_due": dt(2026, 7, 1).isoformat(),
        "completions": [{"ts": dt(2026, 6, 1).isoformat()}],
    }
    r.remove_completion(task, dt(2026, 6, 1).isoformat(), now=now)
    assert task["completions"] == []
    assert task["last_completed"] is None
    # With no completion left, the task falls back to due-now.
    assert task["next_due"] == dt(2026, 6, 13).isoformat()


def test_remove_completion_missing_ts_is_noop():
    now = dt(2026, 6, 13, 10)
    task = {
        "recurrence_type": "floating",
        "interval": 1,
        "unit": "months",
        "last_completed": dt(2026, 6, 1).isoformat(),
        "next_due": dt(2026, 7, 1).isoformat(),
        "completions": [{"ts": dt(2026, 6, 1).isoformat()}],
    }
    r.remove_completion(task, dt(2020, 1, 1).isoformat(), now=now)
    assert task["completions"] == [{"ts": dt(2026, 6, 1).isoformat()}]
    assert task["last_completed"] == dt(2026, 6, 1).isoformat()
