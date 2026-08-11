"""Shared websocket helpers for reading HA's device and entity registries.

The registries are not exposed over the REST API, so registry-level assertions have
to go through the websocket API. ``test_device_cleanup.py`` and
``test_entity_cleanup.py`` each grew a private copy of this; ``test_device_attach.py``
would have been the third, so it lives here instead.
"""

from __future__ import annotations

import json
from typing import Any

import websockets.sync.client
from conftest import HA_URL

_WS_URL = HA_URL.replace("http://", "ws://") + "/api/websocket"


def ws_command(ha, command_type: str) -> Any:
    """Run a single no-argument websocket command and return its result."""
    token = ha.headers["Authorization"].split(" ", 1)[1]
    with websockets.sync.client.connect(_WS_URL) as ws:
        # HA sends auth_required first.
        msg = json.loads(ws.recv())
        assert msg["type"] == "auth_required"
        ws.send(json.dumps({"type": "auth", "access_token": token}))
        msg = json.loads(ws.recv())
        assert msg["type"] == "auth_ok", f"auth failed: {msg}"
        ws.send(json.dumps({"id": 1, "type": command_type}))
        msg = json.loads(ws.recv())
        assert msg.get("success"), f"{command_type} failed: {msg}"
        return msg["result"]


def device_registry(ha) -> list[dict]:
    """Every device registry entry."""
    return ws_command(ha, "config/device_registry/list")


def entity_registry(ha) -> list[dict]:
    """Every entity registry entry."""
    return ws_command(ha, "config/entity_registry/list")


def has_identifier(device: dict, domain: str, value: str) -> bool:
    """True if *device* carries the ``(domain, value)`` registry identifier.

    Identifiers come back over the websocket as a list of ``[domain, id]`` pairs
    rather than tuples, hence the explicit ``list()`` coercion.
    """
    return any(
        list(ident) == [domain, value] for ident in device.get("identifiers", [])
    )


def find_device(ha, domain: str, value: str) -> dict | None:
    """The device carrying ``(domain, value)``, or None."""
    for device in device_registry(ha):
        if has_identifier(device, domain, value):
            return device
    return None


def entities_for_device(ha, device_id: str) -> list[dict]:
    """Every entity registry entry whose ``device_id`` is *device_id*."""
    return [e for e in entity_registry(ha) if e.get("device_id") == device_id]
