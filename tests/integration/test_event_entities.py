"""Integration tests for the global event entity against a real HA container.

The Home Keeper service device has 1 event entity, ``event.home_keeper_events``.
It gets every bus event that has a payload. No other device gets an event entity.
The tests run services and read the entity state over REST. On Home Assistant
2026.7 or later, the ``event_trigger_automation`` fixture also adds an automation
with the Event received trigger on the global entity. It writes what it saw to
``input_text.hk_last_event_entity_event``. Older versions have no such trigger, so
the tests skip that one check and keep every entity check.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import yaml
from conftest import HA_URL, call_service, get_state
from ha_registry import device_registry, entity_registry, has_identifier
from packaging.version import Version

GLOBAL = "event.home_keeper_events"

# The Event received trigger (``trigger: event.received``) is new in this version.
EVENT_TRIGGER_MIN = (2026, 7)
AUTOMATION_ID = "hk_capture_event_entity"
AUTOMATION_ENTITY = "automation.capture_home_keeper_event_entity"
CAPTURE = "input_text.hk_last_event_entity_event"


@pytest.fixture
def event_trigger_automation(ha):
    """Add an automation with the Event received trigger. Return True if it is on.

    Return False on a Home Assistant that has no such trigger. The automation is
    stored through the REST config API and removed again after the test.
    """
    version = Version(ha.get(f"{HA_URL}/api/config").json()["version"])
    if version.release[:2] < EVENT_TRIGGER_MIN:
        yield False
        return
    url = f"{HA_URL}/api/config/automation/config/{AUTOMATION_ID}"
    config = {
        "alias": "Capture Home Keeper event entity",
        "triggers": [
            {
                "trigger": "event.received",
                "target": {"entity_id": GLOBAL},
                "options": {"event_type": ["task_completed", "part_low_stock"]},
            }
        ],
        "actions": [
            {
                "action": "input_text.set_value",
                "target": {"entity_id": CAPTURE},
                "data": {
                    "value": (
                        "{{ trigger.to_state.attributes.event_type }}:"
                        "{{ trigger.to_state.attributes.task_id"
                        " | default(trigger.to_state.attributes.part_id) }}"
                    )
                },
            }
        ],
    }
    ha.post(url, json=config).raise_for_status()
    _wait_for(ha, AUTOMATION_ENTITY, lambda s: s["state"] == "on")
    try:
        yield True
    finally:
        ha.delete(url).raise_for_status()


def _assets(ha):
    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    return resp.get("service_response", resp)["assets"]


def _tasks(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def _water_heater(ha):
    return next(a for a in _assets(ha) if a["name"] == "Garage water heater")


def _payload_event_types() -> set[str]:
    """Each event with a payload, from the trigger list that the model writes."""
    path = (
        Path(__file__).resolve().parents[2]
        / "custom_components"
        / "home_keeper"
        / "triggers.yaml"
    )
    return {key for key in yaml.safe_load(path.read_text()) if key[0] != "."}


def _wait_for(ha, entity_id, check, timeout=20):
    deadline = time.monotonic() + timeout
    state = None
    while time.monotonic() < deadline:
        state = get_state(ha, entity_id)
        if state is not None and check(state):
            return state
        time.sleep(0.5)
    raise AssertionError(f"{entity_id} did not match in time; last state: {state}")


def test_only_the_global_event_entity_exists(ha):
    events = [
        e
        for e in entity_registry(ha)
        if e["platform"] == "home_keeper" and e["entity_id"].startswith("event.")
    ]
    assert [e["entity_id"] for e in events] == [GLOBAL]
    service_device = next(
        d for d in device_registry(ha) if has_identifier(d, "home_keeper", "service")
    )
    assert events[0]["device_id"] == service_device["id"]
    assert events[0]["unique_id"] == "home_keeper_events"


def test_global_entity_mirrors_every_event_with_a_payload(ha):
    glob = get_state(ha, GLOBAL)
    assert glob is not None
    assert set(glob["attributes"]["event_types"]) == _payload_event_types()
    assert "register_companions" not in glob["attributes"]["event_types"]


def test_a_completion_reaches_the_global_entity(ha, event_trigger_automation):
    heater = _water_heater(ha)
    entity_id = GLOBAL
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

    if event_trigger_automation:
        # The automation with the Event received trigger ran.
        _wait_for(ha, CAPTURE, lambda s: s["state"] == f"task_completed:{task['id']}")

    # Undo the completion, so the shared fixture is as it was.
    completed = next(t for t in _tasks(ha) if t["id"] == task["id"])
    ts = completed["completions"][-1]["ts"]
    call_service(
        ha, "home_keeper", "delete_completion", {"task_id": task["id"], "ts": ts}
    )
    _wait_for(
        ha, entity_id, lambda s: s["attributes"].get("event_type") == "task_uncompleted"
    )


def test_a_standalone_task_reaches_the_global_entity(ha):
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


def test_a_stock_crossing_reaches_the_global_entity(ha, event_trigger_automation):
    heater = _water_heater(ha)
    entity_id = GLOBAL
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
        if event_trigger_automation:
            _wait_for(
                ha, CAPTURE, lambda s: s["state"] == f"part_low_stock:{part['id']}"
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
