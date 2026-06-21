"""Unit tests for the pure companion-discovery model (companions_catalog).

The merge logic decides which integrations show as *connected* vs *suggested* in
the panel's Settings → Companions section, from two inputs: self-registered
companions (the push path) and which integration domains have a config entry (the
pull/catalog path). Pure — no Home Assistant runtime.
"""

import hk_companions_catalog as cat

# The catalog ships exactly one curated entry today: Battery Notes -> its glue.
BN = cat.CATALOG[0]
UPSTREAM = BN["upstream_domain"]  # "battery_notes"
GLUE = BN["glue_domain"]  # "home_keeper_battery_notes"


def _by_domain(rows):
    return {r["domain"]: r for r in rows}


def test_self_registered_companion_is_connected():
    registered = {
        "pawsistant": {
            "domain": "pawsistant",
            "name": "Pawsistant",
            "icon": "mdi:paw",
            "description": "Pet care schedules.",
            "config_entry_id": "entry123",
            "capabilities": ["care_schedules"],
        }
    }
    rows = cat.build_companion_list(registered, installed_domains={"pawsistant"})
    row = _by_domain(rows)["pawsistant"]
    assert row["status"] == cat.STATUS_CONNECTED
    assert row["configure_domain"] == "pawsistant"
    assert row["config_entry_id"] == "entry123"
    assert row["capabilities"] == ["care_schedules"]


def test_upstream_present_without_glue_is_suggested():
    rows = cat.build_companion_list({}, installed_domains={UPSTREAM})
    row = _by_domain(rows)[GLUE]
    assert row["status"] == cat.STATUS_SUGGESTED
    assert row["upstream_domain"] == UPSTREAM
    assert row["install_url"]  # there's somewhere to go install it


def test_no_upstream_means_no_row():
    rows = cat.build_companion_list({}, installed_domains={"light", "switch"})
    assert rows == []


def test_glue_installed_is_connected_not_suggested():
    # Glue present (config entry) but it hasn't self-registered: still connected,
    # never suggested — don't nag users to install what they already have.
    rows = cat.build_companion_list({}, installed_domains={UPSTREAM, GLUE})
    row = _by_domain(rows)[GLUE]
    assert row["status"] == cat.STATUS_CONNECTED
    assert row["configure_domain"] == GLUE


def test_registered_glue_wins_over_catalog_suggestion():
    # Once the glue self-registers, the catalog must not also emit a suggestion.
    registered = {
        GLUE: {"domain": GLUE, "name": "Battery Notes", "config_entry_id": "e1"}
    }
    rows = cat.build_companion_list(registered, installed_domains={UPSTREAM, GLUE})
    glue_rows = [r for r in rows if r["domain"] == GLUE]
    assert len(glue_rows) == 1
    assert glue_rows[0]["status"] == cat.STATUS_CONNECTED


def test_dismissed_suggestion_is_hidden():
    rows = cat.build_companion_list({}, installed_domains={UPSTREAM}, dismissed={GLUE})
    assert rows == []


def test_dismiss_does_not_hide_a_connected_pairing():
    # Dismissal only silences a *suggestion*; a connected glue is always shown.
    rows = cat.build_companion_list(
        {}, installed_domains={UPSTREAM, GLUE}, dismissed={GLUE}
    )
    assert _by_domain(rows)[GLUE]["status"] == cat.STATUS_CONNECTED
