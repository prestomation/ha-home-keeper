"""Integration test: orphaned device cleanup after a synced/attached task is removed.

When Problem Sensor Sync is disabled (or a sensor/device/area/label is excluded), or
when an ordinary device-attached task is deleted, the config entry reloads and the
per-task entities are removed (covered by ``test_entity_cleanup.py``). This test
covers the *device* side of the same scenario: ``async_setup_entry`` must also drop
Home Keeper from any device that no longer carries one of our entities, so no empty
zero-entity device card lingers under **Settings → Devices & Services → Home Keeper**.

The deterministic case exercised here is a **self-owned** Home Keeper device: a task
with a ``device_id`` that resolves to no real device gets a self-owned device keyed on
``(home_keeper, task_id)``. Deleting the task must remove that device entirely (Home
Keeper was its only config entry) — the same prune that detaches Home Keeper from a
shared device drives both paths via ``async_update_device(remove_config_entry_id=…)``.

Follow-up to #104 (Problem Sensor Sync leaves stale entities/devices after disabling
or exclusions).
"""

import time

from conftest import call_service
from ha_registry import find_device

# ── helpers ──────────────────────────────────────────────────────────────────


def _has_self_owned_device(ha, task_id: str) -> bool:
    """True if a self-owned ``(home_keeper, task_id)`` device exists in the registry."""
    return find_device(ha, "home_keeper", task_id) is not None


# ── test ─────────────────────────────────────────────────────────────────────


def test_self_owned_device_removed_after_task_deleted(ha):
    """Deleting a device-attached task must remove its orphaned self-owned device.

    add_task and delete_task both trigger a config-entry reload. Before the fix,
    async_setup_entry removed the deleted task's per-task entities but left the
    self-owned device behind, so it lingered as an empty Home Keeper device card.
    After the fix, async_prune_orphaned_devices removes the now entity-less device.
    """
    resp = call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Device cleanup probe task",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
            # A fake device_id resolves to no real device, so Home Keeper creates a
            # self-owned device keyed on (home_keeper, task_id) for the per-task
            # entities — exactly the kind of device left orphaned on deletion.
            "device_id": "device_cleanup_probe_fake_device",
        },
        return_response=True,
    )
    task_id = resp.get("service_response", resp)["task_id"]

    try:
        # add_task triggers an entry reload; poll until the self-owned device appears.
        deadline = time.monotonic() + 20
        present = False
        while time.monotonic() < deadline:
            if _has_self_owned_device(ha, task_id):
                present = True
                break
            time.sleep(1)
        assert present, (
            "self-owned Home Keeper device should be created for the probe task"
        )

        # Delete the task — this also triggers a config-entry reload.
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})
        task_id_to_cleanup = task_id
        task_id = None  # consumed; finally block won't re-delete

        # After the reload + prune, the self-owned device must be gone.
        deadline = time.monotonic() + 20
        still_present = True
        while time.monotonic() < deadline:
            if not _has_self_owned_device(ha, task_id_to_cleanup):
                still_present = False
                break
            time.sleep(1)

        assert not still_present, (
            "orphaned self-owned Home Keeper device should be removed from the "
            "device registry after the attached task is deleted"
        )

    finally:
        if task_id:
            try:
                call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})
            except Exception:
                pass
