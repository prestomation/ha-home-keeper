"""The integration's Configure dialog must not delete what it doesn't render.

Home Assistant stores whatever an options flow returns from ``async_create_entry``
as ``entry.options`` **verbatim** — the whole object, not a patch. That is a framework
contract no mock can see, so it needs asserting against a real HA: the unit tier can
prove ``options.merge_flow_input`` merges correctly, but only this tier proves the
flow's return value is what lands on disk.

The form renders seven of the ten option keys. Before ``merge_flow_input``, pressing
Submit deleted every saved profile, notification and dismissed companion — and
notifications then stopped firing, with nothing on screen to say why. A profile now
carries the to-do list it syncs onto, so the same slip would take a household's
configured sync with it.

The flow is driven over HA's REST config API; options are read back over the
``home_keeper/get_options`` websocket command, since the REST config-entries listing
doesn't expose them.
"""

import time

import pytest
from conftest import HA_URL, call_service
from ha_registry import ws_command

ENTRY_ID = "home_keeper_test_entry"

# Seeded by this module rather than relied on from the fixture: test_notifications.py
# deliberately clears profiles and notifications so later tests start clean, and it
# sorts ahead of this file.
# The profile carries a to-do list sync, which is where that setting lives now —
# there is no separate mirror key for the form to forget. Pointed at a list that does
# not exist on purpose: this test is about what a save keeps, and a live target would
# have the mirror put the seeded tasks on a real to-do list and leave them there. An
# unresolvable target logs once and mirrors nothing, which is exactly the inert seed
# this case wants.
PROFILE = {
    "id": "options_flow_profile",
    "name": "Options flow profile",
    "filter": {"status": "overdue", "labels": [], "areas": [], "devices": []},
    "sync": {
        "entity_id": "todo.options_flow_list",
        "two_way": True,
        "vanish_as_completed": False,
    },
}
NOTIFICATION = {
    "id": "options_flow_notification",
    "name": "Options flow notification",
    "profile_id": PROFILE["id"],
    "targets": [],
}
DISMISSED = ["options_flow_companion"]


def _start_flow(ha) -> str:
    """Open the options flow for the seeded entry and return its flow id."""
    r = ha.post(
        f"{HA_URL}/api/config/config_entries/options/flow", json={"handler": ENTRY_ID}
    )
    r.raise_for_status()
    body = r.json()
    assert body["step_id"] == "init", body
    return body["flow_id"]


def _submit(ha, flow_id: str, user_input: dict) -> dict:
    r = ha.post(
        f"{HA_URL}/api/config/config_entries/options/flow/{flow_id}", json=user_input
    )
    r.raise_for_status()
    return r.json()


def _options(ha, timeout: int = 60) -> dict:
    """Read the current options, retrying past the entry's post-save reload.

    Saving updates the entry, which fires the update listener and reloads it; the
    websocket command answers with an error while there's no active coordinator.
    """
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            return ws_command(ha, "home_keeper/get_options")["options"]
        except AssertionError as err:  # mid-reload — retry
            last = err
        time.sleep(1)
    raise TimeoutError(f"get_options never succeeded. Last failure: {last}")


@pytest.fixture
def panel_options(ha):
    """Seed the three panel-only options, and clear them again afterwards."""
    call_service(
        ha,
        "home_keeper",
        "set_options",
        {
            "profiles": [PROFILE],
            "notifications": [NOTIFICATION],
            "dismissed_companions": DISMISSED,
        },
    )
    seeded = _options(ha)
    assert seeded["profiles"], "seeding failed; the assertions below would be vacuous"
    assert seeded["notifications"], "seeding failed"
    assert seeded["profiles"][0]["sync"]["entity_id"], "seeding failed"
    yield seeded
    call_service(
        ha,
        "home_keeper",
        "set_options",
        {
            "profiles": [],
            "notifications": [],
            "dismissed_companions": [],
            "one_off_retention_days": 0,
            "shopping_list_entity": "",
        },
    )


def test_options_flow_save_keeps_the_panel_only_options(ha, panel_options):
    """Submitting the Configure dialog leaves profiles/notifications untouched."""
    before = panel_options

    flow_id = _start_flow(ha)
    result = _submit(
        ha,
        flow_id,
        {
            "sync_problem_sensors": before["sync_problem_sensors"],
            "problem_sensor_exclude_entities": [],
            "problem_sensor_exclude_devices": [],
            "problem_sensor_exclude_areas": [],
            "problem_sensor_exclude_labels": [],
            # A real change, so the save actually writes and reloads.
            "one_off_retention_days": 7,
            # shopping_list_entity omitted: a cleared picker drops out of the
            # submission entirely, and that absence is how the mirror is turned off.
        },
    )
    assert result["type"] == "create_entry", result

    after = _options(ha)
    assert after["profiles"] == before["profiles"]
    assert after["notifications"] == before["notifications"]
    assert after["dismissed_companions"] == DISMISSED
    # Spelled out rather than left to the comparison above: the sync block sits one
    # level *inside* a key the form doesn't render, so a merge that kept profiles but
    # re-normalized them past their sync would still satisfy a shallower assertion.
    assert after["profiles"][0]["sync"] == PROFILE["sync"]
    # ...and the fields the form does own took effect.
    assert after["one_off_retention_days"] == 7
    assert after["shopping_list_entity"] == ""


def test_options_flow_form_is_prefilled_from_the_current_options(ha, panel_options):
    """Opening the dialog offers the stored values back, not the defaults."""
    call_service(ha, "home_keeper", "set_options", {"one_off_retention_days": 21})

    flow_id = _start_flow(ha)
    try:
        r = ha.get(f"{HA_URL}/api/config/config_entries/options/flow/{flow_id}")
        r.raise_for_status()
        fields = {
            field["name"]: field for field in r.json()["data_schema"] if "name" in field
        }

        assert fields["one_off_retention_days"]["default"] == 21
    finally:
        ha.delete(f"{HA_URL}/api/config/config_entries/options/flow/{flow_id}")
