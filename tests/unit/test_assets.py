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
