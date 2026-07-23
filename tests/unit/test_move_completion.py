"""Unit tests for ``recurrence.move_completion`` (issue #143).

Re-timestamps an already-recorded completion (back-date or correct it) —
distinct from ``update_completion`` (metadata only, ``ts`` never moves) and from
delete-then-re-add (which would lose metadata and re-stamp at "now"). Covers the
re-derive ordering that matters most: both the removal *and* the re-insertion of
the moved entry happen before ``last_completed``/``next_due`` are computed once
from the final history, so a one-off's only completion being moved does not
transiently look like "history now empty" and get re-armed.
"""

from datetime import datetime, timedelta, timezone

import hk_recurrence as r
import pytest

TZ = timezone(timedelta(hours=-4))


def dt(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def test_move_completion_missing_old_ts_raises():
    task = {
        "recurrence_type": "floating",
        "interval": 1,
        "unit": "months",
        "completions": [{"ts": dt(2026, 6, 1).isoformat()}],
    }
    with pytest.raises(ValueError):
        r.move_completion(
            task,
            dt(2020, 1, 1).isoformat(),
            dt(2026, 6, 5).isoformat(),
            now=dt(2026, 6, 13),
        )


def test_move_completion_floating_rederives_from_new_latest():
    # Moving the latest completion earlier than a prior one must rewind
    # last_completed/next_due to whichever is now actually latest.
    now = dt(2026, 6, 13, 10)
    task = {
        "recurrence_type": "floating",
        "interval": 1,
        "unit": "months",
        "last_completed": dt(2026, 6, 1).isoformat(),
        "next_due": dt(2026, 7, 1).isoformat(),
        "completions": [
            {"ts": dt(2026, 5, 1).isoformat()},
            {"ts": dt(2026, 6, 1).isoformat()},
        ],
    }
    out = r.move_completion(
        task, dt(2026, 6, 1).isoformat(), dt(2026, 4, 1).isoformat(), now=now
    )
    ts_values = {e["ts"] for e in out["completions"]}
    assert ts_values == {dt(2026, 5, 1).isoformat(), dt(2026, 4, 1).isoformat()}
    # The prior May 1 completion is now the latest.
    assert out["last_completed"] == dt(2026, 5, 1).isoformat()
    assert out["next_due"] == dt(2026, 6, 1).isoformat()


def test_move_completion_floating_moves_later_and_advances():
    now = dt(2026, 6, 13, 10)
    task = {
        "recurrence_type": "floating",
        "interval": 1,
        "unit": "months",
        "last_completed": dt(2026, 6, 1).isoformat(),
        "next_due": dt(2026, 7, 1).isoformat(),
        "completions": [{"ts": dt(2026, 6, 1).isoformat()}],
    }
    out = r.move_completion(
        task, dt(2026, 6, 1).isoformat(), dt(2026, 6, 5).isoformat(), now=now
    )
    assert out["completions"] == [{"ts": dt(2026, 6, 5).isoformat()}]
    assert out["last_completed"] == dt(2026, 6, 5).isoformat()
    assert out["next_due"] == dt(2026, 7, 5).isoformat()


def test_move_completion_preserves_metadata():
    now = dt(2026, 6, 13, 10)
    task = {
        "recurrence_type": "floating",
        "interval": 1,
        "unit": "months",
        "last_completed": dt(2026, 6, 1).isoformat(),
        "next_due": dt(2026, 7, 1).isoformat(),
        "completions": [
            {"ts": dt(2026, 6, 1).isoformat(), "note": "filter changed", "cost": 12.5}
        ],
    }
    out = r.move_completion(
        task, dt(2026, 6, 1).isoformat(), dt(2026, 6, 3).isoformat(), now=now
    )
    entry = out["completions"][0]
    assert entry["ts"] == dt(2026, 6, 3).isoformat()
    assert entry["note"] == "filter changed"
    assert entry["cost"] == 12.5


def test_move_completion_collapses_into_existing_ts_moved_metadata_wins():
    # Moving an entry onto a ts that already has one: the moved entry's metadata
    # wins and the entry it collided with is discarded (not merged).
    now = dt(2026, 6, 13, 10)
    task = {
        "recurrence_type": "floating",
        "interval": 1,
        "unit": "months",
        "last_completed": dt(2026, 6, 5).isoformat(),
        "next_due": dt(2026, 7, 5).isoformat(),
        "completions": [
            {"ts": dt(2026, 6, 1).isoformat(), "note": "moved-in"},
            {"ts": dt(2026, 6, 5).isoformat(), "note": "victim"},
        ],
    }
    out = r.move_completion(
        task, dt(2026, 6, 1).isoformat(), dt(2026, 6, 5).isoformat(), now=now
    )
    assert len(out["completions"]) == 1
    assert out["completions"][0] == {
        "ts": dt(2026, 6, 5).isoformat(),
        "note": "moved-in",
    }


def test_move_completion_qualifies_naive_new_ts():
    # The move_completion *service*'s new_completed_at is cv.datetime, which (like
    # complete_task's completed_at) accepts an offset-less value — qualify it with
    # now's zone, same as apply_completion.
    now = dt(2026, 6, 13, 10)
    task = {
        "recurrence_type": "floating",
        "interval": 1,
        "unit": "months",
        "last_completed": dt(2026, 6, 1).isoformat(),
        "next_due": dt(2026, 7, 1).isoformat(),
        "completions": [{"ts": dt(2026, 6, 1).isoformat()}],
    }
    naive = datetime(2026, 6, 2, 9, 30)  # no tzinfo
    out = r.move_completion(
        task, dt(2026, 6, 1).isoformat(), naive.isoformat(), now=now
    )
    assert out["completions"] == [{"ts": dt(2026, 6, 2, 9, 30).isoformat()}]
    assert out["last_completed"] == dt(2026, 6, 2, 9, 30).isoformat()


def test_move_completion_fixed_stays_schedule_driven():
    now = dt(2026, 6, 13, 10)
    anchor = dt(2026, 1, 1, 8)
    task = {
        "recurrence_type": "fixed",
        "interval": 1,
        "freq": "MONTHLY",
        "anchor": anchor.isoformat(),
        "last_completed": dt(2026, 6, 1).isoformat(),
        "next_due": dt(2026, 7, 1, 8).isoformat(),
        "completions": [{"ts": dt(2026, 6, 1).isoformat()}],
    }
    out = r.move_completion(
        task, dt(2026, 6, 1).isoformat(), dt(2026, 6, 10).isoformat(), now=now
    )
    # A fixed task's schedule doesn't care which day the occurrence was logged on.
    assert (
        out["next_due"]
        == r.next_fixed_occurrence(anchor, "MONTHLY", 1, after=now).isoformat()
    )
    assert out["last_completed"] == dt(2026, 6, 10).isoformat()


def test_move_completion_triggered_next_due_untouched():
    now = dt(2026, 6, 16, 10)
    task = {
        "recurrence_type": "triggered",
        "next_due": None,
        "last_completed": dt(2026, 6, 1).isoformat(),
        "completions": [{"ts": dt(2026, 6, 1).isoformat()}],
    }
    out = r.move_completion(
        task, dt(2026, 6, 1).isoformat(), dt(2026, 6, 2).isoformat(), now=now
    )
    # Armed/dormant state is condition-driven, not history-driven: untouched.
    assert out["next_due"] is None
    assert out["last_completed"] == dt(2026, 6, 2).isoformat()


def test_move_completion_sensor_next_due_untouched():
    now = dt(2026, 6, 16, 10)
    task = {
        "recurrence_type": "sensor",
        "next_due": None,
        "last_completed": dt(2026, 6, 1).isoformat(),
        "completions": [{"ts": dt(2026, 6, 1).isoformat()}],
    }
    out = r.move_completion(
        task, dt(2026, 6, 1).isoformat(), dt(2026, 6, 2).isoformat(), now=now
    )
    assert out["next_due"] is None


def test_move_completion_one_off_only_completion_stays_dormant():
    # The critical ordering case: moving a one-off's *only* completion must not
    # transiently look like "history now empty" (which would re-arm next_due to
    # due) — the moved entry is back in history before next_due is (re)computed,
    # so the task correctly stays dormant.
    now = dt(2026, 7, 10, 10)
    due = dt(2026, 7, 1, 8)
    completed_at = dt(2026, 7, 1, 9)
    task = {
        "recurrence_type": "one-off",
        "due": due.isoformat(),
        "next_due": None,
        "last_completed": completed_at.isoformat(),
        "completions": [{"ts": completed_at.isoformat()}],
    }
    out = r.move_completion(
        task, completed_at.isoformat(), dt(2026, 7, 3, 9).isoformat(), now=now
    )
    assert out["next_due"] is None
    assert out["last_completed"] == dt(2026, 7, 3, 9).isoformat()
    assert out["completions"] == [{"ts": dt(2026, 7, 3, 9).isoformat()}]


def test_move_completion_one_off_with_other_completions_stays_dormant():
    now = dt(2026, 7, 10, 10)
    due = dt(2026, 7, 1, 8)
    first = dt(2026, 7, 1, 9)
    second = dt(2026, 7, 2, 9)
    task = {
        "recurrence_type": "one-off",
        "due": due.isoformat(),
        "next_due": None,
        "last_completed": second.isoformat(),
        "completions": [{"ts": first.isoformat()}, {"ts": second.isoformat()}],
    }
    out = r.move_completion(
        task, first.isoformat(), dt(2026, 6, 25).isoformat(), now=now
    )
    assert out["next_due"] is None
    assert out["last_completed"] == second.isoformat()
