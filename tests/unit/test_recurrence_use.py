"""Every branch point in ``recurrence.py`` tolerates a ``use`` task.

Six functions key on the recurrence type. Two raised ``ValueError`` on an unknown one
outright, and 4 more read ``rec_type not in (REC_TRIGGERED, REC_SENSOR)`` and would
have called ``compute_next_due``, hitting the same raise. Before this, the *first*
completion of a use task raised before recording anything.
"""

from datetime import datetime, timedelta, timezone

import hk_recurrence as r
import pytest

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)


def _use(completions=None):
    return {
        "id": "t1",
        "name": "Wear jacket",
        "recurrence_type": "use",
        "completions": list(completions or []),
        "skips": [],
        "last_completed": None,
        "next_due": None,
    }


def test_apply_completion_records_the_use_and_arms_nothing():
    task = _use()
    r.apply_completion(task, NOW, now=NOW)
    assert task["next_due"] is None
    assert [entry["ts"] for entry in task["completions"]] == [NOW.isoformat()]
    assert task["last_completed"] == NOW.isoformat()


def test_apply_completion_keeps_per_completion_metadata():
    """A use carries the same note/cost/photo/who every other completion does."""
    task = _use()
    r.apply_completion(task, NOW, now=NOW, metadata={"note": "wet hike"})
    assert task["completions"][0]["note"] == "wet hike"


def test_repeated_completions_accumulate():
    task = _use()
    for i in range(5):
        r.apply_completion(task, NOW - timedelta(hours=i), now=NOW)
    assert len(task["completions"]) == 5
    assert task["next_due"] is None


def test_skip_occurrence_logs_the_skip_and_leaves_the_count_alone():
    task = _use([{"ts": (NOW - timedelta(days=1)).isoformat()}])
    r.skip_occurrence(task, now=NOW)
    assert task["next_due"] is None
    assert len(task["skips"]) == 1
    assert len(task["completions"]) == 1


def test_remove_completion_leaves_a_use_task_dormant():
    task = _use()
    r.apply_completion(task, NOW, now=NOW)
    r.remove_completion(task, NOW.isoformat(), now=NOW)
    assert task["next_due"] is None
    assert task["completions"] == []


def test_remove_completion_from_a_multi_entry_log_is_still_dormant():
    task = _use()
    first = NOW - timedelta(hours=2)
    r.apply_completion(task, first, now=NOW)
    r.apply_completion(task, NOW, now=NOW)
    r.remove_completion(task, NOW.isoformat(), now=NOW)
    assert task["next_due"] is None
    assert task["last_completed"] == first.isoformat()


def test_move_completion_leaves_a_use_task_dormant():
    task = _use()
    r.apply_completion(task, NOW - timedelta(days=2), now=NOW)
    moved = NOW - timedelta(days=1)
    r.move_completion(
        task, (NOW - timedelta(days=2)).isoformat(), moved.isoformat(), now=NOW
    )
    assert task["next_due"] is None
    assert task["last_completed"] == moved.isoformat()


def test_record_skip_leaves_a_use_task_dormant():
    task = _use()
    r.record_skip(task, NOW)
    assert task["next_due"] is None


def test_compute_next_due_refuses_a_use_task():
    """Loud on purpose: no caller reaches here, and ``now`` would be a wrong answer.

    Returning ``now`` (the triggered/sensor answer) would strand a counting task as
    permanently overdue on every time surface.
    """
    with pytest.raises(ValueError, match="never due"):
        r.compute_next_due(_use(), now=NOW)


def test_is_overdue_is_false_for_a_use_task():
    assert r.is_overdue(_use(), now=NOW) is False
