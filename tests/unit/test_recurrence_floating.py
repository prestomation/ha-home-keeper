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


def test_floating_next_due_uses_now_when_never_completed():
    nd = r.compute_floating_next_due(None, 30, "days", now=dt(2026, 6, 13))
    assert nd == dt(2026, 7, 13)


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
