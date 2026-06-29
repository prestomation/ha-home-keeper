"""Integration test: per-task entity cleanup after task deletion.

When a device-attached task is deleted (or Problem Sensor Sync removes a synced
task), the config entry reloads.  ``async_setup_entry`` must clean up the
entity-registry entries for the deleted task's per-task entities
(sensor.*_next_due, binary_sensor.*_overdue, button.*_done) so they don't
linger as orphaned "unavailable" entries on the device page.

Issue: #104 — Problem Sensor Sync leaves stale entities after disabling or exclusions
"""

import time

from conftest import HA_URL, call_service, list_states


# ── helpers ──────────────────────────────────────────────────────────────────


def _list_tasks(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def _entity_registry(ha) -> list[dict]:
    """Fetch all entity registry entries via HA's admin REST endpoint."""
    r = ha.get(f"{HA_URL}/api/config/entity_registry")
    r.raise_for_status()
    return r.json()


def _find_button_by_name(ha, name_substr: str):
    """Return (entity_id, friendly_name) for the first button whose name contains name_substr."""
    for s in list_states(ha):
        if not s["entity_id"].startswith("button."):
            continue
        fn = s.get("attributes", {}).get("friendly_name", "")
        if name_substr in fn:
            return s["entity_id"], fn
    return None, None


def _unique_ids_in_registry(ha) -> set[str]:
    return {e["unique_id"] for e in _entity_registry(ha) if e.get("unique_id")}


# ── test ─────────────────────────────────────────────────────────────────────


def test_stale_per_task_entities_removed_after_task_deleted(ha):
    """Deleting a device-attached task must remove its per-task entity registry entries.

    add_task and delete_task both trigger a config-entry reload.  Before the fix,
    async_setup_entry only adds entities for the current task set — it never removes
    orphaned registry entries for deleted tasks.  After the fix, it scans the
    registry at setup time and removes stale entries so they don't resurface on the
    device page after an HA restart.
    """
    resp = call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Entity cleanup probe task",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "years",
            # A fake device_id gives the task per-task entities on a self-owned
            # synthetic device (the same pattern used in test_lifecycle.py).
            "device_id": "cleanup_probe_fake_device_104",
        },
        return_response=True,
    )
    task_id = resp.get("service_response", resp)["task_id"]

    try:
        # add_task triggers an entry reload; poll until the button entity appears.
        probe_button_eid = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            probe_button_eid, _ = _find_button_by_name(ha, "Entity cleanup probe")
            if probe_button_eid:
                break
            time.sleep(1)
        assert probe_button_eid, "probe button entity should appear in states after add_task"

        # Verify all three per-task unique-ids exist in the entity registry.
        button_uid = f"home_keeper_{task_id}_done"
        sensor_uid = f"home_keeper_{task_id}_next_due"
        binary_uid = f"home_keeper_{task_id}_overdue"
        reg_uids = _unique_ids_in_registry(ha)
        assert button_uid in reg_uids, "button registry entry should exist before delete"
        assert sensor_uid in reg_uids, "sensor registry entry should exist before delete"
        assert binary_uid in reg_uids, "binary_sensor registry entry should exist before delete"

        # Delete the task — this also triggers a config-entry reload.
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})
        task_id = None  # consumed; finally block won't re-delete

        # After the reload, all three entity registry entries must be gone.
        # Poll up to 20 s for the reload to complete and the cleanup to propagate.
        stale_uids: set[str] = {button_uid, sensor_uid, binary_uid}
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            current_uids = _unique_ids_in_registry(ha)
            stale_uids = {uid for uid in stale_uids if uid in current_uids}
            if not stale_uids:
                break
            time.sleep(1)

        assert not stale_uids, (
            f"stale entity registry entries should be removed after task deletion: {stale_uids}"
        )

    finally:
        if task_id:
            try:
                call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})
            except Exception:
                pass
