"""Companion presets through a real Home Assistant.

The Pawsistant stub registers 1 preset at its setup: Pet feeder, low battery, over the
Battery Notes stub's battery sensor (42 %, below its limit of 50). These tests read it
through the open ``list_declarative_presets`` command, register and remove presets of a
test domain, and accept a companion preset into a declarative companion.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests
from conftest import HA_URL, call_service
from ha_registry import ws_send

STUB_ID = "pawsistant/home_keeper_battery_notes_percent_low"
DOMAIN = "hk_preset_probe"
ROWS: list[dict[str, Any]] = [
    {
        "domain": "tuya_local",
        "brand": "Probe",
        "icon": "mdi:car",
        "duties": [
            {
                "duty": "check_probe",
                "shape": "percent_low",
                "keys": ["filter_life"],
                "limit": 10,
            }
        ],
    }
]
NAMES = {"check_probe": {"en": "Check the probe filter"}}
PROBE_ID = f"{DOMAIN}/tuya_local_percent_low"


def _presets(ha) -> dict[str, dict[str, Any]]:
    token = ha.headers["Authorization"].split(" ", 1)[1]
    reply = ws_send(token, {"type": "home_keeper/list_declarative_presets"})
    assert reply.get("success"), reply
    return {p["id"]: p for p in reply["result"]["presets"]}


def _post(ha, service: str, data: dict) -> requests.Response:
    return ha.post(
        f"{HA_URL}/api/services/home_keeper/{service}?return_response",
        json=data,
        timeout=60,
    )


@pytest.fixture
def probe(ha):
    yield
    call_service(ha, "home_keeper", "unregister_presets", {"domain": DOMAIN})


def test_the_stub_preset_is_in_the_list_with_its_companion(ha):
    rows = _presets(ha)
    row = rows[STUB_ID]
    assert row["source"] == "companion"
    assert row["provided_by"] == {"domain": "pawsistant", "name": "Pawsistant"}
    assert row["group"] == "integration"
    assert row["matches"] == 1
    assert row["default_spec"]["preset_id"] == STUB_ID
    assert row["default_spec"]["task_template"]["task_names"] == {
        "battery_level": "Charge the pet feeder"
    }
    shipped = rows["device_pulse"]
    assert shipped["source"] == "builtin"
    assert shipped["provided_by"] is None


def test_register_replaces_and_unregister_removes(ha, probe):
    reply = _post(
        ha, "register_presets", {"domain": DOMAIN, "rows": ROWS, "duty_names": NAMES}
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["service_response"] == {"preset_ids": [PROBE_ID]}
    row = _presets(ha)[PROBE_ID]
    # The domain has no register_companion name, so the list names it by its domain.
    assert row["provided_by"] == {"domain": DOMAIN, "name": DOMAIN}
    assert row["matches"] == 1
    alert = [
        dict(
            ROWS[0],
            duties=[
                {
                    "duty": "check_probe",
                    "shape": "alert",
                    "keys": ["filter_life"],
                    "state": "on",
                }
            ],
        )
    ]
    reply = _post(
        ha, "register_presets", {"domain": DOMAIN, "rows": alert, "duty_names": NAMES}
    )
    assert reply.status_code == 200, reply.text
    rows = _presets(ha)
    assert PROBE_ID not in rows
    assert f"{DOMAIN}/tuya_local_alert_on" in rows
    call_service(ha, "home_keeper", "unregister_presets", {"domain": DOMAIN})
    assert not [i for i in _presets(ha) if i.startswith(DOMAIN + "/")]


def test_a_bad_row_fails_the_call_and_keeps_the_old_set(ha, probe):
    assert _post(
        ha, "register_presets", {"domain": DOMAIN, "rows": ROWS, "duty_names": NAMES}
    ).ok
    bad = [dict(ROWS[0], icon="car")]
    reply = _post(
        ha, "register_presets", {"domain": DOMAIN, "rows": bad, "duty_names": NAMES}
    )
    assert reply.status_code in (400, 500), reply.text
    if reply.status_code == 400:
        assert "rows[0].icon" in reply.text
    assert PROBE_ID in _presets(ha)


def test_an_unknown_field_is_refused(ha):
    reply = _post(ha, "register_presets", {"domain": DOMAIN, "rows": ROWS, "extra": 1})
    assert reply.status_code == 400, reply.text
    assert not [i for i in _presets(ha) if i.startswith(DOMAIN + "/")]


def test_an_accepted_preset_survives_unregister(ha, probe):
    assert _post(
        ha, "register_presets", {"domain": DOMAIN, "rows": ROWS, "duty_names": NAMES}
    ).ok
    spec = dict(_presets(ha)[PROBE_ID]["default_spec"])
    added = call_service(
        ha, "home_keeper", "add_declarative_companion", spec, return_response=True
    )
    spec_id = added["service_response"]["companion"]["id"]
    try:
        call_service(ha, "home_keeper", "unregister_presets", {"domain": DOMAIN})
        listed = call_service(
            ha, "home_keeper", "list_declarative_companions", {}, return_response=True
        )
        kept = {c["id"]: c for c in listed["service_response"]["companions"]}
        assert kept[spec_id]["preset_id"] == PROBE_ID
    finally:
        call_service(ha, "home_keeper", "delete_declarative_companion", {"id": spec_id})
