"""A ``use`` task never gets a due date, from any path that could give it one.

The whole feature rests on this invariant. A use task with a ``next_due`` is a task
nothing can complete out of that state: it would sit overdue on the filter pills, the
overdue ``binary_sensor``, the calendar and every notification, forever.
"""

from datetime import datetime, timedelta, timezone

import hk_models as models
import pytest

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)


def _use(**extra):
    return models.build_task(
        {"name": "Wear jacket", "recurrence_type": "use", **extra}, now=NOW
    )


def test_build_task_gives_a_use_task_no_due_date():
    assert _use()["next_due"] is None


def test_a_seed_completion_counts_but_still_arms_nothing():
    task = _use(last_completed=(NOW - timedelta(days=1)).isoformat())
    assert task["next_due"] is None
    assert len(task["completions"]) == 1


def test_a_use_task_stores_no_schedule_fields():
    task = _use()
    for field in ("interval", "unit", "freq", "anchor", "due"):
        assert field not in task


def test_interval_and_unit_are_ignored_rather_than_validated():
    """An explicit type wins over inference, and the early return drops the cadence."""
    task = _use(interval=25, unit="days")
    assert task["recurrence_type"] == "use"
    assert "interval" not in task


def test_use_is_a_valid_recurrence_type():
    assert "use" in models.RECURRENCE_TYPES


@pytest.mark.parametrize(
    "updates",
    [
        {"name": "Wear the other jacket"},
        {"notes": "left pocket"},
        {"device_id": "dev1"},
        {"area_id": "hall"},
        {"enabled": False},
        {"labels": ["outdoors"]},
        {"recurrence_type": "use"},
        {"interval": 3},
        {"unit": "days"},
        {"active_season": None},
    ],
)
def test_no_merge_update_path_gives_a_use_task_a_due_date(updates):
    merged = models.merge_update(_use(), updates, now=NOW)
    assert merged["next_due"] is None


def test_converting_a_scheduled_task_into_a_use_task_drops_its_due_date():
    """A carried-over schedule date would read as permanently overdue."""
    floating = models.build_task(
        {
            "name": "Anode",
            "recurrence_type": "floating",
            "interval": 12,
            "unit": "months",
        },
        now=NOW,
    )
    assert floating["next_due"] is not None
    merged = models.merge_update(floating, {"recurrence_type": "use"}, now=NOW)
    assert merged["next_due"] is None


def test_converting_a_use_task_into_a_floating_task_gives_it_one_back():
    merged = models.merge_update(
        _use(),
        {"recurrence_type": "floating", "interval": 6, "unit": "months"},
        now=NOW,
    )
    assert merged["next_due"] is not None


def test_a_use_task_edited_with_a_stale_due_date_still_has_none():
    """``merge_update`` carries ``due`` forward in its candidate; the branch is
    unconditional so the from-type cannot matter."""
    task = _use()
    task["next_due"] = NOW.isoformat()
    merged = models.merge_update(task, {"name": "Renamed"}, now=NOW)
    assert merged["next_due"] is None
