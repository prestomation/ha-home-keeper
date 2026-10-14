"""Companion panel tabs against a real Home Assistant.

The ``hk_demo_tab`` stub (tests/integration/stubs) registers the ``demo-tab`` tab with
``panel_tabs.async_register_panel_tab`` at its setup, and serves the tab module from
its own static path. These tests read the tab back through the admin-only websocket
command, which is what the panel reads.
"""

import requests
from conftest import HA_URL, call_service
from ha_registry import ws_send


def _owner_token(ha) -> str:
    return ha.headers["Authorization"].split(" ", 1)[1]


def _tabs(ha, **extra) -> list[dict]:
    msg = ws_send(_owner_token(ha), {"type": "home_keeper/get_panel_tabs", **extra})
    assert msg.get("success"), msg
    return msg["result"]["tabs"]


def test_the_demo_tab_is_in_the_list(ha):
    tabs = _tabs(ha)
    demo = next((t for t in tabs if t["id"] == "demo-tab"), None)
    assert demo == {
        "id": "demo-tab",
        "companion": "hk_demo_tab",
        "title": "Library",
        "icon": "mdi:bookshelf",
        "module_url": "/hk_demo_tab_static/demo-tab.js?v=1",
        "element": "home-keeper-demo-tab",
        "host_api": 1,
        "order": 100,
    }, tabs


def test_the_title_follows_the_language_and_falls_back_to_english(ha):
    assert _tabs(ha, language="de")[0]["title"] == "Bibliothek"
    assert _tabs(ha, language="de-AT")[0]["title"] == "Bibliothek"
    assert _tabs(ha, language="fr")[0]["title"] == "Library"


def test_the_companion_serves_the_tab_module(ha):
    r = requests.get(f"{HA_URL}/hk_demo_tab_static/demo-tab.js", timeout=10)
    assert r.status_code == 200
    assert "home-keeper-demo-tab" in r.text


def test_register_companion_cannot_add_a_tab(ha):
    """The service is open to every user with service access, so it drops a tab."""
    call_service(
        ha,
        "home_keeper",
        "register_companion",
        {
            # The stub's own descriptor, so the companion list stays as seeded.
            "domain": "hk_demo_tab",
            "name": "Demo library",
            "icon": "mdi:bookshelf",
            "description": "A test companion that adds a Library tab to the panel.",
            "config_entry_id": "demo_hk_demo_tab",
            "panel_tab": {
                "id": "probe",
                "module_url": "/hk_demo_tab_static/demo-tab.js",
                "element": "home-keeper-probe",
            },
        },
    )
    assert [t["id"] for t in _tabs(ha)] == ["demo-tab"]


def test_a_hidden_tab_is_still_in_the_list(ha):
    """The seeded options hide the demo tab. The list has it, for Settings."""
    msg = ws_send(_owner_token(ha), {"type": "home_keeper/get_options"})
    assert msg.get("success"), msg
    assert "demo-tab" in msg["result"]["options"]["hidden_panel_tabs"]
    assert [t["id"] for t in _tabs(ha)] == ["demo-tab"]


def test_a_reload_of_home_keeper_keeps_the_tab(ha):
    """The registry lives for the Home Assistant run, like the sidebar panel."""
    call_service(
        ha,
        "homeassistant",
        "reload_config_entry",
        {"entry_id": "home_keeper_test_entry"},
    )
    assert [t["id"] for t in _tabs(ha)] == ["demo-tab"]
