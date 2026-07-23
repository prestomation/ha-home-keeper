"""Integration tests for actionable notifications against a real HA container.

There's no mobile-app companion in the test container, so the notify *delivery* is
a no-op (best-effort, swallowed) — these cover the parts that don't need a phone:
the ``home_keeper.notify`` service resolving a profile and reporting what's due, and
the ``mobile_app_notification_action`` listener routing a tapped action back into the
store (completing the task, with the notification origin echoed).

One test (below) *does* have somewhere to actually see delivered text: HA's built-in
``notify.persistent_notification`` target, which needs no companion app. It's used to
prove the notification text is localized end-to-end (#150) — through the real
``hass.config.language`` -> ``notifier.py`` -> ``notifications.py`` path, not just the
pure builders under a fake ``lang`` kwarg (already covered by
``tests/unit/test_notifications.py``).
"""

import asyncio
import json
import time

import websockets
from conftest import HA_URL, call_service

WS_URL = "ws://localhost:8123/api/websocket"


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


async def _ws_commands(token, commands):
    """Open one authed websocket; send each command; return the replies."""
    results = []
    async with websockets.connect(WS_URL, max_size=None) as ws:
        assert json.loads(await ws.recv())["type"] == "auth_required"
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        assert json.loads(await ws.recv())["type"] == "auth_ok"
        msg_id = 0
        for command in commands:
            msg_id += 1
            await ws.send(json.dumps({"id": msg_id, **command}))
            reply = json.loads(await ws.recv())
            results.append(reply)
    return results


def _run_ws(token, commands):
    return asyncio.run(_ws_commands(token, commands))


def test_notify_persistent_notification_is_localized(ha, ha_token):
    """A translated notification actually lands in a real HA surface (#150).

    ``notify.persistent_notification`` needs no mobile-app companion, so — unlike the
    mobile_app-targeted test above — the delivered text can be inspected via the
    ``persistent_notification/get`` websocket command. This exercises the real
    ``hass.config.language`` -> ``notifier.py`` -> ``notifications.py`` path end to
    end, not just the pure builders under an explicit ``lang`` kwarg.
    """
    label = "hk_notify_i18n_test"
    task_id = call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Notify i18n integration task",
            "recurrence_type": "floating",
            "interval": 7,
            "unit": "days",
            "labels": [label],
        },
        return_response=True,
    ).get("service_response", {})["task_id"]
    call_service(
        ha,
        "home_keeper",
        "set_options",
        {
            "profiles": [
                {
                    "id": "i18n_testprofile",
                    "name": "i18n test",
                    "filter": {"status": "overdue", "labels": [label]},
                }
            ],
        },
    )

    try:
        (update_reply,) = _run_ws(
            ha_token, [{"type": "config/core/update", "language": "es"}]
        )
        assert update_reply["success"], update_reply
        # A language change reloads Home Keeper (it relocalizes generated task names),
        # which briefly tears down and rebuilds its platforms/services. A service call
        # that races that reload can 400 transiently; give it a moment to settle.
        time.sleep(1)

        call_service(ha, "persistent_notification", "dismiss_all", {})
        call_service(
            ha,
            "home_keeper",
            "notify",
            {"profile": "i18n_testprofile", "target": ["persistent_notification"]},
        )

        (get_reply,) = _run_ws(ha_token, [{"type": "persistent_notification/get"}])
        assert get_reply["success"], get_reply
        notifications = get_reply["result"]
        assert len(notifications) == 1, notifications
        # Spanish overdue phrasing ("Vencida hace N días.") -- not asserting the exact
        # day count, which drifts with the wall clock; the count/plural-form logic is
        # already covered by tests/unit/test_notifications.py.
        assert "Venc" in notifications[0]["message"], notifications[0]
    finally:
        # Never let the language flip or a leftover notification/profile leak into
        # other tests sharing this container.
        _run_ws(ha_token, [{"type": "config/core/update", "language": "en"}])
        time.sleep(1)  # let the reload back to English settle (see above)
        call_service(ha, "persistent_notification", "dismiss_all", {})
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})
        call_service(
            ha, "home_keeper", "set_options", {"profiles": [], "notifications": []}
        )
