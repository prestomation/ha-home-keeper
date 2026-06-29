"""Integration tests: stale entity cleanup after task deletion and metadata removal.

Two scenarios:

1. Per-task entity cleanup after task deletion — when a device-attached task is
   deleted (or Problem Sensor Sync removes a synced task) the config entry reloads.
   ``async_setup_entry`` must clean up the entity-registry entries for the deleted
   task's per-task entities (sensor.*_next_due, binary_sensor.*_overdue,
   button.*_done) so they don't linger as orphaned "unavailable" entries on the
   device page.

2. Asset date sensor cleanup after metadata removal — when a tracked date metadata
   entry is removed from an asset (via ``update_asset``), ``async_setup_entry`` must
   remove the corresponding ``sensor.*`` entity from the registry so it doesn't
   linger as "unavailable" on the device page.

Issue: #104 — Problem Sensor Sync leaves stale entities after disabling or exclusions
"""

import json
import time

import websockets.sync.client
from conftest import HA_URL, call_service, list_states

# ── helpers ──────────────────────────────────────────────────────────────────

_WS_URL = HA_URL.replace("http://", "ws://") + "/api/websocket"


def _entity_registry(ha) -> list[dict]:
    """Fetch all entity registry entries via HA's WebSocket API."""
    token = ha.headers["Authorization"].split(" ", 1)[1]
    with websockets.sync.client.connect(_WS_URL) as ws:
        # HA sends auth_required first
        msg = json.loads(ws.recv())
        assert msg["type"] == "auth_required"
        ws.send(json.dumps({"type": "auth", "access_token": token}))
        msg = json.loads(ws.recv())
        assert msg["type"] == "auth_ok", f"auth failed: {msg}"
        ws.send(json.dumps({"id": 1, "type": "config/entity_registry/list"}))
        msg = json.loads(ws.recv())
        assert msg.get("success"), f"entity_registry/list failed: {msg}"
        return msg["result"]


def _find_button_by_name(ha, name_substr: str):
    """Return (entity_id, friendly_name) for first button matching name_substr."""
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
            "unit": "months",
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
        assert probe_button_eid, (
            "probe button entity should appear in states after add_task"
        )

        # Verify all three per-task unique-ids exist in the entity registry.
        button_uid = f"home_keeper_{task_id}_done"
        sensor_uid = f"home_keeper_{task_id}_next_due"
        binary_uid = f"home_keeper_{task_id}_overdue"
        reg_uids = _unique_ids_in_registry(ha)
        assert button_uid in reg_uids, (
            "button registry entry should exist before delete"
        )
        assert sensor_uid in reg_uids, (
            "sensor registry entry should exist before delete"
        )
        assert binary_uid in reg_uids, (
            "binary_sensor registry entry should exist before delete"
        )

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
            "stale entity registry entries should be removed after task deletion: "
            f"{stale_uids}"
        )

    finally:
        if task_id:
            try:
                call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})
            except Exception:
                pass


def test_stale_asset_date_sensor_removed_after_metadata_untracked(ha):
    """Removing a tracked date metadata entry must remove its entity registry entry.

    update_asset triggers a config-entry reload.  Before the fix,
    async_setup_entry only creates sensors for the current tracked-date set; it
    never removed stale registry entries for entries that were un-tracked or
    deleted.  After the fix, the setup pass scans the registry and removes any
    ``home_keeper_asset_*_meta_*`` sensor whose (asset_id, meta_id) pair is no
    longer in the live tracked-dates set.
    """
    resp = call_service(
        ha,
        "home_keeper",
        "add_asset",
        {
            "name": "Date sensor cleanup probe appliance",
            "manufacturer": "Test Co",
            "metadata": [
                {
                    "id": "probe_meta_warranty",
                    "type": "date",
                    "label": "Probe warranty expiry",
                    "value": "2030-01-01",
                    "track": True,
                }
            ],
        },
        return_response=True,
    )
    asset_id = resp.get("service_response", resp)["asset_id"]

    try:
        # add_asset triggers a reload; poll until the asset is provisioned with a
        # device_id and the date sensor appears in the entity registry.
        meta_uid = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            assets_resp = call_service(
                ha, "home_keeper", "list_assets", {}, return_response=True
            )
            assets = assets_resp.get("service_response", assets_resp)["assets"]
            probe = next((a for a in assets if a["id"] == asset_id), None)
            if probe and probe.get("device_id"):
                # Device provisioned — look up the meta entry id that was assigned.
                for entry in probe.get("metadata") or []:
                    if entry.get("label") == "Probe warranty expiry":
                        meta_uid = f"home_keeper_asset_{asset_id}_meta_{entry['id']}"
                        break
            if meta_uid and meta_uid in _unique_ids_in_registry(ha):
                break
            time.sleep(1)

        assert meta_uid, (
            "asset date sensor unique-id should appear in entity registry"
            " after add_asset"
        )

        # Remove the tracked metadata by updating the asset with an empty list.
        # update_asset triggers a config-entry reload; async_setup_entry must then
        # clean up the now-stale registry entry.
        call_service(
            ha,
            "home_keeper",
            "update_asset",
            {"asset_id": asset_id, "metadata": []},
        )

        # Poll up to 20 s for the registry entry to disappear.
        deadline = time.monotonic() + 20
        stale = True
        while time.monotonic() < deadline:
            if meta_uid not in _unique_ids_in_registry(ha):
                stale = False
                break
            time.sleep(1)

        assert not stale, (
            f"stale asset date sensor {meta_uid!r} should be removed from the "
            "entity registry after metadata is un-tracked via update_asset"
        )

    finally:
        try:
            call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset_id})
        except Exception:
            pass
