"""Integration coverage for the cost sensors (#460).

The unit tier proves the arithmetic. What only a real Home Assistant can prove:

* the sensors are on the service device, with the monetary device class and the
  currency of the instance as the unit;
* a completion with a cost moves the spend totals;
* a new window adds a sensor, and a removed window's registry entry is pruned, over the
  real options-write-then-reload path.
"""

import time

from conftest import call_service, get_state
from ha_registry import entities_for_device, entity_registry, find_device

_UIDS = (
    "home_keeper_spend_30d",
    "home_keeper_spend_60d",
    "home_keeper_spend_all",
    "home_keeper_purchases",
)


def _registry_entry(ha, unique_id: str) -> dict | None:
    for entry in entity_registry(ha):
        if entry.get("unique_id") == unique_id:
            return entry
    return None


def _poll(fn, timeout=25):
    deadline = time.monotonic() + timeout
    result = None
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(1)
    return result


def test_cost_sensors_are_on_the_service_device(ha):
    device = _poll(lambda: find_device(ha, "home_keeper", "service"))
    assert device, "the Home Keeper service device should be registered"
    unique_ids = {e.get("unique_id") for e in entities_for_device(ha, device["id"])}
    for uid in _UIDS:
        assert uid in unique_ids, f"{uid} should be on the service device: {unique_ids}"
        entry = _registry_entry(ha, uid)
        state = _poll(lambda eid=entry["entity_id"]: get_state(ha, eid))
        assert state, f"{uid} should have a state"
        assert state["attributes"].get("device_class") == "monetary", state
        assert isinstance(state["attributes"].get("count"), int), state
        float(state["state"])


def test_a_completion_cost_moves_the_spend(ha):
    entity_id = _poll(lambda: _registry_entry(ha, "home_keeper_spend_30d"))["entity_id"]
    all_id = _registry_entry(ha, "home_keeper_spend_all")["entity_id"]
    before = float(get_state(ha, entity_id)["state"])
    before_all = float(get_state(ha, all_id)["state"])

    created = call_service(
        ha,
        "home_keeper",
        "add_task",
        {"name": "IT cost probe", "interval": 30, "unit": "days"},
        return_response=True,
    )
    task_id = created.get("service_response", created)["task_id"]
    try:
        call_service(
            ha, "home_keeper", "complete_task", {"task_id": task_id, "cost": 12.5}
        )
        moved = _poll(
            lambda: (
                abs(float(get_state(ha, entity_id)["state"]) - (before + 12.5)) < 0.001
            )
        )
        assert moved, "the 30-day spend should count the new cost"
        assert abs(float(get_state(ha, all_id)["state"]) - (before_all + 12.5)) < 0.001
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})

    # A deleted standalone task keeps no history, so its cost leaves the totals.
    back = _poll(lambda: abs(float(get_state(ha, entity_id)["state"]) - before) < 0.001)
    assert back, "deleting the task should take its cost out of the spend"


def test_window_sensors_follow_the_option(ha):
    call_service(ha, "home_keeper", "set_options", {"cost_windows": [7, 30]})
    try:
        assert _poll(lambda: _registry_entry(ha, "home_keeper_spend_7d")), (
            "a new window should add its sensor"
        )
        gone = _poll(lambda: _registry_entry(ha, "home_keeper_spend_60d") is None)
        assert gone, "a removed window should prune its sensor"
        assert _registry_entry(ha, "home_keeper_spend_30d"), "a kept window stays"
    finally:
        call_service(ha, "home_keeper", "set_options", {"cost_windows": [30, 60]})
    assert _poll(lambda: _registry_entry(ha, "home_keeper_spend_60d"))
    assert _poll(lambda: _registry_entry(ha, "home_keeper_spend_7d") is None)


def test_duplicate_windows_count_once_for_the_cap(ha):
    # 5 items but 3 days: the service drops duplicates before it checks the cap of 4.
    call_service(
        ha, "home_keeper", "set_options", {"cost_windows": [30, 30, 60, 60, 90]}
    )
    try:
        assert _poll(lambda: _registry_entry(ha, "home_keeper_spend_90d")), (
            "a list with duplicates should still set its windows"
        )
    finally:
        call_service(ha, "home_keeper", "set_options", {"cost_windows": [30, 60]})
    assert _poll(lambda: _registry_entry(ha, "home_keeper_spend_90d") is None)
