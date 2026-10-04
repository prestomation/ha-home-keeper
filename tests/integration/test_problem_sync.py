"""Integration coverage for the problem-sensor → task sync (real HA container).

The test config enables ``sync_problem_sensors`` on the Home Keeper entry and ships
a ``device_class: problem`` template binary sensor (``binary_sensor.sump_pump_problem``,
kept on). So Home Keeper should mirror it as an armed, un-completable triggered task.
"""

import time
from datetime import UTC, datetime, timedelta

from conftest import HA_URL, call_service
from ha_registry import ws_send

SENSOR = "binary_sensor.sump_pump_problem"


def _list_tasks(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def _synced_task(ha):
    """The task mirroring SENSOR, or None — polled (sync runs after a reload).

    Tolerates the transient "No active coordinator" (HTTP 500) while the entry is
    mid-reload by simply retrying.
    """
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            for task in _list_tasks(ha):
                src = (task.get("source") or {}).get("problem_sensor")
                if src and src.get("entity_id") == SENSOR:
                    return task
        except Exception:
            pass
        time.sleep(1)
    return None


def test_problem_sensor_is_mirrored_as_an_armed_managed_task(ha):
    task = _synced_task(ha)
    assert task is not None, "expected a synced task for the problem binary sensor"
    assert task["recurrence_type"] == "triggered"
    # The sensor is on (problem active), so the task is armed (due now), not dormant.
    assert task["next_due"] is not None
    mb = task.get("managed_by") or {}
    assert mb.get("completion_blocked") is True
    assert mb.get("deletion_protected") is True


def test_synced_problem_task_cannot_be_completed(ha):
    task = _synced_task(ha)
    assert task is not None
    # complete_task is rejected: the problem must be resolved in the originating
    # integration (the sensor returns to OK), not marked done in Home Keeper.
    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/complete_task",
        json={"task_id": task["id"]},
    )
    assert r.status_code >= 400, (
        f"completing a synced problem task should be rejected, got {r.status_code}"
    )


def test_synced_problem_task_note_is_editable_and_persists(ha):
    # Unlike completion, a synced problem task's *note* is user-editable — it's the
    # place to record what to remember next time this problem fires (there's no device
    # to model). update_task is not blocked by the synced-task guard.
    task = _synced_task(ha)
    assert task is not None
    note = "Reset the pump breaker in the garage panel, then prime it."
    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/update_task",
        json={"task_id": task["id"], "notes": note},
    )
    assert r.status_code < 400, (
        f"editing a synced task's note should be allowed, got {r.status_code}"
    )
    # The note round-trips on the same synced task (matched by sensor entity_id).
    deadline = time.monotonic() + 15
    again = None
    while time.monotonic() < deadline:
        again = _synced_task(ha)
        if again is not None and again.get("notes") == note:
            break
        time.sleep(1)
    assert again is not None and again["notes"] == note, (
        "note did not persist on the synced task"
    )


def test_synced_problem_task_can_be_snoozed_but_not_skipped(ha):
    """Snooze is the one mutating verb a synced task accepts (#248).

    Mark done and Skip both assert the problem is dealt with, which only the
    originating integration can decide, so the store keeps rejecting them. Snooze
    asserts nothing of the sort — it defers the reminder and leaves the problem
    standing — and it has to survive the reconciler, which reads armed as
    ``next_due is not None`` and so must leave a deferred mirror alone.
    """
    task = _synced_task(ha)
    assert task is not None
    armed_at = task["next_due"]
    assert armed_at is not None, "expected the mirror to be armed"

    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/skip_task",
        json={"task_id": task["id"]},
    )
    assert r.status_code >= 400, f"skip should still be rejected, got {r.status_code}"

    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/snooze_task",
        json={"task_id": task["id"], "hours": 48},
    )
    assert r.status_code < 400, (
        f"snooze should be allowed, got {r.status_code} {r.text}"
    )

    try:
        # The deferral sticks. The reconciler still counts the mirror as armed, so its
        # next pass leaves the snooze alone rather than dragging next_due back to now.
        deadline = time.monotonic() + 15
        again = None
        while time.monotonic() < deadline:
            again = _synced_task(ha)
            if again is not None and again["next_due"] != armed_at:
                break
            time.sleep(1)
        assert again is not None and again["next_due"] != armed_at, (
            "snooze did not move next_due on the synced task"
        )
        deferred = datetime.fromisoformat(again["next_due"])
        assert deferred > datetime.now(UTC) + timedelta(hours=24), (
            f"expected next_due ~48h out, got {again['next_due']}"
        )
    finally:
        # Re-arm by cycling the sync: the mirror is dropped and rebuilt against a
        # sensor that still reports a problem, so the seeded fixture (and every other
        # test that expects an overdue mirror) sees an armed task again.
        call_service(ha, "home_keeper", "set_options", {"sync_problem_sensors": False})
        call_service(ha, "home_keeper", "set_options", {"sync_problem_sensors": True})
        restored = _synced_task(ha)
        assert restored is not None and restored["next_due"] is not None, (
            "failed to re-arm the synced task after the snooze test"
        )


def test_synced_problem_task_walks_with_a_snooze_only_button_set(ha):
    """A walk notification carries the mirror, offering Snooze rather than Mark done.

    Profiles used to drop these outright (#248), so no Profile ever saw one. They now
    match like any other overdue task, and the walk stays advanceable because the one
    button it offers is the one the store accepts.
    """
    task = _synced_task(ha)
    assert task is not None
    label = "hk_problem_notify_test"

    # Tag the mirror so the profile below selects it and nothing else. `labels` is not
    # one of the sync's locked fields, so the edit survives the next reconcile.
    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/update_task",
        json={"task_id": task["id"], "labels": [label]},
    )
    assert r.status_code < 400, f"labelling the synced task failed: {r.status_code}"

    try:
        call_service(
            ha,
            "home_keeper",
            "set_options",
            {
                "profiles": [
                    {
                        "id": "problemprofile",
                        "name": "The sump pump",
                        "filter": {
                            "status": "all",
                            "groups": [{"labels": [label]}],
                        },
                    }
                ],
                "notifications": [
                    {
                        "id": "problemwalk",
                        "name": "Walk",
                        "profile_id": "problemprofile",
                        "style": "walk",
                        "actions": ["complete", "snooze", "skip", "open"],
                        "targets": ["mobile_app_test"],
                    },
                ],
            },
        )

        resp = call_service(
            ha,
            "home_keeper",
            "notify",
            {"notification": "problemwalk"},
            return_response=True,
        )
        body = resp.get("service_response", resp)
        assert body["matched"] == 1, body
        assert body["sent"] == task["id"], body
    finally:
        ha.post(
            f"{HA_URL}/api/services/home_keeper/update_task",
            json={"task_id": task["id"], "labels": []},
        )
        call_service(
            ha, "home_keeper", "set_options", {"profiles": [], "notifications": []}
        )


def _rename_entity(ha, entity_id, new_entity_id):
    """Change an entity id in the registry, as a person does in the entity settings."""
    token = ha.headers["Authorization"].split(" ", 1)[1]
    reply = ws_send(
        token,
        {
            "type": "config/entity_registry/update",
            "entity_id": entity_id,
            "new_entity_id": new_entity_id,
        },
    )
    assert reply.get("success"), reply


def _mirror_of(ha, entity_id, timeout=45):
    """The mirror task whose source names *entity_id*, polled; None on a timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            for task in _list_tasks(ha):
                src = (task.get("source") or {}).get("problem_sensor")
                if src and src.get("entity_id") == entity_id:
                    return task
        except Exception:
            pass
        time.sleep(1)
    return None


def test_b18_2_an_entity_id_rename_keeps_the_mirror_task(ha):
    """Renaming the sensor's entity_id moves its mirror; nothing is made again.

    The entity-registry ``update`` event carries ``old_entity_id``. Home Keeper read
    only the new id, so the old mirror was an orphan and was deleted with its labels,
    history and note, and an empty mirror was made for the new id.
    """
    task = _synced_task(ha)
    assert task is not None
    label = "b18_2_rename_label"
    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/update_task",
        json={"task_id": task["id"], "labels": [*task.get("labels", []), label]},
    )
    assert r.status_code < 400, r.text

    renamed = "binary_sensor.sump_pump_problem_renamed_b18_2"
    _rename_entity(ha, SENSOR, renamed)
    try:
        moved = _mirror_of(ha, renamed)
        assert moved is not None, "the mirror must follow the rename"
        assert moved["id"] == task["id"], "a rename must not replace the mirror"
        assert label in moved["labels"]
        assert _mirror_of(ha, SENSOR, timeout=1) is None
    finally:
        _rename_entity(ha, renamed, SENSOR)
        back = _mirror_of(ha, SENSOR)
        assert back is not None and back["id"] == task["id"]
        ha.post(
            f"{HA_URL}/api/services/home_keeper/update_task",
            json={
                "task_id": task["id"],
                "labels": [lab for lab in back.get("labels", []) if lab != label],
            },
        )
