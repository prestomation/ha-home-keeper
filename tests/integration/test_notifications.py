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
    # A brand-new floating task is due-now (overdue) immediately. A unique label scopes
    # the profile to *this* task so the seeded demo tasks don't crowd the queue.
    label = "hk_notify_test"
    resp = call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Notify integration task",
            "recurrence_type": "floating",
            "interval": 7,
            "unit": "days",
            "labels": [label],
        },
        return_response=True,
    )
    task_id = resp.get("service_response", resp)["task_id"]

    # A standalone Profile (saved filter) scoped to our label, plus a Notification
    # that references it. Explicit ids so the test can reference them.
    call_service(
        ha,
        "home_keeper",
        "set_options",
        {
            "profiles": [
                {
                    "id": "testprofile",
                    "name": "Test",
                    "filter": {"status": "overdue", "labels": [label]},
                }
            ],
            "notifications": [
                {
                    "id": "testnotif",
                    "name": "Test notif",
                    "profile_id": "testprofile",
                    "targets": [],
                    "actions": ["complete", "snooze"],
                    "style": "walk",
                }
            ],
        },
    )

    # notify a saved notification → resolves its profile and reports what's due.
    resp = call_service(
        ha,
        "home_keeper",
        "notify",
        {"notification": "testnotif"},
        return_response=True,
    )
    body = resp.get("service_response", resp)
    assert body["matched"] == 1
    assert body["sent"] == task_id

    # notify a bare profile + inline delivery also works (ad-hoc).
    resp = call_service(
        ha, "home_keeper", "notify", {"profile": "testprofile"}, return_response=True
    )
    assert resp.get("service_response", resp)["matched"] == 1

    # Tapping "Mark done" routes via the notification id and completes the task.
    _fire_action(ha, f"home_keeper::complete::{task_id}::testnotif")

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
    # Clear profiles/notifications so other tests start clean.
    call_service(
        ha, "home_keeper", "set_options", {"profiles": [], "notifications": []}
    )
