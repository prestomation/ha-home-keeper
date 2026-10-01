"""Low-severity review findings in the pure recurrence engine (group B).

Each test names the finding it pins.
"""

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import hk_recurrence as r
import pytest

TZ = timezone(timedelta(hours=-4))
NY = ZoneInfo("America/New_York")


def dt(y, m, d, hh=0, mm=0, tz=TZ):
    return datetime(y, m, d, hh, mm, tzinfo=tz)


# ── B07-7: undoing the skip of a one-off re-arms it ──────────────────────────


def _skipped_one_off():
    now = dt(2026, 6, 13, 10)
    task = {
        "recurrence_type": "one-off",
        "due": dt(2026, 6, 20, 9).isoformat(),
        "next_due": dt(2026, 6, 20, 9).isoformat(),
        "last_completed": None,
        "completions": [],
        "skips": [],
    }
    task = r.skip_occurrence(task, now=now)
    assert task["next_due"] is None
    return task, task["skips"][0]["ts"]


def test_b07_7_removing_the_skip_of_a_one_off_re_arms_it():
    task, ts = _skipped_one_off()
    out = r.remove_skip(task, ts)
    assert out["skips"] == []
    assert out["next_due"] == dt(2026, 6, 20, 9).isoformat()


def test_b07_7_an_unknown_skip_ts_leaves_the_one_off_dormant():
    task, _ts = _skipped_one_off()
    out = r.remove_skip(task, "2020-01-01T00:00:00+00:00")
    assert out["next_due"] is None
    assert len(out["skips"]) == 1


def test_b07_7_a_remaining_skip_keeps_the_one_off_dormant():
    task, ts = _skipped_one_off()
    task["skips"].append({"ts": dt(2026, 6, 14).isoformat()})
    out = r.remove_skip(task, ts)
    assert out["next_due"] is None


def test_b07_7_a_completed_one_off_stays_dormant():
    task, ts = _skipped_one_off()
    task["last_completed"] = dt(2026, 6, 14).isoformat()
    out = r.remove_skip(task, ts)
    assert out["next_due"] is None


def test_b07_7_an_armed_one_off_keeps_its_own_due():
    task, ts = _skipped_one_off()
    task["next_due"] = dt(2026, 7, 1).isoformat()
    out = r.remove_skip(task, ts)
    assert out["next_due"] == dt(2026, 7, 1).isoformat()


def test_b07_7_other_types_are_not_re_armed():
    now = dt(2026, 6, 13, 10)
    task = {
        "recurrence_type": "triggered",
        "due": dt(2026, 6, 20, 9).isoformat(),
        "next_due": now.isoformat(),
        "skips": [],
    }
    task = r.skip_occurrence(task, now=now)
    out = r.remove_skip(task, task["skips"][0]["ts"])
    assert out["next_due"] is None


# ── B07-8: a gap-hour occurrence on the spring-forward day ──────────────────


@pytest.mark.parametrize("freq", ["DAILY", "WEEKLY"])
def test_b07_8_a_gap_hour_occurrence_is_on_the_grid(freq):
    # 2026-03-08 is a Sunday, the day New York skips 02:00-03:00.
    anchor = datetime(2026, 3, 1, 2, 30, tzinfo=NY)
    task = {"recurrence_type": "fixed", "freq": freq, "interval": 1}
    # How storage hands the occurrence back: 02:30-05:00, re-homed to 03:30 EDT.
    stored = datetime.fromisoformat("2026-03-08T02:30:00-05:00").astimezone(NY)
    assert r._is_occurrence(task, anchor, stored)
    # A different instant is still off the grid.
    assert not r._is_occurrence(task, anchor, stored + timedelta(minutes=1))


@pytest.mark.parametrize(
    ("freq", "after_due"), [("DAILY", (2026, 3, 9)), ("WEEKLY", (2026, 3, 15))]
)
def test_b07_8_completing_before_a_gap_hour_occurrence_advances(freq, after_due):
    task = {
        "recurrence_type": "fixed",
        "freq": freq,
        "interval": 1,
        "anchor": "2026-03-01T02:30:00-05:00",
        "next_due": "2026-03-08T02:30:00-05:00",
        "last_completed": None,
        "completions": [],
        "skips": [],
    }
    now = datetime(2026, 3, 8, 1, 0, tzinfo=NY)
    done = r.apply_completion(dict(task), now, now=now)
    due = datetime.fromisoformat(done["next_due"])
    assert due.astimezone(NY).date() == datetime(*after_due).date()
    skipped = r.skip_occurrence(dict(task), now=now - timedelta(hours=3))
    due = datetime.fromisoformat(skipped["next_due"])
    assert due.astimezone(NY).date() == datetime(*after_due).date()


def test_b07_8_instants_compare_across_zones():
    task = {"recurrence_type": "fixed", "freq": "DAILY", "interval": 1}
    anchor = dt(2026, 6, 1, 10)
    assert r._is_occurrence(task, anchor, dt(2026, 6, 5, 14, tz=UTC))
    assert not r._is_occurrence(task, anchor, dt(2026, 6, 5, 10, tz=UTC))


# ── B07-9: a fixed season clamp lands inside the season ─────────────────────


def _sparse_task(anchor):
    return {
        "recurrence_type": "fixed",
        "freq": "WEEKLY",
        "interval": 2,
        "anchor": anchor.isoformat(),
        "active_season": {"start": "12-01", "end": "12-10"},
    }


def test_b07_9_the_clamp_walks_on_to_an_in_season_occurrence():
    task = _sparse_task(dt(2026, 1, 9, 9))
    due = r.compute_next_due(task, now=dt(2026, 9, 30, 9))
    # 2026-12-11 is the first grid date after Dec 1, but it is out of season.
    assert r.in_season(due, task["active_season"])
    assert due == r.next_in_season_occurrence(
        dt(2026, 1, 9, 9),
        "WEEKLY",
        2,
        task["active_season"],
        after=dt(2026, 12, 1) - timedelta(seconds=1),
    )
    assert due.date() == datetime(2027, 12, 10).date()


def test_b07_9_an_in_season_first_occurrence_is_kept():
    task = _sparse_task(dt(2026, 1, 2, 9))
    due = r.compute_next_due(task, now=dt(2026, 9, 30, 9))
    assert due.date() == datetime(2026, 12, 4).date()


def test_b07_9_a_grid_that_never_meets_the_season_keeps_the_old_answer():
    task = {
        "recurrence_type": "fixed",
        "freq": "MONTHLY",
        "interval": 12,
        "anchor": dt(2026, 1, 15, 9).isoformat(),
        "active_season": {"start": "03-01", "end": "03-31"},
    }
    assert (
        r.next_in_season_occurrence(
            dt(2026, 1, 15, 9),
            "MONTHLY",
            12,
            task["active_season"],
            after=dt(2026, 2, 1),
        )
        is None
    )
    due = r.compute_next_due(task, now=dt(2026, 2, 1))
    # The first grid date after the next season start, as before.
    assert due == dt(2028, 1, 15, 9)


def test_b07_9_the_walk_returns_the_first_in_season_occurrence():
    season = {"start": "06-01", "end": "06-30"}
    found = r.next_in_season_occurrence(
        dt(2026, 1, 1, 9), "DAILY", 1, season, after=dt(2026, 6, 10, 12)
    )
    assert found == dt(2026, 6, 11, 9)
