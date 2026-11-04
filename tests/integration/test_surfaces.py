"""Touch every surface once, so the Home Assistant log shows what each one logs.

This is a smoke test. It asserts little on purpose: the run's value is the
container log, which ``ci/check_ha_log.py`` reads in the last CI step. That gate
fails on a blocking call on the event loop, an unawaited coroutine or a warning
from our code. A path that no test runs is a path the gate cannot see, and the
blocking-call bug of #247 sat in such a path (a string table read at the first
error reply).

It covers what the other files in this tier skip:

- the diagnostics download, for the config entry and for a device;
- the options flow form;
- every registered service, with a probe that is safe to run in any order.

A probe is a read, a dry run, or a call that names something that does not exist, so
it reaches the handler and its error path without changing state. A service whose
probe could change state has a reason in ``SKIPPED``.
"""

from __future__ import annotations

import pytest
from conftest import HA_URL
from ha_registry import device_registry
from test_api_surface import api_surface

ENTRY_ID = "home_keeper_test_entry"
MISSING = "surface_missing"

# Calls that must succeed, with the data that makes them read-only.
READS: dict[str, dict] = {
    "list_tasks": {},
    "list_profiles": {},
    "list_assets": {},
    "list_companions": {},
    "list_declarative_companions": {},
    "export_appliance_report": {},
    "export_data": {},
    "import_data": {
        "document": '{"home_keeper": {"format": 1}, "tasks": []}',
        "dry_run": True,
    },
    # No field changes, so it saves nothing and reloads nothing.
    "set_options": {},
}

# Services whose probe could change state, each with the reason.
SKIPPED = {
    "delete_orphaned_tasks": "it deletes the tasks of removed devices; no id can miss",
    "register_companion": "it registers a companion that no service removes",
    "add_declarative_companion": "a full call would add a companion",
}

# A schema error is a 400. A handled error of a service (a missing id) is a 400 on
# current Home Assistant and a 500 with no message on 2026.1, the oldest one that we
# support. Any other status is an unhandled error. ``handled_error_status`` finds out
# which one this Home Assistant answers, with a call that is known to be a not-found.


ID_FIELDS = ("task_id", "asset_id", "part_id", "document_id", "photo_id", "id")
PROBED = sorted(set(api_surface.SERVICE_NAMES) - set(SKIPPED))


def _post(ha, name: str, data: dict, *, with_response: bool):
    url = f"{HA_URL}/api/services/home_keeper/{name}"
    if with_response:
        url += "?return_response"
    return ha.post(url, json=data, timeout=60)


def _field_names(ha) -> dict[str, set[str]]:
    """The fields of each Home Keeper service, as the service registry lists them."""
    reply = ha.get(f"{HA_URL}/api/services", timeout=60)
    reply.raise_for_status()
    (domain,) = (d for d in reply.json() if d["domain"] == "home_keeper")
    return {n: set(s.get("fields", {})) for n, s in domain["services"].items()}


@pytest.fixture(scope="module")
def handled_error_status(ha) -> int:
    reply = _post(ha, "delete_task", {"task_id": MISSING}, with_response=False)
    assert reply.status_code in (400, 500), (reply.status_code, reply.text[:300])
    return reply.status_code


def test_skipped_services_exist():
    assert set(SKIPPED) <= set(api_surface.SERVICE_NAMES)


@pytest.mark.parametrize("name", PROBED)
def test_each_service_answers_a_probe(ha, handled_error_status, name):
    spec = next(s for s in api_surface.SERVICES if s.name == name)
    data = READS.get(name)
    if data is None:
        # A missing id, for each id field that the service takes.
        data = {f: MISSING for f in ID_FIELDS if f in _field_names(ha)[name]}
    reply = _post(ha, name, data, with_response=spec.response == "only")
    ok = (200, 400, handled_error_status)
    assert reply.status_code in ok, (name, reply.status_code, reply.text[:300])
    if name in READS:
        assert reply.status_code == 200, (name, reply.text[:300])


def test_config_entry_diagnostics_download(ha):
    reply = ha.get(f"{HA_URL}/api/diagnostics/config_entry/{ENTRY_ID}", timeout=60)
    assert reply.status_code == 200, reply.text[:300]
    body = reply.json()
    assert body["data"]["counts"]["tasks"] >= 0
    assert body["integration_manifest"]["domain"] == "home_keeper"


def test_device_diagnostics_download(ha):
    devices = [
        d
        for d in device_registry(ha)
        if any(identifier[0] == "home_keeper" for identifier in d["identifiers"])
    ]
    assert devices, "the fixture has no Home Keeper device, so nothing was checked"
    reply = ha.get(
        f"{HA_URL}/api/diagnostics/config_entry/{ENTRY_ID}/device/{devices[0]['id']}",
        timeout=60,
    )
    assert reply.status_code == 200, reply.text[:300]


def test_options_flow_form_renders_and_can_be_aborted(ha):
    start = ha.post(
        f"{HA_URL}/api/config/config_entries/options/flow",
        json={"handler": ENTRY_ID},
        timeout=60,
    )
    assert start.status_code == 200, start.text[:300]
    body = start.json()
    assert body["type"] == "form"
    assert body["step_id"] == "init"
    assert body["data_schema"], "the form has no fields"
    abort = ha.delete(
        f"{HA_URL}/api/config/config_entries/options/flow/{body['flow_id']}",
        timeout=60,
    )
    assert abort.status_code == 200, abort.text[:300]
