"""Schedule maths, over generated inputs rather than chosen ones.

Every other recurrence test states its inputs as literals. That is the right shape for
a scenario ("Jan 31 plus a month is Feb 28") and the wrong shape for an *invariant*
("the fast path always agrees with the slow one"), because an invariant is a claim
about a whole domain and a literal only ever samples one point in it.

`test_recurrence_fixed.py` already writes one of these by hand: `_naive_next_monthly`
is a reference implementation, compared against the real one over 6 chosen anchors.
This file keeps that idea and replaces the 6 with a generator. It exists because that
function has twice shipped a defect a wider domain would have caught first — both times
a far-past anchor blowing the iteration cap, taking the next-due sensor and the calendar
down with it.

Run just these: `pytest tests/unit -m property`.
"""

from __future__ import annotations

import calendar
import itertools
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import hk_recurrence as r
import property_strategies as ps
import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st

pytestmark = pytest.mark.property

# A reference walk is O(steps), so the domain has to stay finite. 20000 covers ~54
# years of DAILY at interval 1, which is past every anchor the generator produces.
_MAX_REFERENCE_STEPS = 20_000

_UTC = ZoneInfo("UTC")


def _naive_next(
    anchor: datetime, freq: str, interval: int, after: datetime
) -> datetime:
    """Reference: the first occurrence strictly after *after*, one step at a time.

    Deliberately the slowest correct implementation. `next_fixed_occurrence` jumps in
    O(1) where it can, and this is the thing that jump has to agree with.
    """
    if anchor > after:
        return anchor
    occ = anchor
    for _ in range(_MAX_REFERENCE_STEPS):
        occ = r._step(occ, freq, interval)
        if occ > after:
            return occ
    raise AssertionError("reference walk did not terminate")


@given(
    anchor=ps.aware_datetimes(min_year=1970, max_year=2030),
    freq=st.sampled_from(["DAILY", "WEEKLY", "MONTHLY"]),
    interval=st.integers(1, 24),
    gap_days=st.integers(0, 14_000),
)
def test_r1_the_fast_path_agrees_with_single_stepping(anchor, freq, interval, gap_days):
    """R1. `next_fixed_occurrence` equals walking the schedule one step at a time.

    Generalises `test_recurrence_fixed.py::test_next_monthly_far_past_matches_naive_
    across_day_clamping`, which asserts exactly this over 6 hand-picked anchors.

    The reference shares `_step` with the code under test, so this is not an oracle for
    `_step` itself — it isolates the *jumping*, which is where both shipped defects
    were. `_step` has its own properties in R5a and R5b, which do not use it to check
    itself.
    """
    after = anchor + timedelta(days=gap_days)
    # Keep the reference walk finite; the unbounded domain is R2's job.
    step_days = {"DAILY": 1, "WEEKLY": 7, "MONTHLY": 28}[freq] * interval
    assume(gap_days / step_days < _MAX_REFERENCE_STEPS - 1)

    actual = r.next_fixed_occurrence(anchor, freq, interval, after=after)
    expected = _naive_next(anchor, freq, interval, after)
    assert actual == expected, (
        f"anchor={anchor.isoformat()} freq={freq} interval={interval} "
        f"after={after.isoformat()}: fast path gave {actual.isoformat()}, "
        f"single-stepping gives {expected.isoformat()}"
    )


@given(
    anchor=ps.aware_datetimes(min_year=1970, max_year=2035),
    freq=st.sampled_from(["DAILY", "WEEKLY", "MONTHLY"]),
    interval=st.integers(1, 999),
    gap_days=st.integers(0, 40_000),
)
def test_r2_next_occurrence_never_raises_and_lands_after(
    anchor, freq, interval, gap_days
):
    """R2. Over a domain far wider than R1's, the call returns a sane answer.

    No reference implementation, so this can carry the anchors R1 has to skip — which
    is the point, because "a very old anchor" is precisely the shape that took the
    calendar down twice. The claim is deliberately about behaviour, not timing: a
    deadline would make this a flake on a slow runner.
    """
    after = anchor + timedelta(days=gap_days)
    occurrence = r.next_fixed_occurrence(anchor, freq, interval, after=after)
    assert occurrence > after
    assert occurrence >= anchor


@given(
    moment=ps.aware_datetimes(),
    months=st.integers(-600, 600),
)
def test_r3_add_months_keeps_the_clock_and_clamps_the_day(moment, months):
    """R3. `add_months` moves the month and nothing else.

    The docstring at `recurrence.py:47` promises time-of-day and tzinfo survive, and
    the comment below it claims the negative direction works too. No test exercised a
    negative `months` before this one.
    """
    moved = r.add_months(moment, months)

    assert moved.tzinfo is moment.tzinfo
    assert (moved.hour, moved.minute, moved.second, moved.microsecond) == (
        moment.hour,
        moment.minute,
        moment.second,
        moment.microsecond,
    )
    # The month index lands where plain arithmetic says it should.
    index = (moment.year * 12 + moment.month - 1) + months
    assert (moved.year, moved.month) == (index // 12, index % 12 + 1)
    # The day is the original, or the last day of the shorter month it landed in.
    assert moved.day == min(moment.day, calendar.monthrange(moved.year, moved.month)[1])


@given(
    moment=ps.aware_datetimes(),
    months=st.integers(-600, 600),
)
def test_r3b_add_months_round_trips_when_the_day_cannot_clamp(moment, months):
    """R3b. Days 1-28 exist in every month, so the move is reversible for them.

    Only for those days. Mar 31 goes to Feb 28 and back to Mar 28, so asserting this
    unconditionally would be a false property rather than a found bug.
    """
    assume(moment.day <= 28)
    assert r.add_months(r.add_months(moment, months), -months) == moment


def _floating_with(season: list[dict]) -> dict:
    return {
        "recurrence_type": "floating",
        "interval": 1,
        "unit": "months",
        "active_season": season,
    }


@given(
    moment=ps.aware_datetimes(min_year=2020, max_year=2030),
    season=ps.seasons(always_exists=True),
)
def test_r4_clamping_a_floating_task_lands_inside_its_season(moment, season):
    """R4. `_clamp_season` moves a due date forward into the season, never backward.

    Floating only, and that is not a convenience. A *fixed* task's grid can legitimately
    never intersect its season — `test_calendar.py::test_event_is_none_when_the_grid_
    never_lands_in_the_season` asserts exactly that — so the fixed version of this
    property is false.

    Season boundaries are drawn from dates that exist every year. February 29 is the
    exception and it is a real defect, pinned by `test_r4b` below rather than hidden
    by widening this assertion.
    """
    clamped = r._clamp_season(moment, _floating_with(season))
    assert clamped >= moment
    assert r.in_season(clamped, season)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "A season boundary on February 29 disagrees with itself. "
        "`_next_season_start` clamps the day to Feb 28 in a non-leap year, exactly as "
        "its docstring says it does, but `in_season` applies no such clamp when it "
        "checks. So a task is clamped to a date outside the season it was clamped "
        "into, in 3 years out of 4. Fixing it changes user-visible scheduling, so it "
        "is a separate change with its own changelog entry."
    ),
)
@given(
    moment=ps.aware_datetimes(min_year=2020, max_year=2030),
    season=ps.seasons(),
)
@example(
    # 2021 is not a leap year, and this is an ordinary 6-day season, not a degenerate
    # single-day one. Pinned so `strict=True` can never pass on an unlucky draw.
    moment=datetime(2021, 1, 1, tzinfo=ps.TZ),
    season=[{"start": "02-29", "end": "03-05"}],
)
def test_r4b_a_season_boundary_on_february_29_clamps_out_of_its_own_season(
    moment, season
):
    """R4b. The same claim as R4, over the boundary R4 excludes. Known broken."""
    clamped = r._clamp_season(moment, _floating_with(season))
    assert r.in_season(clamped, season)


@given(
    # Already unique on `ts`: `_record_entry` is the only writer of these lists, so by
    # induction it never receives one that already holds twins. Generating twins would
    # test a state the function cannot be in.
    existing=st.lists(
        st.builds(
            lambda i: {"ts": f"2026-01-{i:02d}T09:00:00+00:00"}, st.integers(1, 28)
        ),
        max_size=520,
        unique_by=lambda e: e["ts"],
    ),
    new_day=st.integers(1, 28),
)
def test_r6_recording_an_entry_dedupes_on_ts_and_caps_the_tail(existing, new_day):
    """R6. `_record_entry` replaces on a duplicate `ts`, else appends, then tail-slices.

    Note what is *not* claimed: the result is not sorted. `recurrence.py:356` appends
    and slices, so asserting sortedness would fail on the first generated input. The
    `ts` pool is small on purpose, so duplicates actually occur.
    """
    entry = {"ts": f"2026-01-{new_day:02d}T09:00:00+00:00", "marker": "new"}
    before_count = sum(1 for e in existing if e["ts"] == entry["ts"])
    result = r._record_entry(existing, entry)

    # Say the whole answer rather than poking at it: replace the first twin in place,
    # otherwise append, then keep the tail. A dict diff then names what moved.
    if before_count:
        index = next(i for i, e in enumerate(existing) if e["ts"] == entry["ts"])
        expected = [*existing[:index], entry, *existing[index + 1 :]]
    else:
        expected = [*existing, entry]
    expected = expected[-r.MAX_COMPLETION_HISTORY :]

    assert result == expected
    assert len(result) <= r.MAX_COMPLETION_HISTORY
    # Exactly one entry carries that ts, so undo and edit can tell the log apart.
    assert sum(1 for e in result if e["ts"] == entry["ts"]) == 1


# ── Real timezones ───────────────────────────────────────────────────────────
#
# `recurrence.py:207` states that `_step` is "correct across DST and month-length
# clamping". Until these two, nothing tested it: every other recurrence test runs on
# `timezone(timedelta(hours=-4))`, a fixed offset with no transitions, and no test in
# the repository built a `ZoneInfo` at all. The claim turns out to be true. These keep
# it true, over 7 real zones including a 30-minute DST shift and a 45-minute offset.


@given(
    anchor=ps.zoned_datetimes(),
    freq=st.sampled_from(["DAILY", "WEEKLY", "MONTHLY"]),
    interval=st.integers(1, 12),
)
def test_r5a_occurrences_keep_the_anchor_local_wall_time(anchor, freq, interval):
    """R5a. Every occurrence reads at the same clock time as its anchor.

    This is what a recurring task actually promises: "every Tuesday at 09:00" means
    09:00 local, on both sides of a transition, not a fixed number of hours apart.
    """
    end = anchor + timedelta(days=400)
    for occurrence in r.expand_fixed_occurrences(anchor, freq, interval, anchor, end):
        assert (occurrence.hour, occurrence.minute) == (anchor.hour, anchor.minute), (
            f"anchor={anchor.isoformat()} freq={freq} interval={interval}: "
            f"{occurrence.isoformat()} reads at a different clock time"
        )


@given(
    anchor=ps.zoned_datetimes(),
    freq=st.sampled_from(["DAILY", "WEEKLY", "MONTHLY"]),
    interval=st.integers(1, 12),
)
def test_r5b_occurrences_move_forward_in_absolute_time(anchor, freq, interval):
    """R5b. Holding the wall time still does not let the real time go backwards.

    The two promises pull against each other: keeping 02:30 across a spring-forward
    makes that step 23 hours rather than 24. It stays positive because the smallest
    schedule step is a day and the largest shift is an hour, but that is a margin, not
    a guarantee anyone wrote down. This writes it down. A regression here would put a
    calendar event before the one it follows.
    """
    end = anchor + timedelta(days=400)
    occurrences = r.expand_fixed_occurrences(anchor, freq, interval, anchor, end)
    absolute = [o.astimezone(_UTC) for o in occurrences]
    assert all(a < b for a, b in itertools.pairwise(absolute)), (
        f"anchor={anchor.isoformat()} freq={freq} interval={interval}: "
        f"occurrences are not in order once converted to UTC"
    )


@given(
    last_completed=ps.aware_datetimes(min_year=2000, max_year=2030),
    interval=st.integers(1, 60),
    unit=st.sampled_from(["days", "weeks", "months"]),
    now=ps.aware_datetimes(min_year=2024, max_year=2030),
)
def test_r7_a_floating_schedule_always_moves_forward(
    last_completed, interval, unit, now
):
    """R7. The next due date of a completed floating task is after that completion.

    Every interval is at least 1, so there is no input for which the schedule may
    stand still or go backwards. Catches a sign error or a swapped unit, neither of
    which a single literal example reliably shows.
    """
    due = r.compute_floating_next_due(last_completed, interval, unit, now=now)
    assert due > last_completed
