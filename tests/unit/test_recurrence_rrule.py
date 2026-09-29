"""Fixed schedules as RRULEs: parsing, expansion, month end, DST and moved dates.

The rule engine in ``recurrence.py`` expands an RFC 5545 RRULE with ``dateutil`` and
adds 3 things on top: wall time across a clock change, "the 31st or the last day"
for a plain monthly rule, and single moved dates. Each block below pins one of them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import hk_models as models
import hk_recurrence as r
import pytest

TZ = timezone(timedelta(hours=-4))
LA = ZoneInfo("America/Los_Angeles")


def dt(y, m, d, hh=0, mm=0, tz=TZ):
    return datetime(y, m, d, hh, mm, tzinfo=tz)


def _fixed(rule: str, anchor: datetime, **over) -> dict:
    task = {
        "id": "t1",
        "name": "Take trash out",
        "recurrence_type": "fixed",
        "rrule": rule,
        "anchor": anchor.isoformat(),
        "moved_occurrences": [],
    }
    task.update(over)
    return task


# ── normalize_rule ──────────────────────────────────────────────────────────


def test_a_rule_is_upper_cased_and_loses_its_rrule_prefix():
    assert r.normalize_rule(" rrule:freq=weekly;byday=tu,fr ") == (
        "FREQ=WEEKLY;BYDAY=TU,FR"
    )


def test_freq_is_written_first_whatever_order_it_came_in():
    assert r.normalize_rule("BYDAY=TU;FREQ=WEEKLY") == "FREQ=WEEKLY;BYDAY=TU"


@pytest.mark.parametrize(
    ("rule", "reason"),
    [
        ("", "syntax"),
        ("   ", "syntax"),
        ("FREQ", "syntax"),
        ("FREQ=WEEKLY;BYDAY", "syntax"),
        ("FREQ=WEEKLY;BYDAY=XX", "syntax"),
        ("FREQ=WEEKLY;INTERVAL=0", "syntax"),
        ("FREQ=WEEKLY;INTERVAL=two", "syntax"),
        ("FREQ=WEEKLY;INTERVAL=10001", "syntax"),
        ("BYDAY=TU", "freq"),
        ("FREQ=HOURLY", "freq"),
        ("FREQ=MINUTELY", "freq"),
        ("FREQ=MONTHLY;COUNT=3", "forbidden"),
        ("FREQ=MONTHLY;UNTIL=20270101T000000", "forbidden"),
        ("FREQ=DAILY;BYHOUR=8,20", "forbidden"),
        ("FREQ=DAILY;BYMINUTE=5", "forbidden"),
        ("FREQ=DAILY;BYSECOND=5", "forbidden"),
        ("FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30", "empty"),
        ("FREQ=DAILY;" + "BYMONTH=1;" * 60, "length"),
    ],
)
def test_a_rule_home_keeper_cannot_store_is_refused_with_a_reason(rule, reason):
    with pytest.raises(r.RuleError) as err:
        r.normalize_rule(rule)
    assert err.value.reason == reason


def test_a_rule_that_is_not_text_is_refused():
    with pytest.raises(r.RuleError) as err:
        r.normalize_rule(None)
    assert err.value.reason == "syntax"


def test_forbidden_parts_are_all_named():
    with pytest.raises(r.RuleError) as err:
        r.normalize_rule("FREQ=DAILY;UNTIL=20270101T000000;COUNT=2")
    assert err.value.detail == "COUNT,UNTIL"


def test_a_leap_day_rule_is_valid_because_it_comes_round():
    assert r.normalize_rule("FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29") == (
        "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29"
    )


# ── legacy_rule / task_rule ────────────────────────────────────────────────


def test_the_legacy_pair_becomes_a_plain_rule():
    assert r.legacy_rule("WEEKLY", 2) == "FREQ=WEEKLY;INTERVAL=2"


@pytest.mark.parametrize(("freq", "interval"), [("YEARLY", 1), ("DAILY", 0)])
def test_a_legacy_pair_that_never_existed_is_refused(freq, interval):
    with pytest.raises(r.RuleError):
        r.legacy_rule(freq, interval)


def test_task_rule_reads_the_rule_and_falls_back_to_the_legacy_pair():
    assert r.task_rule({"rrule": "FREQ=DAILY"}) == "FREQ=DAILY"
    assert r.task_rule({"freq": "MONTHLY", "interval": 3}) == "FREQ=MONTHLY;INTERVAL=3"
    assert r.task_rule({"freq": "DAILY"}) == "FREQ=DAILY;INTERVAL=1"


# ── effective_rule ─────────────────────────────────────────────────────────


def test_a_plain_weekly_rule_takes_its_day_from_the_start():
    wednesday = datetime(2026, 9, 30, 7)
    assert r.effective_rule("FREQ=WEEKLY", wednesday) == "FREQ=WEEKLY;BYDAY=WE"


def test_a_plain_monthly_rule_takes_its_day_from_the_start():
    assert r.effective_rule("FREQ=MONTHLY", datetime(2026, 1, 15)) == (
        "FREQ=MONTHLY;BYMONTHDAY=15"
    )


def test_a_plain_monthly_rule_on_the_31st_means_the_last_day_of_a_short_month():
    assert r.effective_rule("FREQ=MONTHLY;INTERVAL=1", datetime(2026, 1, 31)) == (
        "FREQ=MONTHLY;INTERVAL=1;BYMONTHDAY=28,29,30,31;BYSETPOS=-1"
    )


def test_a_plain_yearly_rule_on_february_29_means_february_28_otherwise():
    assert r.effective_rule("FREQ=YEARLY", datetime(2028, 2, 29)) == (
        "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=28,29;BYSETPOS=-1"
    )


def test_a_plain_yearly_rule_takes_month_and_day_from_the_start():
    assert r.effective_rule("FREQ=YEARLY", datetime(2026, 7, 4)) == (
        "FREQ=YEARLY;BYMONTH=7;BYMONTHDAY=4"
    )


def test_a_rule_that_names_its_days_is_left_alone():
    rule = "FREQ=MONTHLY;BYDAY=1TU"
    assert r.effective_rule(rule, datetime(2026, 1, 31)) == rule


def test_a_monthly_rule_with_its_own_setpos_keeps_the_start_day():
    assert r.effective_rule("FREQ=MONTHLY;BYSETPOS=1", datetime(2026, 1, 31)) == (
        "FREQ=MONTHLY;BYSETPOS=1;BYMONTHDAY=31"
    )


# ── expansion ──────────────────────────────────────────────────────────────


def test_tuesday_and_friday_every_week():
    anchor = dt(2026, 9, 29, 7)  # a Tuesday
    got = r.expand_fixed_occurrences(
        anchor, "FREQ=WEEKLY;BYDAY=TU,FR", dt(2026, 9, 29), dt(2026, 10, 11)
    )
    assert [o.strftime("%a %d") for o in got] == [
        "Tue 29",
        "Fri 02",
        "Tue 06",
        "Fri 09",
    ]
    assert all((o.hour, o.minute) == (7, 0) for o in got)


def test_the_first_occurrence_is_the_first_rule_date_after_the_anchor():
    # Anchored on a Wednesday, a Tue/Fri rule starts on the Friday, not the Wednesday.
    anchor = dt(2026, 9, 30, 7)
    got = r.next_fixed_occurrence(
        anchor, "FREQ=WEEKLY;BYDAY=TU,FR", after=dt(2026, 9, 1)
    )
    assert got == dt(2026, 10, 2, 7)


def test_first_tuesday_of_each_month():
    anchor = dt(2026, 10, 1, 9)
    got = r.expand_fixed_occurrences(
        anchor, "FREQ=MONTHLY;BYDAY=1TU", dt(2026, 10, 1), dt(2027, 2, 1)
    )
    assert [o.date().isoformat() for o in got] == [
        "2026-10-06",
        "2026-11-03",
        "2026-12-01",
        "2027-01-05",
    ]


def test_last_friday_of_each_month():
    anchor = dt(2026, 1, 1, 18)
    got = r.expand_fixed_occurrences(
        anchor, "FREQ=MONTHLY;BYDAY=-1FR", dt(2026, 1, 1), dt(2026, 4, 1)
    )
    assert [o.date().isoformat() for o in got] == [
        "2026-01-30",
        "2026-02-27",
        "2026-03-27",
    ]


def test_every_other_week_on_two_days_keeps_its_fortnight():
    anchor = dt(2026, 1, 5, 8)  # Monday of week 1
    got = r.expand_fixed_occurrences(
        anchor,
        "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH",
        dt(2026, 1, 1),
        dt(2026, 2, 1),
    )
    assert [o.date().isoformat() for o in got] == [
        "2026-01-05",
        "2026-01-08",
        "2026-01-19",
        "2026-01-22",
    ]


def test_every_other_week_stays_on_its_fortnight_from_a_far_past_anchor():
    # The start moves forward in whole periods; an odd number of weeks would put the
    # schedule on the other fortnight.
    anchor = dt(2019, 1, 7, 8)  # Monday
    after = dt(2026, 6, 13)
    got = r.next_fixed_occurrence(
        anchor, "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO", after=after
    )
    weeks = (got - anchor).days // 7
    assert weeks % 2 == 0
    assert got > after
    assert got - after <= timedelta(weeks=2)


def test_a_monthly_rule_on_the_31st_returns_to_the_31st():
    anchor = dt(2026, 1, 31, 9)
    got = r.expand_fixed_occurrences(
        anchor, "FREQ=MONTHLY;INTERVAL=1", dt(2026, 1, 1), dt(2026, 6, 1)
    )
    assert [o.date().isoformat() for o in got] == [
        "2026-01-31",
        "2026-02-28",
        "2026-03-31",
        "2026-04-30",
        "2026-05-31",
    ]


def test_a_yearly_leap_day_task_lands_on_february_28_in_other_years():
    anchor = dt(2028, 2, 29, 9)
    got = r.expand_fixed_occurrences(
        anchor, "FREQ=YEARLY", dt(2028, 1, 1), dt(2033, 1, 1)
    )
    assert [o.date().isoformat() for o in got] == [
        "2028-02-29",
        "2029-02-28",
        "2030-02-28",
        "2031-02-28",
        "2032-02-29",
    ]


def test_seven_in_the_morning_stays_seven_across_the_autumn_clock_change():
    anchor = datetime(2026, 9, 29, 7, tzinfo=LA)
    got = r.expand_fixed_occurrences(
        anchor,
        "FREQ=WEEKLY;BYDAY=TU,FR",
        datetime(2026, 10, 27, tzinfo=LA),
        datetime(2026, 11, 7, tzinfo=LA),
    )
    assert [(o.date().isoformat(), o.hour) for o in got] == [
        ("2026-10-27", 7),
        ("2026-10-30", 7),
        ("2026-11-03", 7),
        ("2026-11-06", 7),
    ]
    # The clocks went back on Nov 1: the offset changed, the wall time did not.
    assert got[1].utcoffset() == timedelta(hours=-7)
    assert got[2].utcoffset() == timedelta(hours=-8)


def test_an_anchor_that_went_through_storage_keeps_its_wall_time():
    # Stored as -07:00, read back in November under -08:00: still 07:00 local.
    stored = datetime.fromisoformat(datetime(2026, 9, 29, 7, tzinfo=LA).isoformat())
    got = r.next_fixed_occurrence(
        stored, "FREQ=WEEKLY;BYDAY=TU", after=datetime(2026, 11, 2, tzinfo=LA)
    )
    assert (got.date().isoformat(), got.hour) == ("2026-11-03", 7)


def test_a_far_past_daily_anchor_answers_the_right_day():
    anchor = dt(1990, 1, 1, 8)
    got = r.next_fixed_occurrence(anchor, "FREQ=DAILY", after=dt(2026, 6, 13, 9))
    assert got == dt(2026, 6, 14, 8)


def test_a_long_interval_reaches_its_next_date_past_the_20_year_horizon():
    anchor = dt(2000, 1, 1, 9)
    got = r.next_fixed_occurrence(
        anchor, "FREQ=MONTHLY;INTERVAL=300", after=dt(2000, 1, 2)
    )
    assert got == dt(2025, 1, 1, 9)


def test_a_yearly_rule_from_a_far_past_anchor():
    anchor = dt(1950, 7, 4, 10)
    got = r.next_fixed_occurrence(anchor, "FREQ=YEARLY", after=dt(2026, 7, 5))
    assert got == dt(2027, 7, 4, 10)


def test_an_empty_range_expands_to_nothing():
    anchor = dt(2026, 1, 1, 8)
    assert (
        r.expand_fixed_occurrences(anchor, "FREQ=DAILY", dt(2026, 6, 2), dt(2026, 6, 1))
        == []
    )


def test_expansion_is_capped():
    anchor = dt(2026, 1, 1, 8)
    got = r.expand_fixed_occurrences(
        anchor, "FREQ=DAILY", dt(2026, 1, 1), dt(2030, 1, 1)
    )
    assert len(got) == r.MAX_EXPAND_ITERATIONS


def test_a_rule_with_no_future_date_raises():
    # Not storable (normalize_rule refuses it), but the engine must not loop on it.
    with pytest.raises(ValueError):
        r.next_fixed_occurrence(
            dt(2026, 1, 1), "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30", after=dt(2026, 1, 2)
        )


def test_is_rule_occurrence():
    anchor = dt(2026, 9, 29, 7)
    assert r.is_rule_occurrence(anchor, "FREQ=WEEKLY;BYDAY=TU,FR", dt(2026, 10, 2, 7))
    assert not r.is_rule_occurrence(
        anchor, "FREQ=WEEKLY;BYDAY=TU,FR", dt(2026, 10, 3, 7)
    )
    assert not r.is_rule_occurrence(
        anchor, "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30", dt(2026, 10, 3, 7)
    )


# ── moved dates ────────────────────────────────────────────────────────────

ANCHOR = dt(2026, 9, 29, 7)  # Tuesday
RULE = "FREQ=WEEKLY;BYDAY=TU,FR"
NOW = dt(2026, 9, 29, 12)  # after Tuesday's 07:00


def _trash(**over) -> dict:
    task = _fixed(RULE, ANCHOR, next_due=dt(2026, 10, 2, 7).isoformat())
    task.update(over)
    return task


def test_a_move_takes_its_date_off_the_schedule_and_puts_the_new_one_on():
    moves = [
        {"from": dt(2026, 10, 9, 7).isoformat(), "to": dt(2026, 10, 10, 7).isoformat()}
    ]
    got = r.expand_fixed_occurrences(
        ANCHOR, RULE, dt(2026, 10, 5), dt(2026, 10, 15), moves=moves
    )
    assert [o.strftime("%a %d") for o in got] == ["Tue 06", "Sat 10", "Tue 13"]


def test_the_next_date_skips_a_date_that_moved_away():
    moves = [
        {"from": dt(2026, 10, 2, 7).isoformat(), "to": dt(2026, 10, 3, 7).isoformat()}
    ]
    got = r.next_fixed_occurrence(ANCHOR, RULE, after=NOW, moves=moves)
    assert got == dt(2026, 10, 3, 7)


def test_the_next_date_can_be_a_move_to_before_the_next_rule_date():
    moves = [
        {"from": dt(2026, 10, 6, 7).isoformat(), "to": dt(2026, 9, 30, 7).isoformat()}
    ]
    got = r.next_fixed_occurrence(ANCHOR, RULE, after=NOW, moves=moves)
    assert got == dt(2026, 9, 30, 7)


def test_several_moved_dates_in_a_row_are_all_skipped():
    moves = [
        {"from": dt(2026, 10, 2, 7).isoformat(), "to": dt(2026, 10, 20, 8).isoformat()},
        {"from": dt(2026, 10, 6, 7).isoformat(), "to": dt(2026, 10, 21, 8).isoformat()},
    ]
    got = r.next_fixed_occurrence(ANCHOR, RULE, after=NOW, moves=moves)
    assert got == dt(2026, 10, 9, 7)


def test_bad_move_rows_are_ignored_by_the_engine():
    moves = [
        {"from": "nope", "to": "x"},
        {"to": "2026-10-02T07:00:00"},
        "text",
        {
            "from": "2026-10-02T07:00:00",
            "to": "2026-10-03T07:00:00",  # naive
        },
    ]
    got = r.next_fixed_occurrence(ANCHOR, RULE, after=NOW, moves=moves)
    assert got == dt(2026, 10, 2, 7)


def test_move_occurrence_records_the_move():
    task = _trash()
    _, original, previous = r.move_occurrence(
        task, dt(2026, 10, 9, 7), dt(2026, 10, 10, 7), now=NOW
    )
    assert original == dt(2026, 10, 9, 7)
    assert previous is None
    assert task["moved_occurrences"] == [
        {"from": dt(2026, 10, 9, 7).isoformat(), "to": dt(2026, 10, 10, 7).isoformat()}
    ]
    # Friday the 2nd is still the date on the board.
    assert task["next_due"] == dt(2026, 10, 2, 7).isoformat()


def test_moving_a_moved_date_again_keeps_where_it_came_from():
    task = _trash()
    r.move_occurrence(task, dt(2026, 10, 9, 7), dt(2026, 10, 10, 7), now=NOW)
    _, original, previous = r.move_occurrence(
        task, dt(2026, 10, 9, 7), dt(2026, 10, 11, 7), now=NOW
    )
    assert previous == dt(2026, 10, 10, 7)
    assert original == dt(2026, 10, 9, 7)
    assert task["moved_occurrences"] == [
        {"from": dt(2026, 10, 9, 7).isoformat(), "to": dt(2026, 10, 11, 7).isoformat()}
    ]


def test_a_calendar_can_name_a_moved_date_by_where_it_is_now():
    task = _trash()
    r.move_occurrence(task, dt(2026, 10, 9, 7), dt(2026, 10, 10, 7), now=NOW)
    _, original, _ = r.move_occurrence(
        task, dt(2026, 10, 10, 7), dt(2026, 10, 11, 7), now=NOW
    )
    assert original == dt(2026, 10, 9, 7)
    assert len(task["moved_occurrences"]) == 1


def test_moving_a_date_back_to_its_own_time_undoes_the_move():
    task = _trash()
    r.move_occurrence(task, dt(2026, 10, 9, 7), dt(2026, 10, 10, 7), now=NOW)
    r.move_occurrence(task, dt(2026, 10, 9, 7), dt(2026, 10, 9, 7), now=NOW)
    assert task["moved_occurrences"] == []


def test_moving_the_shown_date_moves_next_due():
    task = _trash()
    r.move_occurrence(task, dt(2026, 10, 2, 7), dt(2026, 10, 3, 7), now=NOW)
    assert task["next_due"] == dt(2026, 10, 3, 7).isoformat()
    # And undoing it puts next_due back.
    r.move_occurrence(task, dt(2026, 10, 2, 7), dt(2026, 10, 2, 7), now=NOW)
    assert task["next_due"] == dt(2026, 10, 2, 7).isoformat()


def test_moving_a_later_date_to_before_the_shown_one_brings_next_due_forward():
    task = _trash()
    r.move_occurrence(task, dt(2026, 10, 6, 7), dt(2026, 9, 30, 7), now=NOW)
    assert task["next_due"] == dt(2026, 9, 30, 7).isoformat()


def test_a_snooze_keeps_its_date_when_another_date_moves():
    snoozed = dt(2026, 10, 3, 18)  # off the schedule
    task = _trash(next_due=snoozed.isoformat())
    r.move_occurrence(task, dt(2026, 10, 6, 7), dt(2026, 9, 30, 7), now=NOW)
    assert task["next_due"] == snoozed.isoformat()


def test_a_task_with_no_due_date_gets_one():
    task = _trash(next_due=None)
    r.move_occurrence(task, dt(2026, 10, 2, 7), dt(2026, 10, 3, 7), now=NOW)
    assert task["next_due"] == dt(2026, 10, 3, 7).isoformat()


def test_a_naive_move_is_read_in_the_zone_of_now():
    task = _trash()
    r.move_occurrence(
        task, datetime(2026, 10, 9, 7), datetime(2026, 10, 10, 7), now=NOW
    )
    assert task["moved_occurrences"][0]["to"] == dt(2026, 10, 10, 7).isoformat()


@pytest.mark.parametrize(
    ("occurrence", "to", "message"),
    [
        (dt(2026, 10, 8, 7), dt(2026, 10, 10, 7), "not a date of this schedule"),
        (dt(2026, 10, 9, 7), dt(2026, 9, 28, 7), "in the future"),
        (dt(2026, 10, 9, 7), dt(2026, 10, 13, 7), "already a date"),
    ],
)
def test_a_move_that_makes_no_sense_is_refused(occurrence, to, message):
    task = _trash()
    before = dict(task)
    with pytest.raises(ValueError, match=message):
        r.move_occurrence(task, occurrence, to, now=NOW)
    assert task == before


def test_a_move_onto_another_moved_date_is_refused():
    task = _trash()
    r.move_occurrence(task, dt(2026, 10, 9, 7), dt(2026, 10, 10, 7), now=NOW)
    with pytest.raises(ValueError, match="already a date"):
        r.move_occurrence(task, dt(2026, 10, 13, 7), dt(2026, 10, 10, 7), now=NOW)


def test_only_a_fixed_task_has_dates_to_move():
    with pytest.raises(ValueError, match="fixed"):
        r.move_occurrence(
            {"recurrence_type": "floating"}, NOW, NOW + timedelta(days=1), now=NOW
        )


def test_the_number_of_moves_is_capped():
    moves = [
        {
            "from": (ANCHOR + timedelta(weeks=i)).isoformat(),
            "to": (ANCHOR + timedelta(weeks=i, hours=2)).isoformat(),
        }
        for i in range(1, r.MAX_MOVED_OCCURRENCES + 1)
    ]
    task = _trash(moved_occurrences=moves)
    with pytest.raises(ValueError, match="too many"):
        r.move_occurrence(task, dt(2026, 10, 2, 7), dt(2026, 10, 3, 7), now=NOW)


def test_prune_drops_only_moves_fully_in_the_past():
    old = {"from": dt(2026, 9, 1, 7).isoformat(), "to": dt(2026, 9, 2, 7).isoformat()}
    straddle = {
        "from": dt(2026, 9, 25, 7).isoformat(),
        "to": dt(2026, 10, 1, 7).isoformat(),
    }
    future = {
        "from": dt(2026, 10, 9, 7).isoformat(),
        "to": dt(2026, 10, 10, 7).isoformat(),
    }
    task = _trash(moved_occurrences=[old, straddle, future, {"from": "bad"}])
    r.prune_moves(task, before=dt(2026, 9, 28))
    assert task["moved_occurrences"] == [straddle, future]


def test_prune_leaves_a_task_with_no_moves_alone():
    task = _trash(moved_occurrences=[])
    assert r.prune_moves(task, before=NOW) is task
    assert task["moved_occurrences"] == []


def test_completing_on_a_moved_date_advances_to_the_next_date():
    task = _trash()
    r.move_occurrence(task, dt(2026, 10, 2, 7), dt(2026, 10, 3, 7), now=NOW)
    done = dt(2026, 10, 3, 7, 30)
    r.apply_completion(task, done, now=done)
    assert task["next_due"] == dt(2026, 10, 6, 7).isoformat()


def test_completing_prunes_the_move_it_is_done_with():
    task = _trash()
    r.move_occurrence(task, dt(2026, 10, 2, 7), dt(2026, 10, 3, 7), now=NOW)
    later = dt(2026, 10, 7, 9)
    r.apply_completion(task, later, now=later)
    assert task["moved_occurrences"] == []


def test_upcoming_occurrences_marks_the_moved_rows():
    task = _trash()
    r.move_occurrence(task, dt(2026, 10, 9, 7), dt(2026, 10, 10, 7), now=NOW)
    rows = r.upcoming_occurrences(task, now=NOW, count=4)
    assert rows == [
        {"start": dt(2026, 10, 2, 7).isoformat(), "moved_from": None},
        {"start": dt(2026, 10, 6, 7).isoformat(), "moved_from": None},
        {
            "start": dt(2026, 10, 10, 7).isoformat(),
            "moved_from": dt(2026, 10, 9, 7).isoformat(),
        },
        {"start": dt(2026, 10, 13, 7).isoformat(), "moved_from": None},
    ]


def test_upcoming_occurrences_respects_the_season():
    task = _trash(active_season=[{"start": "11-01", "end": "12-31"}])
    rows = r.upcoming_occurrences(task, now=NOW, count=2)
    assert [row["start"][:10] for row in rows] == ["2026-11-03", "2026-11-06"]


def test_upcoming_occurrences_stops_at_a_rule_with_no_dates():
    task = _fixed("FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30", ANCHOR)
    assert r.upcoming_occurrences(task, now=NOW, count=3) == []


def test_is_task_occurrence_counts_a_move_target_and_not_its_source():
    task = _trash()
    r.move_occurrence(task, dt(2026, 10, 9, 7), dt(2026, 10, 10, 7), now=NOW)
    assert r.is_task_occurrence(task, dt(2026, 10, 10, 7))
    assert not r.is_task_occurrence(task, dt(2026, 10, 9, 7))
    assert r.task_moves(task) == [(dt(2026, 10, 9, 7), dt(2026, 10, 10, 7))]


# ── the model ──────────────────────────────────────────────────────────────

MODEL_NOW = dt(2026, 9, 29, 12)


def _build(**data) -> dict:
    return models.build_task(
        {"name": "Take trash out", "recurrence_type": "fixed", **data},
        now=MODEL_NOW,
    )


def test_build_stores_the_rule_and_no_legacy_pair():
    task = _build(rrule="freq=weekly;byday=tu,fr", anchor="2026-09-29T07:00:00")
    assert task["rrule"] == "FREQ=WEEKLY;BYDAY=TU,FR"
    assert task["moved_occurrences"] == []
    assert "freq" not in task
    assert "interval" not in task
    assert task["next_due"] == dt(2026, 10, 2, 7).isoformat()


def test_build_converts_the_legacy_pair():
    task = _build(freq="WEEKLY", interval=2, anchor="2026-09-29T07:00:00")
    assert task["rrule"] == "FREQ=WEEKLY;INTERVAL=2"


def test_an_rrule_alone_makes_a_fixed_task():
    task = models.build_task(
        {"name": "Rent", "rrule": "FREQ=MONTHLY", "anchor": "2026-10-01T09:00:00"},
        now=MODEL_NOW,
    )
    assert task["recurrence_type"] == "fixed"


def test_the_anchor_drops_a_fraction_of_a_second():
    task = _build(rrule="FREQ=DAILY", anchor="2026-09-29T07:00:00.123456")
    assert task["anchor"] == dt(2026, 9, 29, 7).isoformat()


@pytest.mark.parametrize(
    ("rule", "words"),
    [
        ("FREQ=HOURLY", "FREQ=DAILY, WEEKLY, MONTHLY or YEARLY"),
        ("FREQ=DAILY;COUNT=2", "cannot use COUNT"),
        ("nonsense", "not valid iCalendar"),
        ("FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30", "no dates"),
        ("FREQ=DAILY;" + "BYMONTH=1;" * 60, "too long"),
    ],
)
def test_a_bad_rule_is_refused_in_words_a_user_can_act_on(rule, words):
    with pytest.raises(models.TaskValidationError, match=words):
        _build(rrule=rule, anchor="2026-09-29T07:00:00")


def test_a_bad_legacy_freq_is_still_refused():
    with pytest.raises(models.TaskValidationError, match="invalid freq"):
        _build(freq="YEARLY", anchor="2026-09-29T07:00:00")


def test_an_interval_edit_keeps_the_days_of_the_rule():
    task = _build(rrule="FREQ=WEEKLY;BYDAY=TU,FR", anchor="2026-09-29T07:00:00")
    edited = models.merge_update(task, {"interval": 2}, now=MODEL_NOW)
    assert edited["rrule"] == "FREQ=WEEKLY;BYDAY=TU,FR;INTERVAL=2"


def test_a_frequency_edit_makes_a_plain_rule_of_the_new_frequency():
    task = _build(rrule="FREQ=WEEKLY;BYDAY=TU,FR", anchor="2026-09-29T07:00:00")
    edited = models.merge_update(task, {"freq": "DAILY"}, now=MODEL_NOW)
    assert edited["rrule"] == "FREQ=DAILY;INTERVAL=1"


def test_a_frequency_edit_keeps_the_interval():
    task = _build(rrule="FREQ=WEEKLY;INTERVAL=2;BYDAY=TU", anchor="2026-09-29T07:00:00")
    edited = models.merge_update(task, {"freq": "MONTHLY"}, now=MODEL_NOW)
    assert edited["rrule"] == "FREQ=MONTHLY;INTERVAL=2"


def test_a_legacy_edit_cannot_set_a_frequency_the_legacy_field_never_had():
    task = _build(rrule="FREQ=WEEKLY;BYDAY=TU", anchor="2026-09-29T07:00:00")
    with pytest.raises(models.TaskValidationError, match="invalid freq"):
        models.merge_update(task, {"freq": "YEARLY"}, now=MODEL_NOW)


def test_the_same_frequency_keeps_the_days():
    task = _build(rrule="FREQ=WEEKLY;BYDAY=TU,FR", anchor="2026-09-29T07:00:00")
    edited = models.merge_update(task, {"freq": "WEEKLY"}, now=MODEL_NOW)
    assert edited["rrule"] == "FREQ=WEEKLY;BYDAY=TU,FR"


def test_a_rule_edit_drops_moves_the_new_rule_does_not_have():
    task = _build(rrule="FREQ=WEEKLY;BYDAY=TU,FR", anchor="2026-09-29T07:00:00")
    keep = {
        "from": dt(2026, 10, 6, 7).isoformat(),
        "to": dt(2026, 10, 7, 7).isoformat(),
    }
    drop = {
        "from": dt(2026, 10, 9, 7).isoformat(),
        "to": dt(2026, 10, 10, 7).isoformat(),
    }
    task["moved_occurrences"] = [keep, drop]
    edited = models.merge_update(task, {"rrule": "FREQ=WEEKLY;BYDAY=TU"}, now=MODEL_NOW)
    assert edited["moved_occurrences"] == [keep]


def test_a_rename_keeps_the_moves():
    task = _build(rrule="FREQ=WEEKLY;BYDAY=TU,FR", anchor="2026-09-29T07:00:00")
    move = {
        "from": dt(2026, 10, 9, 7).isoformat(),
        "to": dt(2026, 10, 10, 7).isoformat(),
    }
    task["moved_occurrences"] = [move]
    edited = models.merge_update(task, {"name": "Bins"}, now=MODEL_NOW)
    assert edited["moved_occurrences"] == [move]


def test_leaving_the_fixed_schedule_drops_the_rule_and_moves():
    task = _build(rrule="FREQ=WEEKLY;BYDAY=TU,FR", anchor="2026-09-29T07:00:00")
    edited = models.merge_update(
        task,
        {"recurrence_type": "floating", "interval": 1, "unit": "weeks"},
        now=MODEL_NOW,
    )
    assert "rrule" not in edited
    assert "moved_occurrences" not in edited
    assert edited["interval"] == 1


def test_becoming_fixed_drops_the_floating_interval():
    task = models.build_task(
        {"name": "Bins", "interval": 3, "unit": "days"}, now=MODEL_NOW
    )
    edited = models.merge_update(
        task,
        {
            "recurrence_type": "fixed",
            "rrule": "FREQ=WEEKLY;BYDAY=TU",
            "anchor": "2026-09-29T07:00:00",
        },
        now=MODEL_NOW,
    )
    assert edited["rrule"] == "FREQ=WEEKLY;BYDAY=TU"
    assert "interval" not in edited


def test_moves_are_normalized():
    task = _build(
        rrule="FREQ=WEEKLY;BYDAY=TU,FR",
        anchor="2026-09-29T07:00:00",
        moved_occurrences=[
            {"from": "2026-10-09T07:00:00", "to": "2026-10-10T07:00:00.5"}
        ],
    )
    assert task["moved_occurrences"] == [
        {"from": dt(2026, 10, 9, 7).isoformat(), "to": dt(2026, 10, 10, 7).isoformat()}
    ]


@pytest.mark.parametrize(
    ("moves", "words"),
    [
        ("text", "must be a list"),
        (["text"], "must be an object"),
        ([{"from": "2026-10-09T07:00:00"}], "valid 'to'"),
        ([{"from": "x", "to": "2026-10-09T07:00:00"}], "valid 'from'"),
        (
            [
                {"from": "2026-10-09T07:00:00", "to": "2026-10-10T07:00:00"},
                {"from": "2026-10-09T07:00:00", "to": "2026-10-11T07:00:00"},
            ],
            "already moved",
        ),
        (
            [
                {"from": f"2026-10-{d:02d}T07:00:00", "to": f"2026-11-{d:02d}T07:00:00"}
                for d in range(1, 29)
            ]
            * 4,
            "at most",
        ),
    ],
)
def test_bad_moves_are_refused(moves, words):
    with pytest.raises(models.TaskValidationError, match=words):
        _build(
            rrule="FREQ=WEEKLY;BYDAY=TU,FR",
            anchor="2026-09-29T07:00:00",
            moved_occurrences=moves,
        )


def test_empty_moves_become_an_empty_list():
    task = _build(
        rrule="FREQ=DAILY", anchor="2026-09-29T07:00:00", moved_occurrences=None
    )
    assert task["moved_occurrences"] == []


# ── the load-time migration ────────────────────────────────────────────────


def test_a_stored_legacy_fixed_task_is_converted_once():
    task = {
        "recurrence_type": "fixed",
        "freq": "MONTHLY",
        "interval": 3,
        "anchor": "2026-01-31T09:00:00-04:00",
    }
    assert models.migrate_legacy_fixed_schedule(task) is True
    assert task == {
        "recurrence_type": "fixed",
        "rrule": "FREQ=MONTHLY;INTERVAL=3",
        "anchor": "2026-01-31T09:00:00-04:00",
        "moved_occurrences": [],
    }
    assert models.migrate_legacy_fixed_schedule(task) is False


def test_the_migration_leaves_other_kinds_alone():
    task = {"recurrence_type": "floating", "interval": 1, "unit": "days"}
    assert models.migrate_legacy_fixed_schedule(task) is False
    assert task == {"recurrence_type": "floating", "interval": 1, "unit": "days"}


def test_the_migration_skips_a_task_it_cannot_read():
    task = {"recurrence_type": "fixed", "freq": "SOMETIMES"}
    assert models.migrate_legacy_fixed_schedule(task) is False
    assert task == {"recurrence_type": "fixed", "freq": "SOMETIMES"}


def test_the_migration_reads_a_bad_interval_as_one():
    task = {"recurrence_type": "fixed", "freq": "DAILY", "interval": "x"}
    assert models.migrate_legacy_fixed_schedule(task) is True
    assert task["rrule"] == "FREQ=DAILY;INTERVAL=1"


def test_the_migration_removes_a_stale_pair_next_to_a_rule():
    task = {"recurrence_type": "fixed", "rrule": "FREQ=DAILY", "freq": "DAILY"}
    assert models.migrate_legacy_fixed_schedule(task) is True
    assert task == {
        "recurrence_type": "fixed",
        "rrule": "FREQ=DAILY",
        "moved_occurrences": [],
    }


# ── the zone a date is judged in ───────────────────────────────────────────
#
# Storage keeps a bare offset, so an anchor from July reads -07:00 and a date in
# November -08:00. The engine expands in the probe's zone, so every caller that
# judges a stored date has to hand it Home Assistant's zone first.

LA_NOW = datetime(2026, 11, 20, 12, tzinfo=LA)


def _summer_task(**over) -> dict:
    task = _fixed(
        "FREQ=WEEKLY;BYDAY=TU",
        datetime.fromisoformat("2026-07-07T10:00:00-07:00"),
        next_due="2026-11-24T10:00:00-08:00",
    )
    task.update(over)
    return task


def test_a_winter_date_of_a_summer_anchor_is_on_the_schedule():
    task = _summer_task()
    winter = datetime.fromisoformat("2026-11-24T10:00:00-08:00")
    assert not r.is_task_occurrence(task, winter)  # judged at the anchor's offset
    assert r.is_task_occurrence(task, winter, tz=LA)
    anchor = datetime.fromisoformat(task["anchor"])
    assert r.is_rule_occurrence(anchor, task["rrule"], winter, tz=LA)


def test_a_date_sent_as_an_offset_string_moves_across_the_clock_change():
    task = _summer_task()
    _, original, _ = r.move_occurrence(
        task,
        datetime.fromisoformat("2026-11-24T10:00:00-08:00"),
        datetime.fromisoformat("2026-11-25T10:00:00-08:00"),
        now=LA_NOW,
    )
    assert original == datetime(2026, 11, 24, 10, tzinfo=LA)
    # The date on the board is the one that moved, so next_due follows it.
    assert task["next_due"] == datetime(2026, 11, 25, 10, tzinfo=LA).isoformat()


def test_undoing_a_move_whose_date_has_passed_is_refused():
    task = _trash()
    r.move_occurrence(task, dt(2026, 10, 2, 7), dt(2026, 10, 3, 7), now=NOW)
    later = dt(2026, 10, 2, 12)
    with pytest.raises(ValueError, match="cannot be undone"):
        r.move_occurrence(task, dt(2026, 10, 2, 7), dt(2026, 10, 2, 7), now=later)
    assert len(task["moved_occurrences"]) == 1


def test_a_calendar_moved_date_is_stored_in_the_zone_of_now():
    task = _summer_task()
    r.move_occurrence(
        task,
        datetime.fromisoformat("2026-12-01T10:00:00-08:00"),
        datetime.fromisoformat("2026-12-02T10:00:00-08:00"),
        now=LA_NOW,
    )
    # A second move names the date by where it is now, at yet another offset form.
    _, original, previous = r.move_occurrence(
        task,
        datetime.fromisoformat("2026-12-02T18:00:00+00:00"),
        datetime.fromisoformat("2026-12-03T10:00:00-08:00"),
        now=LA_NOW,
    )
    assert original == datetime(2026, 12, 1, 10, tzinfo=LA)
    assert previous == datetime(2026, 12, 2, 10, tzinfo=LA)


def test_a_rule_edit_keeps_a_winter_move_of_a_summer_anchor():
    task = models.build_task(
        {
            "name": "Bins",
            "rrule": "FREQ=WEEKLY;BYDAY=TU",
            "anchor": "2026-07-07T10:00:00-07:00",
        },
        now=LA_NOW,
    )
    move = {"from": "2026-12-01T10:00:00-08:00", "to": "2026-12-02T10:00:00-08:00"}
    task["moved_occurrences"] = [move]
    edited = models.merge_update(task, {"rrule": "FREQ=WEEKLY;BYDAY=TU,FR"}, now=LA_NOW)
    assert edited["moved_occurrences"] == [move]


# ── the migration keeps next_due on the new schedule ─────────────────────


def test_a_month_end_task_left_on_the_28th_moves_to_the_new_date():
    task = {
        "recurrence_type": "fixed",
        "freq": "MONTHLY",
        "interval": 1,
        "anchor": "2026-01-31T09:00:00-04:00",
        "next_due": "2026-10-28T09:00:00-04:00",
    }
    assert models.migrate_legacy_fixed_schedule(task, now=dt(2026, 10, 1)) is True
    assert task["next_due"] == dt(2026, 10, 31, 9).isoformat()


def test_a_snoozed_month_end_task_keeps_its_snooze():
    # Off the schedule at another time of day: a snooze, not an old clamp.
    task = {
        "recurrence_type": "fixed",
        "freq": "MONTHLY",
        "interval": 1,
        "anchor": "2026-01-31T09:00:00-04:00",
        "next_due": "2026-10-28T18:00:00-04:00",
    }
    models.migrate_legacy_fixed_schedule(task, now=dt(2026, 10, 1))
    assert task["next_due"] == "2026-10-28T18:00:00-04:00"


def test_a_month_end_task_already_on_the_new_date_is_left_alone():
    task = {
        "recurrence_type": "fixed",
        "freq": "MONTHLY",
        "interval": 1,
        "anchor": "2026-01-31T09:00:00-04:00",
        "next_due": "2026-10-31T09:00:00-04:00",
    }
    models.migrate_legacy_fixed_schedule(task, now=dt(2026, 10, 1))
    assert task["next_due"] == "2026-10-31T09:00:00-04:00"


def test_a_weekly_task_is_never_realigned():
    task = {
        "recurrence_type": "fixed",
        "freq": "WEEKLY",
        "interval": 1,
        "anchor": "2026-01-31T09:00:00-04:00",
        "next_due": "2026-10-28T09:00:00-04:00",
    }
    models.migrate_legacy_fixed_schedule(task, now=dt(2026, 10, 1))
    assert task["next_due"] == "2026-10-28T09:00:00-04:00"


def test_an_anchor_with_a_fraction_of_a_second_loses_it_with_its_due_date():
    task = {
        "recurrence_type": "fixed",
        "freq": "DAILY",
        "interval": 1,
        "anchor": "2026-01-01T08:00:00.250000-04:00",
        "next_due": "2026-10-02T08:00:00.250000-04:00",
    }
    models.migrate_legacy_fixed_schedule(task, now=dt(2026, 10, 1))
    assert task["anchor"] == "2026-01-01T08:00:00-04:00"
    assert task["next_due"] == "2026-10-02T08:00:00-04:00"
    r.apply_completion(task, dt(2026, 10, 2, 8, 30), now=dt(2026, 10, 2, 8, 30))
    assert task["next_due"] == dt(2026, 10, 3, 8).isoformat()


def test_the_migration_survives_a_task_without_dates():
    task = {"recurrence_type": "fixed", "freq": "DAILY"}
    assert models.migrate_legacy_fixed_schedule(task, now=dt(2026, 10, 1)) is True
    assert task["rrule"] == "FREQ=DAILY;INTERVAL=1"
