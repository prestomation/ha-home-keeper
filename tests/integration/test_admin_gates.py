"""Integration coverage for Home Keeper's privilege model.

Who may do what rests entirely on Home Assistant framework contracts — the panel's
``require_admin`` flag, ``@websocket_api.require_admin``, and ``Unauthorized``
raised from a service handler. A unit test mocks all three away and would happily
pass against a build where none of them holds (which is exactly how the service-side
bypass survived: the websocket commands were decorated, their service twins were
not). So the gates are asserted here, against a real HA with a real second user.

The suite creates one non-admin user through HA's own auth API, logs in as them, and
then drives both surfaces — REST service calls and the websocket API — with both
tokens, asserting the admin succeeds where the non-admin is refused.
"""

import uuid

import pytest
import requests
from conftest import HA_URL, _login, call_service
from ha_registry import ws_send

NON_ADMIN_USERNAME = "housemate"
NON_ADMIN_PASSWORD = "housemate-pw-1"


def _owner_token(ha) -> str:
    return ha.headers["Authorization"].split(" ", 1)[1]


@pytest.fixture(scope="session")
def non_admin_token(ha) -> str:
    """A token for a **non-admin** user, created on first use.

    HA has no REST endpoint for user creation, so this goes over the websocket as the
    owner: ``config/auth/create`` mints the user in the ``system-users`` group (the
    non-admin group; admins are ``system-admin``), then
    ``config/auth_provider/homeassistant/create`` gives it credentials to log in with.

    Log in first and only provision on failure: HA keeps users in ``.storage/auth``,
    which survives a re-run against a container that is already up, and creating the
    credentials twice is an error (while creating the *user* twice quietly succeeds,
    leaving a duplicate behind).
    """
    try:
        return _login(NON_ADMIN_USERNAME, NON_ADMIN_PASSWORD)
    except (requests.HTTPError, KeyError):
        pass  # not provisioned yet — do it now

    owner = _owner_token(ha)
    created = ws_send(
        owner,
        {
            "type": "config/auth/create",
            "name": "Housemate",
            "group_ids": ["system-users"],
        },
    )
    assert created.get("success"), f"user create failed: {created}"
    user = created["result"]["user"]
    # `config/auth/create` echoes group membership, not an is_admin flag: HA derives
    # admin-ness from the group, so assert on the group the fixture asked for —
    # otherwise a silently-promoted user would make every assertion below vacuous.
    assert user["group_ids"] == ["system-users"], (
        f"fixture user is not in the non-admin group: {user}"
    )
    credentials = ws_send(
        owner,
        {
            "type": "config/auth_provider/homeassistant/create",
            "user_id": user["id"],
            "username": NON_ADMIN_USERNAME,
            "password": NON_ADMIN_PASSWORD,
        },
    )
    assert credentials.get("success"), f"credential create failed: {credentials}"
    return _login(NON_ADMIN_USERNAME, NON_ADMIN_PASSWORD)


@pytest.fixture(scope="session")
def non_admin(non_admin_token):
    """A requests session authenticated as the non-admin user."""
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {non_admin_token}",
            "Content-Type": "application/json",
        }
    )
    return session


@pytest.fixture(scope="session")
def priced_asset(ha):
    """An appliance carrying every field the projection is meant to withhold."""
    name = f"Gate probe {uuid.uuid4().hex[:8]}"
    call_service(
        ha,
        "home_keeper",
        "add_asset",
        {
            "name": name,
            "serial_number": "SN-SECRET-1",
            "cost": 2499.0,
            "metadata": [
                {"type": "text", "label": "Insurer", "value": "Acme Mutual"},
                {"type": "link", "label": "Product page", "value": "https://ex.com/p"},
            ],
            "parts": [{"name": "Filter", "cost": 39.5, "url": "https://ex.com/filter"}],
        },
    )
    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    assets = resp.get("service_response", resp)["assets"]
    asset = next(a for a in assets if a["name"] == name)
    yield asset
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def _call(session, service, data=None, return_response=False):
    """A raw service call that returns the response rather than raising on 4xx."""
    url = f"{HA_URL}/api/services/home_keeper/{service}"
    if return_response:
        url += "?return_response"
    return session.post(url, json=data or {})


# ── the service-side bypass (the two gates that didn't hold) ────────────────


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("export_inventory", {}),
        ("set_options", {"sync_problem_sensors": True}),
    ],
)
def test_admin_only_services_refuse_a_non_admin(non_admin, service, data):
    # Both have ``@websocket_api.require_admin`` twins. Calling the service instead
    # used to return the identical payload to anyone with a login.
    r = _call(non_admin, service, data, return_response=service == "export_inventory")
    assert r.status_code == 401, f"{service} answered a non-admin: {r.status_code}"


def test_export_inventory_still_works_for_an_admin(ha):
    # The gate must refuse the right people only — an admin still gets the report.
    resp = call_service(ha, "home_keeper", "export_inventory", {}, return_response=True)
    payload = resp.get("service_response", resp)
    assert "inventory" in payload and "csv" in payload


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("add_asset", {"name": "Should not exist"}),
        ("update_asset", {"asset_id": "whatever", "name": "Renamed"}),
        ("delete_asset", {"asset_id": "whatever"}),
        (
            "add_asset_document",
            {"asset_id": "x", "document": {"name": "n", "url": "https://e.com"}},
        ),
    ],
)
def test_asset_mutation_services_refuse_a_non_admin(non_admin, service, data):
    # Appliance CRUD creates and removes device-registry entries, which HA core
    # reserves for admins. The gate runs before any lookup, so a bogus asset_id still
    # gets 401 rather than a 400 that would reveal whether the asset exists.
    r = _call(non_admin, service, data)
    assert r.status_code == 401, f"{service} answered a non-admin: {r.status_code}"


def test_non_admin_can_still_complete_a_task(ha, non_admin):
    # The other half of the model: usage stays open. A household member must still be
    # able to mark something done, or the gates have broken the product.
    name = f"Gate usage probe {uuid.uuid4().hex[:8]}"
    call_service(
        ha,
        "home_keeper",
        "add_task",
        {"name": name, "recurrence_type": "floating", "interval": 7, "unit": "days"},
    )
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    task = next(
        t for t in resp.get("service_response", resp)["tasks"] if t["name"] == name
    )
    try:
        r = _call(non_admin, "complete_task", {"task_id": task["id"]})
        assert r.status_code == 200, f"a non-admin could not complete a task: {r.text}"
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task["id"]})


# ── the non-admin asset projection ──────────────────────────────────────────


def _assets_over_ws(token):
    msg = ws_send(token, {"type": "home_keeper/get_assets"})
    assert msg.get("success"), f"get_assets failed: {msg}"
    return msg["result"]["assets"]


def test_get_assets_withholds_costs_and_serials_from_a_non_admin(
    non_admin_token, priced_asset
):
    projected = next(
        a for a in _assets_over_ws(non_admin_token) if a["id"] == priced_asset["id"]
    )
    assert "cost" not in projected
    assert "serial_number" not in projected
    assert "cost" not in projected["parts"][0]
    assert [m["label"] for m in projected["metadata"]] == ["Product page"]


def test_get_assets_still_carries_what_the_card_renders(non_admin_token, priced_asset):
    # The card resolves card links against documents, link metadata and part URLs; if
    # the projection took those too, every non-admin's dashboard would lose its chips.
    projected = next(
        a for a in _assets_over_ws(non_admin_token) if a["id"] == priced_asset["id"]
    )
    assert projected["parts"][0]["url"] == "https://ex.com/filter"
    assert projected["metadata"][0]["value"] == "https://ex.com/p"


def test_get_assets_is_unabridged_for_an_admin(ha, priced_asset):
    full = next(
        a for a in _assets_over_ws(_owner_token(ha)) if a["id"] == priced_asset["id"]
    )
    assert full["cost"] == 2499.0
    assert full["serial_number"] == "SN-SECRET-1"


def test_list_assets_service_projects_for_a_non_admin(non_admin, priced_asset):
    # The service twin of get_assets: projecting only the websocket read would leave
    # `call_service` as an open door to the same data.
    r = _call(non_admin, "list_assets", {}, return_response=True)
    assert r.status_code == 200
    payload = r.json()
    assets = payload.get("service_response", payload)["assets"]
    projected = next(a for a in assets if a["id"] == priced_asset["id"])
    assert "cost" not in projected and "serial_number" not in projected


def test_asset_mutation_commands_refuse_a_non_admin(non_admin_token, priced_asset):
    # Each of these echoes the full asset back in its result, so leaving them open
    # would hand a non-admin the very fields the projection withholds.
    msg = ws_send(
        non_admin_token,
        {
            "type": "home_keeper/update_asset",
            "asset_id": priced_asset["id"],
            "updates": {},
        },
    )
    assert not msg.get("success")
    assert msg["error"]["code"] == "unauthorized"


# ── the panel is admin-only ─────────────────────────────────────────────────


def test_panel_is_hidden_from_a_non_admin(ha, non_admin_token):
    admin_panels = ws_send(_owner_token(ha), {"type": "get_panels"})
    assert admin_panels.get("success")
    assert "home-keeper" in admin_panels["result"], "the panel should exist for admins"

    panels = ws_send(non_admin_token, {"type": "get_panels"})
    assert panels.get("success")
    assert "home-keeper" not in panels["result"], (
        "administration is admin-only — the panel must not be offered to a non-admin"
    )
