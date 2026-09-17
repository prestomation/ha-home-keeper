"""Unit tests for the pure count aggregation behind the task-count sensors."""

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import hk_models as models
import hk_profiles as profiles
import hk_task_counts as task_counts
import pytest

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 5, 10, 12, 0, tzinfo=TZ)
WINDOW = timedelta(days=3)


def make_task(name, due, **extra):
    """A real task, placed at an exact due instant.

    Built through ``models.build_task`` so the dict is the one the rest of the
    integration passes around, then given an explicit ``next_due`` — the counts are
    about *where a task sits relative to now*, and computing that from a recurrence
    would make every assertion depend on the engine as well.
    """
    task = models.build_task({"name": name, "interval": 30, "unit": "days"}, now=NOW)
    task["next_due"] = due.isoformat() if due else None
    task.update(extra)
    return task


@pytest.fixture
def tasks():
    """Two overdue, one due soon, one far out, one dormant."""
    return [
        make_task("Gutters", NOW - timedelta(days=10)),
        make_task("Filter", NOW - timedelta(hours=1)),
        make_task("Smoke alarm", NOW + timedelta(days=2)),
        make_task("Deck stain", NOW + timedelta(days=30)),
        make_task("Someday", None),
    ]


def filt(**over):
    return profiles.normalize_filter(over)


def count(tasks, **over):
    return task_counts.count_tasks(tasks, filt(**over), now=NOW, window=WINDOW)


# ── the state follows the profile's own status tier ──────────────────────────


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (profiles.STATUS_OVERDUE, 2),
        (profiles.STATUS_DUE_SOON, 3),
        (profiles.STATUS_ALL, 4),
    ],
)
def test_state_follows_the_profile_status(tasks, status, expected):
    result = count(tasks, status=status)
    assert result["state"] == expected


def test_state_equals_total_for_an_every_task_profile(tasks):
    result = count(tasks, status=profiles.STATUS_ALL)
    assert result["state"] == result["total"] == 4


def test_total_ignores_the_status_filter(tasks):
    # An overdue profile still reports the size of the world it draws from, so a card
    # can say "2 of 4".
    result = count(tasks, status=profiles.STATUS_OVERDUE)
    assert result["state"] == 2
    assert result["total"] == 4


def test_total_honours_the_scope_filters(tasks):
    tasks[0]["labels"] = ["dog"]
    result = count(tasks, status=profiles.STATUS_OVERDUE, labels=["dog"])
    assert result["state"] == 1
    assert result["total"] == 1
    assert result["overdue"] == 1
    assert result["next_task_name"] == "Gutters"


def test_exclusions_shrink_every_count(tasks):
    tasks[0]["labels"] = ["indoor"]
    result = count(tasks, status=profiles.STATUS_ALL, exclude_labels=["indoor"])
    assert result["total"] == 3
    assert result["overdue"] == 1
    assert result["next_task_name"] == "Filter"


# ── the bands partition cleanly ──────────────────────────────────────────────


def test_due_soon_excludes_overdue(tasks):
    result = count(tasks, status=profiles.STATUS_DUE_SOON)
    assert result["overdue"] == 2
    assert result["due_soon"] == 1
    # The state of a due-soon profile is the two bands together, never due_soon alone.
    assert result["state"] == result["overdue"] + result["due_soon"]


def test_window_boundaries():
    at_window = make_task("Edge", NOW + WINDOW)
    past_window = make_task("Past edge", NOW + WINDOW + timedelta(seconds=1))
    due_now = make_task("Now", NOW)
    result = count([at_window, past_window, due_now], status=profiles.STATUS_ALL)
    assert result["due_soon"] == 1  # exactly at the window still counts
    assert result["overdue"] == 1  # the due instant itself is overdue, not due-soon
    assert result["total"] == 3


def test_a_custom_window_moves_the_due_soon_band():
    # The window is a real parameter, not decoration: it decides both the due_soon
    # count and what a due-soon profile's state admits.
    task = make_task("Edge", NOW + timedelta(days=5))
    wide = task_counts.count_tasks(
        [task], filt(status=profiles.STATUS_DUE_SOON), now=NOW, window=timedelta(days=7)
    )
    assert wide["due_soon"] == 1
    assert wide["state"] == 1
    narrow = task_counts.count_tasks(
        [task], filt(status=profiles.STATUS_DUE_SOON), now=NOW, window=WINDOW
    )
    assert narrow["due_soon"] == 0
    assert narrow["state"] == 0
    # The scope is unaffected either way — it admits every scheduled task.
    assert wide["total"] == narrow["total"] == 1


def test_default_window_is_the_shared_three_days():
    # The sensor and the overdue event must agree on what "due soon" means.
    task = make_task("Edge", NOW + timedelta(days=3) - timedelta(seconds=1))
    result = task_counts.count_tasks([task], filt(status=profiles.STATUS_ALL), now=NOW)
    assert result["due_soon"] == 1


# ── due_today is a calendar date in the caller's zone ─────────────────────────


def test_due_today_is_a_local_calendar_date():
    tz = ZoneInfo("America/Los_Angeles")
    now = datetime(2026, 5, 10, 23, 0, tzinfo=tz)
    tasks = [
        make_task("Tonight", datetime(2026, 5, 10, 23, 30, tzinfo=tz)),
        make_task("Just after midnight", datetime(2026, 5, 11, 0, 30, tzinfo=tz)),
        make_task("This morning", datetime(2026, 5, 10, 1, 0, tzinfo=tz)),
    ]
    result = task_counts.count_tasks(
        tasks, filt(status=profiles.STATUS_ALL), now=now, window=WINDOW
    )
    # Not a 24-hour window: 00:30 tomorrow is inside 24h and is still not "today",
    # while 01:00 this morning is in the past and is.
    assert result["due_today"] == 2


def test_due_today_reads_a_foreign_offset_in_the_callers_zone():
    tz = ZoneInfo("America/Los_Angeles")
    now = datetime(2026, 5, 10, 18, 0, tzinfo=tz)
    # 2026-05-11T02:00 UTC is 19:00 on the 10th in Los Angeles: today, locally.
    task = make_task("UTC stored", datetime(2026, 5, 11, 2, 0, tzinfo=UTC))
    result = task_counts.count_tasks(
        [task], filt(status=profiles.STATUS_ALL), now=now, window=WINDOW
    )
    assert result["due_today"] == 1


# ── the next task up ─────────────────────────────────────────────────────────


def test_next_up_is_the_earliest_in_scope(tasks):
    result = count(tasks, status=profiles.STATUS_ALL)
    assert result["next_task_name"] == "Gutters"
    assert result["next_due"] == tasks[0]["next_due"]
    assert result["next_task_id"] == tasks[0]["id"]


def test_next_up_points_at_the_scope_not_the_state():
    # Nothing is overdue, so an overdue profile reads 0 — and still names what is
    # coming, which is what lets a badge say "none overdue, next in 2 days".
    upcoming = make_task("Smoke alarm", NOW + timedelta(days=2))
    result = count([upcoming], status=profiles.STATUS_OVERDUE)
    assert result["state"] == 0
    assert result["next_task_name"] == "Smoke alarm"


def test_most_overdue_days(tasks):
    assert count(tasks, status=profiles.STATUS_OVERDUE)["most_overdue_days"] == 10.0


def test_most_overdue_days_rounds_to_one_place():
    task = make_task("Gutters", NOW - timedelta(days=10, minutes=57))
    assert count([task], status=profiles.STATUS_ALL)["most_overdue_days"] == 10.0
    task["next_due"] = (NOW - timedelta(days=10, hours=4)).isoformat()
    assert count([task], status=profiles.STATUS_ALL)["most_overdue_days"] == 10.2


def test_most_overdue_days_is_none_when_nothing_is_overdue():
    upcoming = make_task("Smoke alarm", NOW + timedelta(days=2))
    assert count([upcoming], status=profiles.STATUS_ALL)["most_overdue_days"] is None


# ── degenerate inputs ────────────────────────────────────────────────────────


def test_no_tasks_at_all():
    result = count([], status=profiles.STATUS_ALL)
    assert result["state"] == result["total"] == result["overdue"] == 0
    assert result["due_soon"] == result["due_today"] == 0
    assert result["next_due"] is None
    assert result["next_task_name"] is None
    assert result["next_task_id"] is None
    assert result["most_overdue_days"] is None


def test_dormant_and_disabled_tasks_are_out_of_scope():
    tasks = [
        make_task("Someday", None),
        make_task("Off", NOW - timedelta(days=5), enabled=False),
    ]
    result = count(tasks, status=profiles.STATUS_ALL)
    assert result["total"] == 0
    assert result["overdue"] == 0
    assert result["next_task_name"] is None


# ── the published contract ───────────────────────────────────────────────────


def test_result_keys_are_exactly_the_contract(tasks):
    # These names are entity attributes users template against. A rename or a new key
    # must be a deliberate edit here, and to api_surface.py and the user guide.
    assert set(count(tasks)) == set(task_counts.COUNT_KEYS)
    assert set(task_counts.COUNT_KEYS) == {
        "state",
        "total",
        "overdue",
        "due_soon",
        "due_today",
        "next_due",
        "next_task_name",
        "next_task_id",
        "most_overdue_days",
    }
