"""Unit tests for asset (appliance) construction / validation / updates.

These exercise the pure ``assets`` model — no Home Assistant runtime. Device
provisioning (``devices.py``) imports HA and is covered by the integration tests.
"""

from datetime import datetime, timedelta, timezone

import hk_assets as a
import pytest

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)


def test_build_virtual_asset_sets_id_identifier_and_created():
    asset = a.build_asset(
        {"name": "Kitchen fridge", "manufacturer": "Frigidaire", "model": "FGHB2868TF"},
        now=NOW,
    )
    assert asset["id"]
    assert asset["kind"] == "virtual"
    assert asset["name"] == "Kitchen fridge"
    assert asset["manufacturer"] == "Frigidaire"
    # device_id is filled later by provisioning; identifiers anchor the device.
    assert asset["device_id"] is None
    assert asset["identifiers"] == [["home_keeper", f"asset_{asset['id']}"]]
    assert asset["created"] == NOW.isoformat()


def test_asset_device_identifier_is_prefixed():
    # Must not collide with a per-task self-owned device (bare task id).
    domain, ident = a.asset_device_identifier("abc-123")
    assert domain == "home_keeper"
    assert ident == "asset_abc-123"


def test_build_virtual_asset_requires_name():
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"manufacturer": "X"}, now=NOW)


def test_build_existing_asset_requires_device_id():
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"kind": "existing"}, now=NOW)


def test_build_existing_asset_keeps_device_id_no_identifier():
    asset = a.build_asset(
        {"kind": "existing", "device_id": "dev_xyz", "warranty_expiry": "2030-01-01"},
        now=NOW,
    )
    assert asset["kind"] == "existing"
    assert asset["device_id"] == "dev_xyz"
    # We don't own the device, so no virtual identifier is minted.
    assert asset["identifiers"] == []
    assert asset["warranty_expiry"] == "2030-01-01"


def test_build_asset_rejects_bad_kind():
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"name": "x", "kind": "imaginary"}, now=NOW)


def test_date_fields_normalized_to_iso_date():
    asset = a.build_asset(
        {
            "name": "Furnace",
            "purchase_date": "2024-03-15",
            # A full datetime should be truncated to its date.
            "warranty_expiry": "2029-03-15T00:00:00",
        },
        now=NOW,
    )
    assert asset["purchase_date"] == "2024-03-15"
    assert asset["warranty_expiry"] == "2029-03-15"


def test_empty_date_is_none():
    asset = a.build_asset({"name": "Furnace", "purchase_date": ""}, now=NOW)
    assert asset["purchase_date"] is None


def test_bad_date_raises():
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"name": "Furnace", "warranty_expiry": "not-a-date"}, now=NOW)


def test_cost_coerced_and_bad_cost_raises():
    asset = a.build_asset({"name": "Furnace", "cost": "1299.99"}, now=NOW)
    assert asset["cost"] == pytest.approx(1299.99)
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"name": "Furnace", "cost": "free"}, now=NOW)


def test_negative_cost_raises():
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"name": "Furnace", "cost": "-5"}, now=NOW)


def test_manual_url_accepts_http_and_https():
    asset = a.build_asset(
        {"name": "Furnace", "manual_url": "https://example.com/manual.pdf"}, now=NOW
    )
    assert asset["manual_url"] == "https://example.com/manual.pdf"
    # Empty is allowed and normalizes to "".
    assert a.build_asset({"name": "Furnace"}, now=NOW)["manual_url"] == ""


def test_manual_url_rejects_non_http_scheme():
    for bad in ("javascript:alert(1)", "ftp://example.com", "data:text/html,x", "/relative"):
        with pytest.raises(a.AssetValidationError):
            a.build_asset({"name": "Furnace", "manual_url": bad}, now=NOW)


def test_manual_url_rejects_overlong():
    long_url = "https://example.com/" + "a" * 3000
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"name": "Furnace", "manual_url": long_url}, now=NOW)


def test_merge_update_validates_url_and_cost():
    asset = a.build_asset({"name": "Furnace"}, now=NOW)
    with pytest.raises(a.AssetValidationError):
        a.merge_update(asset, {"manual_url": "javascript:bad"}, now=NOW)
    with pytest.raises(a.AssetValidationError):
        a.merge_update(asset, {"cost": -1}, now=NOW)
    ok = a.merge_update(asset, {"manual_url": "http://ok.example"}, now=NOW)
    assert ok["manual_url"] == "http://ok.example"


def test_merge_update_changes_metadata_preserves_anchors():
    asset = a.build_asset({"name": "Fridge"}, now=NOW)
    asset["device_id"] = "provisioned_dev_1"  # simulate post-provisioning
    updated = a.merge_update(
        asset, {"manufacturer": "LG", "warranty_expiry": "2031-06-01"}, now=NOW
    )
    assert updated["manufacturer"] == "LG"
    assert updated["warranty_expiry"] == "2031-06-01"
    # Immutable anchors survive an edit.
    assert updated["kind"] == "virtual"
    assert updated["identifiers"] == asset["identifiers"]
    assert updated["device_id"] == "provisioned_dev_1"


def test_merge_update_existing_can_retarget_device():
    asset = a.build_asset(
        {"kind": "existing", "device_id": "dev_a"}, now=NOW
    )
    updated = a.merge_update(asset, {"device_id": "dev_b"}, now=NOW)
    assert updated["device_id"] == "dev_b"
    assert updated["kind"] == "existing"


# ── Phase 0/1/3: icon, parts, relationships, migration ─────────────────────────


def test_icon_valid_and_invalid():
    assert a.build_asset({"name": "Piano", "icon": "mdi:piano"}, now=NOW)["icon"] == "mdi:piano"
    assert a.build_asset({"name": "Piano"}, now=NOW)["icon"] == ""
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"name": "Piano", "icon": "not an icon"}, now=NOW)


def test_parts_default_empty_and_legacy_field_dropped():
    asset = a.build_asset({"name": "Fridge"}, now=NOW)
    assert asset["parts"] == []
    # part_numbers is no longer a stored field on new assets.
    assert "part_numbers" not in asset


def test_parts_normalized_with_ids_and_types():
    asset = a.build_asset(
        {
            "name": "Shades",
            "parts": [
                {"name": "Shade material", "type": "wear", "replace_interval": 10,
                 "replace_unit": "months", "cost": "120"},
                {"name": "Cord", "part_number": "C-9"},  # defaults to consumable
            ],
        },
        now=NOW,
    )
    parts = asset["parts"]
    assert len(parts) == 2
    assert parts[0]["id"] and parts[1]["id"]
    assert parts[0]["type"] == "wear"
    assert parts[0]["replace_interval"] == 10
    assert parts[0]["replace_unit"] == "months"
    assert parts[0]["cost"] == pytest.approx(120.0)
    assert parts[1]["type"] == "consumable"
    assert parts[1]["replace_interval"] is None


def test_part_requires_name_and_valid_type():
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"name": "X", "parts": [{"name": ""}]}, now=NOW)
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"name": "X", "parts": [{"name": "p", "type": "bogus"}]}, now=NOW)


def test_part_bad_interval_unit_rejected():
    with pytest.raises(a.AssetValidationError):
        a.build_asset(
            {"name": "X", "parts": [{"name": "p", "replace_interval": 1, "replace_unit": "eons"}]},
            now=NOW,
        )


def test_merge_update_preserves_part_last_replaced():
    asset = a.build_asset(
        {"name": "Shades", "parts": [{"name": "Material", "type": "wear", "replace_interval": 6, "replace_unit": "months"}]},
        now=NOW,
    )
    pid = asset["parts"][0]["id"]
    asset["parts"][0]["last_replaced"] = "2025-01-01"  # simulate a completion stamp
    # The panel re-submits the part without last_replaced; merge must keep it.
    updated = a.merge_update(
        asset,
        {"parts": [{"id": pid, "name": "Material", "type": "wear", "replace_interval": 12, "replace_unit": "months"}]},
        now=NOW,
    )
    assert updated["parts"][0]["last_replaced"] == "2025-01-01"
    assert updated["parts"][0]["replace_interval"] == 12


def test_migrate_legacy_part_numbers():
    legacy = {"id": "x", "kind": "virtual", "name": "WH", "part_numbers": "anode rod AR-1"}
    changed = a.migrate_legacy_part_numbers(legacy)
    assert changed is True
    assert "part_numbers" not in legacy
    assert legacy["parts"][0]["name"] == "anode rod AR-1"
    assert legacy["parts"][0]["type"] == "consumable"
    # Idempotent: a second pass with parts present and no legacy string is a no-op.
    assert a.migrate_legacy_part_numbers(legacy) is False


def test_parent_asset_id_only_for_virtual():
    virt = a.build_asset({"name": "Sub", "parent_asset_id": "parent-1"}, now=NOW)
    assert virt["parent_asset_id"] == "parent-1"
    existing = a.build_asset(
        {"kind": "existing", "device_id": "dev", "parent_asset_id": "parent-1"}, now=NOW
    )
    assert existing["parent_asset_id"] is None


def test_part_rejects_future_last_replaced():
    from datetime import date, timedelta as _td

    future = (date.today() + _td(days=30)).isoformat()
    with pytest.raises(a.AssetValidationError):
        a.build_asset(
            {"name": "Boiler", "parts": [{"name": "Anode", "last_replaced": future}]},
            now=NOW,
        )


def test_part_allows_today_last_replaced():
    from datetime import date

    asset = a.build_asset(
        {"name": "Boiler", "parts": [{"name": "Anode", "last_replaced": date.today().isoformat()}]},
        now=NOW,
    )
    assert asset["parts"][0]["last_replaced"] == date.today().isoformat()


def test_duplicate_part_ids_are_regenerated():
    asset = a.build_asset(
        {
            "name": "Box",
            "parts": [
                {"id": "dup", "name": "A"},
                {"id": "dup", "name": "B"},
            ],
        },
        now=NOW,
    )
    ids = [p["id"] for p in asset["parts"]]
    assert len(set(ids)) == 2, ids


def test_oversized_replace_interval_rejected():
    with pytest.raises(a.AssetValidationError):
        a.build_asset(
            {"name": "Box", "parts": [{"name": "A", "type": "wear", "replace_interval": 10**9}]},
            now=NOW,
        )


def test_related_device_ids_listified():
    asset = a.build_asset(
        {"name": "Piano", "related_device_ids": ["dev_a", "dev_b", ""]}, now=NOW
    )
    assert asset["related_device_ids"] == ["dev_a", "dev_b"]
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"name": "Piano", "related_device_ids": "notalist"}, now=NOW)


def test_would_create_cycle():
    assets_by_id = {
        "a": {"id": "a", "parent_asset_id": None},
        "b": {"id": "b", "parent_asset_id": "a"},
    }
    # Making 'a' a child of 'b' would loop a->b->a.
    assert a.would_create_cycle(assets_by_id, "a", "b") is True
    # 'b' under 'a' is fine (already the case); a fresh child is fine.
    assert a.would_create_cycle(assets_by_id, "c", "a") is False


# ── spare-inventory tracking (stock / reorder_at) ──────────────────────────────
def test_part_stock_fields_normalized():
    asset = a.build_asset(
        {"name": "Furnace", "parts": [{"name": "Filter", "stock": "4", "reorder_at": "1"}]},
        now=NOW,
    )
    part = asset["parts"][0]
    assert part["stock"] == 4
    assert part["reorder_at"] == 1


def test_part_stock_defaults_none_and_untracked():
    asset = a.build_asset({"name": "X", "parts": [{"name": "Filter"}]}, now=NOW)
    part = asset["parts"][0]
    assert part["stock"] is None and part["reorder_at"] is None


def test_negative_stock_rejected():
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"name": "X", "parts": [{"name": "F", "stock": -1}]}, now=NOW)


def test_non_integer_stock_rejected():
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"name": "X", "parts": [{"name": "F", "stock": "lots"}]}, now=NOW)


def test_oversized_stock_rejected():
    with pytest.raises(a.AssetValidationError):
        a.build_asset(
            {"name": "X", "parts": [{"name": "F", "reorder_at": 10**9}]}, now=NOW
        )


def test_part_is_low():
    assert a.part_is_low({"stock": 1, "reorder_at": 1}) is True
    assert a.part_is_low({"stock": 0, "reorder_at": 1}) is True
    assert a.part_is_low({"stock": 2, "reorder_at": 1}) is False
    # Untracked stock or no threshold is never "low".
    assert a.part_is_low({"stock": None, "reorder_at": 1}) is False
    assert a.part_is_low({"stock": 0, "reorder_at": None}) is False


def test_consume_part_stock_flags_low_only_on_crossing():
    part = {"stock": 3, "reorder_at": 1}
    # 3 -> 2, still above the threshold of 1.
    assert a.consume_part_stock(part) is False
    assert part["stock"] == 2
    # 2 -> 1 crosses from not-low into low.
    assert a.consume_part_stock(part) is True
    assert part["stock"] == 1
    # 1 -> 0, already low: edge-triggered, so no repeat signal.
    assert a.consume_part_stock(part) is False
    assert part["stock"] == 0


def test_consume_part_stock_floors_at_zero_without_refiring():
    # Already low (and at zero): consuming again clamps at zero and does not re-fire.
    part = {"stock": 0, "reorder_at": 0}
    assert a.consume_part_stock(part) is False
    assert part["stock"] == 0


def test_consume_part_stock_noop_when_untracked():
    part = {"stock": None, "reorder_at": 2}
    assert a.consume_part_stock(part) is False
    assert part["stock"] is None


def test_adjust_part_stock_restock_and_clamp():
    part = {"stock": 1, "reorder_at": 1}
    # Restock by 3 -> 4, no longer low.
    assert a.adjust_part_stock(part, 3) is False
    assert part["stock"] == 4
    # Consume 5 -> clamps at 0, now low.
    assert a.adjust_part_stock(part, -5) is True
    assert part["stock"] == 0


def test_adjust_part_stock_begins_tracking_from_zero():
    part = {"stock": None, "reorder_at": None}
    a.adjust_part_stock(part, 2)
    assert part["stock"] == 2


def test_adjust_part_stock_no_refire_while_already_low():
    # Decreasing while already low must not re-signal (edge-triggered).
    part = {"stock": 1, "reorder_at": 2}
    assert a.adjust_part_stock(part, -1) is False
    assert part["stock"] == 0
    # Restocking back up to/below the threshold also doesn't signal.
    assert a.adjust_part_stock(part, 2) is False
    assert part["stock"] == 2


def test_merge_update_clears_part_stock_when_omitted():
    # stock/reorder_at are ordinary editable fields: a resubmit that omits them
    # clears the tracking (so the user can switch it back off), while the
    # backend-managed last_replaced is still preserved.
    asset = a.build_asset(
        {
            "name": "Furnace",
            "parts": [{"name": "Filter", "stock": 3, "reorder_at": 1}],
        },
        now=NOW,
    )
    pid = asset["parts"][0]["id"]
    asset["parts"][0]["last_replaced"] = "2025-01-01"  # backend completion stamp
    updated = a.merge_update(
        asset, {"parts": [{"id": pid, "name": "Filter"}]}, now=NOW
    )
    assert updated["parts"][0]["stock"] is None
    assert updated["parts"][0]["reorder_at"] is None
    assert updated["parts"][0]["last_replaced"] == "2025-01-01"


def test_merge_update_sets_part_stock_from_incoming():
    asset = a.build_asset(
        {"name": "Furnace", "parts": [{"name": "Filter", "stock": 3, "reorder_at": 1}]},
        now=NOW,
    )
    pid = asset["parts"][0]["id"]
    updated = a.merge_update(
        asset,
        {"parts": [{"id": pid, "name": "Filter", "stock": 5, "reorder_at": 2}]},
        now=NOW,
    )
    assert updated["parts"][0]["stock"] == 5
    assert updated["parts"][0]["reorder_at"] == 2
