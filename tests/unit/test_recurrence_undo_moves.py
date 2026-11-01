"""Undo of a completion puts back the moved dates that the completion pruned.

A completion prunes the moves that lie fully in the past. Before the fix, an undo put
``next_due`` back on a moved date whose move record was gone, so the task showed a time
that was on no schedule (goal G4, "defer without loss").
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import hk_models as models
import hk_recurrence as r

NY = ZoneInfo("America/New_York")


def _moved_task():
    now = datetime(2026, 1, 1, 12, tzinfo=NY)
    anchor = datetime(2025, 10, 31, 0, 30, tzinfo=NY)
    task = models.build_task(
        {
            "name": "x",
            "recurrence_type": "fixed",
            "rrule": "FREQ=DAILY",
            "anchor": anchor.isoformat(),
        },
        now=now,
    )
    due = datetime.fromisoformat(task["next_due"])
    r.move_occurrence(task, due, due + timedelta(hours=1), now=now)
    return task, now


def test_undo_does_not_leave_next_due_on_a_pruned_move():
    task, now = _moved_task()
    later = now + timedelta(hours=38)
    r.apply_completion(task, later, now=later)
    r.remove_completion(task, task["completions"][-1]["ts"], now=later)
    shown = datetime.fromisoformat(task["next_due"])
    assert r.is_task_occurrence(task, shown, tz=NY), task["next_due"]


def test_undo_restores_the_pruned_move_record():
    task, now = _moved_task()
    before = [dict(m) for m in task["moved_occurrences"]]
    later = now + timedelta(hours=38)
    r.apply_completion(task, later, now=later)
    assert task["moved_occurrences"] == []
    r.remove_completion(task, task["completions"][-1]["ts"], now=later)
    assert task["moved_occurrences"] == before
    assert task["next_due"] == "2026-01-02T01:30:00-05:00"


def test_completion_without_a_pruned_move_stores_no_extra_key():
    now = datetime(2026, 1, 1, 12, tzinfo=NY)
    task = models.build_task(
        {
            "name": "x",
            "recurrence_type": "fixed",
            "rrule": "FREQ=DAILY",
            "anchor": datetime(2025, 10, 31, 0, 30, tzinfo=NY).isoformat(),
        },
        now=now,
    )
    r.apply_completion(task, now, now=now)
    assert r.PRUNED_MOVES not in task["completions"][-1]


def test_undo_does_not_duplicate_a_move_that_exists_again():
    task, now = _moved_task()
    later = now + timedelta(hours=38)
    r.apply_completion(task, later, now=later)
    entry = task["completions"][-1]
    task["moved_occurrences"] = [dict(m) for m in entry[r.PRUNED_MOVES]]
    r.remove_completion(task, entry["ts"], now=later)
    assert len(task["moved_occurrences"]) == 1


def _row(day):
    return {
        "from": f"2026-02-{day:02d}T00:30:00-05:00",
        "to": f"2026-02-{day:02d}T01:30:00-05:00",
    }


def test_restore_ignores_a_pruned_value_that_is_not_a_list():
    task = {"moved_occurrences": [_row(1)]}
    r._restore_pruned_moves(task, "bad")
    r._restore_pruned_moves(task, None)
    assert task["moved_occurrences"] == [_row(1)]


def test_restore_skips_rows_that_are_not_dicts_and_keeps_the_good_ones():
    task = {}
    r._restore_pruned_moves(task, ["bad", 3, _row(2)])
    assert task["moved_occurrences"] == [_row(2)]


def test_restore_adds_each_original_date_once():
    task = {"moved_occurrences": [_row(1)]}
    r._restore_pruned_moves(task, [_row(1), _row(2), _row(2)])
    assert task["moved_occurrences"] == [_row(1), _row(2)]


def test_restore_copies_the_rows():
    pruned = [_row(3)]
    task = {}
    r._restore_pruned_moves(task, pruned)
    task["moved_occurrences"][0]["to"] = "changed"
    assert pruned == [_row(3)]


def test_restore_stops_at_the_move_cap():
    cap = r.MAX_MOVED_OCCURRENCES
    task = {"moved_occurrences": [_row(d) for d in range(1, cap)]}
    r._restore_pruned_moves(task, [_row(cap), _row(cap + 1)])
    assert len(task["moved_occurrences"]) == cap
    assert task["moved_occurrences"][-1] == _row(cap)


def test_restore_is_for_a_fixed_task_only():
    task = {
        "recurrence_type": "floating",
        "interval": 1,
        "unit": "days",
        "next_due": "2026-01-05T00:00:00+00:00",
        "last_completed": "2026-01-02T00:00:00+00:00",
        "completions": [
            {
                "ts": "2026-01-02T00:00:00+00:00",
                "prior_due": "2026-01-01T00:00:00+00:00",
                "pruned_moves": [_row(5)],
            }
        ],
    }
    now = datetime(2026, 1, 3, tzinfo=NY)
    r.remove_completion(task, "2026-01-02T00:00:00+00:00", now=now)
    assert "moved_occurrences" not in task


def test_only_the_pruned_rows_are_stored_and_a_kept_move_stays():
    task, now = _moved_task()
    old = dict(task["moved_occurrences"][0])
    future_from = datetime(2026, 1, 20, 0, 30, tzinfo=NY)
    r.move_occurrence(task, future_from, future_from + timedelta(hours=1), now=now)
    kept = {
        "from": future_from.isoformat(),
        "to": (future_from + timedelta(hours=1)).isoformat(),
    }
    later = now + timedelta(hours=38)
    r.apply_completion(task, later, now=later)
    assert task["completions"][-1][r.PRUNED_MOVES] == [old]
    assert task["moved_occurrences"] == [kept]
