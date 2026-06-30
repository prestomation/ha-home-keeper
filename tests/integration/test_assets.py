"""Integration tests for assets (virtual devices + asset metadata).

Run against the real Home Assistant Docker container. Verifies that a seeded
virtual asset provisions a registry device with metadata date sensors, that a task
can attach to that virtual device (its per-task entities merge onto the same page),
and that the asset CRUD services round-trip.
"""

from conftest import call_service, list_states


def _find_state(ha, predicate):
    return [s for s in list_states(ha) if predicate(s)]


def test_seeded_virtual_asset_has_warranty_date_sensor(ha):
    # The seeded "Garage water heater" has a tracked "Warranty expiry" date metadata
    # entry, which is surfaced as a date sensor on its (virtual) device page.
    warranty = _find_state(
        ha,
        lambda s: s["entity_id"].startswith("sensor.") and "warranty" in s["entity_id"],
    )
    assert warranty, "expected a warranty-expiry date sensor for the virtual asset"
    assert any(s["state"] == "2032-05-01" for s in warranty)


def test_seeded_virtual_asset_has_purchase_and_install_sensors(ha):
    # The seed tracks "Purchase date" and "Install date" metadata entries (so each is
    # a date sensor); the entity_id derives from the device name + the entry label.
    ids = [s["entity_id"] for s in list_states(ha)]
    assert any("purchase_date" in eid for eid in ids)
    assert any("install_date" in eid for eid in ids)
    # No manufacture-date entry was seeded, so there's no sensor for it.
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
        resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
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
        {
            "kind": "existing",
            "device_id": device_id,
            "metadata": [
                {"type": "text", "label": "Warranty provider", "value": "ACME"}
            ],
        },
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


def test_add_asset_rejects_bad_document_url(ha):
    # Backend validation surfaces a service error for a non-http(s) document link.
    from conftest import HA_URL

    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/add_asset",
        json={
            "name": "Bad url asset",
            "documents": [{"kind": "link", "url": "javascript:alert(1)"}],
        },
    )
    assert r.status_code >= 400, (
        "expected validation error for a malicious document url"
    )


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
    mark_done = [
        s["entity_id"] for s in list_states(ha) if "mark_done" in s["entity_id"]
    ]
    assert any("garage_water_heater" in eid for eid in mark_done), mark_done


def _all_tasks(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def _anode_task(ha):
    return next(t for t in _all_tasks(ha) if "Anode rod" in t.get("name", ""))


def test_cannot_delete_derived_part_task(ha):
    # A wear-part task is owned by its part; deleting it directly must be rejected
    # (otherwise the next reconcile would just recreate it as a "zombie").
    from conftest import HA_URL

    anode = _anode_task(ha)
    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/delete_task", json={"task_id": anode["id"]}
    )
    assert r.status_code >= 400, (
        f"deleting a derived task should be rejected, got {r.status_code}"
    )
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    assert any(
        t["id"] == anode["id"] for t in resp.get("service_response", resp)["tasks"]
    ), "the derived task must still exist after a rejected delete"


def test_completing_derived_part_task_survives_reconcile(ha):
    # Regression: a reconcile must not re-anchor a completed derived task back to the
    # part's last_replaced (which would wipe out the completion).
    import time

    anode = _anode_task(ha)
    asset_id = anode["source"]["part"]["asset_id"]
    call_service(ha, "home_keeper", "complete_task", {"task_id": anode["id"]})
    after_complete = next(t for t in _all_tasks(ha) if t["id"] == anode["id"])
    lc, nd = after_complete["last_completed"], after_complete["next_due"]
    assert lc, "completion should set last_completed"
    # Editing the asset triggers a reconcile of its part tasks.
    call_service(
        ha,
        "home_keeper",
        "update_asset",
        {"asset_id": asset_id, "manufacturer": "poke"},
    )
    time.sleep(1)
    after_reconcile = next(t for t in _all_tasks(ha) if t["id"] == anode["id"])
    assert after_reconcile["last_completed"] == lc, (
        "reconcile must not revert the completion"
    )
    assert after_reconcile["next_due"] == nd


def _part_tasks_for(ha, asset_id):
    """Tasks derived from a specific asset's parts (robust to shared-state runs)."""
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return [
        t
        for t in resp.get("service_response", resp)["tasks"]
        if (t.get("source") or {}).get("part", {}).get("asset_id") == asset_id
    ]


def _newest_asset_named(ha, name):
    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    matches = [
        a for a in resp.get("service_response", resp)["assets"] if a["name"] == name
    ]
    return matches[-1] if matches else None


def test_removing_wear_part_deletes_its_derived_task(ha):
    # Add an appliance with a wear part (creates a derived task), then update the
    # appliance with an empty parts list — the derived task must be removed (no
    # orphaning). update flows through async_apply_asset_change -> reconcile_part_tasks.
    import time
    import uuid

    name = f"Test HVAC {uuid.uuid4().hex[:8]}"
    call_service(
        ha,
        "home_keeper",
        "add_asset",
        {
            "name": name,
            "parts": [
                {
                    "name": "Belt",
                    "type": "wear",
                    "replace_interval": 6,
                    "replace_unit": "months",
                }
            ],
        },
    )
    asset = None
    for _ in range(20):
        asset = _newest_asset_named(ha, name)
        if asset and _part_tasks_for(ha, asset["id"]):
            break
        time.sleep(1)
    assert asset and _part_tasks_for(ha, asset["id"]), (
        "wear part should have created a task"
    )

    call_service(
        ha, "home_keeper", "update_asset", {"asset_id": asset["id"], "parts": []}
    )

    for _ in range(20):
        if not _part_tasks_for(ha, asset["id"]):
            break
        time.sleep(1)
    assert not _part_tasks_for(ha, asset["id"]), (
        "derived task should be removed with its part"
    )
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def test_wear_part_next_due_does_not_drift_on_asset_edit(ha):
    # Regression: a wear part with no last_replaced must keep a stable next_due when
    # the asset is edited. Reconciliation must not re-pass interval/unit and re-anchor
    # the floating clock to "now" on every edit.
    import time
    import uuid

    name = f"Drift probe {uuid.uuid4().hex[:8]}"
    call_service(
        ha,
        "home_keeper",
        "add_asset",
        {
            "name": name,
            "parts": [
                {
                    "name": "Filter",
                    "type": "wear",
                    "replace_interval": 3,
                    "replace_unit": "months",
                }
            ],
        },
    )
    asset = None
    for _ in range(20):
        asset = _newest_asset_named(ha, name)
        if asset and _part_tasks_for(ha, asset["id"]):
            break
        time.sleep(1)
    assert asset and _part_tasks_for(ha, asset["id"]), (
        "wear part should have created a task"
    )
    due_before = _part_tasks_for(ha, asset["id"])[0]["next_due"]

    call_service(
        ha,
        "home_keeper",
        "update_asset",
        {"asset_id": asset["id"], "name": name + " v2"},
    )

    due_after = _part_tasks_for(ha, asset["id"])[0]["next_due"]
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})
    assert due_after == due_before, f"next_due drifted: {due_before} -> {due_after}"


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
    call_service(
        ha,
        "home_keeper",
        "add_asset",
        {"name": "Living room piano", "icon": "mdi:piano"},
    )
    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    assets = resp.get("service_response", resp)["assets"]
    piano = next(a for a in assets if a["name"] == "Living room piano")
    # Relate it to the seeded water heater's (virtual) device as a foreign device.
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


def _assets(ha):
    resp = call_service(ha, "home_keeper", "list_assets", {}, return_response=True)
    return resp.get("service_response", resp)["assets"]


def _tasks(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def test_deleting_a_task_assigned_to_an_appliance_archives_its_history(ha):
    # Reference-counting retention: a task attached to an appliance keeps its
    # completion history on that appliance after the task itself is deleted.
    call_service(ha, "home_keeper", "add_asset", {"name": "Archive test heater"})
    asset = next(a for a in _assets(ha) if a["name"] == "Archive test heater")
    assert asset["device_id"], "virtual asset should be provisioned a device"

    add = call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Archive test flush",
            "recurrence_type": "floating",
            "interval": 6,
            "unit": "months",
            "device_id": asset["device_id"],
        },
        return_response=True,
    )
    task_id = add.get("service_response", add)["task_id"]

    call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
    call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})

    # The task is gone...
    assert all(t["id"] != task_id for t in _tasks(ha))
    # ...but its history is preserved on the appliance.
    asset = next(a for a in _assets(ha) if a["name"] == "Archive test heater")
    history = asset.get("task_history", [])
    entry = next((h for h in history if h["task_id"] == task_id), None)
    assert entry is not None, (
        "deleted task's history should be archived on the appliance"
    )
    assert entry["task_name"] == "Archive test flush"
    assert len(entry["completions"]) == 1

    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def test_deleting_a_standalone_task_does_not_archive(ha):
    # A task with no appliance association just disappears — nothing to retain.
    add = call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Standalone no-archive",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "weeks",
        },
        return_response=True,
    )
    task_id = add.get("service_response", add)["task_id"]
    call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
    call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})

    for asset in _assets(ha):
        assert all(h["task_id"] != task_id for h in asset.get("task_history", [])), (
            "a standalone task's history must not be archived anywhere"
        )


def _water_heater(ha):
    return next(a for a in _assets(ha) if a["name"] == "Garage water heater")


def test_export_inventory_service_returns_report_and_csv(ha):
    # The inventory export rolls the appliance metadata up for an insurance record.
    resp = call_service(ha, "home_keeper", "export_inventory", {}, return_response=True)
    payload = resp.get("service_response", resp)
    report = payload["inventory"]
    assert "assets" in report and "totals" in report
    wh = next(r for r in report["assets"] if r["name"] == "Garage water heater")
    assert wh["cost"] == 649.0
    # Serial number is a first-class identity column on the insurance record.
    assert wh["serial_number"] == "RH-2021-0099823"
    # Other descriptive metadata (warranty, dates…) is flattened into details.
    assert "Warranty expiry:" in wh["details"]
    assert report["totals"]["asset_count"] >= 1
    assert report["totals"]["total_cost"] >= 649.0
    # A ready-to-save CSV is included, with a header row naming the columns.
    csv = payload["csv"]
    assert csv.splitlines()[0].startswith("Name,")
    assert "Garage water heater" in csv


def test_adjust_part_stock_service_clamps_and_restocks(ha):
    wh = _water_heater(ha)
    part = next(p for p in wh["parts"] if p["name"] == "Anode rod")
    # Force to zero (clamped at zero) regardless of prior state, then restock by 2.
    call_service(
        ha,
        "home_keeper",
        "adjust_part_stock",
        {"asset_id": wh["id"], "part_id": part["id"], "delta": -100},
    )
    part = next(p for p in _water_heater(ha)["parts"] if p["name"] == "Anode rod")
    assert part["stock"] == 0
    call_service(
        ha,
        "home_keeper",
        "adjust_part_stock",
        {"asset_id": wh["id"], "part_id": part["id"], "delta": 2},
    )
    part = next(p for p in _water_heater(ha)["parts"] if p["name"] == "Anode rod")
    assert part["stock"] == 2


def test_adjust_part_stock_rejects_unknown_part(ha):
    from conftest import HA_URL

    wh = _water_heater(ha)
    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/adjust_part_stock",
        json={"asset_id": wh["id"], "part_id": "no_such_part", "delta": 1},
    )
    assert r.status_code >= 400, "expected rejection for an unknown part_id"


def test_add_asset_service_accepts_part_stock(ha):
    # Regression: the add/update_asset service schema must accept stock/reorder_at on
    # parts (the websocket path always did) — otherwise the documented service errors.
    call_service(
        ha,
        "home_keeper",
        "add_asset",
        {
            "name": "Stocked widget",
            "parts": [
                {"name": "Spare", "type": "consumable", "stock": 4, "reorder_at": 1}
            ],
        },
    )
    asset = next(a for a in _assets(ha) if a["name"] == "Stocked widget")
    part = asset["parts"][0]
    assert part["stock"] == 4 and part["reorder_at"] == 1
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})


def test_low_stock_event_fires_on_crossing_not_on_restock(ha):
    # A `home_keeper_part_low_stock` event must fire once when stock crosses from
    # not-low into low, and NOT on a restock. A configuration.yaml automation mirrors
    # the event into input_text.hk_last_low_stock_part as "<part_id>@<stock>".
    import time

    from conftest import get_state

    wh = _water_heater(ha)
    pid = next(p for p in wh["parts"] if p["name"] == "Anode rod")["id"]
    sentinel = "input_text.hk_last_low_stock_part"

    def _reset():
        call_service(
            ha, "input_text", "set_value", {"entity_id": sentinel, "value": "none"}
        )

    def _captured():
        st = get_state(ha, sentinel)
        return st["state"] if st else None

    # Restock well above the threshold (reorder_at=2) so the next drop is a crossing.
    call_service(
        ha,
        "home_keeper",
        "adjust_part_stock",
        {"asset_id": wh["id"], "part_id": pid, "delta": 10},
    )
    _reset()
    # Drop across the threshold but stay above zero -> a *low-stock* crossing (a drop
    # all the way to zero is the more specific `part_out_of_stock` event instead). Land
    # at the threshold so the part reads low without being out.
    part = next(p for p in _water_heater(ha)["parts"] if p["id"] == pid)
    target = max(1, part["reorder_at"])
    call_service(
        ha,
        "home_keeper",
        "adjust_part_stock",
        {"asset_id": wh["id"], "part_id": pid, "delta": target - part["stock"]},
    )
    deadline = time.monotonic() + 10
    captured = None
    while time.monotonic() < deadline:
        captured = _captured()
        if captured and captured != "none":
            break
        time.sleep(0.5)
    assert captured == f"{pid}@{target}", (
        f"expected a low-stock event for {pid}, got {captured!r}"
    )

    # A restock that leaves the part not-low must NOT re-fire the event.
    _reset()
    call_service(
        ha,
        "home_keeper",
        "adjust_part_stock",
        {"asset_id": wh["id"], "part_id": pid, "delta": 10},
    )
    time.sleep(2)
    assert _captured() == "none", "a restock must not fire a low-stock event"


def _add_consumable_appliance(ha, name, *, stock, reorder_at):
    """Create a virtual appliance with one stocked consumable; return (asset, part)."""
    import time

    call_service(
        ha,
        "home_keeper",
        "add_asset",
        {
            "name": name,
            "parts": [
                {
                    "name": "Water filter",
                    "type": "consumable",
                    "stock": stock,
                    "reorder_at": reorder_at,
                }
            ],
        },
    )
    for _ in range(20):
        asset = next((a for a in _assets(ha) if a["name"] == name), None)
        if asset and asset.get("parts"):
            return asset, asset["parts"][0]
        time.sleep(1)
    raise AssertionError(f"appliance {name!r} was not provisioned with its part")


def _add_floating_task(ha, name):
    add = call_service(
        ha,
        "home_keeper",
        "add_task",
        {"name": name, "recurrence_type": "floating", "interval": 6, "unit": "months"},
        return_response=True,
    )
    return add.get("service_response", add)["task_id"]


def test_manual_consumable_link_consumes_stock_on_completion(ha):
    # The headline flow: link an arbitrary task to a consumable, then completing it
    # draws down one spare and crosses the reorder threshold -> a low-stock event.
    import time
    import uuid

    from conftest import get_state

    name = f"Fridge {uuid.uuid4().hex[:8]}"
    asset, part = _add_consumable_appliance(ha, name, stock=2, reorder_at=1)
    task_id = _add_floating_task(ha, f"Replace filter {name}")

    # Link the task to the consumable.
    call_service(
        ha,
        "home_keeper",
        "set_task_consumable",
        {"task_id": task_id, "asset_id": asset["id"], "part_id": part["id"]},
    )
    linked = next(t for t in _all_tasks(ha) if t["id"] == task_id)
    assert linked["source"]["part"] == {
        "asset_id": asset["id"],
        "part_id": part["id"],
        "manual": True,
    }

    # Arm the low-stock sentinel automation, then complete the task: stock 2 -> 1,
    # which lands at reorder_at (==1) and fires home_keeper_part_low_stock.
    sentinel = "input_text.hk_last_low_stock_part"
    call_service(
        ha, "input_text", "set_value", {"entity_id": sentinel, "value": "none"}
    )
    call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})

    fresh_part = next(p for p in _assets_part(ha, asset["id"]))
    assert fresh_part["stock"] == 1, "completing a linked task must consume one spare"

    deadline = time.monotonic() + 10
    captured = None
    while time.monotonic() < deadline:
        st = get_state(ha, sentinel)
        captured = st["state"] if st else None
        if captured and captured != "none":
            break
        time.sleep(0.5)
    assert captured == f"{part['id']}@1", (
        f"expected a low-stock event for {part['id']}, got {captured!r}"
    )


def _assets_part(ha, asset_id):
    asset = next(a for a in _assets(ha) if a["id"] == asset_id)
    return list(asset.get("parts", []))


def test_manual_link_survives_reconcile_and_can_be_cleared(ha):
    # A manually-linked task must NOT be orphan-deleted by a reconcile (the part has
    # no wear cadence), and clearing the link drops the part source.
    import time
    import uuid

    name = f"Fridge {uuid.uuid4().hex[:8]}"
    asset, part = _add_consumable_appliance(ha, name, stock=5, reorder_at=1)
    task_id = _add_floating_task(ha, f"Replace filter {name}")
    call_service(
        ha,
        "home_keeper",
        "set_task_consumable",
        {"task_id": task_id, "asset_id": asset["id"], "part_id": part["id"]},
    )

    # Editing the asset triggers a part-task reconcile.
    call_service(
        ha, "home_keeper", "update_asset", {"asset_id": asset["id"], "model": "X"}
    )
    time.sleep(1)
    assert any(t["id"] == task_id for t in _all_tasks(ha)), (
        "a manually-linked task must survive reconcile"
    )

    # Clearing the link (no asset/part) drops the source.
    call_service(ha, "home_keeper", "set_task_consumable", {"task_id": task_id})
    cleared = next(t for t in _all_tasks(ha) if t["id"] == task_id)
    assert not (cleared.get("source") or {}).get("part"), "link should be cleared"


def test_set_task_consumable_rejects_derived_task(ha):
    # A reconciler-derived wear-part task is already bound to its part; re-linking it
    # by hand must be rejected.
    from conftest import HA_URL

    anode = _anode_task(ha)
    asset_id = anode["source"]["part"]["asset_id"]
    part_id = anode["source"]["part"]["part_id"]
    r = ha.post(
        f"{HA_URL}/api/services/home_keeper/set_task_consumable",
        json={"task_id": anode["id"], "asset_id": asset_id, "part_id": part_id},
    )
    assert r.status_code >= 400, (
        f"linking a derived task should be rejected, got {r.status_code}"
    )


def test_manual_link_task_is_deletable(ha):
    # Regression: a manually-linked task is user-owned and must be freely deletable —
    # the wear-part delete guard must not block it (unlike a reconciler-derived task).
    import uuid

    name = f"Fridge {uuid.uuid4().hex[:8]}"
    asset, part = _add_consumable_appliance(ha, name, stock=3, reorder_at=1)
    task_id = _add_floating_task(ha, f"Replace filter {name}")
    call_service(
        ha,
        "home_keeper",
        "set_task_consumable",
        {"task_id": task_id, "asset_id": asset["id"], "part_id": part["id"]},
    )
    # Deleting it must succeed (no "managed by an appliance wear part" rejection).
    call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})
    assert all(t["id"] != task_id for t in _all_tasks(ha)), (
        "a manually-linked task must be deletable"
    )


def test_deleting_asset_unlinks_manual_link_task(ha):
    # Regression: deleting the appliance must NOT delete a user's manually-linked task —
    # it only clears the (now-dangling) link, keeping the task as a standalone task.
    import uuid

    name = f"Fridge {uuid.uuid4().hex[:8]}"
    asset, part = _add_consumable_appliance(ha, name, stock=3, reorder_at=1)
    task_id = _add_floating_task(ha, f"Replace filter {name}")
    call_service(
        ha,
        "home_keeper",
        "set_task_consumable",
        {"task_id": task_id, "asset_id": asset["id"], "part_id": part["id"]},
    )
    call_service(ha, "home_keeper", "delete_asset", {"asset_id": asset["id"]})
    survivor = next((t for t in _all_tasks(ha) if t["id"] == task_id), None)
    assert survivor is not None, (
        "deleting the appliance must not delete the user's task"
    )
    assert not (survivor.get("source") or {}).get("part"), (
        "the dangling consumable link should be cleared"
    )
