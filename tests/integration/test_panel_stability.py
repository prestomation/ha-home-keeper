"""Integration test: a config-entry reload must not take the sidebar panel down (#247).

The reporter of #247 was thrown out of the Home Keeper panel and back to their
default dashboard "every 10 seconds or so", starting with the Settings tab's
**Add notification** button. That button saves through
``options.async_set_options``, which reloads the config entry — and unloading the
entry used to call ``frontend.async_remove_panel``. So a reload deleted
``home-keeper`` from ``hass.panels`` and put it back a moment later, and Home
Assistant's ``partial-panel-resolver`` reacts to a panel disappearing out from
under the page by navigating to the default panel. Whether you were bounced came
down to whether the frontend's ``get_panels`` refetch landed inside the window,
which is why it looked random: the wider the window (a big store, many
integrations, a slow box), the more reliably it fired. Reproduced here by holding
the panel unregistered for a few seconds during setup — the browser leaves
``/home-keeper`` for ``/home/overview`` every time.

The panel is not entry-scoped state to begin with: it points at a static module
URL that ``async_register_static_paths`` serves for the whole HA run, and it is
re-registered with exactly the same config on the way back in. So the invariant
below is the strong one — a reload must not touch it *at all* — rather than "it
comes back quickly enough". ``card.py`` already takes this stance for the card's
Lovelace resource, for the same reason.

``panels_updated`` is the observable: Home Assistant fires it on every
``async_register_built_in_panel`` and every ``async_remove_panel``. Zero events
across a reload means the sidebar entry never moved.
"""

import json
import time

import websockets.sync.client
from conftest import HA_URL, call_service
from ha_registry import ws_send

_WS_URL = HA_URL.replace("http://", "ws://") + "/api/websocket"

PANEL_URL_PATH = "home-keeper"

#: How long to keep listening for a stray ``panels_updated`` after the reload has
#: returned. The reload itself is synchronous, so this only has to cover a task
#: racing just behind it.
_SETTLE_SECONDS = 5


def _entry_id(ha) -> str:
    token = ha.headers["Authorization"].split(" ", 1)[1]
    entries = ws_send(token, {"type": "config_entries/get", "domain": "home_keeper"})
    assert entries.get("success"), entries
    return entries["result"][0]["entry_id"]


def _panels_updated_during(ha, trigger) -> tuple[list[dict], dict]:
    """Run *trigger* with a ``panels_updated`` subscription open.

    Returns the events seen and the panel table as it stands afterwards, both read
    over the one connection so the subscription is provably live before *trigger*
    runs.
    """
    token = ha.headers["Authorization"].split(" ", 1)[1]
    with websockets.sync.client.connect(_WS_URL) as ws:
        assert json.loads(ws.recv())["type"] == "auth_required"
        ws.send(json.dumps({"type": "auth", "access_token": token}))
        assert json.loads(ws.recv())["type"] == "auth_ok"

        ws.send(
            json.dumps(
                {"id": 1, "type": "subscribe_events", "event_type": "panels_updated"}
            )
        )
        subscribed = json.loads(ws.recv())
        assert subscribed.get("success"), subscribed

        trigger()

        events: list[dict] = []
        deadline = time.monotonic() + _SETTLE_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                msg = json.loads(ws.recv(timeout=remaining))
            except TimeoutError:
                break
            if msg.get("id") == 1 and msg.get("type") == "event":
                events.append(msg["event"])

        ws.send(json.dumps({"id": 2, "type": "get_panels"}))
        while True:
            msg = json.loads(ws.recv(timeout=10))
            if msg.get("id") == 2 and msg.get("type") == "result":
                assert msg.get("success"), msg
                return events, msg["result"]


def test_reloading_the_entry_never_removes_the_sidebar_panel(ha):
    entry_id = _entry_id(ha)

    def reload():
        r = ha.post(f"{HA_URL}/api/config/config_entries/entry/{entry_id}/reload")
        r.raise_for_status()

    events, panels = _panels_updated_during(ha, reload)

    assert events == [], (
        f"a config-entry reload moved the sidebar panel ({len(events)} "
        "panels_updated events). Removing and re-adding the panel deletes it from "
        "hass.panels for as long as setup takes, and the frontend navigates anyone "
        "viewing it to their default dashboard (#247)"
    )
    assert PANEL_URL_PATH in panels


def test_saving_options_never_removes_the_sidebar_panel(ha):
    """The reporter's own trigger: saving from the panel's Settings tab.

    Every Settings save (a new notification, a profile, a changed toggle) goes
    through the same ``home_keeper/set_options`` websocket command as this service,
    and that path reloads the entry to re-run the problem-sensor reconcile.
    """

    def save():
        # A real change, not a no-op: `async_set_options` short-circuits without
        # reloading when the merged options equal what is already stored, which
        # would make this assert nothing.
        call_service(ha, "home_keeper", "set_options", {"one_off_retention_days": 3})

    try:
        events, panels = _panels_updated_during(ha, save)
    finally:
        call_service(ha, "home_keeper", "set_options", {"one_off_retention_days": 0})

    assert events == [], (
        "saving Home Keeper's options moved the sidebar panel — this is exactly "
        "what threw the reporter of #247 out of the panel on Add notification"
    )
    assert PANEL_URL_PATH in panels
