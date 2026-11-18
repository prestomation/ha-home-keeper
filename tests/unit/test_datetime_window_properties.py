"""No datetime that a write accepts can make an entity, a refresh or an import raise.

The strategy draws any wall time from year 1 to year 9999 on any UTC offset from
-23:59 to +23:59. Each property feeds that value to a write. The write either
refuses it with ``TaskValidationError``, or each reader of the stored task runs to
the end. The readers are the shipped entity code (to-do list, calendar, next-due
sensor), the refresh steps (the one-off purge, the usage backstop, the counts) and
the import planner.

Mutants that these kill: drop the ``in_window`` call from ``models.check_datetime``,
and any edge of the window above year 9999 minus the longest interval.

Run just these: ``pytest tests/unit -m property``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import hk_models as models
import hk_recurrence as recurrence
import hk_sensor_tasks as sensor_tasks
import hk_task_counts as task_counts
import hk_transfer as transfer
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from test_calendar import _entity as calendar_entity
from test_calendar import cal
from test_count_sensor import sensor
from test_todo import _entity as todo_entity

pytestmark = pytest.mark.property

NOW = datetime(2026, 5, 10, 12, tzinfo=UTC)
#: The zones that the readers use: Home Assistant's zone can be any of these.
ZONES = [timezone(timedelta(hours=-12)), UTC, timezone(timedelta(hours=14))]


def _offsets() -> st.SearchStrategy[timezone]:
    return st.integers(min_value=-(24 * 60 - 1), max_value=24 * 60 - 1).map(
        lambda minutes: timezone(timedelta(minutes=minutes))
    )


def _any_moment() -> st.SearchStrategy[datetime]:
    """Any wall time on any offset, weighted to the edges where overflow lives."""
    edges = st.sampled_from(
        [
            datetime(1, 1, 1),
            datetime(1899, 12, 31, 23, 59, 59),
            datetime(1900, 1, 1),
            datetime(2199, 12, 31, 23, 59, 59),
            datetime(2200, 1, 1),
            datetime(9999, 12, 31, 23, 59, 59),
        ]
    )
    wall = st.one_of(edges, st.datetimes(min_value=datetime(1, 1, 1)))
    return st.builds(lambda w, tz: w.replace(tzinfo=tz), wall, _offsets())


def _read_everything(task: dict) -> None:
    """Run each reader of *task*. A reader that raises fails the property."""
    for zone in ZONES:
        now = NOW.astimezone(zone)
        task_counts.count_tasks([task], {"status": "all"}, now=now)
        recurrence.is_overdue(task, now=now)
        recurrence.one_off_expired(task, 30, now=now)
        cfg = sensor_tasks.sensor_config(task)
        if cfg is not None:
            sensor_tasks.backstop_due(task, cfg, tz=zone)
    todo, _store, _calls = todo_entity(task)
    list(todo.todo_items)
    calendar = calendar_entity({task["id"]: task})
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cal.dt_util, "now", lambda: NOW)
        _ = calendar.event
        calendar._collect_events(NOW - timedelta(days=400), NOW + timedelta(days=400))
    entity = object.__new__(sensor.HomeKeeperNextDueSensor)
    entity._task = task
    value = entity.native_value
    if value is not None:
        # Home Assistant writes a timestamp state in UTC.
        value.astimezone(UTC)


@settings(max_examples=300)
@given(moment=_any_moment())
def test_an_accepted_one_off_due_is_safe_for_every_reader(moment):
    try:
        task = models.build_task(
            {"name": "x", "recurrence_type": "one-off", "due": moment.isoformat()},
            now=NOW,
        )
    except models.TaskValidationError:
        assert not recurrence.in_window(moment)
        return
    assert recurrence.in_window(moment)
    _read_everything(task)
    done = recurrence.apply_completion(task, moment, now=NOW)
    _read_everything(done)


@settings(max_examples=300)
@given(moment=_any_moment())
def test_an_accepted_usage_seed_is_safe_for_every_reader(moment):
    data = {
        "name": "x",
        "recurrence_type": "sensor",
        "sensor": {
            "entity_id": "sensor.a",
            "mode": "usage",
            "target": 10,
            "also_every": {"interval": 10_000, "unit": "months"},
        },
        "last_completed": moment.isoformat(),
    }
    try:
        task = models.build_task(data, now=NOW)
    except models.TaskValidationError:
        assert not recurrence.in_window(moment)
        return
    _read_everything(task)


@settings(max_examples=300)
@given(moment=_any_moment())
def test_a_stored_value_after_the_clamp_is_safe_for_every_reader(moment):
    task = models.build_task({"name": "x", "interval": 1, "unit": "days"}, now=NOW)
    raw = moment.isoformat()
    task.update(next_due=raw, last_completed=raw, completions=[{"ts": raw}])
    models.clamp_task_datetimes(task)
    assert recurrence.in_window(datetime.fromisoformat(task["next_due"]))
    _read_everything(task)


@settings(max_examples=200)
@given(moment=_any_moment())
def test_an_import_with_any_history_date_does_not_raise(moment):
    plan = transfer.plan_import(
        {
            "home_keeper": {"format": 1},
            "tasks": [
                {
                    "name": "T",
                    "interval": 1,
                    "unit": "days",
                    "history": [{"completed_at": moment.isoformat()}],
                },
                {"name": "U", "recurrence_type": "one-off", "due": moment.isoformat()},
            ],
        },
        tasks={},
        assets={},
        now=NOW,
    )
    assert plan.ok is recurrence.in_window(moment)
    for record in plan.records:
        _read_everything(record.payload)


@settings(max_examples=300)
@given(moment=_any_moment())
def test_the_clamp_picks_the_edge_on_the_side_of_the_instant(moment):
    task = models.build_task({"name": "x", "interval": 1, "unit": "days"}, now=NOW)
    task["next_due"] = moment.isoformat()
    models.clamp_task_datetimes(task)
    stored = datetime.fromisoformat(task["next_due"])
    if recurrence.in_window(moment):
        assert stored == moment
    elif moment >= recurrence.DATETIME_MAX:
        assert stored == recurrence.DATETIME_MAX - timedelta(seconds=1)
    else:
        assert stored == recurrence.DATETIME_MIN


@settings(max_examples=200)
@given(moment=_any_moment())
def test_an_import_with_any_moved_date_does_not_raise(moment):
    plan = transfer.plan_import(
        {
            "home_keeper": {"format": 1},
            "tasks": [
                {
                    "name": "V",
                    "rrule": "FREQ=WEEKLY;BYDAY=TU",
                    "anchor": "2026-05-05T07:00:00+00:00",
                    "moved_occurrences": [
                        {"from": "2026-05-12T07:00:00+00:00", "to": moment.isoformat()}
                    ],
                }
            ],
        },
        tasks={},
        assets={},
        now=NOW,
    )
    assert plan.ok is recurrence.in_window(moment)
    for record in plan.records:
        _read_everything(record.payload)
