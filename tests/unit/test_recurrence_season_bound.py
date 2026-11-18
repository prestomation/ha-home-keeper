"""The season walk of a fixed task stops at a fixed bound.

``recurrence.next_in_season_occurrence`` looks for the first date of a fixed schedule
that is inside the task's season. A valid rule can have no date in a season, for
example the 366th day of the year in a June season. These tests prove that the walk
stops after a fixed number of steps and a fixed time horizon, and that
``models.normalize_fields`` refuses such a pair, so the service and the import refuse
the same tasks. Each test counts the calls to ``next_task_occurrence``, so no test
depends on how fast the machine is.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import hk_const as const
import hk_models as models
import hk_recurrence as r
import hk_transfer as tr
import pytest

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 11, 18, 10, tzinfo=TZ)
LEAP_DAY_RULE = "FREQ=DAILY;BYYEARDAY=366"
SHORT_SEASON = [{"start": "06-01", "end": "06-02"}]
# 12 windows: day 1 to day 30 of each month. A rule on the 31st has 7 dates a year,
# and each one is out of season, so each date is 1 step of the walk.
NO_31ST = [
    {"start": f"{month:02d}-01", "end": f"{month:02d}-{min(30, last):02d}"}
    for month, last in enumerate(
        (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31), start=1
    )
]


def dt(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def _fixed(rule: str, season: list[dict] | None, **over) -> dict:
    task = {
        "id": "t1",
        "name": "Season task",
        "recurrence_type": "fixed",
        "rrule": rule,
        "anchor": dt(2026, 1, 1, 9).isoformat(),
        "moved_occurrences": [],
        "active_season": season,
    }
    task.update(over)
    return task


@pytest.fixture
def steps(monkeypatch) -> list[datetime]:
    """Each ``after`` that the engine asks ``next_task_occurrence`` for."""
    calls: list[datetime] = []
    original = r.next_task_occurrence

    def counted(task, *, after):
        calls.append(after)
        return original(task, after=after)

    monkeypatch.setattr(r, "next_task_occurrence", counted)
    return calls


# ── the walk ────────────────────────────────────────────────────────────────


def test_a_season_walk_with_no_date_stops_at_the_time_horizon(steps):
    task = _fixed(LEAP_DAY_RULE, SHORT_SEASON)
    assert r.next_in_season_occurrence(task, SHORT_SEASON, after=NOW) is None
    # 1 season window a year for 20 years, plus the first step and the last one.
    assert 1 <= len(steps) <= 22
    # Each step starts inside the horizon.
    horizon = NOW + r._horizon(LEAP_DAY_RULE)
    assert steps[-1] <= horizon


def test_a_season_walk_with_no_date_stops_at_the_step_cap(steps):
    task = _fixed("FREQ=MONTHLY;BYMONTHDAY=31", NO_31ST)
    assert r.next_in_season_occurrence(task, NO_31ST, after=NOW) is None
    # 7 dates a year for 20 years is more than the cap, so the cap stops the walk.
    assert len(steps) == const.MAX_SEASON_STEPS


def test_a_dense_rule_jumps_to_the_season_start(steps):
    task = _fixed("FREQ=DAILY", SHORT_SEASON)
    found = r.next_in_season_occurrence(task, SHORT_SEASON, after=NOW)
    assert found == dt(2027, 6, 1, 9)
    # The date after NOW is out of season, so the walk jumps to the day before the
    # season start. It does not read the 195 days between.
    assert len(steps) == 2
    assert steps[1] == dt(2027, 6, 1) - timedelta(seconds=1)


def test_a_sparse_rule_finds_a_date_some_years_ahead():
    season = [{"start": "06-13", "end": "06-13"}]
    task = _fixed("FREQ=WEEKLY;BYDAY=FR", season)
    # June 13 is a Friday in 2031, and in no year from 2026 to 2030.
    assert r.next_in_season_occurrence(task, season, after=NOW) == dt(2031, 6, 13, 9)


def test_a_season_walk_moves_past_a_date_on_the_season_start_day():
    # The start of a February 29 window is February 28 in a year with no leap day,
    # and that date is out of season. The walk reads the next date after it.
    season = [{"start": "02-29", "end": "03-01"}]
    task = _fixed("FREQ=DAILY", season, anchor=dt(2026, 1, 1).isoformat())
    found = r.next_in_season_occurrence(task, season, after=dt(2027, 2, 27, 12))
    assert found == dt(2027, 3, 1)


def test_the_clamp_keeps_the_first_date_after_the_season_start(steps):
    task = _fixed(LEAP_DAY_RULE, SHORT_SEASON)
    due = r.compute_next_due(task, now=NOW)
    # The first date after the season start that follows the first date.
    assert due == dt(2032, 12, 31, 9)
    assert len(steps) <= 24


def test_upcoming_dates_stop_when_the_season_has_no_date(steps):
    task = _fixed(LEAP_DAY_RULE, SHORT_SEASON)
    assert r.upcoming_occurrences(task, now=NOW, count=12) == []
    assert len(steps) <= 22


def test_upcoming_dates_of_a_season_task_are_all_in_season():
    task = _fixed("FREQ=WEEKLY;BYDAY=FR", [{"start": "06-01", "end": "06-30"}])
    rows = r.upcoming_occurrences(task, now=NOW, count=6)
    starts = [datetime.fromisoformat(row["start"]) for row in rows]
    assert starts == [
        dt(2027, 6, 4, 9),
        dt(2027, 6, 11, 9),
        dt(2027, 6, 18, 9),
        dt(2027, 6, 25, 9),
        dt(2028, 6, 2, 9),
        dt(2028, 6, 9, 9),
    ]


# ── validation ──────────────────────────────────────────────────────────────


def _task_input(rule: str, season: list[dict] | None) -> dict:
    data = {
        "name": "Season task",
        "recurrence_type": "fixed",
        "rrule": rule,
        "anchor": dt(2026, 1, 1, 9).isoformat(),
    }
    if season is not None:
        data["active_season"] = season
    return data


def test_a_rule_with_no_date_in_its_season_is_refused(steps):
    with pytest.raises(models.TaskValidationError) as err:
        models.build_task(_task_input(LEAP_DAY_RULE, SHORT_SEASON), now=NOW)
    assert str(err.value) == (
        "invalid rrule: the rule has no date in the active season. "
        "Change the rule or the season."
    )
    assert len(steps) <= 24


def test_the_same_rule_without_a_season_is_accepted():
    task = models.build_task(_task_input(LEAP_DAY_RULE, None), now=NOW)
    assert task["next_due"] == dt(2028, 12, 31, 9).isoformat()


def test_a_rule_with_a_date_in_its_season_is_accepted():
    task = models.build_task(_task_input("FREQ=DAILY", SHORT_SEASON), now=NOW)
    assert task["next_due"] == dt(2027, 6, 1, 9).isoformat()


def test_a_floating_task_with_a_short_season_is_accepted():
    data = {
        "name": "Season task",
        "recurrence_type": "floating",
        "interval": 1,
        "unit": "days",
        "active_season": SHORT_SEASON,
    }
    assert models.build_task(data, now=NOW)["active_season"] == SHORT_SEASON


def test_an_update_to_a_season_with_no_date_is_refused():
    task = models.build_task(_task_input(LEAP_DAY_RULE, None), now=NOW)
    with pytest.raises(models.TaskValidationError, match="no date in the active"):
        models.merge_update(task, {"active_season": SHORT_SEASON}, now=NOW)


def test_an_import_reports_a_task_with_no_date_in_its_season(steps):
    document = {
        "home_keeper": {"format": 1},
        "tasks": [
            {**_task_input(LEAP_DAY_RULE, SHORT_SEASON), "name": f"Task {i}"}
            for i in range(3)
        ],
    }
    plan = tr.plan_import(document, tasks={}, assets={}, now=NOW)
    errors = [p for p in plan.problems if p.severity == "error"]
    assert [p.index for p in errors] == [0, 1, 2]
    assert all("no date in the active season" in p.message for p in errors)
    assert not plan.for_section("tasks")
    # Each record stops at the bound.
    assert len(steps) <= 3 * 24


# ── the edges of the bound ──────────────────────────────────────────────────


def test_a_date_at_the_season_start_midnight_is_found():
    season = [{"start": "06-01", "end": "06-30"}]
    task = _fixed("FREQ=DAILY", season, anchor=dt(2026, 1, 1).isoformat())
    found = r.next_in_season_occurrence(task, season, after=dt(2027, 5, 15, 12))
    assert found == dt(2027, 6, 1)


def test_a_date_exactly_at_the_horizon_is_found():
    # The rule dates are on June 1 and out of season. 1 date moves to July 1, and the
    # walk starts exactly 1 horizon before that date.
    rule = "FREQ=YEARLY;INTERVAL=30"
    season = [{"start": "07-01", "end": "07-01"}]
    target = dt(2056, 7, 1, 9)
    task = _fixed(
        rule,
        season,
        anchor=dt(2026, 6, 1, 9).isoformat(),
        moved_occurrences=[
            {"from": dt(2056, 6, 1, 9).isoformat(), "to": target.isoformat()}
        ],
    )
    after = target - r._horizon(rule)
    assert r.next_in_season_occurrence(task, season, after=after) == target
    later = after + timedelta(seconds=1)
    assert r.next_in_season_occurrence(task, season, after=later) == target
    earlier = after - timedelta(seconds=1)
    assert r.next_in_season_occurrence(task, season, after=earlier) is None


def test_a_horizon_past_the_last_year_is_no_limit():
    # 2 periods of 10000 years is past the last year that a datetime can hold.
    season = [{"start": "06-01", "end": "06-30"}]
    task = _fixed(
        "FREQ=YEARLY;INTERVAL=10000", season, anchor=dt(2026, 6, 5).isoformat()
    )
    found = r.next_in_season_occurrence(task, season, after=dt(2026, 1, 1))
    assert found == dt(2026, 6, 5)


def test_the_first_date_counts_for_the_season_check():
    # Friday February 29: 2008, then 2036. Only the first date is inside 20 years.
    data = {
        **_task_input("FREQ=WEEKLY;BYDAY=FR", [{"start": "02-29", "end": "02-29"}]),
        "anchor": dt(2008, 2, 29, 9).isoformat(),
    }
    task = models.build_task(data, now=NOW)
    assert task["next_due"] == dt(2036, 2, 29, 9).isoformat()


def test_the_season_check_ignores_a_task_with_no_season():
    task = _fixed("FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30", None)
    assert models.require_season_date(task) is None


def test_the_season_check_refuses_a_rule_with_no_date_at_all():
    task = _fixed("FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30", SHORT_SEASON)
    with pytest.raises(models.TaskValidationError, match="no date in the active"):
        models.require_season_date(task)
