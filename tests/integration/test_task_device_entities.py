"""The ``task_device_entities`` option disables the per-task entities (#496).

Off sets ``disabled_by=integration`` on each enabled per-task entity in the entity
registry, with no entry reload, so the logbook gets no ``unavailable`` row. A new task
then gets disabled entities. On enables only what the option disabled: an entity that
the user disabled stays disabled. The entity ids stay through off and on.
"""

import time
from datetime import UTC, datetime

from conftest import HA_URL, call_service, get_state
from ha_registry import entity_registry, find_device, ws_send

STUB_DOMAIN = "home_keeper_battery_notes"
STUB_DEVICE_KEY = "e2e_battery_device"
SUFFIXES = ("_done", "_next_due", "_overdue")


def _task_entries(ha, task_id: str) -> dict[str, dict]:
    """The registry entries of the per-task entities of *task_id*, by suffix."""
    found = {}
    for entry in entity_registry(ha):
        uid = entry.get("unique_id") or ""
        for suffix in SUFFIXES:
            if uid == f"home_keeper_{task_id}{suffix}":
                found[suffix] = entry
    return found


def _wait_entries(ha, task_id: str, check, timeout: int = 60) -> dict[str, dict]:
    deadline = time.monotonic() + timeout
    entries: dict[str, dict] = {}
    while time.monotonic() < deadline:
        entries = _task_entries(ha, task_id)
        if len(entries) == 3 and check(entries):
            return entries
        time.sleep(1)
    raise AssertionError(f"registry entries of {task_id} did not settle: {entries}")


def _add_task(ha, name: str, device_id: str) -> str:
    resp = call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": name,
            "recurrence_type": "floating",
            "interval": 3,
            "unit": "months",
            "device_id": device_id,
        },
        return_response=True,
    )
    return resp.get("service_response", resp)["task_id"]


def _set_disabled_by(ha, entity_id: str, disabled_by: str | None) -> None:
    token = ha.headers["Authorization"].split(" ", 1)[1]
    msg = ws_send(
        token,
        {
            "type": "config/entity_registry/update",
            "entity_id": entity_id,
            "disabled_by": disabled_by,
        },
    )
    assert msg.get("success"), msg


def _unavailable_rows(ha, entity_ids: set[str], start: datetime) -> list[str]:
    r = ha.get(
        f"{HA_URL}/api/logbook/{start.isoformat()}",
        params={"end_time": datetime.now(UTC).isoformat()},
    )
    r.raise_for_status()
    return [
        row["entity_id"]
        for row in r.json()
        if row.get("entity_id") in entity_ids and row.get("state") == "unavailable"
    ]


def _hk_entities(ha) -> set[str]:
    r = ha.post(
        f"{HA_URL}/api/template",
        json={"template": "{{ integration_entities('home_keeper') | list | tojson }}"},
    )
    r.raise_for_status()
    return set(r.json())


def test_the_switch_disables_and_enables_the_task_entities(ha):
    device = find_device(ha, STUB_DOMAIN, STUB_DEVICE_KEY)
    assert device is not None, "the battery-notes stub should own a device"
    task_id = _add_task(ha, "Device entities switch probe", device["id"])
    later_id = None
    try:
        before = _wait_entries(
            ha, task_id, lambda e: all(x["disabled_by"] is None for x in e.values())
        )
        ids = {suffix: e["entity_id"] for suffix, e in before.items()}
        # The user disables 1 entity by hand before the switch.
        _set_disabled_by(ha, ids["_next_due"], "user")
        _wait_entries(ha, task_id, lambda e: e["_next_due"]["disabled_by"] == "user")
        entities = _hk_entities(ha)

        start = datetime.now(UTC)
        call_service(ha, "home_keeper", "set_options", {"task_device_entities": False})
        off = _task_entries(ha, task_id)
        assert off["_done"]["disabled_by"] == "integration"
        assert off["_overdue"]["disabled_by"] == "integration"
        assert off["_next_due"]["disabled_by"] == "user"
        # The ids stay, and no entity was written unavailable: there was no reload.
        assert {s: e["entity_id"] for s, e in off.items()} == ids
        time.sleep(5)
        assert _unavailable_rows(ha, entities, start) == []
        assert get_state(ha, ids["_overdue"]) is None

        # A new task while the switch is off gets disabled entities.
        later_id = _add_task(ha, "Device entities switch later", device["id"])
        _wait_entries(
            ha,
            later_id,
            lambda e: all(x["disabled_by"] == "integration" for x in e.values()),
        )

        call_service(ha, "home_keeper", "set_options", {"task_device_entities": True})
        on = _task_entries(ha, task_id)
        assert on["_done"]["disabled_by"] is None
        assert on["_overdue"]["disabled_by"] is None
        assert on["_next_due"]["disabled_by"] == "user"
        assert {s: e["entity_id"] for s, e in on.items()} == ids
        # Home Assistant reloads the entry about 30 seconds after an enable, and that
        # adds the entities again.
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline and get_state(ha, ids["_overdue"]) is None:
            time.sleep(2)
        assert get_state(ha, ids["_overdue"]) is not None
    finally:
        call_service(ha, "home_keeper", "set_options", {"task_device_entities": True})
        for tid in (task_id, later_id):
            if tid:
                call_service(ha, "home_keeper", "delete_task", {"task_id": tid})
