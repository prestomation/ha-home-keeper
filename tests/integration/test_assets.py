"""Integration tests for assets (virtual devices + asset metadata).

Run against the real Home Assistant Docker container. Verifies that a seeded
virtual asset provisions a registry device with metadata date sensors, that a task
can attach to that virtual device (its per-task entities merge onto the same page),
and that the asset CRUD services round-trip.
"""

from conftest import call_service, get_state, list_states, poll_state


def _find_state(ha, predicate):
    return [s for s in list_states(ha) if predicate(s)]


def test_seeded_virtual_asset_has_warranty_date_sensor(ha):
    # The seeded "Garage water heater" asset has a warranty_expiry, which is
    # surfaced as a date sensor on its (virtual) device page.
    warranty = _find_state(
        ha,
        lambda s: s["entity_id"].startswith("sensor.")
        and "warranty" in s["entity_id"],
    )
    assert warranty, "expected a warranty-expiry date sensor for the virtual asset"
    assert any(s["state"] == "2032-05-01" for s in warranty)


def test_seeded_virtual_asset_has_purchase_and_install_sensors(ha):
    ids = [s["entity_id"] for s in list_states(ha)]
    assert any("purchase_date" in eid for eid in ids)
    assert any("install_date" in eid for eid in ids)
    # manufacture_date was null in the seed, so no sensor for it.
    assert not any("manufacture_date" in eid for eid in ids)


def test_list_assets_service_returns_response(ha):
    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    payload = resp.get("service_response", resp)
    assert "assets" in payload
    names = [a.get("name") for a in payload["assets"]]
    assert "Garage water heater" in names
    # The seeded virtual asset should have been provisioned a real device id.
    seeded = next(a for a in payload["assets"] if a["name"] == "Garage water heater")
    assert seeded["device_id"], "virtual asset should have a provisioned device_id"


def test_add_asset_then_attach_task_creates_device_entities(ha):
    # 1. Provision a fresh virtual appliance.
    call_service(
        ha,
        "home_keeper",
        "add_asset",
        {"name": "Test dehumidifier", "manufacturer": "Frigidaire"},
    )

    def _find_new_asset():
        resp = call_service(
            ha, "home_keeper", "list_assets", {}, return_response=True
        )
        payload = resp.get("service_response", resp)
        for a in payload["assets"]:
            if a["name"] == "Test dehumidifier" and a.get("device_id"):
                return a
        return None

    # Poll until the asset is listed with a provisioned device id.
    asset = None
    import time

    for _ in range(20):
        asset = _find_new_asset()
        if asset:
            break
        time.sleep(1)
    assert asset, "added asset was not provisioned with a device id"

    # 2. Attach a task to the virtual device; its per-task button must appear on
    #    that device page.
    call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Empty dehumidifier tank",
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "days",
            "device_id": asset["device_id"],
        },
    )

    def _has_mark_done():
        return any(
            "mark_done" in s["entity_id"] and "dehumidifier" in s["entity_id"]
            for s in list_states(ha)
        )

    for _ in range(20):
        if _has_mark_done():
            break
        time.sleep(1)
    assert _has_mark_done(), "task attached to a virtual device got no device entities"


def test_delete_asset_removes_it_from_listing(ha):
    call_service(ha, "home_keeper", "add_asset", {"name": "Temp asset to delete"})
    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    payload = resp.get("service_response", resp)
    target = next(a for a in payload["assets"] if a["name"] == "Temp asset to delete")

    call_service(ha, "home_keeper", "delete_asset", {"asset_id": target["id"]})

    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    payload = resp.get("service_response", resp)
    assert all(a["id"] != target["id"] for a in payload["assets"])
