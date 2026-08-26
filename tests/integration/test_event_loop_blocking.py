"""Integration test: nothing in Home Keeper reads a file on the event loop (#247).

The log the reporter of #247 pasted is Home Assistant's own blocking-call detector
catching ``backend_i18n`` opening its string tables straight from the loop thread:

    Detected blocking call to read_text with args
    (PosixPath('/config/custom_components/home_keeper/backend_strings/en.json'),)
    inside the event loop by custom integration 'home_keeper'

``backend_i18n`` deliberately has no Home Assistant import — the pure modules
(``problem_tasks``, ``inventory``, ``companions_catalog``) call it, so it cannot
reach for ``hass.async_add_executor_job`` itself — and its ``functools.cache`` only
helps *after* the first read. Those first reads land wherever the first caller
happens to be: the problem-sensor reconcile during setup, a websocket error reply,
a CSV export. ``notifier``'s equivalent was #150; this is the same bug in the other
half of the backend's string handling.

The assertion is the reporter's log itself, read back through ``/api/error_log``.
That covers every path in the integration, not just the two provoked below —
those exist so a refactor that stops resolving strings altogether can't make this
pass by doing nothing.
"""

import json

import websockets.sync.client
from conftest import HA_URL, call_service

_WS_URL = HA_URL.replace("http://", "ws://") + "/api/websocket"


def _ws_call(ha, payload: dict) -> dict:
    token = ha.headers["Authorization"].split(" ", 1)[1]
    with websockets.sync.client.connect(_WS_URL) as ws:
        assert json.loads(ws.recv())["type"] == "auth_required"
        ws.send(json.dumps({"type": "auth", "access_token": token}))
        assert json.loads(ws.recv())["type"] == "auth_ok"
        ws.send(json.dumps({"id": 1, **payload}))
        return json.loads(ws.recv())


def _error_log(ha) -> str:
    r = ha.get(f"{HA_URL}/api/error_log", timeout=30)
    r.raise_for_status()
    return r.text


def test_backend_string_lookups_never_block_the_event_loop(ha):
    # Provoke both string tables from the loop. `translations/<lang>.json` backs a
    # websocket error reply...
    reply = _ws_call(
        ha, {"type": "home_keeper/complete_task", "task_id": "no-such-task-247"}
    )
    assert not reply.get("success"), reply
    # ...and the message must be the *resolved* template, not the bare key: a
    # lookup that silently fell back would leave nothing for this test to measure.
    assert reply["error"]["message"] == "Task not found: no-such-task-247", reply

    # ...while `backend_strings/<lang>.json` backs the inventory CSV's headers.
    export = call_service(ha, "home_keeper", "export_inventory", {}, True)
    csv = export.get("service_response", export)["csv"]
    assert csv.splitlines()[0].startswith("Name,"), csv.splitlines()[0]

    offenders = [
        line
        for line in _error_log(ha).splitlines()
        if "Detected blocking call" in line and "home_keeper" in line
    ]
    assert offenders == [], (
        "Home Assistant caught Home Keeper doing file I/O on the event loop:\n"
        + "\n".join(offenders)
    )
