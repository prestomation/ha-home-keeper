"""Unit tests for skip_occurrence (advance a task with no completion recorded)."""

from datetime import datetime, timedelta, timezone

import hk_recurrence as r

TZ = timezone(timedelta(hours=-4))


def dt(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def test_skip_floating_jumps_one_interval_from_now_without_completing():
    now = dt(2026, 6, 13, 10)
    task = {
        "recurrence_type": "floating",
        "interval": 7,
        "unit": "days",
        "last_completed": "2026-01-01T00:00:00-04:00",
        "next_due": "2026-01-08T00:00:00-04:00",  # long overdue
        "completions": [{"ts": "2026-01-01T00:00:00-04:00"}],
    }
    out = r.skip_occurrence(dict(task), now=now)
    # next_due jumps a fresh interval from now…
    assert out["next_due"] == (now + timedelta(days=7)).isoformat()
    # …and nothing about the completion log / clock changed.
    assert out["last_completed"] == task["last_completed"]
    assert out["completions"] == task["completions"]


def test_skip_floating_months_unit():
    now = dt(2026, 1, 31, 9)
    task = {"recurrence_type": "floating", "interval": 1, "unit": "months"}
    out = r.skip_occurrence(dict(task), now=now)
    # Feb clamps to the 28th (non-leap 2026).
    assert out["next_due"] == dt(2026, 2, 28, 9).isoformat()


def test_skip_fixed_overdue_advances_to_next_future_occurrence():
    task = {
        "recurrence_type": "fixed",
        "freq": "DAILY",
        "interval": 1,
        "anchor": "2026-01-01T08:00:00-04:00",
        "next_due": "2026-06-10T08:00:00-04:00",  # several days overdue
    }
    now = dt(2026, 6, 13, 9)
    out = r.skip_occurrence(dict(task), now=now)
    # Skipping an overdue fixed task lands on the next occurrence after *now*,
    # not the one immediately after the long-past due date.
    assert out["next_due"] == dt(2026, 6, 14, 8).isoformat()


def test_skip_fixed_upcoming_advances_exactly_one_occurrence():
    task = {
        "recurrence_type": "fixed",
        "freq": "WEEKLY",
        "interval": 1,
        "anchor": "2026-01-01T08:00:00-04:00",  # Thursdays
        "next_due": "2026-06-18T08:00:00-04:00",  # upcoming (future)
    }
    now = dt(2026, 6, 13, 9)  # before next_due
    out = r.skip_occurrence(dict(task), now=now)
    # Skips the upcoming occurrence to the following week.
    assert out["next_due"] == dt(2026, 6, 25, 8).isoformat()


def test_skip_one_off_goes_dormant():
    task = {
        "recurrence_type": "one-off",
        "due": "2026-06-10T08:00:00-04:00",
        "next_due": "2026-06-10T08:00:00-04:00",
    }
    out = r.skip_occurrence(dict(task), now=dt(2026, 6, 13))
    assert out["next_due"] is None


def test_skip_triggered_goes_dormant():
    task = {
        "recurrence_type": "triggered",
        "next_due": "2026-06-10T08:00:00-04:00",
    }
    out = r.skip_occurrence(dict(task), now=dt(2026, 6, 13))
    assert out["next_due"] is None


def test_skip_sensor_goes_dormant():
    task = {"recurrence_type": "sensor", "next_due": "2026-06-10T08:00:00-04:00"}
    out = r.skip_occurrence(dict(task), now=dt(2026, 6, 13))
    assert out["next_due"] is None


def test_skip_unknown_recurrence_type_raises():
    import pytest

    with pytest.raises(ValueError, match="unknown recurrence_type"):
        r.skip_occurrence({"recurrence_type": "bogus"}, now=dt(2026, 6, 13))
