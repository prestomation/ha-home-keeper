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
        ("export_appliance_report", {}),
        ("set_options", {"sync_problem_sensors": True}),
        # The portable document is every task, note, serial and cost in the store,
        # and the import writes tasks and appliances wholesale.
        ("export_data", {}),
        ("import_data", {"document": {"home_keeper": {"format": 1}}, "dry_run": True}),
    ],
)
def test_admin_only_services_refuse_a_non_admin(non_admin, service, data):
    # All of these have ``@websocket_api.require_admin`` twins. Calling the service
    # instead used to return the identical payload to anyone with a login.
    # ``set_options`` is the one here that returns nothing; asking it for a response
    # would fail on the shape rather than on the gate we are testing.
    r = _call(non_admin, service, data, return_response=service != "set_options")
    assert r.status_code == 401, f"{service} answered a non-admin: {r.status_code}"


def test_export_appliance_report_still_works_for_an_admin(ha):
    # The gate must refuse the right people only — an admin still gets the report.
    resp = call_service(
        ha, "home_keeper", "export_appliance_report", {}, return_response=True
    )
    payload = resp.get("service_response", resp)
    assert "report" in payload and "csv" in payload


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


# ── the template trigger, which is admin-only on an otherwise open service ──

TANK = "binary_sensor.hk_demo_water_tank_low"
TEMPLATE_BINDING = {
    "entity_id": TANK,
    "mode": "template",
    "template": "{{ state == 'on' }}",
}


def _template_task(name):
    return {
        "name": name,
        "recurrence_type": "sensor",
        "sensor": dict(TEMPLATE_BINDING),
    }


def test_add_task_refuses_a_template_binding_from_a_non_admin(non_admin):
    # ``add_task`` is open to everyone on purpose — a household member has to be able
    # to add a chore. A **template** binding is the one part of a task that is not
    # inert data: Home Keeper renders it, and Jinja reaches registry helpers
    # (``device_attr``, ``area_id``, ``integration_entities``) that a non-admin cannot
    # otherwise enumerate. So the mode alone is gated, and only here: the panel's own
    # route is admin-only twice over, and this is the ``call_service`` path around it.
    r = _call(non_admin, "add_task", _template_task("Should not exist"))
    assert r.status_code == 401, f"a non-admin created a template task: {r.status_code}"


def test_update_task_refuses_a_template_binding_from_a_non_admin(ha, non_admin):
    # The other door into the same field. A non-admin who cannot *create* a template
    # task could otherwise create a plain sensor task and edit a template onto it.
    name = f"Gate template update probe {uuid.uuid4().hex[:8]}"
    call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": name,
            "recurrence_type": "sensor",
            "sensor": {"entity_id": TANK, "mode": "state", "state": "on"},
        },
    )
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    task = next(
        t for t in resp.get("service_response", resp)["tasks"] if t["name"] == name
    )
    try:
        r = _call(
            non_admin,
            "update_task",
            {"task_id": task["id"], "sensor": dict(TEMPLATE_BINDING)},
        )
        assert r.status_code == 401, (
            f"a non-admin set a template on a task: {r.status_code}"
        )
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task["id"]})


def test_a_non_admin_can_still_add_a_plain_sensor_task(ha, non_admin):
    # The gate must refuse the mode, not the service. Refusing every sensor task would
    # take a feature away from the household to protect one field of it.
    name = f"Gate plain sensor probe {uuid.uuid4().hex[:8]}"
    r = _call(
        non_admin,
        "add_task",
        {
            "name": name,
            "recurrence_type": "sensor",
            "sensor": {"entity_id": TANK, "mode": "state", "state": "on"},
        },
    )
    assert r.status_code == 200, f"a non-admin could not add a sensor task: {r.text}"
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    task = next(
        t for t in resp.get("service_response", resp)["tasks"] if t["name"] == name
    )
    call_service(ha, "home_keeper", "delete_task", {"task_id": task["id"]})


def test_an_admin_can_still_add_a_template_task(ha):
    # And the gate must not refuse the right people. An admin's template task is
    # stored with its template intact, which is also the only assertion here that the
    # binding survives ``normalize_sensor`` over the real service.
    name = f"Gate template admin probe {uuid.uuid4().hex[:8]}"
    call_service(ha, "home_keeper", "add_task", _template_task(name))
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    task = next(
        t for t in resp.get("service_response", resp)["tasks"] if t["name"] == name
    )
    try:
        assert task["sensor"]["mode"] == "template"
        assert task["sensor"]["template"] == TEMPLATE_BINDING["template"]
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task["id"]})


def _list_task_named(ha, name):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return next(
        (t for t in resp.get("service_response", resp)["tasks"] if t["name"] == name),
        None,
    )


def test_the_websocket_add_task_refuses_a_template_binding_from_a_non_admin(
    ha, non_admin_token
):
    # The websocket twin of the service gate. ``home_keeper/add_task`` is open to
    # every signed-in user, like the service, so gating only the service left this
    # command as the path around it.
    name = f"Gate ws template probe {uuid.uuid4().hex[:8]}"
    msg = ws_send(
        non_admin_token, {"type": "home_keeper/add_task", "task": _template_task(name)}
    )
    task = _list_task_named(ha, name)
    if task is not None:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task["id"]})
    assert not msg.get("success"), "a non-admin created a template task over ws"
    assert msg["error"]["code"] == "unauthorized", msg
    assert task is None


def test_the_websocket_update_task_refuses_a_template_binding_from_a_non_admin(
    ha, non_admin_token
):
    name = f"Gate ws template update probe {uuid.uuid4().hex[:8]}"
    call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": name,
            "recurrence_type": "sensor",
            "sensor": {"entity_id": TANK, "mode": "state", "state": "on"},
        },
    )
    task = _list_task_named(ha, name)
    try:
        msg = ws_send(
            non_admin_token,
            {
                "type": "home_keeper/update_task",
                "task_id": task["id"],
                "updates": {"sensor": dict(TEMPLATE_BINDING)},
            },
        )
        assert not msg.get("success"), "a non-admin set a template on a task over ws"
        assert msg["error"]["code"] == "unauthorized", msg
        assert _list_task_named(ha, name)["sensor"]["mode"] == "state"
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task["id"]})


def test_the_websocket_add_task_still_takes_a_plain_task_from_a_non_admin(
    ha, non_admin_token
):
    # The gate refuses the mode, not the command.
    name = f"Gate ws plain probe {uuid.uuid4().hex[:8]}"
    msg = ws_send(
        non_admin_token,
        {
            "type": "home_keeper/add_task",
            "task": {
                "name": name,
                "recurrence_type": "sensor",
                "sensor": {"entity_id": TANK, "mode": "state", "state": "on"},
            },
        },
    )
    assert msg.get("success"), f"a non-admin could not add a task over ws: {msg}"
    call_service(
        ha, "home_keeper", "delete_task", {"task_id": msg["result"]["task"]["id"]}
    )


def test_the_websocket_add_task_takes_a_template_binding_from_an_admin(ha):
    name = f"Gate ws template admin probe {uuid.uuid4().hex[:8]}"
    msg = ws_send(
        _owner_token(ha), {"type": "home_keeper/add_task", "task": _template_task(name)}
    )
    assert msg.get("success"), f"an admin could not add a template task over ws: {msg}"
    call_service(
        ha, "home_keeper", "delete_task", {"task_id": msg["result"]["task"]["id"]}
    )


def test_a_non_admin_cannot_author_an_automation_or_a_script(non_admin):
    """The Home Assistant contract the template gate rests on.

    `_caller_is_admin` treats `context.user_id is None` as trusted, which is Home
    Assistant's own convention for an internal or automation-triggered call. That is
    only safe while authoring an automation is itself admin-only: otherwise a
    non-admin could write one that calls `add_task` with a template of their choosing
    and let it run unattended with no user attached, which would walk straight around
    the gate.

    Home Assistant puts `@require_admin` on the config view's `post`, so the hole does
    not exist. But that is *its* contract rather than Home Keeper's, and a unit test
    mocking the framework could never see it change — the #183 argument. Asserted here
    so the day it relaxes, this fails rather than the gate quietly becoming decorative.
    """
    body = {
        "alias": "probe",
        "trigger": [
            {"platform": "state", "entity_id": "binary_sensor.hk_demo_water_tank_low"}
        ],
        "action": [
            {
                "service": "home_keeper.add_task",
                "data": {
                    "name": "escalated",
                    "recurrence_type": "sensor",
                    "sensor": {
                        "entity_id": "binary_sensor.hk_demo_water_tank_low",
                        "mode": "template",
                        "template": "{{ true }}",
                    },
                },
            }
        ],
    }
    key = uuid.uuid4().hex
    for kind in ("automation", "script"):
        r = non_admin.post(f"{HA_URL}/api/config/{kind}/config/{key}", json=body)
        assert r.status_code == 401, (
            f"a non-admin authored a {kind}, so the template gate can be bypassed "
            f"by letting it run with no user attached: {r.status_code}"
        )


def test_a_non_admin_can_rename_an_admin_s_template_task(ha, non_admin):
    """Renaming is not authoring, and the gate must not confuse the two.

    `_verify_template_binding` reads `call.data.get("sensor")`, so an `update_task`
    that does not carry one is not checked. That is correct rather than a gap: the
    template is only reachable through `sensor`, so an update without it cannot
    introduce or change one, and refusing the rename would take the household's own
    task list away to protect a field they are not touching.
    """
    name = f"Gate rename probe {uuid.uuid4().hex[:8]}"
    call_service(ha, "home_keeper", "add_task", _template_task(name))
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    task = next(
        t for t in resp.get("service_response", resp)["tasks"] if t["name"] == name
    )
    try:
        r = _call(
            non_admin, "update_task", {"task_id": task["id"], "name": f"{name} renamed"}
        )
        assert r.status_code == 200, f"a non-admin could not rename a task: {r.text}"

        # The rename went through and the admin's template is untouched — the
        # non-admin changed the one field they sent and nothing else.
        resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
        after = next(
            t
            for t in resp.get("service_response", resp)["tasks"]
            if t["id"] == task["id"]
        )
        assert after["name"] == f"{name} renamed"
        assert after["sensor"]["template"] == TEMPLATE_BINDING["template"]
    finally:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task["id"]})


# ── the companion preview, which renders caller-supplied Jinja ──────────────


def _preview_spec(template):
    return {
        "type": "home_keeper/preview_declarative_companion",
        "companion": {
            "name": "Gate preview probe",
            "description": "",
            "enabled": True,
            "selection": {"domain": "binary_sensor"},
            "trigger": {"mode": "template", "template": template},
            "task_template": {"name_template": "{{ friendly_name }}"},
        },
    }


def test_the_companion_preview_refuses_a_non_admin(non_admin_token):
    """The gate `_verify_template_binding` exists for, on the surface that renders.

    The preview was filed under "read-only helpers for the panel's Add dialog" and
    carried no `require_admin`. It writes nothing, but it takes a Jinja string from
    the caller, renders it against the entity, device and area registries, and hands
    back the answer — a general-purpose template oracle for anyone with a login, and
    the exact power `add_task` refuses a non-admin. No user loses a surface: the panel
    is `require_admin`, so only an admin ever reaches the dialog.
    """
    msg = ws_send(
        non_admin_token,
        _preview_spec("{{ device_id is not none }}"),
    )
    assert not msg.get("success"), (
        "a non-admin rendered a template through the companion preview"
    )
    assert msg["error"]["code"] == "unauthorized", msg


def test_the_companion_preview_still_answers_an_admin(ha):
    # The gate has to refuse the right people only — the dialog it feeds must work.
    msg = ws_send(_owner_token(ha), _preview_spec("{{ state == 'on' }}"))
    assert msg.get("success"), f"preview failed for an admin: {msg}"
    assert "matched" in msg["result"]


def test_the_preview_answers_an_admin_before_the_template_is_written(ha):
    """An empty box is a form mid-typing, not a malformed spec.

    The command used to normalize the draft the way a save does, so the instant a user
    picked Template mode it failed with `sensor.template is required` and the panel
    dropped the match list — at the moment the user most wants to see which entities the
    companion covers. Saving a blank template still fails; only the preview waives it.
    """
    msg = ws_send(_owner_token(ha), _preview_spec(""))
    assert msg.get("success"), f"preview refused an unwritten template: {msg}"
    assert msg["result"]["matched"], "the preview answered with no match list"
    # No verdict and no error: an empty template rendered nothing, so it says nothing.
    for row in msg["result"]["matched"]:
        assert row["trigger_now"] is None
        assert row["trigger_error"] is None


def test_saving_a_companion_with_no_template_still_fails(ha):
    """The other side of the waiver. The preview is the only caller that passes it.

    Asserted over the websocket, which is the panel's own save path and the one that
    reports a validation error rather than a bare 500.
    """
    msg = ws_send(
        _owner_token(ha),
        {
            "type": "home_keeper/add_declarative_companion",
            "companion": _preview_spec("")["companion"],
        },
    )
    assert not msg.get("success"), "a companion saved with no template"
    assert "sensor.template is required" in str(msg["error"]), msg


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
