"""Unit tests for fixed (anchored schedule) recurrence."""

from datetime import datetime, timedelta, timezone

import hk_recurrence as r

TZ = timezone(timedelta(hours=-4))


def dt(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def test_next_daily_occurrence_preserves_time_of_day():
    anchor = dt(2026, 1, 1, 8)
    nxt = r.next_fixed_occurrence(anchor, "DAILY", 1, after=dt(2026, 6, 13, 9))
    assert nxt == dt(2026, 6, 14, 8)


def test_next_occurrence_returns_anchor_when_after_is_before_anchor():
    anchor = dt(2026, 7, 1, 8)
    nxt = r.next_fixed_occurrence(anchor, "DAILY", 1, after=dt(2026, 6, 1))
    assert nxt == anchor


def test_weekly_with_interval():
    anchor = dt(2026, 1, 1, 8)  # Thursday
    nxt = r.next_fixed_occurrence(anchor, "WEEKLY", 2, after=dt(2026, 1, 10))
    # Every 2 weeks from Jan 1: Jan 15, Jan 29 ...
    assert nxt == dt(2026, 1, 15, 8)


def test_monthly_occurrence_clamps_end_of_month():
    anchor = dt(2026, 1, 31, 9)
    nxt = r.next_fixed_occurrence(anchor, "MONTHLY", 1, after=dt(2026, 2, 1))
    assert nxt == dt(2026, 2, 28, 9)


def test_apply_completion_fixed_follows_schedule_not_completion():
    anchor = dt(2026, 1, 1, 8)
    now = dt(2026, 6, 13, 10)  # completed late in the day
    task = {
        "recurrence_type": "fixed",
        "interval": 1,
        "freq": "DAILY",
        "anchor": anchor.isoformat(),
        "completions": [],
    }
    r.apply_completion(task, now, now=now)
    # Next due is the next scheduled 08:00, NOT 24h after completion time.
    assert task["next_due"] == dt(2026, 6, 14, 8).isoformat()


def test_expand_fixed_occurrences_weekly():
    anchor = dt(2026, 1, 1, 8)  # Thursday
    occ = r.expand_fixed_occurrences(
        anchor, "WEEKLY", 1, dt(2026, 6, 1), dt(2026, 6, 30)
    )
    assert [o.date().isoformat() for o in occ] == [
        "2026-06-04",
        "2026-06-11",
        "2026-06-18",
        "2026-06-25",
    ]


def test_expand_empty_when_range_inverted():
    anchor = dt(2026, 1, 1, 8)
    assert (
        r.expand_fixed_occurrences(anchor, "DAILY", 1, dt(2026, 6, 2), dt(2026, 6, 1))
        == []
    )


def test_next_daily_occurrence_with_far_past_anchor_does_not_raise():
    # Regression: a fixed DAILY task left running > MAX_EXPAND_ITERATIONS days used
    # to blow the iteration cap and raise, taking the calendar/sensor down. It must
    # now compute the correct next occurrence (next 08:00) instead.
    anchor = dt(2020, 1, 1, 8)
    nxt = r.next_fixed_occurrence(anchor, "DAILY", 1, after=dt(2026, 6, 13, 9))
    assert nxt == dt(2026, 6, 14, 8)


def test_next_weekly_occurrence_with_far_past_anchor():
    anchor = dt(2014, 1, 2, 8)  # Thursday, ~12 years before `after`
    nxt = r.next_fixed_occurrence(anchor, "WEEKLY", 1, after=dt(2026, 6, 13))
    # Anchored on a Thursday; the first Thursday strictly after Sat 2026-06-13.
    assert nxt.weekday() == anchor.weekday()
    assert nxt > dt(2026, 6, 13)
    assert nxt - timedelta(weeks=1) <= dt(2026, 6, 13)


def test_expand_daily_with_far_past_anchor_returns_window():
    anchor = dt(2020, 1, 1, 8)
    occ = r.expand_fixed_occurrences(anchor, "DAILY", 1, dt(2026, 6, 1), dt(2026, 6, 4))
    assert [o.date().isoformat() for o in occ] == [
        "2026-06-01",
        "2026-06-02",
        "2026-06-03",
    ]


def _naive_next_monthly(anchor, interval, after):
    """Reference: smallest occurrence strictly after *after* by single-stepping."""
    if anchor > after:
        return anchor
    occ = anchor
    while occ <= after:
        occ = r.add_months(occ, interval)
    return occ


def test_next_monthly_occurrence_with_far_past_anchor_does_not_raise():
    # Regression: a fixed MONTHLY task anchored more than MAX_EXPAND_ITERATIONS
    # months (~41.6 years) in the past used to blow the iteration cap and raise a
    # RuntimeError, taking the next-due sensor / calendar / overdue sensor down (the
    # MONTHLY branch of _fast_forward did not jump). It must compute the correct
    # next occurrence instead.
    anchor = dt(1976, 6, 21, 9)  # 50 years before `after`
    after = dt(2026, 6, 21)
    nxt = r.next_fixed_occurrence(anchor, "MONTHLY", 1, after=after)
    assert nxt == dt(2026, 6, 21, 9)
    assert nxt == _naive_next_monthly(anchor, 1, after)


def test_next_monthly_far_past_matches_naive_across_day_clamping():
    # The O(1) MONTHLY fast-forward must stay byte-identical to single-stepping,
    # including end-of-month clamping (Jan 31 -> Feb 28 -> ... sticks at 28) and
    # leap years. Spot-check several clamping-prone anchors/intervals far in the past.
    after = dt(2026, 6, 13, 9)
    cases = [
        (dt(1980, 1, 31, 9), 1),
        (dt(1980, 3, 31, 9), 1),
        (dt(1981, 1, 29, 9), 1),
        (dt(1975, 8, 30, 9), 2),
        (dt(1970, 12, 31, 9), 3),
        (dt(1984, 2, 29, 9), 12),
    ]
    for anchor, interval in cases:
        assert r.next_fixed_occurrence(
            anchor, "MONTHLY", interval, after=after
        ) == _naive_next_monthly(anchor, interval, after), (anchor, interval)


def test_expand_monthly_with_far_past_anchor_returns_window():
    anchor = dt(1980, 1, 31, 9)  # far past + end-of-month clamping
    occ = r.expand_fixed_occurrences(
        anchor, "MONTHLY", 1, dt(2026, 6, 1), dt(2026, 9, 1)
    )
    # Day clamps to 28 permanently once a non-leap February is crossed.
    assert [o.date().isoformat() for o in occ] == [
        "2026-06-28",
        "2026-07-28",
        "2026-08-28",
    ]


def test_remove_completion_keeps_fixed_schedule():
    from datetime import datetime, timedelta, timezone

    import hk_recurrence as r

    tz = timezone(timedelta(hours=-4))
    now = datetime(2026, 6, 13, 10, tzinfo=tz)
    task = {
        "recurrence_type": "fixed",
        "interval": 1,
        "freq": "DAILY",
        "anchor": datetime(2026, 1, 1, 8, tzinfo=tz).isoformat(),
        "last_completed": datetime(2026, 6, 12, 8, tzinfo=tz).isoformat(),
        "next_due": datetime(2026, 6, 14, 8, tzinfo=tz).isoformat(),
        "completions": [{"ts": datetime(2026, 6, 12, 8, tzinfo=tz).isoformat()}],
    }
    r.remove_completion(task, datetime(2026, 6, 12, 8, tzinfo=tz).isoformat(), now=now)
    assert task["completions"] == []
    assert task["last_completed"] is None
    # Fixed schedule is independent of completions: next occurrence after now.
    assert task["next_due"] == datetime(2026, 6, 14, 8, tzinfo=tz).isoformat()
