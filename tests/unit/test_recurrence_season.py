"""Unit tests for active-season clamping of floating and fixed recurrences."""

from datetime import datetime, timedelta, timezone

import hk_recurrence as r

TZ = timezone(timedelta(hours=-4))


def dt(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


# ---------------------------------------------------------------------------
# in_season
# ---------------------------------------------------------------------------


class TestInSeason:
    """Non-wrapping (Apr-Sep) and wrapping (Nov-Mar) with boundary dates."""

    def test_non_wrapping_inside(self):
        season = {"start": "04-01", "end": "09-30"}
        assert r.in_season(dt(2026, 6, 15), season) is True

    def test_non_wrapping_start_boundary(self):
        season = {"start": "04-01", "end": "09-30"}
        assert r.in_season(dt(2026, 4, 1), season) is True

    def test_non_wrapping_end_boundary(self):
        season = {"start": "04-01", "end": "09-30"}
        assert r.in_season(dt(2026, 9, 30), season) is True

    def test_non_wrapping_before(self):
        season = {"start": "04-01", "end": "09-30"}
        assert r.in_season(dt(2026, 3, 31), season) is False

    def test_non_wrapping_after(self):
        season = {"start": "04-01", "end": "09-30"}
        assert r.in_season(dt(2026, 10, 1), season) is False

    def test_wrapping_in_start_half(self):
        season = {"start": "11-01", "end": "03-31"}
        assert r.in_season(dt(2026, 12, 15), season) is True

    def test_wrapping_in_end_half(self):
        season = {"start": "11-01", "end": "03-31"}
        assert r.in_season(dt(2026, 2, 15), season) is True

    def test_wrapping_start_boundary(self):
        season = {"start": "11-01", "end": "03-31"}
        assert r.in_season(dt(2026, 11, 1), season) is True

    def test_wrapping_end_boundary(self):
        season = {"start": "11-01", "end": "03-31"}
        assert r.in_season(dt(2026, 3, 31), season) is True

    def test_wrapping_outside(self):
        season = {"start": "11-01", "end": "03-31"}
        assert r.in_season(dt(2026, 6, 15), season) is False

    def test_wrapping_just_before_start(self):
        season = {"start": "11-01", "end": "03-31"}
        assert r.in_season(dt(2026, 10, 31), season) is False


# ---------------------------------------------------------------------------
# _next_season_start
# ---------------------------------------------------------------------------


class TestNextSeasonStart:
    def test_forward_same_year(self):
        season = {"start": "04-01", "end": "09-30"}
        result = r._next_season_start(dt(2026, 1, 15), season)
        assert result == dt(2026, 4, 1)

    def test_forward_next_year(self):
        season = {"start": "04-01", "end": "09-30"}
        result = r._next_season_start(dt(2026, 10, 1), season)
        assert result == dt(2027, 4, 1)

    def test_on_season_start(self):
        season = {"start": "04-01", "end": "09-30"}
        result = r._next_season_start(dt(2026, 4, 1), season)
        assert result == dt(2026, 4, 1)

    def test_wrapping_season_forward(self):
        season = {"start": "11-01", "end": "03-31"}
        result = r._next_season_start(dt(2026, 5, 1), season)
        assert result == dt(2026, 11, 1)

    def test_day_clamping_short_month(self):
        season = {"start": "02-30", "end": "06-30"}
        result = r._next_season_start(dt(2026, 1, 1), season)
        assert result == dt(2026, 2, 28)

    def test_day_clamping_leap_year(self):
        season = {"start": "02-30", "end": "06-30"}
        result = r._next_season_start(dt(2028, 1, 1), season)
        assert result == dt(2028, 2, 29)

    def test_next_year_when_past_start_in_current_year(self):
        season = {"start": "06-15", "end": "09-30"}
        result = r._next_season_start(dt(2026, 7, 1), season)
        assert result == dt(2027, 6, 15)


# ---------------------------------------------------------------------------
# Floating task clamping
# ---------------------------------------------------------------------------


class TestFloatingClamping:
    def test_in_season_unchanged(self):
        """A next_due inside the season is returned as-is."""
        task = {
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "months",
            "last_completed": dt(2026, 5, 15).isoformat(),
            "active_season": {"start": "04-01", "end": "09-30"},
        }
        result = r.compute_next_due(task, now=dt(2026, 5, 15))
        assert result == r.add_months(dt(2026, 5, 15), 2)  # Jul 15

    def test_out_of_season_clamped(self):
        """Completed Sep 15 + 2 months = Nov 15 → clamped to Apr 1 next year."""
        task = {
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "months",
            "last_completed": dt(2026, 9, 15).isoformat(),
            "active_season": {"start": "04-01", "end": "09-30"},
        }
        result = r.compute_next_due(task, now=dt(2026, 9, 15))
        assert result == dt(2027, 4, 1)

    def test_never_completed_in_season(self):
        """A never-completed task due now — now is in-season, stays as-is."""
        now = dt(2026, 6, 1)
        task = {
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
            "last_completed": None,
            "active_season": {"start": "04-01", "end": "09-30"},
        }
        result = r.compute_next_due(task, now=now)
        assert result == now

    def test_never_completed_off_season(self):
        """A never-completed task due now — now is off-season, clamped forward."""
        now = dt(2026, 11, 1)
        task = {
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
            "last_completed": None,
            "active_season": {"start": "04-01", "end": "09-30"},
        }
        result = r.compute_next_due(task, now=now)
        assert result == dt(2027, 4, 1)

    def test_no_season_unchanged(self):
        """No active_season — baseline unaffected."""
        task = {
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "months",
            "last_completed": dt(2026, 9, 15).isoformat(),
        }
        result = r.compute_next_due(task, now=dt(2026, 9, 15))
        assert result == r.add_months(dt(2026, 9, 15), 2)

    def test_wrapping_season(self):
        """Nov-Mar wrapping season: Apr 15 + 2 months = Jun → clamped to Nov 1."""
        task = {
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "months",
            "last_completed": dt(2026, 4, 15).isoformat(),
            "active_season": {"start": "11-01", "end": "03-31"},
        }
        result = r.compute_next_due(task, now=dt(2026, 4, 15))
        assert result == dt(2026, 11, 1)


# ---------------------------------------------------------------------------
# Fixed task clamping
# ---------------------------------------------------------------------------


class TestFixedClamping:
    def test_in_season_unchanged(self):
        task = {
            "recurrence_type": "fixed",
            "freq": "MONTHLY",
            "interval": 1,
            "anchor": dt(2026, 1, 1).isoformat(),
            "active_season": {"start": "04-01", "end": "09-30"},
        }
        now = dt(2026, 5, 15)
        result = r.compute_next_due(task, now=now)
        assert result == dt(2026, 6, 1)

    def test_out_of_season_grid_aligned(self):
        """Oct 15 now + monthly from Jan 1 → next occurrence is Nov 1, off-season.
        Season starts Apr 1 → first grid occurrence on/after Apr 1 is Apr 1."""
        task = {
            "recurrence_type": "fixed",
            "freq": "MONTHLY",
            "interval": 1,
            "anchor": dt(2026, 1, 1).isoformat(),
            "active_season": {"start": "04-01", "end": "09-30"},
        }
        now = dt(2026, 10, 15)
        result = r.compute_next_due(task, now=now)
        assert result == dt(2027, 4, 1)

    def test_grid_alignment_with_interval(self):
        """Every-2-months from Jan 1 → Jan, Mar, May, Jul, Sep, Nov...
        Season Apr-Sep, now is Oct → season start Apr 1 → first grid occ
        on/after Apr 1 is May 1."""
        task = {
            "recurrence_type": "fixed",
            "freq": "MONTHLY",
            "interval": 2,
            "anchor": dt(2026, 1, 1).isoformat(),
            "active_season": {"start": "04-01", "end": "09-30"},
        }
        now = dt(2026, 10, 15)
        result = r.compute_next_due(task, now=now)
        assert result == dt(2027, 5, 1)

    def test_no_season_unchanged(self):
        task = {
            "recurrence_type": "fixed",
            "freq": "MONTHLY",
            "interval": 1,
            "anchor": dt(2026, 1, 1).isoformat(),
        }
        now = dt(2026, 10, 15)
        result = r.compute_next_due(task, now=now)
        assert result == dt(2026, 11, 1)


# ---------------------------------------------------------------------------
# apply_completion with season
# ---------------------------------------------------------------------------


class TestApplyCompletionSeason:
    def test_floating_clamped(self):
        task = {
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "months",
            "last_completed": None,
            "completions": [],
            "active_season": {"start": "04-01", "end": "09-30"},
        }
        completed = dt(2026, 9, 1)
        r.apply_completion(task, completed, now=completed)
        assert task["next_due"] == dt(2027, 4, 1).isoformat()

    def test_floating_in_season(self):
        task = {
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
            "last_completed": None,
            "completions": [],
            "active_season": {"start": "04-01", "end": "09-30"},
        }
        completed = dt(2026, 5, 1)
        r.apply_completion(task, completed, now=completed)
        assert task["next_due"] == dt(2026, 6, 1).isoformat()

    def test_fixed_clamped(self):
        task = {
            "recurrence_type": "fixed",
            "freq": "MONTHLY",
            "interval": 1,
            "anchor": dt(2026, 1, 1).isoformat(),
            "completions": [],
            "active_season": {"start": "04-01", "end": "09-30"},
        }
        now = dt(2026, 9, 15)
        r.apply_completion(task, now, now=now)
        assert task["next_due"] == dt(2027, 4, 1).isoformat()


# ---------------------------------------------------------------------------
# skip_occurrence with season
# ---------------------------------------------------------------------------


class TestSkipOccurrenceSeason:
    def test_floating_skip_clamped(self):
        task = {
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "months",
            "next_due": dt(2026, 8, 15).isoformat(),
            "active_season": {"start": "04-01", "end": "09-30"},
        }
        now = dt(2026, 8, 15)
        r.skip_occurrence(task, now=now)
        assert task["next_due"] == dt(2027, 4, 1).isoformat()

    def test_floating_skip_in_season(self):
        task = {
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
            "next_due": dt(2026, 5, 1).isoformat(),
            "active_season": {"start": "04-01", "end": "09-30"},
        }
        now = dt(2026, 5, 1)
        r.skip_occurrence(task, now=now)
        assert task["next_due"] == dt(2026, 6, 1).isoformat()

    def test_fixed_skip_clamped(self):
        task = {
            "recurrence_type": "fixed",
            "freq": "MONTHLY",
            "interval": 1,
            "anchor": dt(2026, 1, 1).isoformat(),
            "next_due": dt(2026, 9, 1).isoformat(),
            "active_season": {"start": "04-01", "end": "09-30"},
        }
        now = dt(2026, 9, 15)
        r.skip_occurrence(task, now=now)
        assert task["next_due"] == dt(2027, 4, 1).isoformat()


# ---------------------------------------------------------------------------
# Wrapping season end-to-end
# ---------------------------------------------------------------------------


class TestWrappingSeasonEndToEnd:
    def test_floating_wrapping_in_season(self):
        """Nov-Mar season: completed Dec 1 + 1 month = Jan 1, still in season."""
        task = {
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
            "last_completed": dt(2026, 12, 1).isoformat(),
            "active_season": {"start": "11-01", "end": "03-31"},
        }
        result = r.compute_next_due(task, now=dt(2026, 12, 1))
        assert result == dt(2027, 1, 1)

    def test_floating_wrapping_out_of_season(self):
        """Nov-Mar season: completed Mar 1 + 2 months = May 1, off-season → Nov 1."""
        task = {
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "months",
            "last_completed": dt(2027, 3, 1).isoformat(),
            "active_season": {"start": "11-01", "end": "03-31"},
        }
        result = r.compute_next_due(task, now=dt(2027, 3, 1))
        assert result == dt(2027, 11, 1)

    def test_fixed_wrapping(self):
        """Nov-Mar season, monthly from Jan 1: now is May → off-season.
        Next season start is Nov 1 → grid occurrence Nov 1."""
        task = {
            "recurrence_type": "fixed",
            "freq": "MONTHLY",
            "interval": 1,
            "anchor": dt(2026, 1, 1).isoformat(),
            "active_season": {"start": "11-01", "end": "03-31"},
        }
        now = dt(2026, 5, 15)
        result = r.compute_next_due(task, now=now)
        assert result == dt(2026, 11, 1)
