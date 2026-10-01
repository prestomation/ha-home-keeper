"""Unit tests for floating recurrence (reset-from-completion)."""

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import hk_recurrence as r
from asserts import raises_exactly

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

    with raises_exactly(ValueError, "interval must be >= 1, got 0"):
        r.add_interval(dt(2026, 1, 1), 0, "days")
    with raises_exactly(ValueError, "unknown unit: 'fortnights'"):
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


def test_apply_completion_qualifies_naive_completed_at():
    # HA's cv.datetime hands over a *naive* datetime for offset-less service input.
    # A naive value must be qualified with now's zone before persisting — otherwise
    # last_completed/ts/next_due are stored naive and every later aware comparison
    # (is_overdue, history max) raises TypeError.
    now = dt(2026, 6, 13, 10)
    task = {
        "recurrence_type": "floating",
        "interval": 1,
        "unit": "months",
        "completions": [],
    }
    naive = datetime(2026, 6, 12, 9, 30)  # no tzinfo
    r.apply_completion(task, naive, now=now)
    assert task["last_completed"] == dt(2026, 6, 12, 9, 30).isoformat()
    assert task["next_due"] == dt(2026, 7, 12, 9, 30).isoformat()
    # The stored values are aware: comparisons against an aware now must not raise.
    assert r.is_overdue(task, now=now) is False


def test_apply_completion_idempotent_for_duplicate_ts():
    # Two completions at the identical instant (double-tapped notification) must not
    # create an ambiguous duplicate history entry — the second replaces the first.
    now = dt(2026, 6, 13, 10)
    task = {
        "recurrence_type": "floating",
        "interval": 1,
        "unit": "months",
        "completions": [],
    }
    r.apply_completion(task, now, now=now, metadata={"note": "first"})
    r.apply_completion(task, now, now=now, metadata={"note": "second"})
    assert len(task["completions"]) == 1
    assert task["completions"][0]["note"] == "second"


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


# --- Back-filled and removed rows, and the HA zone (B07-2, B07-3, B07-4) -----

LA = ZoneInfo("America/Los_Angeles")


def la(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=LA)


def _monthly(**over):
    task = {
        "recurrence_type": "floating",
        "interval": 1,
        "unit": "months",
        "completions": [],
    }
    task.update(over)
    return task


def test_b07_3_a_back_filled_completion_keeps_last_completed_and_next_due():
    """B07-3: log a forgotten Aug 15 completion after the Sep 20 one."""
    task = _monthly()
    sep20 = la(2026, 9, 20, 9)
    r.apply_completion(task, sep20, now=sep20)
    assert task["next_due"] == la(2026, 10, 20, 9).isoformat()
    now = la(2026, 9, 30, 12)
    r.apply_completion(task, la(2026, 8, 15, 9), now=now, metadata={"note": "late"})
    assert task["last_completed"] == sep20.isoformat()
    assert task["next_due"] == la(2026, 10, 20, 9).isoformat()
    assert not r.is_overdue(task, now=now)
    assert [c["ts"] for c in task["completions"]] == [
        sep20.isoformat(),
        la(2026, 8, 15, 9).isoformat(),
    ]
    assert task["completions"][1]["note"] == "late"


def test_b07_3_a_completion_at_the_latest_instant_is_not_a_back_fill():
    """The same instant again replaces the row and still counts as the latest."""
    task = _monthly()
    sep20 = la(2026, 9, 20, 9)
    r.apply_completion(task, sep20, now=sep20)
    task["next_due"] = la(2026, 9, 25).isoformat()
    r.apply_completion(task, sep20, now=la(2026, 9, 30))
    assert task["next_due"] == la(2026, 10, 20, 9).isoformat()
    assert len(task["completions"]) == 1


def test_b07_3_a_back_fill_on_a_fixed_task_leaves_the_schedule():
    anchor = la(2026, 1, 1, 9)
    task = {
        "recurrence_type": "fixed",
        "interval": 1,
        "freq": "MONTHLY",
        "anchor": anchor.isoformat(),
        "next_due": la(2026, 9, 1, 9).isoformat(),
        "completions": [],
    }
    sep1 = la(2026, 9, 1, 10)
    r.apply_completion(task, sep1, now=sep1)
    assert task["next_due"] == la(2026, 10, 1, 9).isoformat()
    r.apply_completion(task, la(2026, 8, 1, 10), now=la(2026, 9, 2))
    assert task["next_due"] == la(2026, 10, 1, 9).isoformat()
    assert task["last_completed"] == sep1.isoformat()
    assert r.PRIOR_DUE not in task["completions"][-1]


def test_b07_3_a_back_fill_on_a_one_off_keeps_the_latest_date():
    task = {
        "recurrence_type": "one-off",
        "due": la(2026, 9, 1).isoformat(),
        "next_due": la(2026, 9, 1).isoformat(),
        "completions": [],
    }
    done = la(2026, 9, 2)
    r.apply_completion(task, done, now=done)
    r.apply_completion(task, la(2026, 8, 1), now=la(2026, 9, 3))
    assert task["last_completed"] == done.isoformat()
    assert task["next_due"] is None


def test_b07_2_deleting_an_old_row_keeps_a_later_skip():
    """B07-2 (b): completed Jul 1 and Aug 1, skipped Sep 1, delete Jul 1."""
    task = _monthly()
    jul1, aug1 = la(2026, 7, 1, 9), la(2026, 8, 1, 9)
    r.apply_completion(task, jul1, now=jul1)
    r.apply_completion(task, aug1, now=aug1)
    r.skip_occurrence(task, now=la(2026, 9, 1, 9))
    assert task["next_due"] == la(2026, 10, 1, 9).isoformat()
    r.remove_completion(task, jul1.isoformat(), now=la(2026, 9, 2))
    assert task["next_due"] == la(2026, 10, 1, 9).isoformat()
    assert task["last_completed"] == aug1.isoformat()


def test_b07_2_deleting_the_latest_row_still_rewinds_the_clock():
    task = _monthly()
    jul1, aug1 = la(2026, 7, 1, 9), la(2026, 8, 1, 9)
    r.apply_completion(task, jul1, now=jul1)
    r.apply_completion(task, aug1, now=aug1)
    r.remove_completion(task, aug1.isoformat(), now=la(2026, 8, 2))
    assert task["next_due"] == la(2026, 8, 1, 9).isoformat()
    assert task["last_completed"] == jul1.isoformat()


def test_b07_2_a_skip_at_the_same_instant_as_the_deleted_row_keeps_next_due():
    """A skip at the instant of the removed completion is not before it."""
    task = _monthly()
    jul1, aug1 = la(2026, 7, 1, 9), la(2026, 8, 1, 9)
    r.apply_completion(task, jul1, now=jul1)
    r.apply_completion(task, aug1, now=aug1)
    r.skip_occurrence(task, now=aug1)
    skipped_due = task["next_due"]
    assert skipped_due != la(2026, 8, 1, 9).isoformat()
    r.remove_completion(task, aug1.isoformat(), now=la(2026, 8, 2))
    assert task["last_completed"] == jul1.isoformat()
    assert task["next_due"] == skipped_due


def test_b07_3_a_first_completion_on_a_task_with_no_log_key():
    """A task stored by an older release can have no ``completions`` key."""
    task = _monthly()
    del task["completions"]
    done = la(2026, 7, 1, 9)
    r.apply_completion(task, done, now=done)
    assert task["last_completed"] == done.isoformat()
    assert task["next_due"] == la(2026, 8, 1, 9).isoformat()
    assert [c["ts"] for c in task["completions"]] == [done.isoformat()]


def test_b07_4_undo_recalculates_on_the_ha_wall_clock_across_dst():
    """B07-4: done 23:30 PST, undo of a later Done keeps 23:30 PDT on Mar 20."""
    task = _monthly()
    feb20 = la(2026, 2, 20, 23, 30)
    r.apply_completion(task, feb20, now=feb20)
    live = task["next_due"]
    assert live == la(2026, 3, 20, 23, 30).isoformat()
    mistake = la(2026, 3, 1, 12)
    r.apply_completion(task, mistake, now=mistake)
    r.remove_completion(task, mistake.isoformat(), now=mistake)
    assert task["next_due"] == live
    assert datetime.fromisoformat(task["next_due"]).astimezone(LA).day == 20


def test_b07_4_a_utc_completion_is_counted_on_the_ha_wall_clock():
    """A panel sends a back-dated completion as UTC text."""
    task = _monthly(interval=1, unit="days")
    utc = datetime(2026, 3, 8, 7, 30, tzinfo=UTC)  # Mar 7 23:30 PST
    r.apply_completion(task, utc, now=la(2026, 3, 9))
    assert datetime.fromisoformat(task["next_due"]) == la(2026, 3, 8, 23, 30)


def test_b07_4_a_season_start_is_local_midnight():
    """Season Dec 1 - Feb 28; done in July (PDT); due Dec 1 00:00 PST, in season."""
    season = [{"start": "12-01", "end": "02-28"}]
    task = _monthly(active_season=season)
    jul15 = la(2026, 7, 15, 9)
    r.apply_completion(task, jul15, now=la(2026, 7, 15, 9))
    assert task["next_due"] == la(2026, 12, 1).isoformat()
    again = r.compute_next_due(task, now=la(2026, 7, 16))
    assert again == la(2026, 12, 1)
    assert again.date().isoformat() == "2026-12-01"
    assert r.in_season(again, season)


# --- latest_completion (B15-7) -----------------------------------------------


def test_b15_7_latest_completion_compares_instants_not_text() -> None:
    # As text, the UTC entry sorts after the -07:00 one. As instants it is earlier:
    # 03:00 UTC is before 21:00-07:00 (04:00 UTC).
    backdated = {"ts": "2026-03-02T03:00:00+00:00", "note": "backdated"}
    latest = {"ts": "2026-03-01T21:00:00-07:00", "note": "latest"}
    assert r.latest_completion([backdated, latest]) is latest
    assert r.latest_completion([latest, backdated]) is latest


def test_b15_7_latest_completion_skips_a_missing_or_bad_ts() -> None:
    good = {"ts": "2026-03-01T10:00:00+00:00"}
    assert r.latest_completion([{}, {"ts": None}, {"ts": "not a date"}, good]) is good
    assert r.latest_completion([good, {"ts": "zzz"}]) is good
    assert r.latest_completion([{"ts": "bad"}]) is None
    assert r.latest_completion([]) is None


def test_b15_7_latest_completion_keeps_the_first_of_a_tie() -> None:
    first = {"ts": "2026-03-01T10:00:00+00:00", "n": 1}
    second = {"ts": "2026-03-01T11:00:00+01:00", "n": 2}
    assert r.latest_completion([first, second]) is first
