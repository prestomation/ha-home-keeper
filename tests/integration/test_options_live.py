"""An options change that keeps the entity set does not reload the entry (#467).

A reload makes Home Assistant write ``unavailable`` for each Home Keeper entity and
then the state again, so each options change put many rows in the logbook. These
tests read the real logbook of the container around 1 options change.
"""

import time
from datetime import UTC, datetime

from conftest import HA_URL, call_service, get_state, list_states, poll_state


def _hk_entities(ha) -> set[str]:
    r = ha.post(
        f"{HA_URL}/api/template",
        json={"template": "{{ integration_entities('home_keeper') | list | tojson }}"},
    )
    r.raise_for_status()
    return set(r.json())


def _unavailable_rows(ha, entities: set[str], start: datetime) -> list[str]:
    """The Home Keeper entities that the logbook shows as unavailable since *start*."""
    r = ha.get(
        f"{HA_URL}/api/logbook/{start.isoformat()}",
        params={"end_time": datetime.now(UTC).isoformat()},
    )
    r.raise_for_status()
    return [
        row["entity_id"]
        for row in r.json()
        if row.get("entity_id") in entities and row.get("state") == "unavailable"
    ]


def test_a_live_options_change_writes_no_unavailable_rows(ha):
    entities = _hk_entities(ha)
    assert entities, "expected Home Keeper entities in the test config"
    start = datetime.now(UTC)
    try:
        call_service(ha, "home_keeper", "set_options", {"allow_snooze": False})
        # A reload, had there been one, writes its rows within this wait.
        time.sleep(5)
        assert _unavailable_rows(ha, entities, start) == []
    finally:
        call_service(ha, "home_keeper", "set_options", {"allow_snooze": True})


def test_a_new_cost_window_still_adds_its_sensor(ha):
    """A change that adds an entity reloads, so the platform makes the entity."""
    try:
        call_service(ha, "home_keeper", "set_options", {"cost_windows": [7, 30, 60]})
        ids = {
            state["entity_id"]
            for state in list_states(ha)
            if "spend" in state["entity_id"] and "7" in state["entity_id"]
        }
        assert ids, "expected a 7-day spend sensor after the reload"
        spend_7d = sorted(ids)[0]
        poll_state(ha, spend_7d, lambda s: s != "unavailable")
    finally:
        call_service(ha, "home_keeper", "set_options", {"cost_windows": [30, 60]})
    # The reload for the removed window prunes its sensor.
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        state = get_state(ha, spend_7d)
        if state is None or state["state"] == "unavailable":
            break
        time.sleep(1)
    else:
        raise AssertionError(f"{spend_7d} should go when its window goes")
