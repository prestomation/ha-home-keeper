"""The config-entry migration to profile filter groups (entry version 1 -> 2).

A profile's filter used to carry one flat set of include/exclude lists. It now carries
``groups``, and nothing reads the flat keys any more — so a stored profile has to be
converted, once, before anything reads it. ``__init__.async_migrate_entry`` does that
with ``profiles.migrate_options_v1``, and Home Assistant calls it because
``HomeKeeperConfigFlow.VERSION`` is 2 while the seeded entry on disk says 1.

The unit tier proves the conversion is correct on a dict. Only this tier proves Home
Assistant *runs* it: the version check, the ``async_update_entry`` write and the
re-read on the next boot are framework contracts no mock can see.

The seed is one pre-groups profile ("Legacy chores") in
``ha_config/.storage/core.config_entries``, on an entry stored at ``version: 1``. Home
Assistant rewrites that file in place as it boots, so a local run leaves it migrated;
the assertions below hold either way, but **the committed seed must stay at version 1**
— ``git checkout tests/integration/ha_config/.storage/core.config_entries`` after a
local run, or the next run tests nothing.

This module deliberately sorts ahead of ``test_notifications.py``, which replaces the
whole saved profile list.
"""

import json
import time
from pathlib import Path

import pytest
from conftest import HA_URL, call_service
from ha_registry import ws_send

ENTRY_ID = "home_keeper_test_entry"
LEGACY_PROFILE_ID = "itest_legacy_flat"

#: The container mounts this directory as ``/config``, so the file Home Assistant
#: writes is the file read here. There is no other way in: the config-entry version is
#: not exposed over the REST or websocket APIs.
STORAGE = Path(__file__).parent / "ha_config" / ".storage" / "core.config_entries"

#: The keys a pre-groups filter carried. None of them may survive the migration.
LEGACY_KEYS = (
    "labels",
    "areas",
    "devices",
    "companions",
    "exclude_labels",
    "exclude_areas",
    "exclude_devices",
    "exclude_companions",
    "exclude_shopping",
)


def _profiles(ha):
    resp = call_service(ha, "home_keeper", "list_profiles", {}, return_response=True)
    return resp.get("service_response", resp)["profiles"]


def _entry_on_disk(timeout=30):
    """The seeded Home Keeper entry as Home Assistant last wrote it.

    Polled: the migration's ``async_update_entry`` schedules a delayed save, so the
    file can still hold the pre-migration copy for a moment after HA reports RUNNING.
    """
    deadline = time.monotonic() + timeout
    entry = None
    while time.monotonic() < deadline:
        data = json.loads(STORAGE.read_text())
        entry = next(e for e in data["data"]["entries"] if e["entry_id"] == ENTRY_ID)
        if entry["version"] >= 2:
            return entry
        time.sleep(1)
    return entry


def test_the_seeded_legacy_profile_reads_back_in_the_groups_shape(ha):
    """The stored filter is converted: one group, and no flat key left behind."""
    profile = next(
        (p for p in _profiles(ha) if p["id"] == LEGACY_PROFILE_ID),
        None,
    )
    assert profile is not None, "the seeded legacy profile is gone; check test order"
    assert profile["name"] == "Legacy chores"
    filt = profile["filter"]
    assert set(filt) == {"groups", "status"}, filt
    assert filt["status"] == "all"
    for key in LEGACY_KEYS:
        assert key not in filt, key

    # The flat lists became one group, unchanged.
    (group,) = filt["groups"]
    assert group["labels"] == ["legacy"]
    assert group["labels_match"] == "any"
    assert group["exclude_areas"] == ["garage"]
    assert group["areas"] == []
    assert group["exclude_shopping"] is False


def test_every_profile_reads_back_in_the_groups_shape(ha):
    """Not only the seeded one: no reader may ever see a pre-groups filter."""
    for profile in _profiles(ha):
        filt = profile["filter"]
        assert "groups" in filt, profile["id"]
        assert filt["groups"], profile["id"]
        for key in LEGACY_KEYS:
            assert key not in filt, (profile["id"], key)


def test_the_entry_on_disk_is_at_version_2(ha):
    """Home Assistant ran the migration and wrote the new version back.

    Without the version bump the migration never runs again, so the entry version is
    what makes the conversion a one-time event rather than a re-read.
    """
    entry = _entry_on_disk()
    assert entry["version"] == 2, entry["version"]
    saved = next(
        (p for p in entry["options"]["profiles"] if p["id"] == LEGACY_PROFILE_ID),
        None,
    )
    assert saved is not None, "the migrated profile is not in the written options"
    assert "groups" in saved["filter"], saved["filter"]


def _legacy_payload(key):
    return {
        "profiles": [
            {
                "id": "itest_legacy_rejected",
                "name": "Rejected",
                "filter": {
                    "status": "all",
                    key: True if key == "exclude_shopping" else ["x"],
                },
            }
        ]
    }


@pytest.mark.parametrize("key", LEGACY_KEYS)
def test_the_service_refuses_a_pre_groups_filter(ha, key):
    """A write still on the old shape fails loudly instead of saving a wide filter.

    The flat keys are read nowhere, so a saved profile carrying them would select the
    profile's whole status tier without saying so — an automation would look like it
    worked. ``profiles.check_profiles_use_groups`` guards both write paths; this is the
    service half, where a schema failure is an HTTP 400. (Home Assistant's REST API
    answers a ``vol.Invalid`` with a bare Bad Request, so the message itself is
    asserted over the websocket below.)
    """
    before = _profiles(ha)
    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/set_options", json=_legacy_payload(key)
    )
    assert r.status_code == 400, (r.status_code, r.text)
    # ...and the refusal changed nothing.
    assert _profiles(ha) == before


def test_the_panel_command_refuses_a_pre_groups_filter_and_says_why(ha, ha_token):
    """The other write path, where the message is what the panel shows the user."""
    before = _profiles(ha)
    msg = ws_send(
        ha_token,
        {"type": "home_keeper/set_options", "options": _legacy_payload("labels")},
    )
    assert not msg.get("success"), msg
    assert "filter.groups" in msg["error"]["message"], msg
    assert _profiles(ha) == before
