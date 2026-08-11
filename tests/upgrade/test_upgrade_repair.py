"""The automatic repair for an install that upgraded Home Assistant first (#183).

Someone who upgraded Home Assistant before Home Keeper is left with a ghost device per
attached thing and tasks pointing at device ids Home Assistant invalidated. This is the
path that cannot be avoided by ordering — the damage happened before the fixed version
ever loaded — so it has to be repaired rather than prevented.

``devices.async_heal_split_device_ids`` does it at setup with no user action. These
tests are its acceptance criteria, run against the genuinely damaged world the
``ha_first`` path produces.
"""

from __future__ import annotations

SOURCE_DOMAIN = "hk_upgrade_source"
KITCHEN = "kitchen_sensor"
BAMBU_SERIAL = "AC12309BH109"


def test_every_task_points_at_a_live_device(repair_run):
    """No task should be left pointing at a device id that no longer exists."""
    live = {d["id"] for d in repair_run.after["devices"]}
    dangling = [
        (t["name"], t["device_id"])
        for t in repair_run.after["tasks"]
        if t.get("device_id") and t["device_id"] not in live
    ]
    assert not dangling, (
        f"{len(dangling)} task(s) still point at a dead device: {dangling}"
    )


def test_source_namespace_copies_are_healed_too(repair_run):
    """The contributor's own copy of the id must be healed as well.

    Not a nicety: bambu-lab and battery-notes match their existing tasks on
    ``source.<ns>.device_id``. Healing only the task's field leaves them unable to find
    the task, so they create a duplicate and the stale one persists.
    """
    live = {d["id"] for d in repair_run.after["devices"]}
    dangling = []
    for task in repair_run.after["tasks"]:
        for namespace, payload in (task.get("source") or {}).items():
            if not isinstance(payload, dict):
                continue
            device_id = payload.get("device_id")
            if device_id and device_id not in live:
                dangling.append((task["name"], namespace, device_id))
    assert not dangling, f"stale ids left in source namespaces: {dangling}"


def test_tasks_land_back_on_the_real_device(repair_run):
    """A repaired task points at the device its owning integration kept."""
    task = next(
        t
        for t in repair_run.after["tasks"]
        if t["name"] == "Upgrade probe foreign task"
    )
    device = repair_run.device(task["device_id"])
    assert device is not None, "the probe task's device should resolve after the repair"
    assert any(
        list(i) == [SOURCE_DOMAIN, KITCHEN] for i in device.get("identifiers", [])
    ), (
        f"expected the kitchen sensor, got {device.get('name')!r} "
        f"{device.get('identifiers')}"
    )
    assert not any("home_keeper" in e for e in device.get("config_entries") or ()), (
        "the task should point at the real device, not at a Home Keeper-owned copy"
    )


def test_the_ghost_devices_are_gone(repair_run):
    """With the entities moved back, the leftover halves are pruned."""
    ghosts = [
        (d["id"][:8], d.get("name"))
        for d in repair_run.after["devices"]
        if any("home_keeper" in e for e in d.get("config_entries") or ())
        and not any(
            i[0] == "home_keeper" for i in d.get("identifiers", []) if len(i) == 2
        )
    ]
    assert not ghosts, f"Home Keeper still owns device(s) it did not create: {ghosts}"


def test_no_duplicate_glue_tasks_survive(repair_run):
    """Each companion ends up with the task count it started with, not more."""
    for namespace in (
        "home_keeper_battery_notes",
        "home_keeper_bambu_lab",
        "pawsistant",
    ):
        before = [
            t
            for t in repair_run.before["tasks"]
            if (t.get("source") or {}).get(namespace)
        ]
        after = [
            t
            for t in repair_run.after["tasks"]
            if (t.get("source") or {}).get(namespace)
        ]
        assert len(after) <= len(before), (
            f"{namespace} went from {len(before)} to {len(after)} task(s): "
            f"{[t['name'] for t in after]}"
        )
