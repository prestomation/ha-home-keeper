"""Integration tests for the event entities against a real HA container.

The fixture's garage water heater is a virtual appliance with an attached task
("Replace Anode rod") and stocked parts. Its device gets a Home Keeper events
entity, and the Home Keeper service device gets the global entity. The tests run
services and read the entity states over REST. An automation in
``ha_config/configuration.yaml`` uses the Event received trigger on the water
heater entity, and writes what it saw to ``input_text.hk_last_event_entity_event``.
"""

from __future__ import annotations

import time

from conftest import call_service, get_state
from ha_registry import device_registry, entity_registry, has_identifier

GLOBAL = "event.home_keeper_events"


def _assets(ha):
    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    return resp.get("service_response", resp)["assets"]


def _tasks(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def _water_heater(ha):
    return next(a for a in _assets(ha) if a["name"] == "Garage water heater")


def _device_entity(ha, device_id: str) -> dict:
    uid = f"home_keeper_device_{device_id}_events"
    matches = [
        e
        for e in entity_registry(ha)
        if e["platform"] == "home_keeper" and e["unique_id"] == uid
    ]
    assert len(matches) == 1, f"no event entity for {device_id}"
    return matches[0]


def _wait_for(ha, entity_id, check, timeout=20):
    deadline = time.monotonic() + timeout
    state = None
    while time.monotonic() < deadline:
        state = get_state(ha, entity_id)
        if state is not None and check(state):
            return state
        time.sleep(0.5)
    raise AssertionError(f"{entity_id} did not match in time; last state: {state}")


def test_event_entities_exist_on_the_right_devices(ha):
    heater = _water_heater(ha)
    entry = _device_entity(ha, heater["device_id"])
    assert entry["device_id"] == heater["device_id"]
    assert entry["entity_id"] == "event.garage_water_heater_home_keeper_events"

    state = get_state(ha, entry["entity_id"])
    types = state["attributes"]["event_types"]
    assert "task_completed" in types
    assert "part_low_stock" in types
    assert "asset_archived" in types
    assert "companion_connected" not in types

    glob = get_state(ha, GLOBAL)
    assert glob is not None
    assert "companion_connected" in glob["attributes"]["event_types"]
    assert "task_created" in glob["attributes"]["event_types"]
    service_device = next(
        d for d in device_registry(ha) if has_identifier(d, "home_keeper", "service")
    )
    glob_entry = next(e for e in entity_registry(ha) if e["entity_id"] == GLOBAL)
    assert glob_entry["device_id"] == service_device["id"]


def test_a_completion_reaches_the_device_entity_and_the_global_entity(ha):
    heater = _water_heater(ha)
    entity_id = _device_entity(ha, heater["device_id"])["entity_id"]
    task = next(t for t in _tasks(ha) if t["name"].startswith("Replace Anode rod"))
    before = get_state(ha, entity_id)["state"]

    call_service(
        ha,
        "home_keeper",
        "complete_task",
        {"task_id": task["id"], "origin": "event_entity_test", "note": "secret"},
    )
    state = _wait_for(
        ha,
        entity_id,
        lambda s: (
            s["state"] != before
            and s["attributes"].get("event_type") == "task_completed"
        ),
    )
    attrs = state["attributes"]
    assert attrs["task_id"] == task["id"]
    assert attrs["device_id"] == heater["device_id"]
    assert attrs["origin"] == "event_entity_test"
    # A long note stays on the bus event only; the recorder keeps each event.
    assert "note" not in attrs
    assert "source" not in attrs

    glob = _wait_for(
        ha,
        GLOBAL,
        lambda s: (
            s["attributes"].get("event_type") == "task_completed"
            and s["attributes"].get("task_id") == task["id"]
        ),
    )
    assert glob["attributes"]["origin"] == "event_entity_test"

    # The automation with the Event received trigger ran.
    _wait_for(
        ha,
        "input_text.hk_last_event_entity_event",
        lambda s: s["state"] == f"task_completed:{task['id']}",
    )

    # Undo the completion, so the shared fixture is as it was.
    completed = next(t for t in _tasks(ha) if t["id"] == task["id"])
    ts = completed["completions"][-1]["ts"]
    call_service(
        ha, "home_keeper", "delete_completion", {"task_id": task["id"], "ts": ts}
    )
    _wait_for(
        ha, entity_id, lambda s: s["attributes"].get("event_type") == "task_uncompleted"
    )


def test_a_standalone_task_reaches_only_the_global_entity(ha):
    heater = _water_heater(ha)
    entity_id = _device_entity(ha, heater["device_id"])["entity_id"]
    before = get_state(ha, entity_id)["state"]
    task = next(t for t in _tasks(ha) if not t.get("device_id") and t.get("enabled"))

    call_service(ha, "home_keeper", "skip_task", {"task_id": task["id"]})
    _wait_for(
        ha,
        GLOBAL,
        lambda s: (
            s["attributes"].get("event_type") == "task_skipped"
            and s["attributes"].get("task_id") == task["id"]
        ),
    )
    assert get_state(ha, entity_id)["state"] == before


def test_a_stock_crossing_reaches_the_appliance_entity(ha):
    heater = _water_heater(ha)
    entity_id = _device_entity(ha, heater["device_id"])["entity_id"]
    part = next(p for p in heater["parts"] if p["name"] == "Sediment pre-filter")
    start = part["stock"]
    assert start > part["reorder_at"], "the fixture part must start above its threshold"
    drop = part["reorder_at"] - start

    call_service(
        ha,
        "home_keeper",
        "adjust_part_stock",
        {"asset_id": heater["id"], "part_id": part["id"], "delta": drop},
    )
    try:
        state = _wait_for(
            ha,
            entity_id,
            lambda s: (
                s["attributes"].get("event_type") == "part_low_stock"
                and s["attributes"].get("part_id") == part["id"]
            ),
        )
        assert state["attributes"]["asset_id"] == heater["id"]
        _wait_for(
            ha,
            "input_text.hk_last_event_entity_event",
            lambda s: s["state"] == f"part_low_stock:{part['id']}",
        )
    finally:
        call_service(
            ha,
            "home_keeper",
            "adjust_part_stock",
            {"asset_id": heater["id"], "part_id": part["id"], "delta": -drop},
        )
    _wait_for(
        ha, entity_id, lambda s: s["attributes"].get("event_type") == "part_restocked"
    )
