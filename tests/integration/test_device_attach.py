"""Integration test: the *foreign* device attachment contract (#183).

Home Keeper's headline device behaviour is that a task attached to a device another
integration owns puts its per-task entities **on that device's page** — the
Battery-Notes-style merge described in ``docs/DESIGN.md`` → "Device attachment".
``coordinator.device_info_for_task`` implements it by copying the foreign device's
identifiers and connections verbatim into a ``DeviceInfo``.

**Home Assistant 2026.8 made identifiers unique per config entry**, so that copy
stopped merging and instead forked a *duplicate* device owned by Home Keeper's config
entry — carrying no ``name``, which is why #183 saw raw GUIDs where a device name
belonged. Home Keeper now links entities to the device instead
(``coordinator.device_link_for_task`` sets ``entity.device_entry``), which restores
the original behaviour without claiming the device.

These are the assertions that should have existed. The suite already covered the
*self-owned* device path (``test_device_cleanup.py``, whose docstring says as much),
but nothing asserted the foreign-device path, so the regression landed silently even
though CI was already running the affected Home Assistant version.
"""

import time
from contextlib import contextmanager

from conftest import call_service
from ha_registry import (
    device_registry,
    entities_for_device,
    find_device,
    has_identifier,
)

# The stub's device, registered by tests/integration/stubs/home_keeper_battery_notes.
# It stands in for any device Home Keeper does not own.
STUB_DOMAIN = "home_keeper_battery_notes"
STUB_DEVICE_KEY = "e2e_battery_device"


def _wait_for_entities(
    ha, device_id: str, platform: str, timeout: int = 25
) -> list[dict]:
    """Entities on *device_id* belonging to *platform*, once any appear."""
    deadline = time.monotonic() + timeout
    found: list[dict] = []
    while time.monotonic() < deadline:
        found = [
            e
            for e in entities_for_device(ha, device_id)
            if e.get("platform") == platform
        ]
        if found:
            return found
        time.sleep(1)
    return found


@contextmanager
def _attached_task(ha):
    """Create a task attached to the stub's device; yield (device_id, task_id)."""
    stub_device = find_device(ha, STUB_DOMAIN, STUB_DEVICE_KEY)
    assert stub_device is not None, (
        "the battery-notes stub should own a device; is the stub mounted and loaded?"
    )
    stub_device_id = stub_device["id"]

    resp = call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Device attach probe task",
            "recurrence_type": "floating",
            "interval": 3,
            "unit": "months",
            "device_id": stub_device_id,
        },
        return_response=True,
    )
    task_id = resp.get("service_response", resp)["task_id"]
    try:
        # add_task reloads the config entry; let the entities be registered.
        _wait_for_entities(ha, stub_device_id, "home_keeper")
        yield stub_device_id, task_id
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})


# Two tests rather than one with several assertions, so a partial regression is
# legible: losing entity placement and forking a duplicate are separate failures with
# separate causes, and bundling them would report either as "device attachment broke".


def test_task_entities_land_on_the_foreign_device(ha):
    """The per-task entities belong to the device the task points at."""
    with _attached_task(ha) as (stub_device_id, _task_id):
        hk_entities = [
            e
            for e in entities_for_device(ha, stub_device_id)
            if e.get("platform") == "home_keeper"
        ]
        assert hk_entities, (
            "Home Keeper's per-task entities should be registered against the "
            f"foreign device {stub_device_id}, but none were found on it"
        )


def test_attaching_a_task_does_not_fork_a_duplicate_device(ha):
    """Attaching must not mint a second device carrying the same identifiers.

    The regression this guards: copying the target's identifiers into a ``DeviceInfo``
    created a second, nameless device under Home Keeper's config entry on HA 2026.8+
    (#183). Entity-level linking adds no device at all, so exactly one device carries
    these identifiers no matter how many tasks attach to it.
    """
    with _attached_task(ha) as (stub_device_id, task_id):
        devices = device_registry(ha)

        self_owned = [d for d in devices if has_identifier(d, "home_keeper", task_id)]
        assert not self_owned, (
            "a task attached to a real device must not also get a self-owned "
            f"(home_keeper, {task_id}) device: {self_owned}"
        )

        forked = [
            d
            for d in devices
            if d["id"] != stub_device_id
            and has_identifier(d, STUB_DOMAIN, STUB_DEVICE_KEY)
        ]
        assert not forked, (
            "the stub device's identifiers must not appear on a second device — "
            f"Home Keeper forked a duplicate: "
            f"{[(d['id'], d.get('name')) for d in forked]}"
        )
