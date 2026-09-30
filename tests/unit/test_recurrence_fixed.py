"""Unit tests for fixed (anchored schedule) recurrence."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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


def test_completing_before_the_time_of_day_moves_to_the_next_occurrence():
    # Regression (#331): a DAILY task anchored at 10:00 and marked done at 09:00 used
    # to stay due at 10:00 *today*. The schedule advanced past ``now``, which is still
    # before the occurrence the task was showing, so it landed straight back on that
    # occurrence and the completion read as though it had done nothing. An anchor late
    # in the evening was unusable this way for nearly the whole day.
    anchor = dt(2026, 9, 8, 10)
    now = dt(2026, 9, 8, 9)
    task = {
        "recurrence_type": "fixed",
        "interval": 1,
        "freq": "DAILY",
        "anchor": anchor.isoformat(),
        "next_due": anchor.isoformat(),
        "completions": [],
    }
    r.apply_completion(task, now, now=now)
    assert task["next_due"] == dt(2026, 9, 9, 10).isoformat()
    assert task["last_completed"] == now.isoformat()


def test_completing_an_overdue_fixed_task_collapses_the_missed_occurrences():
    # The other half of ``max(now, next_due)``: a long-overdue task lands on the next
    # occurrence after *now* rather than crawling the grid one missed occurrence per
    # completion. The completion twin of
    # ``test_skip_fixed_overdue_advances_to_next_future_occurrence``.
    task = {
        "recurrence_type": "fixed",
        "interval": 1,
        "freq": "DAILY",
        "anchor": dt(2026, 1, 1, 8).isoformat(),
        "next_due": dt(2026, 6, 10, 8).isoformat(),  # several days overdue
        "completions": [],
    }
    now = dt(2026, 6, 13, 9)
    r.apply_completion(task, now, now=now)
    assert task["next_due"] == dt(2026, 6, 14, 8).isoformat()


def test_completing_an_upcoming_fixed_task_advances_exactly_one_occurrence():
    # An occurrence still ahead of ``now`` advances by exactly one step, never more.
    # This is what pins ``max`` rather than ``min``: taking the smaller operand here
    # would hand back the occurrence the task is already showing.
    anchor = dt(2026, 6, 18, 8)
    task = {
        "recurrence_type": "fixed",
        "interval": 1,
        "freq": "WEEKLY",
        "anchor": anchor.isoformat(),
        "next_due": anchor.isoformat(),
        "completions": [],
    }
    now = dt(2026, 6, 13, 9)
    r.apply_completion(task, now, now=now)
    assert task["next_due"] == dt(2026, 6, 25, 8).isoformat()


def test_completing_a_fixed_task_with_no_due_date_advances_from_now():
    # ``models.build_task`` records a ``last_completed`` seed *before* it computes the
    # schedule, so the task reaching ``apply_completion`` carries no ``next_due`` at
    # all. There is no occurrence on the board to clear, so *now* is the whole answer.
    task = {
        "recurrence_type": "fixed",
        "interval": 1,
        "freq": "DAILY",
        "anchor": dt(2026, 1, 1, 8).isoformat(),
        "completions": [],
    }
    now = dt(2026, 6, 13, 9)
    r.apply_completion(task, now, now=now)
    assert task["next_due"] == dt(2026, 6, 14, 8).isoformat()


def test_undoing_a_completion_puts_the_cleared_occurrence_back():
    # The asymmetry with ``move_completion``: an undo is *meant* to rewind, so
    # ``remove_completion`` recomputes from the anchor and today's occurrence returns
    # to every time surface.
    anchor = dt(2026, 9, 8, 10)
    now = dt(2026, 9, 8, 9)
    task = {
        "recurrence_type": "fixed",
        "interval": 1,
        "freq": "DAILY",
        "anchor": anchor.isoformat(),
        "next_due": anchor.isoformat(),
        "completions": [],
    }
    r.apply_completion(task, now, now=now)
    assert task["next_due"] == dt(2026, 9, 9, 10).isoformat()
    r.remove_completion(task, now.isoformat(), now=now)
    assert task["next_due"] == anchor.isoformat()
    assert task["last_completed"] is None


def test_a_schedule_keeps_its_local_hour_across_dst_after_a_storage_round_trip():
    # Regression: an ISO string carries an *offset*, not a zone identity, so whatever
    # tzinfo the anchor had when it was written, it reloads as a fixed offset —
    # ``fromisoformat("...-07:00").tzinfo`` is ``timezone(timedelta(hours=-7))``, not
    # ``ZoneInfo``. ``_step`` then holds that offset's wall clock, and a 10:00 task
    # reads 09:00 once the zone leaves DST.
    #
    # ``test_r5a`` proves ``_step`` keeps local wall time, but only for a live
    # ``ZoneInfo`` anchor — the shape storage can never hand back. This pins the shape
    # production actually produces.
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/Los_Angeles")
    stored = datetime(2026, 9, 8, 10, tzinfo=zone).isoformat()
    anchor = datetime.fromisoformat(stored)  # the reload, offset-only

    after_dst_ends = datetime(2026, 11, 5, 9, tzinfo=zone)
    nxt = r.next_fixed_occurrence(anchor, "DAILY", 1, after=after_dst_ends)

    local = nxt.astimezone(zone)
    assert (local.hour, local.minute) == (10, 0), (
        f"stored {stored} reloaded as {anchor.tzinfo!r} and drifted to "
        f"{local.isoformat()}"
    )


def test_a_utc_anchor_still_schedules_at_the_hour_the_user_chose():
    # The shape every panel-created task already carries: the browser converted the
    # user's 10:00 to UTC before sending it. Read back in the user's zone it is still
    # their 10:00, and it has to stay their 10:00 after the clock changes.
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/Los_Angeles")
    anchor = datetime.fromisoformat("2026-09-08T17:00:00+00:00")  # 10:00 PDT

    for probe, label in (
        (datetime(2026, 9, 8, 9, tzinfo=zone), "same day, before the occurrence"),
        (datetime(2026, 11, 5, 9, tzinfo=zone), "after DST ends"),
    ):
        nxt = r.next_fixed_occurrence(anchor, "DAILY", 1, after=probe).astimezone(zone)
        assert (nxt.hour, nxt.minute) == (10, 0), f"{label}: got {nxt.isoformat()}"


# ── a deferred next_due is not an occurrence ──────────────────────────────────
def _weekly_monday():
    """A fixed task on Mondays at 09:00, showing its next occurrence."""
    anchor = dt(2026, 1, 5, 9)  # a Monday
    return {
        "recurrence_type": "fixed",
        "interval": 1,
        "freq": "WEEKLY",
        "anchor": anchor.isoformat(),
        "next_due": anchor.isoformat(),
        "completions": [],
    }


def test_completing_a_snoozed_fixed_task_takes_the_next_occurrence():
    """A snooze target is not on the grid, so it must not move the schedule.

    ``store.snooze_task`` writes an arbitrary instant into ``next_due``. Advancing
    past *that* skipped every occurrence between the task's real one and the snooze
    target: snoozing a Monday task by a week and then doing it anyway lost the
    Monday in between.
    """
    task = _weekly_monday()
    task["next_due"] = dt(2026, 1, 15, 9).isoformat()  # snoozed 10 days out
    now = dt(2026, 1, 5, 10)
    out = r.apply_completion(task, now, now=now)
    assert out["next_due"] == dt(2026, 1, 12, 9).isoformat()


def test_skipping_a_snoozed_fixed_task_takes_the_next_occurrence():
    task = _weekly_monday()
    task["next_due"] = dt(2026, 1, 15, 9).isoformat()
    out = r.skip_occurrence(task, now=dt(2026, 1, 5, 10))
    assert out["next_due"] == dt(2026, 1, 12, 9).isoformat()


def test_completing_a_task_moved_to_today_takes_the_next_occurrence():
    """``set_due_today`` writes ``now``, which is off the grid the same way."""
    task = _weekly_monday()
    now = dt(2026, 1, 5, 10)
    task["next_due"] = now.isoformat()
    out = r.apply_completion(task, now, now=now)
    assert out["next_due"] == dt(2026, 1, 12, 9).isoformat()


def test_an_occurrence_on_the_grid_still_moves_the_schedule_past_it():
    """#331 stays fixed: done at 08:00 must not hand back today's 09:00."""
    task = _weekly_monday()
    now = dt(2026, 1, 5, 8)
    out = r.apply_completion(task, now, now=now)
    assert out["next_due"] == dt(2026, 1, 12, 9).isoformat()


def test_an_overdue_fixed_task_still_collapses_the_missed_occurrences():
    task = _weekly_monday()
    now = dt(2026, 2, 4, 10)  # a Wednesday, 4 Mondays later
    out = r.apply_completion(task, now, now=now)
    assert out["next_due"] == dt(2026, 2, 9, 9).isoformat()


# --- Schedule state that the log does not hold (B07-1, B07-2, B07-5) ---------

LA = ZoneInfo("America/Los_Angeles")


def la(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=LA)


def _fixed(anchor, freq="DAILY", **over):
    task = {
        "recurrence_type": "fixed",
        "interval": 1,
        "freq": freq,
        "anchor": anchor.isoformat(),
        "next_due": anchor.isoformat(),
        "completions": [],
    }
    task.update(over)
    return task


def test_b07_1_undo_on_an_overdue_fixed_task_puts_the_overdue_occurrence_back():
    """B07-1: Done by mistake on an overdue task, then Undo, keeps it overdue."""
    task = _fixed(la(2026, 1, 1, 9), "MONTHLY", next_due=la(2026, 9, 1, 9).isoformat())
    now = la(2026, 9, 20, 12)
    assert r.is_overdue(task, now=now)
    r.apply_completion(task, now, now=now)
    assert task["next_due"] == la(2026, 10, 1, 9).isoformat()
    assert task["completions"][-1][r.PRIOR_DUE] == la(2026, 9, 1, 9).isoformat()
    r.remove_completion(task, now.isoformat(), now=now)
    assert task["next_due"] == la(2026, 9, 1, 9).isoformat()
    assert r.is_overdue(task, now=now)
    assert task["last_completed"] is None


def test_b07_1_a_task_with_no_due_date_records_no_prior_due():
    """Nothing to put back, so the undo calculates the date from the anchor."""
    task = _fixed(dt(2026, 1, 1, 8))
    del task["next_due"]
    now = dt(2026, 6, 13, 9)
    r.apply_completion(task, now, now=now)
    assert r.PRIOR_DUE not in task["completions"][0]
    r.remove_completion(task, now.isoformat(), now=now)
    assert task["next_due"] == dt(2026, 6, 14, 8).isoformat()


def test_b07_1_a_later_skip_keeps_its_due_date_after_the_undo():
    task = _fixed(la(2026, 9, 1, 10))
    done = la(2026, 9, 1, 11)
    r.apply_completion(task, done, now=done)
    skipped = la(2026, 9, 2, 11)
    r.skip_occurrence(task, now=skipped)
    assert task["next_due"] == la(2026, 9, 3, 10).isoformat()
    r.remove_completion(task, done.isoformat(), now=skipped)
    assert task["next_due"] == la(2026, 9, 3, 10).isoformat()
    assert task["last_completed"] is None


def test_b07_1_an_undo_after_an_earlier_skip_puts_the_date_back():
    """A skip before the undone completion does not block the undo."""
    task = _fixed(la(2026, 9, 1, 10))
    skipped = la(2026, 9, 1, 11)
    r.skip_occurrence(task, now=skipped)
    done = la(2026, 9, 2, 11)
    r.apply_completion(task, done, now=done)
    assert task["next_due"] == la(2026, 9, 3, 10).isoformat()
    r.remove_completion(task, done.isoformat(), now=done)
    assert task["next_due"] == la(2026, 9, 2, 10).isoformat()


def test_b07_2_deleting_an_old_row_keeps_an_early_completion():
    """B07-2 (a): a stray old row goes, today's early Done stays done."""
    old = la(2026, 8, 1, 10)
    task = _fixed(la(2026, 7, 1, 10))
    r.apply_completion(task, old, now=old)
    task["next_due"] = la(2026, 9, 30, 10).isoformat()
    early = la(2026, 9, 30, 9)
    r.apply_completion(task, early, now=early)
    assert task["next_due"] == la(2026, 10, 1, 10).isoformat()
    r.remove_completion(task, old.isoformat(), now=early)
    assert task["next_due"] == la(2026, 10, 1, 10).isoformat()
    assert task["last_completed"] == early.isoformat()
    assert not r.is_overdue(task, now=la(2026, 9, 30, 10, 1))


def test_b07_2_an_unknown_ts_changes_nothing():
    task = _fixed(la(2026, 9, 1, 10), next_due=la(2026, 9, 20, 18).isoformat())
    r.remove_completion(task, la(2020, 1, 1).isoformat(), now=la(2026, 9, 2))
    assert task["next_due"] == la(2026, 9, 20, 18).isoformat()


def test_b07_5_due_today_then_done_moves_past_the_occurrence_it_replaced():
    """B07-5: Saturdays at 10:00; Due today on Wednesday, then Done."""
    task = _fixed(
        la(2026, 9, 5, 10), "WEEKLY", next_due=la(2026, 10, 3, 10).isoformat()
    )
    wed = la(2026, 9, 30, 12)
    r.defer(task, wed, now=wed)
    assert task["next_due"] == wed.isoformat()
    assert task[r.DEFERRED_FROM] == la(2026, 10, 3, 10).isoformat()
    r.apply_completion(task, wed, now=wed)
    assert task["next_due"] == la(2026, 10, 10, 10).isoformat()


def test_b07_5_monthly_due_today_then_done():
    task = _fixed(
        la(2026, 1, 28, 9), "MONTHLY", next_due=la(2026, 10, 28, 9).isoformat()
    )
    now = la(2026, 10, 10, 12)
    r.defer(task, now, now=now)
    r.apply_completion(task, now, now=now)
    assert task["next_due"] == la(2026, 11, 28, 9).isoformat()


def test_b07_5_an_early_snooze_then_done_before_the_time_of_day():
    """Snooze 24 h on Friday, Done on Saturday at 09:00, before the 10:00 slot."""
    task = _fixed(
        la(2026, 9, 5, 10), "WEEKLY", next_due=la(2026, 10, 3, 10).isoformat()
    )
    fri = la(2026, 10, 2, 8)
    r.defer(task, fri + timedelta(hours=24), now=fri)
    # A second snooze keeps the occurrence that the first one moved.
    r.defer(task, la(2026, 10, 3, 8, 30), now=fri)
    assert task[r.DEFERRED_FROM] == la(2026, 10, 3, 10).isoformat()
    sat = la(2026, 10, 3, 9)
    r.apply_completion(task, sat, now=sat)
    assert task["next_due"] == la(2026, 10, 10, 10).isoformat()


def test_b07_5_skip_after_due_today_moves_past_the_occurrence_too():
    task = _fixed(
        la(2026, 9, 5, 10), "WEEKLY", next_due=la(2026, 10, 3, 10).isoformat()
    )
    wed = la(2026, 9, 30, 12)
    r.defer(task, wed, now=wed)
    r.skip_occurrence(task, now=wed)
    assert task["next_due"] == la(2026, 10, 10, 10).isoformat()


def test_b07_5_a_record_off_the_grid_is_ignored():
    """A stale record from an old schedule does not move the new one."""
    task = _fixed(
        la(2026, 9, 5, 10), "WEEKLY", next_due=la(2026, 9, 30, 12).isoformat()
    )
    task[r.DEFERRED_FROM] = la(2026, 10, 3, 11).isoformat()
    now = la(2026, 9, 30, 12)
    r.apply_completion(task, now, now=now)
    assert task["next_due"] == la(2026, 10, 3, 10).isoformat()


def test_b07_5_defer_records_nothing_for_an_off_grid_or_floating_task():
    task = _fixed(
        la(2026, 9, 5, 10), "WEEKLY", next_due=la(2026, 10, 1, 12).isoformat()
    )
    r.defer(task, la(2026, 10, 2), now=la(2026, 9, 30))
    assert r.DEFERRED_FROM not in task
    floating = {"recurrence_type": "floating", "next_due": la(2026, 10, 3).isoformat()}
    r.defer(floating, la(2026, 10, 5), now=la(2026, 9, 30))
    assert floating == {
        "recurrence_type": "floating",
        "next_due": la(2026, 10, 5).isoformat(),
    }


def test_b07_5_defer_of_a_task_with_no_due_date_only_sets_it():
    task = _fixed(la(2026, 9, 5, 10), "WEEKLY")
    del task["next_due"]
    r.defer(task, la(2026, 10, 2), now=la(2026, 9, 30))
    assert r.DEFERRED_FROM not in task
    assert task["next_due"] == la(2026, 10, 2).isoformat()


def test_b07_5_defer_reads_the_grid_in_the_ha_zone():
    """A stored -07:00 due date after the DST change is still on the grid."""
    task = _fixed(la(2026, 9, 5, 10), "WEEKLY")
    stored = datetime(2026, 11, 7, 10, tzinfo=timezone(timedelta(hours=-8)))
    task["next_due"] = stored.isoformat()
    r.defer(task, la(2026, 11, 5, 12), now=la(2026, 11, 5, 12))
    assert task[r.DEFERRED_FROM] == stored.isoformat()
