"""Active season through the real service API, against a running Home Assistant.

``services.yaml`` describing a field is not the same as the service accepting it:
the call is validated against the voluptuous schema in ``__init__.py``, which
refuses anything it doesn't declare. `active_season` shipped documented and
undeclared, so every automation that tried to set a season got "extra keys not
allowed" — a gap no unit test can see, because the schema only exists once Home
Assistant registers the service.

The season maths itself is unit-tested (`tests/unit/test_recurrence_season.py`);
what belongs here is the contract an automation actually touches.
"""

import time

from conftest import call_service


def _add(ha, payload):
    resp = call_service(ha, "home_keeper", "add_task", payload, return_response=True)
    return resp.get("service_response", resp)["task_id"]


def _task(ha, task_id):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    tasks = resp.get("service_response", resp)["tasks"]
    return next(t for t in tasks if t["id"] == task_id)


def test_add_task_accepts_a_list_of_season_windows(ha):
    task_id = _add(
        ha,
        {
            "name": "Season list probe",
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "months",
            "active_season": [
                {"start": "03-01", "end": "05-31"},
                {"start": "09-01", "end": "10-31"},
            ],
        },
    )
    try:
        task = _task(ha, task_id)
        assert task["active_season"] == [
            {"start": "03-01", "end": "05-31"},
            {"start": "09-01", "end": "10-31"},
        ]
        # The season is what decides the date, so it has to land inside a window.
        assert task["next_due"][5:7] in {"03", "04", "05", "09", "10"}
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})


def test_add_task_accepts_a_single_window_object(ha):
    """One window may be passed as one object — `services.yaml` promises that."""
    task_id = _add(
        ha,
        {
            "name": "Season object probe",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
            "active_season": {"start": "04-01", "end": "09-30"},
        },
    )
    try:
        assert _task(ha, task_id)["active_season"] == [
            {"start": "04-01", "end": "09-30"}
        ]
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})


def test_update_task_replaces_and_clears_the_season(ha):
    task_id = _add(
        ha,
        {
            "name": "Season update probe",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
            "active_season": [{"start": "04-01", "end": "09-30"}],
        },
    )
    try:
        call_service(
            ha,
            "home_keeper",
            "update_task",
            {
                "task_id": task_id,
                "active_season": [
                    {"start": "04-01", "end": "09-30"},
                    {"start": "11-01", "end": "12-31"},
                ],
            },
        )
        time.sleep(1)
        assert len(_task(ha, task_id)["active_season"]) == 2

        # Null clears it: the task goes back to being due all year round.
        call_service(
            ha,
            "home_keeper",
            "update_task",
            {"task_id": task_id, "active_season": None},
        )
        time.sleep(1)
        assert _task(ha, task_id)["active_season"] is None
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})
