"""Integration test: the Home Keeper card is registered as a Lovelace resource.

The card used to be injected via ``frontend.add_extra_js_url``; it is now a
storage-mode Lovelace *module resource* (see ``card.py``). This asserts, against
the real HA container, that exactly one such resource exists with the canonical
bundle URL — the storage-mode half of the refactor (spec AC-002).
"""

import json

import websockets.sync.client
from conftest import HA_URL

_WS_URL = HA_URL.replace("http://", "ws://") + "/api/websocket"
_CARD_BASE_URL = "/home_keeper_panel/home-keeper-card.js"


def _lovelace_resources(ha):
    token = ha.headers["Authorization"].split(" ", 1)[1]
    with websockets.sync.client.connect(_WS_URL) as ws:
        assert json.loads(ws.recv())["type"] == "auth_required"
        ws.send(json.dumps({"type": "auth", "access_token": token}))
        assert json.loads(ws.recv())["type"] == "auth_ok"
        ws.send(json.dumps({"id": 1, "type": "lovelace/resources"}))
        msg = json.loads(ws.recv())
    assert msg.get("success"), f"lovelace/resources failed: {msg}"
    return msg["result"]


def test_card_registered_as_single_module_resource(ha):
    resources = _lovelace_resources(ha)
    ours = [
        r
        for r in resources
        if str(r.get("url", "")).split("?", 1)[0] == _CARD_BASE_URL
    ]
    assert len(ours) == 1, f"expected exactly one card resource, got {ours}"
    assert ours[0]["type"] == "module"
    # The cache-busting token keeps the URL fresh across rebuilds.
    assert ours[0]["url"].startswith(f"{_CARD_BASE_URL}?v=")
