"""Unit tests for the set due time of floating tasks (#438)."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

import hk_models as m
import hk_recurrence as r

TZ = ZoneInfo("America/Los_Angeles")
EIGHT = time(8, 0)


def dt(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def floating(**extra):
    return {
        "recurrence_type": "floating",
        "interval": 90,
        "unit": "days",
        "completions": [],
        "last_completed": None,
        "next_due": None,
        **extra,
    }


# ── snap_to_due_time ─────────────────────────────────────────────────────────


def test_snap_without_a_due_time_returns_the_value():
    value = dt(2027, 1, 5, 22, 42)
    assert r.snap_to_due_time(value, None) is value
    assert r.snap_to_due_time(value, None, round_up=True) is value


def test_snap_keeps_the_date():
    assert r.snap_to_due_time(dt(2027, 1, 5, 22, 42), EIGHT) == dt(2027, 1, 5, 8)
    assert r.snap_to_due_time(dt(2027, 1, 5, 0, 5), EIGHT) == dt(2027, 1, 5, 8)


def test_snap_round_up_moves_to_the_next_set_time():
    # Later than the set time: the next day.
    assert r.snap_to_due_time(dt(2027, 1, 5, 23), EIGHT, round_up=True) == dt(
        2027, 1, 6, 8
    )
    # Earlier than the set time: the same day.
    assert r.snap_to_due_time(dt(2027, 1, 5, 7), EIGHT, round_up=True) == dt(
        2027, 1, 5, 8
    )
    # At the set time: no change.
    assert r.snap_to_due_time(dt(2027, 1, 5, 8), EIGHT, round_up=True) == dt(
        2027, 1, 5, 8
    )


def test_snap_keeps_wall_time_across_daylight_saving():
    # 2027-03-14 is the spring change in Los Angeles. The offset changes, the
    # wall time does not.
    snapped = r.snap_to_due_time(dt(2027, 3, 14, 22), EIGHT)
    assert (snapped.hour, snapped.minute) == (8, 0)
    assert snapped.utcoffset() != dt(2027, 3, 13, 8).utcoffset()


# ── completion, skip and compute_next_due ────────────────────────────────────


def test_completion_is_due_at_the_set_time_on_its_date():
    now = dt(2026, 10, 7, 22, 42)
    task = r.apply_completion(floating(), now, now=now, due_time=EIGHT)
    assert task["next_due"] == dt(2027, 1, 5, 8).isoformat()


def test_completion_without_a_due_time_keeps_the_clock_time():
    now = dt(2026, 10, 7, 22, 42)
    task = r.apply_completion(floating(), now, now=now)
    assert task["next_due"] == dt(2027, 1, 5, 22, 42).isoformat()


def test_completion_records_no_prior_due_when_the_date_is_the_snapped_one():
    # The live calculation snaps too, so a due date that a completion set is not
    # read as a moved date (``_keeps_prior_due``).
    first = dt(2026, 10, 7, 22, 42)
    task = r.apply_completion(floating(), first, now=first, due_time=EIGHT)
    second = dt(2027, 1, 5, 9)
    task = r.apply_completion(task, second, now=second, due_time=EIGHT)
    assert r.PRIOR_DUE not in task["completions"][-1]


def test_skip_is_due_at_the_set_time():
    now = dt(2026, 10, 7, 22, 59)
    task = floating(interval=1, next_due=dt(2026, 10, 7, 8).isoformat())
    task = r.skip_occurrence(task, now=now, due_time=EIGHT)
    assert task["next_due"] == dt(2026, 10, 8, 8).isoformat()


def test_never_completed_task_stays_due_now():
    now = dt(2026, 10, 7, 6)
    assert r.compute_next_due(floating(), now=now, due_time=EIGHT) == now


def test_compute_next_due_snaps_a_completed_task():
    task = floating(last_completed=dt(2026, 10, 7, 22, 42).isoformat())
    due = r.compute_next_due(task, now=dt(2026, 10, 8), due_time=EIGHT)
    assert due == dt(2027, 1, 5, 8)


def test_snap_stays_inside_the_season():
    # 90 days from 7 Oct is 5 Jan, outside an April to September season. The clamp
    # moves to 1 April at midnight, and the snap keeps that date.
    task = floating(active_season={"start": "04-01", "end": "09-30"})
    now = dt(2026, 10, 7, 22, 42)
    task = r.apply_completion(task, now, now=now, due_time=EIGHT)
    assert task["next_due"] == dt(2027, 4, 1, 8).isoformat()


def test_undo_rewinds_to_the_snapped_date():
    first = dt(2026, 7, 1, 21)
    second = dt(2026, 10, 7, 22, 42)
    task = r.apply_completion(floating(), first, now=first, due_time=EIGHT)
    task = r.apply_completion(task, second, now=second, due_time=EIGHT)
    task = r.remove_completion(task, second.isoformat(), now=second, due_time=EIGHT)
    assert task["next_due"] == dt(2026, 9, 29, 8).isoformat()


def test_move_completion_recomputes_the_snapped_date():
    first = dt(2026, 10, 7, 22, 42)
    task = r.apply_completion(floating(), first, now=first, due_time=EIGHT)
    moved = dt(2026, 10, 9, 23, 30)
    task = r.move_completion(
        task, first.isoformat(), moved.isoformat(), now=moved, due_time=EIGHT
    )
    assert task["next_due"] == dt(2027, 1, 7, 8).isoformat()


def test_fixed_tasks_do_not_snap():
    anchor = dt(2026, 1, 1, 19)
    task = {
        "recurrence_type": "fixed",
        "freq": "DAILY",
        "interval": 1,
        "anchor": anchor.isoformat(),
    }
    due = r.compute_next_due(task, now=dt(2026, 10, 7, 9), due_time=EIGHT)
    assert due == dt(2026, 10, 7, 19)


# ── snap_future_floating ─────────────────────────────────────────────────────


def test_snap_future_floating_moves_only_future_floating_dates():
    now = dt(2026, 10, 7, 10)
    tasks = {
        "future": floating(next_due=dt(2027, 1, 5, 22, 42).isoformat()),
        "later_today": floating(next_due=dt(2026, 10, 7, 22, 42).isoformat()),
        "due_now": floating(next_due=dt(2026, 10, 7, 9).isoformat()),
        "dormant": floating(next_due=None),
        "fixed": {
            "recurrence_type": "fixed",
            "next_due": dt(2027, 1, 5, 19).isoformat(),
        },
        "snapped": floating(next_due=dt(2027, 2, 1, 8).isoformat()),
    }
    changed = r.snap_future_floating(tasks, EIGHT, now=now)
    assert changed == [tasks["future"], tasks["later_today"]]
    assert tasks["future"]["next_due"] == dt(2027, 1, 5, 8).isoformat()
    # A task due later today becomes due at the set time today, which can be
    # earlier than now. It is due today, so that is the point.
    assert tasks["later_today"]["next_due"] == dt(2026, 10, 7, 8).isoformat()
    assert tasks["due_now"]["next_due"] == dt(2026, 10, 7, 9).isoformat()
    assert tasks["dormant"]["next_due"] is None
    assert tasks["fixed"]["next_due"] == dt(2027, 1, 5, 19).isoformat()


def test_snap_future_floating_does_nothing_without_a_due_time():
    tasks = {"a": floating(next_due=dt(2027, 1, 5, 22, 42).isoformat())}
    assert r.snap_future_floating(tasks, None, now=dt(2026, 10, 7)) == []
    assert tasks["a"]["next_due"] == dt(2027, 1, 5, 22, 42).isoformat()


def test_snap_future_floating_reads_the_stored_offset_in_the_local_zone():
    # A stored ISO string keeps only an offset. 06:42 UTC on 6 Jan is 22:42 on
    # 5 Jan in Los Angeles, so the local date is 5 Jan.
    tasks = {"a": floating(next_due="2027-01-06T06:42:00+00:00")}
    r.snap_future_floating(tasks, EIGHT, now=dt(2026, 10, 7))
    assert tasks["a"]["next_due"] == dt(2027, 1, 5, 8).isoformat()


def test_snap_future_floating_goes_past_tasks_it_leaves():
    # A task that stays (fixed, or due at exactly now) does not stop the walk.
    now = dt(2026, 10, 7, 10)
    tasks = {
        "fixed": {
            "recurrence_type": "fixed",
            "next_due": dt(2027, 1, 5, 19).isoformat(),
        },
        "exactly_now": floating(next_due=now.isoformat()),
        "future": floating(next_due=dt(2027, 1, 5, 22, 42).isoformat()),
    }
    assert r.snap_future_floating(tasks, EIGHT, now=now) == [tasks["future"]]
    assert tasks["exactly_now"]["next_due"] == now.isoformat()
    assert tasks["future"]["next_due"] == dt(2027, 1, 5, 8).isoformat()


# ── models: creation and edit ────────────────────────────────────────────────


def test_build_task_snaps_a_seeded_completion():
    now = dt(2026, 10, 8, 9)
    task = m.build_task(
        {
            "name": "Furnace filter",
            "interval": 90,
            "unit": "days",
            "last_completed": dt(2026, 10, 7, 22, 42).isoformat(),
        },
        now=now,
        due_time=EIGHT,
    )
    assert task["next_due"] == dt(2027, 1, 5, 8).isoformat()


def test_merge_update_snaps_a_new_interval():
    now = dt(2026, 10, 8, 9)
    task = m.build_task(
        {
            "name": "Furnace filter",
            "interval": 90,
            "unit": "days",
            "last_completed": dt(2026, 10, 7, 22, 42).isoformat(),
        },
        now=now,
    )
    merged = m.merge_update(task, {"interval": 30}, now=now, due_time=EIGHT)
    assert merged["next_due"] == dt(2026, 11, 6, 8).isoformat()
