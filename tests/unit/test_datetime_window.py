"""Every datetime that a task stores stays inside 1 window, and date math stays safe.

The window is ``recurrence.DATETIME_MIN`` to ``recurrence.DATETIME_MAX`` in UTC. A
value outside it is refused when a caller writes it, and is moved to the nearest edge
when the store loads it. The date math that reads a stored value also catches
``OverflowError`` and ``ValueError``, so 1 bad value cannot stop a refresh.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import hk_models as models
import hk_recurrence as recurrence
import hk_sensor_tasks as sensor_tasks
import hk_task_counts as task_counts
import hk_transfer as transfer
import pytest

NOW = datetime(2026, 5, 10, 12, tzinfo=UTC)

#: Each value is outside the window. The first 2 also overflow ``datetime`` when
#: Python converts them to UTC.
OUTSIDE = [
    "9999-12-31T23:59:59-12:00",
    "0001-01-01T00:00:00+14:00",
    "9999-12-15T00:00:00+00:00",
    "2200-01-01T00:00:00+00:00",
    "2199-12-31T23:00:00-02:00",
    "1899-12-31T23:59:59+00:00",
    "1900-01-01T01:00:00+02:00",
]
INSIDE = [
    "1900-01-01T00:00:00+00:00",
    "1900-01-01T05:00:00-01:00",
    "2199-12-31T23:59:59+00:00",
    "2026-05-10T12:00:00+14:00",
]


# ── the window ───────────────────────────────────────────────────────────────
def test_window_edges_are_1900_and_2200_utc():
    assert datetime(1900, 1, 1, tzinfo=UTC) == recurrence.DATETIME_MIN
    assert datetime(2200, 1, 1, tzinfo=UTC) == recurrence.DATETIME_MAX


@pytest.mark.parametrize("value", INSIDE)
def test_in_window_accepts_a_value_inside(value):
    assert recurrence.in_window(datetime.fromisoformat(value)) is True


@pytest.mark.parametrize("value", OUTSIDE)
def test_in_window_refuses_a_value_outside(value):
    assert recurrence.in_window(datetime.fromisoformat(value)) is False


@pytest.mark.parametrize("value", OUTSIDE)
def test_check_datetime_names_the_field(value):
    with pytest.raises(models.TaskValidationError, match="due must be between"):
        models.check_datetime(datetime.fromisoformat(value), "due")


@pytest.mark.parametrize("value", INSIDE)
def test_check_datetime_returns_a_value_inside(value):
    parsed = datetime.fromisoformat(value)
    assert models.check_datetime(parsed, "due") is parsed


# ── build_task and merge_update ──────────────────────────────────────────────
@pytest.mark.parametrize("value", OUTSIDE)
def test_a_one_off_due_outside_the_window_is_refused(value):
    with pytest.raises(models.TaskValidationError, match="due must be between"):
        models.build_task(
            {"name": "x", "recurrence_type": "one-off", "due": value}, now=NOW
        )


@pytest.mark.parametrize("value", INSIDE)
def test_a_one_off_due_inside_the_window_is_stored(value):
    task = models.build_task(
        {"name": "x", "recurrence_type": "one-off", "due": value}, now=NOW
    )
    assert task["due"] == datetime.fromisoformat(value).isoformat()


@pytest.mark.parametrize("value", OUTSIDE)
def test_a_fixed_anchor_outside_the_window_is_refused(value):
    with pytest.raises(models.TaskValidationError, match="anchor must be between"):
        models.build_task(
            {
                "name": "x",
                "recurrence_type": "fixed",
                "freq": "weekly",
                "interval": 1,
                "anchor": value,
            },
            now=NOW,
        )


def _usage(**extra):
    return {
        "name": "x",
        "recurrence_type": "sensor",
        "sensor": {
            "entity_id": "sensor.a",
            "mode": "usage",
            "target": 10,
            "also_every": {"interval": 1, "unit": "months"},
        },
        **extra,
    }


@pytest.mark.parametrize("value", OUTSIDE)
def test_a_last_completed_seed_outside_the_window_is_refused(value):
    with pytest.raises(
        models.TaskValidationError, match="last_completed must be between"
    ):
        models.build_task(_usage(last_completed=value), now=NOW)


def test_an_update_with_a_due_outside_the_window_is_refused():
    task = models.build_task(
        {"name": "x", "recurrence_type": "one-off", "due": "2026-06-01T00:00:00+00:00"},
        now=NOW,
    )
    with pytest.raises(models.TaskValidationError, match="due must be between"):
        models.merge_update(task, {"due": "9999-12-31T23:59:59-12:00"}, now=NOW)


# ── date math on a stored value ──────────────────────────────────────────────
def test_backstop_due_is_none_when_the_interval_overflows():
    task = models.build_task(_usage(), now=NOW)
    task["completions"] = [{"ts": "9999-12-15T00:00:00+00:00"}]
    task["last_completed"] = "9999-12-15T00:00:00+00:00"
    assert sensor_tasks.backstop_due(task, sensor_tasks.sensor_config(task)) is None


def test_backstop_due_still_counts_from_a_value_inside_the_window():
    task = models.build_task(_usage(), now=NOW)
    task["completions"] = [{"ts": "2199-12-15T00:00:00+00:00"}]
    task["last_completed"] = "2199-12-15T00:00:00+00:00"
    due = sensor_tasks.backstop_due(task, sensor_tasks.sensor_config(task))
    assert due == datetime(2200, 1, 15, tzinfo=UTC)


def _completed_one_off(last_completed: str) -> dict:
    task = models.build_task(
        {"name": "x", "recurrence_type": "one-off", "due": "2026-06-01T00:00:00+00:00"},
        now=NOW,
    )
    task["next_due"] = None
    task["last_completed"] = last_completed
    task["completions"] = [{"ts": last_completed}]
    return task


def test_one_off_expired_is_false_when_the_retention_overflows():
    task = _completed_one_off("9999-12-31T00:00:00+00:00")
    assert recurrence.one_off_expired(task, 30, now=NOW) is False


def test_one_off_expired_is_still_true_after_the_retention():
    task = _completed_one_off("2026-01-01T00:00:00+00:00")
    assert recurrence.one_off_expired(task, 30, now=NOW) is True


@pytest.mark.parametrize("value", OUTSIDE[:2])
def test_count_tasks_does_not_raise_on_a_due_that_overflows(value):
    task = models.build_task({"name": "x", "interval": 1, "unit": "days"}, now=NOW)
    task["next_due"] = value
    counts = task_counts.count_tasks([task], {"status": "all"}, now=NOW)
    assert counts["total"] == 1
    assert counts["due_today"] == 0


# ── the clamp on load ────────────────────────────────────────────────────────
def test_clamp_moves_each_stored_value_to_the_nearest_edge():
    task = _completed_one_off("9999-12-31T00:00:00+00:00")
    task["next_due"] = "0001-01-01T00:00:00+14:00"
    task["skips"] = [{"ts": "9999-12-31T23:59:59-12:00"}]
    task["moved_occurrences"] = [
        {"from": "2026-06-01T00:00:00+00:00", "to": "9999-01-01T00:00:00+00:00"}
    ]
    changed = models.clamp_task_datetimes(task, tz=UTC)
    top = (recurrence.DATETIME_MAX - timedelta(seconds=1)).isoformat()
    assert task["last_completed"] == top
    assert task["completions"] == [{"ts": top}]
    assert task["skips"] == [{"ts": top}]
    assert task["next_due"] == recurrence.DATETIME_MIN.isoformat()
    assert task["moved_occurrences"][0] == {
        "from": "2026-06-01T00:00:00+00:00",
        "to": top,
    }
    assert sorted(changed) == [
        "completions",
        "last_completed",
        "moved_occurrences",
        "next_due",
        "skips",
    ]


def test_clamp_keeps_a_task_inside_the_window_as_it_is():
    task = _completed_one_off("2026-01-01T00:00:00-05:00")
    before = dict(task)
    assert models.clamp_task_datetimes(task, tz=UTC) == []
    assert task == before


def test_clamp_keeps_a_value_that_is_not_a_date():
    task = _completed_one_off("2026-01-01T00:00:00+00:00")
    task["next_due"] = "soon"
    assert models.clamp_task_datetimes(task, tz=UTC) == []
    assert task["next_due"] == "soon"


# ── import ───────────────────────────────────────────────────────────────────
def _plan(document):
    return transfer.plan_import(document, tasks={}, assets={}, now=NOW)


@pytest.mark.parametrize("value", OUTSIDE)
def test_an_import_with_history_outside_the_window_reports_a_problem(value):
    plan = _plan(
        {
            "home_keeper": {"format": 1},
            "tasks": [
                {
                    "name": "T",
                    "interval": 1,
                    "unit": "days",
                    "history": [{"completed_at": value}],
                }
            ],
        }
    )
    assert not plan.ok
    problem = plan.problems[0]
    assert problem.path == "tasks[0].history[0].completed_at"
    assert problem.message == f'"{value}" must be between 1900 and 2200 UTC.'


@pytest.mark.parametrize("value", OUTSIDE)
def test_an_import_with_a_due_outside_the_window_reports_a_problem(value):
    plan = _plan(
        {
            "home_keeper": {"format": 1},
            "tasks": [{"name": "T", "recurrence_type": "one-off", "due": value}],
        }
    )
    messages = [p.message for p in plan.problems if p.severity == "error"]
    assert any("due must be between" in message for message in messages), messages
    assert len(plan.records) == 0


def test_an_import_that_overflows_in_the_replay_reports_a_problem(monkeypatch):
    def _overflow(*args, **kwargs):
        raise OverflowError("date value out of range")

    monkeypatch.setattr(transfer, "apply_history", _overflow)
    plan = _plan(
        {
            "home_keeper": {"format": 1},
            "tasks": [{"name": "T", "interval": 1, "unit": "days"}],
        }
    )
    messages = [p.message for p in plan.problems if p.severity == "error"]
    assert messages == ["date value out of range"]
    assert len(plan.records) == 0


def test_check_datetime_refuses_a_value_far_ahead_in_a_local_zone():
    # 2199-12-31 23:30 at UTC-1 is 2200-01-01 00:30 in UTC.
    value = datetime(2199, 12, 31, 23, 30, tzinfo=timezone(timedelta(hours=-1)))
    with pytest.raises(models.TaskValidationError):
        models.check_datetime(value, "due")


# ── edges of the helpers ─────────────────────────────────────────────────────
@pytest.mark.parametrize("value", [None, "", 20260510, NOW, "soon", "2026-05-10T12:00"])
def test_stored_moment_is_none_for_a_value_it_cannot_use(value):
    assert recurrence.stored_moment(value) is None


def test_stored_moment_reads_an_aware_value_inside_the_window():
    assert recurrence.stored_moment(NOW.isoformat()) == NOW


def test_iso_passes_an_aware_datetime_through():
    assert transfer._iso(NOW, tz=UTC) is NOW


def test_iso_names_the_date_in_its_error():
    with pytest.raises(models.TaskValidationError, match=r"^date must be between"):
        transfer._iso("9999-01-01", tz=UTC)


def test_a_naive_seed_gets_the_zone_of_now():
    east = datetime(2026, 5, 10, 12, tzinfo=timezone(timedelta(hours=5)))
    task = models.build_task(
        {
            "name": "x",
            "interval": 1,
            "unit": "days",
            "last_completed": "2026-05-01T08:00",
        },
        now=east,
    )
    assert task["last_completed"] == "2026-05-01T08:00:00+05:00"


def test_clamp_moves_a_value_on_the_top_edge_to_the_last_second():
    task = _completed_one_off("2200-01-01T00:00:00+00:00")
    models.clamp_task_datetimes(task, tz=UTC)
    assert (
        task["last_completed"]
        == (recurrence.DATETIME_MAX - timedelta(seconds=1)).isoformat()
    )


def test_clamp_goes_on_past_a_list_or_an_entry_that_is_not_valid():
    task = _completed_one_off("2026-01-01T00:00:00+00:00")
    task["completions"] = "junk"
    task["skips"] = ["junk", {"ts": "9999-01-01T00:00:00+00:00"}]
    assert models.clamp_task_datetimes(task, tz=UTC) == ["skips"]
    assert (
        task["skips"][1]["ts"]
        == (recurrence.DATETIME_MAX - timedelta(seconds=1)).isoformat()
    )


def test_an_import_reports_each_history_date_outside_the_window():
    plan = _plan(
        {
            "home_keeper": {"format": 1},
            "tasks": [
                {
                    "name": "T",
                    "interval": 1,
                    "unit": "days",
                    "history": [
                        {"completed_at": "9999-01-01"},
                        {"completed_at": "1800-01-01"},
                    ],
                }
            ],
        }
    )
    assert [(p.section, p.index, p.path) for p in plan.problems] == [
        ("tasks", 0, "tasks[0].history[0].completed_at"),
        ("tasks", 0, "tasks[0].history[1].completed_at"),
    ]


def test_an_import_reads_a_bare_history_date_in_utc_for_the_window(monkeypatch):
    # In a system zone of UTC+14, a naive read of 1900-01-01 00:00 is in 1899 UTC.
    import time

    monkeypatch.setenv("TZ", "Etc/GMT-14")
    time.tzset()
    try:
        plan = _plan(
            {
                "home_keeper": {"format": 1},
                "tasks": [
                    {
                        "name": "T",
                        "interval": 1,
                        "unit": "days",
                        "history": [{"completed_at": "1900-01-01T00:00:00"}],
                    }
                ],
            }
        )
    finally:
        monkeypatch.undo()
        time.tzset()
    assert [p.message for p in plan.problems if "between" in p.message] == []


# ── moved dates ──────────────────────────────────────────────────────────────
def _moved(to: str) -> dict:
    return {
        "name": "Bins",
        "rrule": "FREQ=WEEKLY;BYDAY=TU",
        "anchor": "2026-05-05T07:00:00+00:00",
        "moved_occurrences": [{"from": "2026-05-12T07:00:00+00:00", "to": to}],
    }


@pytest.mark.parametrize("value", OUTSIDE)
def test_a_moved_date_outside_the_window_is_refused(value):
    with pytest.raises(
        models.TaskValidationError, match=r"moved_occurrences\[0\]\.to must be between"
    ):
        models.build_task(_moved(value), now=NOW)


def test_a_moved_date_inside_the_window_is_stored():
    task = models.build_task(_moved("2026-05-13T07:00:00+00:00"), now=NOW)
    assert task["moved_occurrences"][0]["to"] == "2026-05-13T07:00:00+00:00"


@pytest.mark.parametrize("value", OUTSIDE)
def test_an_import_with_a_moved_date_outside_the_window_reports_a_problem(value):
    plan = _plan({"home_keeper": {"format": 1}, "tasks": [_moved(value)]})
    messages = [p.message for p in plan.problems if p.severity == "error"]
    assert any("moved_occurrences[0].to must be between" in m for m in messages), (
        messages
    )
    assert len(plan.records) == 0


@pytest.mark.parametrize(
    ("value", "edge"),
    [
        ("2199-12-31T23:00:00-02:00", "top"),
        ("2200-01-01T01:00:00+02:00", "inside"),
        ("1900-01-01T01:00:00+02:00", "bottom"),
        ("1899-12-31T23:00:00-02:00", "inside"),
        ("9999-12-31T23:59:59-12:00", "top"),
        ("0001-01-01T00:00:00+14:00", "bottom"),
    ],
)
def test_clamp_picks_the_edge_by_the_utc_instant(value, edge):
    task = _completed_one_off(value)
    models.clamp_task_datetimes(task, tz=UTC)
    expected = {
        "top": (recurrence.DATETIME_MAX - timedelta(seconds=1)).isoformat(),
        "bottom": recurrence.DATETIME_MIN.isoformat(),
        "inside": value,
    }[edge]
    assert task["last_completed"] == expected


def test_moved_dates_take_an_empty_value_and_a_full_list():
    assert models.normalize_moved_occurrences("") == []
    start = datetime(2026, 5, 12, 7, tzinfo=UTC)
    full = [
        {
            "from": (start + timedelta(weeks=n)).isoformat(),
            "to": (start + timedelta(weeks=n, days=1)).isoformat(),
        }
        for n in range(models.MAX_MOVED_OCCURRENCES)
    ]
    assert len(models.normalize_moved_occurrences(full)) == len(full)


def test_moved_dates_that_are_not_a_list_are_refused():
    with pytest.raises(
        models.TaskValidationError, match=r"^moved_occurrences must be a list$"
    ):
        models.normalize_moved_occurrences({"from": "x"})


# ── a naive stored value ─────────────────────────────────────────────────────
WEST = timezone(timedelta(hours=-4))


def test_clamp_gives_a_naive_stored_value_the_zone_it_is_passed():
    # Older builds stored a part date as is, which gave a naive due date.
    task = _completed_one_off("2026-01-01T00:00:00")
    task["next_due"] = "2026-07-01T00:00:00"
    changed = models.clamp_task_datetimes(task, tz=WEST)
    assert task["last_completed"] == "2026-01-01T00:00:00-04:00"
    assert task["next_due"] == "2026-07-01T00:00:00-04:00"
    assert task["completions"] == [{"ts": "2026-01-01T00:00:00-04:00"}]
    assert sorted(changed) == ["completions", "last_completed", "next_due"]


def test_clamp_tests_a_naive_stored_value_in_its_zone_against_the_window():
    task = _completed_one_off("9999-12-31T00:00:00")
    task["next_due"] = "0001-01-01T00:00:00"
    models.clamp_task_datetimes(task, tz=WEST)
    assert (
        task["last_completed"]
        == (recurrence.DATETIME_MAX - timedelta(seconds=1)).isoformat()
    )
    assert task["next_due"] == recurrence.DATETIME_MIN.isoformat()
    # The readers compare it with an aware now, which a naive value cannot do.
    assert recurrence.is_overdue(task, now=NOW) is True
