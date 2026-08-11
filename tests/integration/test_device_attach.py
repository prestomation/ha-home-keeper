"""Integration test: the *foreign* device attachment contract (#183).

Home Keeper's headline device behaviour is that a task attached to a device another
integration owns puts its per-task entities **on that device's page** — the
Battery-Notes-style merge described in ``docs/DESIGN.md`` → "Device attachment".
``coordinator.device_info_for_task`` implements it by copying the foreign device's
identifiers and connections verbatim into a ``DeviceInfo``.

**Home Assistant 2026.8 made identifiers unique per config entry**, so that copy no
longer merges — it silently forks a *duplicate* device owned by Home Keeper's config
entry. Every symptom in #183 traces back to it.

Observed on 2026.8 with this fixture: the stub's device and a second device carry the
same identifiers, and the fork's ``name`` is ``None`` — ``device_info_for_task`` sends
no ``name`` when it believes it is merging onto an existing device. A nameless device
is why #183 item 1 sees raw GUIDs: both HA's device picker and the panel's
``deviceName()`` fall back to the device id when a device resolves but has no name.
The stored ``device_id`` is not stale; the device it points at simply has no name.

This test is the assertion that should have existed. The suite already covered the
*self-owned* device path (``test_device_cleanup.py``, whose docstring says as much),
but nothing asserted the foreign-device path, so the regression landed silently even
though CI was already running the affected Home Assistant version.

It is marked ``xfail(strict=True)`` deliberately: it documents the broken contract
today and turns into a hard failure the moment a fix lands, forcing the marker off
rather than letting a stale expectation rot. Do not weaken the assertions to make it
pass — a passing version of this test on 2026.8 would mean it stopped testing
anything.
"""

import time

import pytest
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


@pytest.mark.xfail(
    reason="HA 2026.8 forks a duplicate device instead of merging; see #183",
    strict=True,
)
def test_task_entities_land_on_the_foreign_device(ha):
    """A device-attached task puts its entities on that device, not on a fork."""
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
        # add_task reloads the config entry; wait for our entities to be registered.
        hk_entities = _wait_for_entities(ha, stub_device_id, "home_keeper")

        # 1. The per-task entities belong to the foreign device.
        assert hk_entities, (
            "Home Keeper's per-task entities should be registered against the "
            f"foreign device {stub_device_id}, but none were found on it"
        )

        # 2. No duplicate device was forked for the task. Pre-2026.8 the identifier
        #    copy merged; post-2026.8 it creates a second device carrying the same
        #    identifiers under Home Keeper's config entry.
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
            f"Home Keeper forked a duplicate: {forked}"
        )
    finally:
        if task_id:
            call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})
