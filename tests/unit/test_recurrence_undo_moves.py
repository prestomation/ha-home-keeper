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
