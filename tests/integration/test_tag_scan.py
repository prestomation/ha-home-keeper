"""Integration tests for NFC/RFID tag completion against a real HA container.

Home Keeper never reads a tag itself: it listens for the ``tag_scanned`` event Home
Assistant core's ``tag`` integration fires and routes the scanned id back to the
tasks bound to it. Firing that event over the REST API is exactly what a phone tap
or an ESPHome reader produces, so these cover the whole path — the listener, the
store's completion chokepoint, and the scan-only gate that refuses every other way
of marking a task done.
"""

import time

from conftest import HA_URL, call_service, poll_state

# Unique to this module so the scans here can't collide with a seeded task's tag.
TAG = "hk-itest-tag"
OTHER_TAG = "hk-itest-tag-unknown"


def _fire_scan(ha, tag_id):
    r = ha.post(f"{HA_URL}/api/events/tag_scanned", json={"tag_id": tag_id})
    r.raise_for_status()


def _list_tasks(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def _get_task(ha, task_id):
    return next((t for t in _list_tasks(ha) if t["id"] == task_id), None)


def _add_task(ha, name, **fields):
    resp = call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": name,
            "recurrence_type": "floating",
            "interval": 7,
            "unit": "days",
            **fields,
        },
        return_response=True,
    )
    return resp.get("service_response", resp)["task_id"]


def _poll_task(ha, task_id, condition, timeout=20):
    deadline = time.monotonic() + timeout
    task = None
    while time.monotonic() < deadline:
        task = _get_task(ha, task_id)
        if task is not None and condition(task):
            return task
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting on task {task_id}. Last seen: {task}")


def test_tag_scan_completes_every_task_bound_to_the_tag(ha):
    # One sticker, two jobs: a scan completes both tasks that name the tag, and marks
    # the completion with the scan origin so an automation can tell it apart from a
    # tap on the Done button.
    first = _add_task(ha, "Tag scan probe A", tag_id=TAG)
    second = _add_task(ha, "Tag scan probe B", tag_id=TAG)
    untagged = _add_task(ha, "Tag scan bystander")
    try:
        _fire_scan(ha, TAG)

        for task_id in (first, second):
            task = _poll_task(ha, task_id, lambda t: t["completions"])
            assert task["last_completed"], "a scan must stamp last_completed"
            assert len(task["completions"]) == 1

        # The completion event carries the scan marker (captured by the automation in
        # ha_config/configuration.yaml).
        poll_state(
            ha,
            "input_text.hk_last_completed_origin",
            lambda s: s == "home_keeper_tag_scan",
        )
        # A task with no tag is untouched by somebody else's scan.
        assert not _get_task(ha, untagged)["completions"]
    finally:
        for task_id in (first, second, untagged):
            call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})


def test_scanning_an_unknown_tag_changes_nothing(ha):
    # Tags are shared with the rest of Home Assistant, so most scans belong to
    # somebody else's automation and must be a silent no-op here — including for a
    # task bound to a *different* tag (routing is an exact match, not a fallback).
    task_id = _add_task(ha, "Tag scan miss probe", tag_id=TAG)

    def _completion_state():
        return {
            t["id"]: (t["last_completed"], len(t["completions"]))
            for t in _list_tasks(ha)
        }

    try:
        before = _completion_state()
        _fire_scan(ha, OTHER_TAG)
        time.sleep(3)  # let the (no-op) listener run
        assert _completion_state() == before
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})


def test_require_tag_scan_refuses_every_other_completion_surface(ha):
    # The point of the flag: "done" means somebody was standing in front of the thing,
    # so the to-do card and a bare service call are both refused.
    task_id = _add_task(ha, "Scan-only probe", tag_id=TAG, require_tag_scan=True)
    try:
        task = _get_task(ha, task_id)
        assert task["tag_id"] == TAG and task["require_tag_scan"] is True

        rejected = ha.post(
            f"{HA_URL}/api/services/home_keeper/complete_task",
            json={"task_id": task_id},
        )
        assert rejected.status_code >= 400, (
            f"bare complete_task should be refused, got {rejected.status_code}"
        )
        assert not _get_task(ha, task_id)["completions"]

        # Checking the item off in HA's to-do card routes through the same chokepoint
        # and surfaces the refusal as an error rather than silently completing.
        rejected = ha.post(
            f"{HA_URL}/api/services/todo/update_item",
            json={
                "entity_id": "todo.home_keeper_tasks",
                "item": "Scan-only probe",
                "status": "completed",
            },
        )
        assert rejected.status_code >= 400, (
            f"to-do completion should be refused, got {rejected.status_code}"
        )
        assert not _get_task(ha, task_id)["completions"]

        # The scan marker is what unlocks it — here through the service, which an
        # integration mirroring a reader of its own would use.
        call_service(
            ha,
            "home_keeper",
            "complete_task",
            {"task_id": task_id, "origin": "home_keeper_tag_scan"},
        )
        task = _poll_task(ha, task_id, lambda t: t["completions"])
        assert len(task["completions"]) == 1
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})


def test_a_real_scan_completes_a_scan_only_task(ha):
    task_id = _add_task(ha, "Scan-only scan probe", tag_id=TAG, require_tag_scan=True)
    try:
        _fire_scan(ha, TAG)
        task = _poll_task(ha, task_id, lambda t: t["completions"])
        assert task["last_completed"]
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})


def test_update_task_cannot_unlink_the_tag_while_a_scan_is_required(ha):
    # Clearing the tag alone would leave the task requiring a scan it can never get,
    # locking it out of every completion surface — rejected, and the task is unchanged.
    task_id = _add_task(ha, "Scan-only unlink probe", tag_id=TAG, require_tag_scan=True)
    try:
        rejected = ha.post(
            f"{HA_URL}/api/services/home_keeper/update_task",
            json={"task_id": task_id, "tag_id": None},
        )
        assert rejected.status_code >= 400, (
            f"unlinking a required tag should be refused, got {rejected.status_code}"
        )
        task = _get_task(ha, task_id)
        assert task["tag_id"] == TAG and task["require_tag_scan"] is True

        # Dropping the requirement and the tag together is a legitimate edit.
        call_service(
            ha,
            "home_keeper",
            "update_task",
            {"task_id": task_id, "tag_id": None, "require_tag_scan": False},
        )
        task = _get_task(ha, task_id)
        assert task["tag_id"] is None and task["require_tag_scan"] is False
        # ...and the task is completable by hand again.
        call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
        assert _poll_task(ha, task_id, lambda t: t["completions"])
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})


def test_tag_integration_is_loaded(ha):
    # The listener needs no ``tag`` component to work (it listens for a bare event),
    # but the panel's tag picker reads HA's tag list, so the container has it enabled.
    r = ha.get(f"{HA_URL}/api/config")
    r.raise_for_status()
    assert "tag" in r.json()["components"]
