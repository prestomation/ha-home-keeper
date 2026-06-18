"""Integration tests for Home Keeper's bus events against a real HA container.

Subscribes over the Home Assistant websocket API and asserts the lifecycle and stock
events fire with the right payloads when the corresponding services are called. The
time-based transition events (overdue / due-soon) are covered by the pure unit tests
(``tests/unit/test_transitions.py``) since they depend on the coordinator's periodic
refresh; here we cover the deterministic, mutation-driven events.
"""

import asyncio
import json

import pytest
import websockets
from conftest import HA_URL, call_service

WS_URL = "ws://localhost:8123/api/websocket"


async def _capture(token, event_types, action, *, expected, timeout=20):
    """Subscribe to *event_types*, run *action* (sync), return captured events.

    Returns a list of ``(event_type, data)`` in arrival order, stopping once
    *expected* events are seen or *timeout* elapses.
    """
    captured = []
    async with websockets.connect(WS_URL, max_size=None) as ws:
        assert json.loads(await ws.recv())["type"] == "auth_required"
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        assert json.loads(await ws.recv())["type"] == "auth_ok"

        msg_id = 0
        for event_type in event_types:
            msg_id += 1
            await ws.send(
                json.dumps(
                    {"id": msg_id, "type": "subscribe_events", "event_type": event_type}
                )
            )
            result = json.loads(await ws.recv())
            assert result["success"], result

        # Run the blocking REST action off the event loop, then drain events.
        await asyncio.get_event_loop().run_in_executor(None, action)

        async def _drain():
            while len(captured) < expected:
                msg = json.loads(await ws.recv())
                if msg.get("type") == "event":
                    ev = msg["event"]
                    captured.append((ev["event_type"], ev["data"]))

        try:
            await asyncio.wait_for(_drain(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
    return captured


def _run(token, event_types, action, *, expected, timeout=20):
    return asyncio.run(
        _capture(token, event_types, action, expected=expected, timeout=timeout)
    )


def _by_type(captured):
    out = {}
    for event_type, data in captured:
        out.setdefault(event_type, []).append(data)
    return out


def test_task_lifecycle_events(ha, ha_token):
    created_id = {}

    def action():
        resp = call_service(
            ha,
            "home_keeper",
            "add_task",
            {"name": "Event test task", "recurrence_type": "floating",
             "interval": 7, "unit": "days"},
            return_response=True,
        )
        body = resp.get("service_response", resp)
        created_id["id"] = body["task_id"]
        call_service(ha, "home_keeper", "update_task",
                     {"task_id": body["task_id"], "name": "Renamed task"})
        call_service(ha, "home_keeper", "complete_task", {"task_id": body["task_id"]})
        call_service(ha, "home_keeper", "delete_task", {"task_id": body["task_id"]})

    events = _by_type(
        _run(
            ha_token,
            [
                "home_keeper_task_created",
                "home_keeper_task_updated",
                "home_keeper_task_completed",
                "home_keeper_task_deleted",
            ],
            action,
            expected=4,
        )
    )

    assert "home_keeper_task_created" in events
    assert events["home_keeper_task_created"][0]["name"] == "Event test task"
    # Spine fields are present on the lifecycle payload.
    created = events["home_keeper_task_created"][0]
    assert created["recurrence_type"] == "floating"
    assert "next_due" in created and "enabled" in created

    assert events["home_keeper_task_updated"][0]["changed_fields"] == ["name"]
    assert events["home_keeper_task_completed"][0]["task_id"] == created_id["id"]
    assert "completed_at" in events["home_keeper_task_completed"][0]
    assert events["home_keeper_task_deleted"][0]["task_id"] == created_id["id"]


def test_stock_transition_events(ha, ha_token):
    """A part driven low -> out -> restocked fires one event per crossing."""
    ids = {}

    def setup_asset():
        call_service(
            ha,
            "home_keeper",
            "add_asset",
            {
                "name": "Event test appliance",
                "parts": [
                    {"name": "Widget", "type": "consumable", "stock": 2, "reorder_at": 1}
                ],
            },
        )
        assets = call_service(
            ha, "home_keeper", "list_assets", {}, return_response=True
        )
        body = assets.get("service_response", assets)
        asset = next(a for a in body["assets"] if a["name"] == "Event test appliance")
        ids["asset_id"] = asset["id"]
        ids["part_id"] = asset["parts"][0]["id"]

    setup_asset()

    def action():
        # 2 -> 1 (low), 1 -> 0 (out), 0 -> 5 (restocked).
        for delta in (-1, -1, 5):
            call_service(
                ha,
                "home_keeper",
                "adjust_part_stock",
                {"asset_id": ids["asset_id"], "part_id": ids["part_id"], "delta": delta},
            )

    events = _by_type(
        _run(
            ha_token,
            [
                "home_keeper_part_low_stock",
                "home_keeper_part_out_of_stock",
                "home_keeper_part_restocked",
            ],
            action,
            expected=3,
        )
    )

    assert events["home_keeper_part_low_stock"][0]["part_name"] == "Widget"
    assert events["home_keeper_part_out_of_stock"][0]["stock"] == 0
    assert "home_keeper_part_restocked" in events

    # Clean up the asset we created.
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": ids["asset_id"]})


async def _ws_commands(token, commands):
    """Open one authed websocket, send each command dict (id auto-assigned), return results."""
    results = []
    async with websockets.connect(WS_URL, max_size=None) as ws:
        assert json.loads(await ws.recv())["type"] == "auth_required"
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        assert json.loads(await ws.recv())["type"] == "auth_ok"
        msg_id = 0
        for command in commands:
            msg_id += 1
            await ws.send(json.dumps({"id": msg_id, **command}))
            reply = json.loads(await ws.recv())
            results.append(reply)
    return results


def test_device_triggers_offered_for_appliance_and_task_devices(ha, ha_token):
    """async_get_triggers offers Home Keeper triggers on the right devices."""
    (devices_reply,) = _run_ws(
        ha_token, [{"type": "config/device_registry/list"}]
    )
    devices = devices_reply["result"]

    def _is_hk(device):
        return any(
            (pair[0] if isinstance(pair, (list, tuple)) else None) == "home_keeper"
            for pair in device.get("identifiers", [])
        )

    hk_devices = [d for d in devices if _is_hk(d)]
    assert hk_devices, "expected at least one Home Keeper registry device"

    # Fetch the triggers for every HK device and collect the trigger types per device.
    replies = _run_ws(
        ha_token,
        [
            {"type": "device_automation/trigger/list", "device_id": d["id"]}
            for d in hk_devices
        ],
    )
    all_types = set()
    for reply in replies:
        for trig in reply["result"]:
            if trig.get("domain") == "home_keeper":
                all_types.add(trig["type"])

    # The seeded config has both a virtual appliance (with stocked wear parts) and
    # task devices, so across all HK devices we expect both task and stock triggers.
    assert "task_overdue" in all_types
    assert "part_low_stock" in all_types
    assert "part_out_of_stock" in all_types


def _run_ws(token, commands):
    return asyncio.run(_ws_commands(token, commands))


def test_asset_lifecycle_events(ha, ha_token):
    def action():
        call_service(ha, "home_keeper", "add_asset", {"name": "Asset event appliance"})

    events = _by_type(
        _run(ha_token, ["home_keeper_asset_created"], action, expected=1)
    )
    assert events["home_keeper_asset_created"][0]["asset_name"] == "Asset event appliance"

    # Find and delete it, asserting the deletion event.
    assets = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    body = assets.get("service_response", assets)
    asset_id = next(
        a["id"] for a in body["assets"] if a["name"] == "Asset event appliance"
    )

    def delete():
        call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset_id})

    events = _by_type(
        _run(ha_token, ["home_keeper_asset_deleted"], delete, expected=1)
    )
    assert events["home_keeper_asset_deleted"][0]["asset_id"] == asset_id
