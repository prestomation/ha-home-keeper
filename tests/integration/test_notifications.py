"""Integration tests for actionable notifications against a real HA container.

There's no mobile-app companion in the test container, so the notify *delivery* is
a no-op (best-effort, swallowed) — these cover the parts that don't need a phone:
the ``home_keeper.notify`` service resolving a profile and reporting what's due, and
the ``mobile_app_notification_action`` listener routing a tapped action back into the
store (completing the task, with the notification origin echoed).
"""

import time

from conftest import HA_URL, call_service


def _fire_action(ha, action):
    r = ha.post(
        f"{HA_URL}/api/events/mobile_app_notification_action", json={"action": action}
    )
    r.raise_for_status()


def _get_task(ha, task_id):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    body = resp.get("service_response", resp)
    return next((t for t in body["tasks"] if t["id"] == task_id), None)


def test_notify_service_and_action_completes(ha, ha_token):
    # A brand-new floating task is due-now (overdue) immediately.
    resp = call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Notify integration task",
            "recurrence_type": "floating",
            "interval": 7,
            "unit": "days",
        },
        return_response=True,
    )
    task_id = resp.get("service_response", resp)["task_id"]

    # A profile (explicit id so the test can reference it) that matches overdue tasks.
    call_service(
        ha,
        "home_keeper",
        "set_options",
        {
            "notify_profiles": [
                {
                    "id": "testprofile",
                    "name": "Test",
                    "targets": [],
                    "filter": {"status": "overdue"},
                    "actions": ["complete", "snooze"],
                    "style": "walk",
                }
            ]
        },
    )

    # The notify service resolves the profile and reports what's due.
    resp = call_service(
        ha, "home_keeper", "notify", {"profile": "testprofile"}, return_response=True
    )
    body = resp.get("service_response", resp)
    assert body["matched"] >= 1
    assert body["sent"] == task_id

    # Tapping "Mark done" on the notification completes the task via the listener.
    _fire_action(ha, f"home_keeper::complete::{task_id}::testprofile")

    deadline = time.monotonic() + 20
    completed = False
    while time.monotonic() < deadline:
        task = _get_task(ha, task_id)
        if task and task.get("completions"):
            completed = True
            break
        time.sleep(1)
    assert completed, "notification action did not complete the task"

    # A foreign / unknown action is ignored (no error, task already complete).
    _fire_action(ha, "some_other_app::complete::whatever::x")

    call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})
    # Clear the profile so other tests start clean.
    call_service(ha, "home_keeper", "set_options", {"notify_profiles": []})
