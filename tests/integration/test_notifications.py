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
                    # A present-but-nonexistent target: there's no companion app in the
                    # container, so the actual push is a swallowed no-op, but a target
                    # must be set or notify rejects the send (nowhere to deliver).
                    "targets": ["mobile_app_test"],
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

    # notify a profile with an explicit target also works (ad-hoc).
    resp = call_service(
        ha,
        "home_keeper",
        "notify",
        {"profile": "testprofile", "target": "mobile_app_test"},
        return_response=True,
    )
    assert resp.get("service_response", resp)["matched"] == 1

    # A bare profile (no target) is rejected, not a silent no-op — a profile is only a
    # filter, so there's nowhere to deliver. It raises ServiceValidationError; the
    # response-supporting notify service surfaces that as a 5xx over the REST API (same
    # as the other notify_* validation errors), so assert it errored rather than 200.
    rejected = ha.post(
        f"{HA_URL}/api/services/home_keeper/notify?return_response",
        json={"profile": "testprofile"},
    )
    assert rejected.status_code >= 400, (
        f"bare-profile notify should be rejected, got {rejected.status_code}"
    )

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

    # N1: a *stale* "Mark done" tap (same action re-fired after the task was already
    # completed) must be a no-op. The completion moved next_due into the future, so
    # the task is no longer overdue and the second tap must not double-advance /
    # append a second completion.
    completed_task = _get_task(ha, task_id)
    before_count = len(completed_task.get("completions", []))
    before_next_due = completed_task.get("next_due")
    before_last = completed_task.get("last_completed")
    _fire_action(ha, f"home_keeper::complete::{task_id}::testnotif")
    time.sleep(3)  # let the (no-op) action handler run
    after_task = _get_task(ha, task_id)
    assert len(after_task.get("completions", [])) == before_count, (
        "stale complete tap should not append a second completion"
    )
    assert after_task.get("next_due") == before_next_due, (
        "stale complete tap should not advance next_due"
    )
    assert after_task.get("last_completed") == before_last

    # A foreign / unknown action is ignored (no error, task already complete).
    _fire_action(ha, "some_other_app::complete::whatever::x")

    call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})
    # Clear profiles/notifications so other tests start clean.
    call_service(
        ha, "home_keeper", "set_options", {"profiles": [], "notifications": []}
    )
