"""Integration tests for the Home Keeper triggers against a real HA container.

Each test stores an automation through the REST config API, with Home Keeper
triggers (``trigger: home_keeper.<event>``) and 1 action. The action adds
``<trigger id>:<first 8 characters of the id>`` to ``input_text.hk_last_trigger``,
so a test reads every trigger that fired for 1 change. The automation runs in
``queued`` mode, so 2 triggers on 1 event both write.

The fixture has 3 kinds of device: the garage water heater (a virtual appliance
with a task and parts), the self-owned device of "Replace water filter" (its
device_id is not in the registry), and the battery-notes stub device that another
integration owns. "Rex: Vet checkup" is a standalone task with the label ``dog``.
The same tests run on the oldest Home Assistant and on stable.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from conftest import HA_URL, call_service, get_state
from ha_registry import (
    device_registry,
    entities_for_device,
    entity_registry,
    find_device,
    has_identifier,
    ws_send,
)

CAPTURE = "input_text.hk_last_trigger"
STUB_DOMAIN = "home_keeper_battery_notes"
STUB_DEVICE_KEY = "e2e_battery_device"
_TRIGGERS_YAML = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "home_keeper"
    / "triggers.yaml"
)


def _trigger_keys() -> list[str]:
    data = yaml.safe_load(_TRIGGERS_YAML.read_text())
    return [key for key in data if not key.startswith(".")]


def _targeted(key: str) -> bool:
    data = yaml.safe_load(_TRIGGERS_YAML.read_text())
    return bool(data[key])


def _token(ha) -> str:
    return ha.headers["Authorization"].split(" ", 1)[1]


def _tasks(ha) -> list[dict]:
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def _assets(ha) -> list[dict]:
    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    return resp.get("service_response", resp)["assets"]


def _task(ha, prefix: str) -> dict:
    return next(t for t in _tasks(ha) if t["name"].startswith(prefix))


def _heater(ha) -> dict:
    return next(a for a in _assets(ha) if a["name"] == "Garage water heater")


def _service_device_id(ha) -> str:
    device = find_device(ha, "home_keeper", "service")
    assert device is not None
    return device["id"]


def _set_capture(ha, value: str) -> None:
    call_service(ha, "input_text", "set_value", {"entity_id": CAPTURE, "value": value})


def _fired(ha) -> set[str]:
    state = get_state(ha, CAPTURE)
    return set((state or {}).get("state", "").split())


def _wait_fired(ha, want: set[str], timeout: float = 20) -> set[str]:
    """Wait until every token in *want* is in the capture, then a bit more."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if want <= _fired(ha):
            # Give a trigger that must not fire the time to fire anyway.
            time.sleep(2)
            return _fired(ha)
        time.sleep(0.5)
    raise AssertionError(f"wanted {sorted(want)}; got {sorted(_fired(ha))}")


def _wait_automation_on(ha, entity_id: str, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = get_state(ha, entity_id)
        if state is not None and state["state"] == "on":
            return
        time.sleep(0.5)
    raise AssertionError(f"{entity_id} did not turn on")


@contextmanager
def _automation(ha, automation_id: str, triggers: list[dict]):
    """Store an automation with *triggers*, and remove it after the block."""
    url = f"{HA_URL}/api/config/automation/config/{automation_id}"
    value = (
        "{{ (states('" + CAPTURE + "') ~ ' ' ~ trigger.id ~ ':' ~ "
        "(trigger.event.data.task_id or trigger.event.data.part_id or "
        "trigger.event.data.asset_id or trigger.event.data.kind or '')[:8])"
        "[-250:] }}"
    )
    config = {
        "alias": f"HK trigger test {automation_id}",
        "mode": "queued",
        "max": 50,
        "triggers": triggers,
        "actions": [
            {
                "action": "input_text.set_value",
                "target": {"entity_id": CAPTURE},
                "data": {"value": value},
            }
        ],
    }
    ha.post(url, json=config).raise_for_status()
    _wait_automation_on(ha, f"automation.hk_trigger_test_{automation_id}")
    _set_capture(ha, "")
    try:
        yield
    finally:
        ha.delete(url).raise_for_status()
        _set_capture(ha, "")


def _hk(key: str, trigger_id: str, target: dict | None = None) -> dict:
    trigger = {"trigger": f"home_keeper.{key}", "id": trigger_id}
    if target is not None:
        trigger["target"] = target
    return trigger


def _complete(ha, task: dict) -> None:
    call_service(
        ha, "home_keeper", "complete_task", {"task_id": task["id"], "origin": "test"}
    )


def _uncomplete(ha, task_id: str) -> None:
    task = next(t for t in _tasks(ha) if t["id"] == task_id)
    ts = task["completions"][-1]["ts"]
    call_service(ha, "home_keeper", "delete_completion", {"task_id": task_id, "ts": ts})


@contextmanager
def _foreign_task(ha):
    """A task on the stub device that another integration owns."""
    stub = find_device(ha, STUB_DOMAIN, STUB_DEVICE_KEY)
    assert stub is not None, "the battery-notes stub device is missing"
    resp = call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Trigger probe on a foreign device",
            "recurrence_type": "floating",
            "interval": 3,
            "unit": "months",
            "device_id": stub["id"],
        },
        return_response=True,
    )
    task_id = resp.get("service_response", resp)["task_id"]
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if any(
                e.get("platform") == "home_keeper"
                for e in entities_for_device(ha, stub["id"])
            ):
                break
            time.sleep(1)
        yield stub["id"], task_id
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})


# ── The trigger list ─────────────────────────────────────────────────────────


def test_every_trigger_validates_in_home_assistant(ha):
    """Home Assistant knows each trigger, and a target is required where it must be."""
    service = _service_device_id(ha)
    keys = _trigger_keys()
    assert len(keys) == 31
    triggers = [
        _hk(key, key, {"device_id": service} if _targeted(key) else None)
        for key in keys
    ]
    reply = ws_send(_token(ha), {"type": "validate_config", "triggers": triggers})
    assert reply.get("success"), reply
    assert reply["result"]["triggers"] == {"valid": True, "error": None}

    missing = ws_send(
        _token(ha),
        {"type": "validate_config", "triggers": [_hk("task_completed", "x")]},
    )
    assert missing["result"]["triggers"]["valid"] is False


def test_every_trigger_attaches_and_the_service_device_means_every_event(ha):
    service = _service_device_id(ha)
    keys = _trigger_keys()
    triggers = [
        _hk(key, key, {"device_id": service} if _targeted(key) else None)
        for key in keys
    ]
    task = _task(ha, "Take medicine")
    with _automation(ha, "all", triggers):
        _complete(ha, task)
        fired = _wait_fired(ha, {f"task_completed:{task['id'][:8]}"})
        call_service(ha, "home_keeper", "export_data", {}, return_response=True)
        fired = _wait_fired(ha, {"data_exported:data"})
    _uncomplete(ha, task["id"])
    assert "task_completed:" + task["id"][:8] in fired


# ── Task triggers on each kind of device ─────────────────────────────────────


def test_task_trigger_on_each_kind_of_device_fires_for_its_task_only(ha):
    heater = _heater(ha)
    heater_task = _task(ha, "Replace Anode rod")
    filter_task = _task(ha, "Replace water filter")
    self_owned = find_device(ha, "home_keeper", filter_task["id"])
    assert self_owned is not None, "the self-owned device is missing"
    standalone = _task(ha, "Rex: Vet checkup")
    assert not standalone.get("device_id")

    with _foreign_task(ha) as (stub_id, foreign_id):
        triggers = [
            _hk("task_completed", "appliance", {"device_id": heater["device_id"]}),
            _hk("task_completed", "selfowned", {"device_id": self_owned["id"]}),
            _hk("task_completed", "foreign", {"device_id": stub_id}),
            _hk("task_completed", "label", {"label_id": "dog"}),
        ]
        with _automation(ha, "kinds", triggers):
            cases = [
                (heater_task["id"], "appliance"),
                (filter_task["id"], "selfowned"),
                (foreign_id, "foreign"),
                (standalone["id"], "label"),
            ]
            for task_id, trigger_id in cases:
                _set_capture(ha, "")
                call_service(
                    ha,
                    "home_keeper",
                    "complete_task",
                    {"task_id": task_id, "origin": "test"},
                )
                token = f"{trigger_id}:{task_id[:8]}"
                assert _wait_fired(ha, {token}) == {token}
                _uncomplete(ha, task_id)


def test_task_trigger_targets_an_entity(ha):
    heater = _heater(ha)
    task = _task(ha, "Replace Anode rod")
    overdue = next(
        e["entity_id"]
        for e in entity_registry(ha)
        if e["platform"] == "home_keeper"
        and e["unique_id"] == f"home_keeper_{task['id']}_overdue"
    )
    other = next(
        t
        for t in _tasks(ha)
        if t.get("device_id") == heater["device_id"] and t["id"] != task["id"]
    )
    with _automation(
        ha, "entity", [_hk("task_snoozed", "entity", {"entity_id": overdue})]
    ):
        call_service(
            ha, "home_keeper", "snooze_task", {"task_id": other["id"], "hours": 24}
        )
        call_service(
            ha, "home_keeper", "snooze_task", {"task_id": task["id"], "hours": 24}
        )
        token = f"entity:{task['id'][:8]}"
        assert _wait_fired(ha, {token}) == {token}


@pytest.fixture
def area(ha):
    """A new area, removed again after the test."""
    reply = ws_send(
        _token(ha), {"type": "config/area_registry/create", "name": "HK trigger area"}
    )
    assert reply.get("success"), reply
    area_id = reply["result"]["area_id"]
    try:
        yield area_id
    finally:
        ws_send(_token(ha), {"type": "config/area_registry/delete", "area_id": area_id})


def test_task_trigger_targets_an_area_by_device_and_by_task(ha, area):
    heater = _heater(ha)
    heater_task = _task(ha, "Replace Anode rod")
    standalone = _task(ha, "Take medicine")
    reply = ws_send(
        _token(ha),
        {
            "type": "config/device_registry/update",
            "device_id": heater["device_id"],
            "area_id": area,
        },
    )
    assert reply.get("success"), reply
    call_service(
        ha, "home_keeper", "update_task", {"task_id": standalone["id"], "area_id": area}
    )
    try:
        with _automation(ha, "area", [_hk("task_skipped", "area", {"area_id": area})]):
            call_service(ha, "home_keeper", "skip_task", {"task_id": heater_task["id"]})
            call_service(ha, "home_keeper", "skip_task", {"task_id": standalone["id"]})
            want = {f"area:{heater_task['id'][:8]}", f"area:{standalone['id'][:8]}"}
            assert _wait_fired(ha, want) == want
    finally:
        call_service(
            ha,
            "home_keeper",
            "update_task",
            {"task_id": standalone["id"], "area_id": ""},
        )
        ws_send(
            _token(ha),
            {
                "type": "config/device_registry/update",
                "device_id": heater["device_id"],
                "area_id": None,
            },
        )


# ── Part and appliance triggers ──────────────────────────────────────────────


def test_part_trigger_on_the_appliance_device(ha):
    heater = _heater(ha)
    part = next(p for p in heater["parts"] if p["name"] == "Sediment pre-filter")
    drop = part["reorder_at"] - part["stock"]
    assert drop < 0, "the fixture part must start above its threshold"
    triggers = [
        _hk("part_low_stock", "low", {"device_id": heater["device_id"]}),
        _hk("part_restocked", "back", {"device_id": heater["device_id"]}),
    ]
    with _automation(ha, "stock", triggers):
        args = {"asset_id": heater["id"], "part_id": part["id"], "delta": drop}
        call_service(ha, "home_keeper", "adjust_part_stock", args)
        try:
            assert _wait_fired(ha, {f"low:{part['id'][:8]}"})
        finally:
            call_service(
                ha, "home_keeper", "adjust_part_stock", {**args, "delta": -drop}
            )
        assert f"back:{part['id'][:8]}" in _wait_fired(ha, {f"back:{part['id'][:8]}"})


# ── Removed targets ──────────────────────────────────────────────────────────


def test_a_removed_device_or_task_matches_no_event_and_breaks_nothing(ha):
    task = _task(ha, "Take medicine")
    with _foreign_task(ha) as (_stub_id, foreign_id):
        overdue = next(
            e["entity_id"]
            for e in entity_registry(ha)
            if e["unique_id"] == f"home_keeper_{foreign_id}_overdue"
        )
    # The task is gone, so its entity is gone too. Target it and a missing device.
    triggers = [
        _hk("task_completed", "gone_entity", {"entity_id": overdue}),
        _hk("task_completed", "gone_device", {"device_id": "no_such_device"}),
        _hk("task_completed", "label", {"label_id": "dog"}),
    ]
    rex = _task(ha, "Rex: Vet checkup")
    with _automation(ha, "removed", triggers):
        _complete(ha, task)
        _complete(ha, rex)
        token = f"label:{rex['id'][:8]}"
        assert _wait_fired(ha, {token}) == {token}
    _uncomplete(ha, task["id"])
    _uncomplete(ha, rex["id"])
    assert not any(
        has_identifier(d, "home_keeper", foreign_id) for d in device_registry(ha)
    )
