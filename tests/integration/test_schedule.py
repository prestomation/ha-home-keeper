"""Schedule state through the real services (B07-1, B07-2, B07-5, B11-2).

Each test drives Home Assistant over HTTP and reads the stored task back, so the
assertions cover the service schemas, the store chokepoint and the recurrence math
together. The container runs on America/New_York (ha_config/configuration.yaml);
every time here is built in that zone from the container's real clock.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from conftest import call_service

TZ = ZoneInfo("America/New_York")
CALENDAR = "calendar.home_keeper_upcoming_tasks"


def _response(resp):
    return resp.get("service_response", resp)


def _task(ha, task_id):
    tasks = _response(
        call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    )["tasks"]
    return next(t for t in tasks if t["id"] == task_id)


def _instant(value):
    return datetime.fromisoformat(value)


def _add(ha, name, **fields):
    resp = call_service(
        ha, "home_keeper", "add_task", {"name": name, **fields}, return_response=True
    )
    return _response(resp)["task_id"]


def _delete(ha, task_id):
    call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})


def _weekly_fixed(ha, name):
    """A weekly fixed task whose next occurrence is 2 days from now at 09:00."""
    anchor = (datetime.now(TZ) + timedelta(days=2)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    task_id = _add(
        ha,
        name,
        recurrence_type="fixed",
        freq="WEEKLY",
        interval=1,
        anchor=anchor.isoformat(),
    )
    assert _instant(_task(ha, task_id)["next_due"]) == anchor
    return task_id, anchor


def test_b07_5_snooze_then_complete_moves_past_the_snoozed_occurrence(ha):
    task_id, anchor = _weekly_fixed(ha, "Schedule snooze probe")
    try:
        snoozed = anchor + timedelta(days=3, hours=2)
        call_service(
            ha,
            "home_keeper",
            "snooze_task",
            {"task_id": task_id, "until": snoozed.isoformat()},
        )
        task = _task(ha, task_id)
        assert _instant(task["next_due"]) == snoozed
        assert _instant(task["deferred_from"]) == anchor

        call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
        # The completion clears the occurrence that the snooze moved. The next one
        # is a week after it, not the occurrence the user just did.
        assert _instant(_task(ha, task_id)["next_due"]) == anchor + timedelta(days=7)
    finally:
        _delete(ha, task_id)


def test_b07_5_due_today_then_complete_moves_past_the_moved_occurrence(ha):
    task_id, anchor = _weekly_fixed(ha, "Schedule due today probe")
    try:
        call_service(ha, "home_keeper", "set_due_today", {"task_id": task_id})
        task = _task(ha, task_id)
        assert _instant(task["next_due"]) < anchor
        assert _instant(task["deferred_from"]) == anchor

        call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
        assert _instant(_task(ha, task_id)["next_due"]) == anchor + timedelta(days=7)
    finally:
        _delete(ha, task_id)


def test_b07_1_undo_of_a_fixed_completion_puts_the_due_date_back(ha):
    task_id, anchor = _weekly_fixed(ha, "Schedule undo probe")
    try:
        call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
        task = _task(ha, task_id)
        assert _instant(task["next_due"]) == anchor + timedelta(days=7)
        (entry,) = task["completions"]
        assert _instant(entry["prior_due"]) == anchor

        call_service(
            ha,
            "home_keeper",
            "delete_completion",
            {"task_id": task_id, "ts": entry["ts"]},
        )
        task = _task(ha, task_id)
        assert task["completions"] == []
        assert _instant(task["next_due"]) == anchor
    finally:
        _delete(ha, task_id)


def _floating_done_twice_then_snoozed(ha, name):
    now = datetime.now(TZ).replace(microsecond=0)
    older = (now - timedelta(days=40)).isoformat()
    newer = (now - timedelta(days=5)).isoformat()
    task_id = _add(
        ha,
        name,
        recurrence_type="floating",
        interval=30,
        unit="days",
        last_completed=older,
    )
    call_service(
        ha,
        "home_keeper",
        "complete_task",
        {"task_id": task_id, "completed_at": newer},
    )
    snoozed = (now + timedelta(days=60)).replace(second=0)
    call_service(
        ha,
        "home_keeper",
        "snooze_task",
        {"task_id": task_id, "until": snoozed.isoformat()},
    )
    task = _task(ha, task_id)
    assert _instant(task["next_due"]) == snoozed
    assert [_instant(e["ts"]) for e in task["completions"]] == [
        _instant(older),
        _instant(newer),
    ]
    return task_id, task, older, newer


def test_b07_2_deleting_an_older_completion_keeps_next_due(ha):
    task_id, before, _older, newer = _floating_done_twice_then_snoozed(
        ha, "Schedule delete older probe"
    )
    try:
        call_service(
            ha,
            "home_keeper",
            "delete_completion",
            {"task_id": task_id, "ts": before["completions"][0]["ts"]},
        )
        task = _task(ha, task_id)
        assert [_instant(e["ts"]) for e in task["completions"]] == [_instant(newer)]
        assert task["last_completed"] == before["last_completed"]
        # The log edit is below the latest completion, so the snooze stays.
        assert task["next_due"] == before["next_due"]
    finally:
        _delete(ha, task_id)


def test_b07_2_moving_an_older_completion_keeps_next_due(ha):
    task_id, before, older, newer = _floating_done_twice_then_snoozed(
        ha, "Schedule move older probe"
    )
    try:
        moved_to = (_instant(older) + timedelta(days=1)).isoformat()
        call_service(
            ha,
            "home_keeper",
            "move_completion",
            {
                "task_id": task_id,
                "old_ts": before["completions"][0]["ts"],
                "new_completed_at": moved_to,
            },
        )
        task = _task(ha, task_id)
        assert sorted(_instant(e["ts"]) for e in task["completions"]) == [
            _instant(moved_to),
            _instant(newer),
        ]
        assert task["last_completed"] == before["last_completed"]
        assert task["next_due"] == before["next_due"]
    finally:
        _delete(ha, task_id)


def test_b11_2_calendar_follows_a_snoozed_fixed_task(ha):
    name = "Schedule calendar snooze probe"
    anchor = (datetime.now(TZ) + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    task_id = _add(
        ha,
        name,
        recurrence_type="fixed",
        freq="DAILY",
        interval=1,
        anchor=anchor.isoformat(),
    )
    try:
        snoozed = anchor + timedelta(days=3, hours=2)
        call_service(
            ha,
            "home_keeper",
            "snooze_task",
            {"task_id": task_id, "until": snoozed.isoformat()},
        )
        window_end = anchor + timedelta(days=5, hours=12)
        resp = call_service(
            ha,
            "calendar",
            "get_events",
            {
                "entity_id": CALENDAR,
                "start_date_time": datetime.now(TZ).isoformat(),
                "end_date_time": window_end.isoformat(),
            },
            return_response=True,
        )
        events = _response(resp)[CALENDAR]["events"]
        starts = sorted(_instant(e["start"]) for e in events if e["summary"] == name)
        # The occurrences that the snooze moved are gone. The snoozed date is on
        # the calendar, and the grid comes back after it.
        assert starts == [
            snoozed,
            anchor + timedelta(days=4),
            anchor + timedelta(days=5),
        ]
    finally:
        _delete(ha, task_id)
