"""Integration coverage for the aggregate task-count sensors.

The unit tier proves the arithmetic. What only a real Home Assistant can prove is the
framework wiring around it, and every assertion here is one a mocked registry would
have answered "yes" to whether or not it was true:

* the service device is registered, is typed ``service``, and **survives** the two
  device passes that run on every setup — the one that removes orphaned devices and
  the one that reconciles appliance devices;
* a profile's sensor appears when the profile is saved and its registry entry is
  removed when the profile is deleted, over the real options-write-then-reload path;
* renaming a profile keeps the entity id, because the unique id is anchored to the
  profile's id rather than its name.
"""

import time

from conftest import call_service, get_state
from ha_registry import entities_for_device, entity_registry, find_device

_ALL_SENSOR = "sensor.home_keeper_tasks"

_PROFILE = {
    "id": "it_count_profile",
    "name": "Count probe",
    "filter": {"status": "all", "labels": [], "areas": [], "devices": []},
}
_PROFILE_UID = "home_keeper_profile_it_count_profile_tasks"


def _registry_entry(ha, unique_id: str) -> dict | None:
    for entry in entity_registry(ha):
        if entry.get("unique_id") == unique_id:
            return entry
    return None


def _poll(fn, timeout=25):
    """Wait for *fn* to return something truthy across a config-entry reload."""
    deadline = time.monotonic() + timeout
    result = None
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(1)
    return result


def test_all_tasks_sensor_exists_and_counts_overdue(ha):
    """The all-of-Home-Keeper sensor is always there, and its state is the count."""
    state = _poll(lambda: get_state(ha, _ALL_SENSOR))
    assert state, f"{_ALL_SENSOR} should exist on every install"
    assert state["state"].isdigit(), f"state should be a count, got {state['state']!r}"

    attrs = state["attributes"]
    # The published attribute contract, as a template author sees it.
    for key in ("total", "overdue", "due_soon", "due_today"):
        assert isinstance(attrs.get(key), int), f"{key} should be an int: {attrs}"
    for key in ("next_due", "next_task_name", "next_task_id", "most_overdue_days"):
        assert key in attrs, f"{key} should be published even when empty: {attrs}"
    # It counts every task, so it can never report more overdue than it has tasks.
    assert attrs["overdue"] <= attrs["total"]
    assert int(state["state"]) == attrs["overdue"], (
        "the all-tasks sensor's state is the overdue count"
    )


def test_service_device_survives_the_device_passes(ha):
    """The "Home Keeper" service device is registered and is never pruned.

    ``async_prune_orphaned_devices`` runs on every setup and drops our config entry
    from any non-asset device carrying none of our entities. This device is not an
    asset device, so it is checked rather than skipped, and only the unconditional
    all-tasks sensor keeps it alive.
    """
    device = _poll(lambda: find_device(ha, "home_keeper", "service"))
    assert device, "the Home Keeper service device should be registered"
    assert device.get("entry_type") == "service", (
        f"it should not render as hardware: {device}"
    )

    entities = entities_for_device(ha, device["id"])
    unique_ids = {e.get("unique_id") for e in entities}
    assert "home_keeper_tasks" in unique_ids, (
        f"the all-tasks sensor should live on the service device: {unique_ids}"
    )

    # Force a reload, so both device passes run again, and confirm it is still there.
    call_service(ha, "home_keeper", "set_options", {"allow_snooze": True})
    device = _poll(lambda: find_device(ha, "home_keeper", "service"))
    assert device, "the service device should survive a setup with the device passes"


def test_profile_sensor_lifecycle(ha):
    """A profile's sensor appears, keeps its entity id on rename, and is pruned."""
    call_service(ha, "home_keeper", "set_options", {"profiles": [_PROFILE]})
    try:
        entry = _poll(lambda: _registry_entry(ha, _PROFILE_UID))
        assert entry, "saving a profile should create its count sensor"
        entity_id = entry["entity_id"]
        assert entity_id.startswith("sensor."), entity_id

        state = _poll(lambda: get_state(ha, entity_id))
        assert state, f"{entity_id} should have a state"
        # This profile's status is "all", so its state is the size of its scope.
        assert int(state["state"]) == state["attributes"]["total"]

        # A rename must not move the entity: the unique id is keyed on the profile id,
        # which is what keeps a dashboard badge working across an edit.
        renamed = {**_PROFILE, "name": "Count probe renamed"}
        call_service(ha, "home_keeper", "set_options", {"profiles": [renamed]})
        entry = _poll(lambda: _registry_entry(ha, _PROFILE_UID))
        assert entry and entry["entity_id"] == entity_id, (
            "renaming a profile must keep its entity id"
        )
    finally:
        call_service(ha, "home_keeper", "set_options", {"profiles": []})

    # Deleting the profile removes the registry entry rather than leaving it
    # "unavailable" on the device page.
    gone = _poll(lambda: _registry_entry(ha, _PROFILE_UID) is None)
    assert gone, "deleting a profile should remove its count sensor registry entry"
    # The all-tasks sensor is untouched by any of that.
    assert get_state(ha, _ALL_SENSOR), "the all-tasks sensor should still be there"
