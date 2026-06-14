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


def test_existing_device_asset_persists_identifier_snapshot(ha):
    # Provision a virtual appliance (a real registry device), then attach an
    # "existing"-kind metadata asset to that device. Reconciliation must persist the
    # device's identifiers snapshot onto the asset (the bug fix) so cross-restart
    # recovery can work — verify it shows up in list_assets.
    import time

    call_service(ha, "home_keeper", "add_asset", {"name": "Snapshot host device"})

    def _device_id_for(name):
        resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
        payload = resp.get("service_response", resp)
        for a in payload["assets"]:
            if a["name"] == name and a.get("device_id"):
                return a["device_id"]
        return None

    device_id = None
    for _ in range(20):
        device_id = _device_id_for("Snapshot host device")
        if device_id:
            break
        time.sleep(1)
    assert device_id, "virtual host device was not provisioned"

    call_service(
        ha,
        "home_keeper",
        "add_asset",
        {"kind": "existing", "device_id": device_id, "warranty_provider": "ACME"},
    )

    def _existing_asset():
        resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
        payload = resp.get("service_response", resp)
        for a in payload["assets"]:
            if a.get("kind") == "existing" and a.get("device_id") == device_id:
                return a
        return None

    asset = None
    for _ in range(20):
        asset = _existing_asset()
        if asset and asset.get("identifiers"):
            break
        time.sleep(1)
    assert asset, "existing-device asset not found"
    # The snapshot was refreshed from the live device AND persisted.
    assert asset["identifiers"], "device identifiers snapshot was not persisted"


def test_add_asset_rejects_bad_url(ha):
    # Backend validation surfaces a service error for a non-http(s) manual_url.
    from conftest import HA_URL

    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/add_asset",
        json={"name": "Bad url asset", "manual_url": "javascript:alert(1)"},
    )
    assert r.status_code >= 400, "expected validation error for malicious manual_url"


def test_wear_part_creates_maintenance_task_with_device_entities(ha):
    # The seeded water heater's anode rod is a wear item (replace every 12 months),
    # so a derived task exists and lands a mark-done button on the appliance device.
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    tasks = resp.get("service_response", resp)["tasks"]
    anode_tasks = [t for t in tasks if "Anode rod" in t.get("name", "")]
    assert anode_tasks, "expected a derived task for the wear part"
    assert anode_tasks[0].get("source", {}).get("part"), "task should carry part source"
    # Its per-task entities appear; the button merges onto the appliance device, so
    # its entity_id derives from the device name ("Garage water heater").
    mark_done = [s["entity_id"] for s in list_states(ha) if "mark_done" in s["entity_id"]]
    assert any("garage_water_heater" in eid for eid in mark_done), mark_done


def test_subdevice_has_warranty_independent_and_parent_seeded(ha):
    # Both the shades parent and the radio-shade subdevice are provisioned virtual
    # devices; list_assets reflects the parent link.
    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    assets = resp.get("service_response", resp)["assets"]
    radio = next(a for a in assets if a["id"] == "asset_radio_shade")
    shades = next(a for a in assets if a["id"] == "asset_shades")
    assert radio["parent_asset_id"] == "asset_shades"
    assert radio["device_id"] and shades["device_id"]


def test_related_device_can_be_attached(ha):
    # Create a virtual appliance, then relate it to an existing device id and confirm
    # the relationship round-trips (panel-only association for foreign devices).
    call_service(ha, "home_keeper", "add_asset", {"name": "Living room piano", "icon": "mdi:piano"})
    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    assets = resp.get("service_response", resp)["assets"]
    piano = next(a for a in assets if a["name"] == "Living room piano")
    # Relate it to the seeded water heater's (virtual) device as a stand-in foreign device.
    wh = next(a for a in assets if a["id"] == "asset_water_heater")
    call_service(
        ha,
        "home_keeper",
        "update_asset",
        {"asset_id": piano["id"], "related_device_ids": [wh["device_id"]]},
    )
    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    assets = resp.get("service_response", resp)["assets"]
    piano = next(a for a in assets if a["id"] == piano["id"])
    assert piano["related_device_ids"] == [wh["device_id"]]


def test_add_asset_rejects_unknown_area(ha):
    from conftest import HA_URL

    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/add_asset",
        json={"name": "Bad area asset", "area_id": "no_such_area_xyz"},
    )
    assert r.status_code >= 400, "expected rejection of an unknown area_id"


def test_delete_asset_removes_it_from_listing(ha):
    call_service(ha, "home_keeper", "add_asset", {"name": "Temp asset to delete"})
    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    payload = resp.get("service_response", resp)
    target = next(a for a in payload["assets"] if a["name"] == "Temp asset to delete")

    call_service(ha, "home_keeper", "delete_asset", {"asset_id": target["id"]})

    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    payload = resp.get("service_response", resp)
    assert all(a["id"] != target["id"] for a in payload["assets"])
