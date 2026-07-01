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


def test_serial_number_is_a_first_class_text_field():
    # serial_number normalizes like manufacturer/model and round-trips through build +
    # update (it syncs into the device-page info block in devices.py).
    asset = a.build_asset(
        {"name": "Water heater", "serial_number": "  RH-2021-0099  "}, now=NOW
    )
    assert asset["serial_number"] == "RH-2021-0099"
    updated = a.merge_update(asset, {"serial_number": "NEW-SERIAL"}, now=NOW)
    assert updated["serial_number"] == "NEW-SERIAL"
    # Omitted on update -> preserved (text fields read from existing).
    untouched = a.merge_update(updated, {"model": "XE50"}, now=NOW)
    assert untouched["serial_number"] == "NEW-SERIAL"


def test_serial_number_defaults_empty_when_absent():
    asset = a.build_asset({"name": "No serial"}, now=NOW)
    assert asset["serial_number"] == ""


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
        {
            "kind": "existing",
            "device_id": "dev_xyz",
            "metadata": [
                {"type": "date", "label": "Warranty expiry", "value": "2030-01-01"}
            ],
        },
        now=NOW,
    )
    assert asset["kind"] == "existing"
    assert asset["device_id"] == "dev_xyz"
    # We don't own the device, so no virtual identifier is minted.
    assert asset["identifiers"] == []
    assert asset["metadata"][0]["value"] == "2030-01-01"


def test_build_asset_rejects_bad_kind():
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"name": "x", "kind": "imaginary"}, now=NOW)


def test_metadata_entries_normalized():
    asset = a.build_asset(
        {
            "name": "Furnace",
            "metadata": [
                {"type": "date", "label": "Purchase date", "value": "2024-03-15"},
                # A full datetime should be truncated to its date.
                {
                    "type": "date",
                    "label": "Warranty expiry",
                    "value": "2029-03-15T00:00:00",
                    "track": True,
                },
                {
                    "type": "link",
                    "label": "Spec sheet",
                    "value": "https://example.com/spec.pdf",
                },
                {"type": "text", "label": "Serial", "value": "  SN-7  "},
            ],
        },
        now=NOW,
    )
    meta = asset["metadata"]
    assert meta[0]["value"] == "2024-03-15"
    # Non-tracked date defaults track to False; tracked one keeps it True.
    assert meta[0]["track"] is False
    assert meta[1]["value"] == "2029-03-15"
    assert meta[1]["track"] is True
    assert meta[2]["value"] == "https://example.com/spec.pdf"
    assert meta[3]["value"] == "SN-7"  # trimmed
    # Every entry gets a stable id.
    assert all(entry["id"] for entry in meta)


def test_metadata_requires_label():
    with pytest.raises(a.AssetValidationError):
        a.build_asset(
            {"name": "Furnace", "metadata": [{"type": "text", "value": "orphan"}]},
            now=NOW,
        )


def test_metadata_rejects_bad_type():
    with pytest.raises(a.AssetValidationError):
        a.build_asset(
            {
                "name": "Furnace",
                "metadata": [{"type": "number", "label": "x", "value": "1"}],
            },
            now=NOW,
        )


def test_metadata_empty_date_is_blank():
    asset = a.build_asset(
        {
            "name": "Furnace",
            "metadata": [{"type": "date", "label": "Purchase date", "value": ""}],
        },
        now=NOW,
    )
    assert asset["metadata"][0]["value"] == ""


def test_metadata_bad_date_raises():
    with pytest.raises(a.AssetValidationError):
        a.build_asset(
            {
                "name": "Furnace",
                "metadata": [
                    {"type": "date", "label": "Warranty", "value": "not-a-date"}
                ],
            },
            now=NOW,
        )


def test_metadata_link_rejects_non_http():
    with pytest.raises(a.AssetValidationError):
        a.build_asset(
            {
                "name": "Furnace",
                "metadata": [
                    {"type": "link", "label": "Bad", "value": "javascript:alert(1)"}
                ],
            },
            now=NOW,
        )


def test_cost_coerced_and_bad_cost_raises():
    asset = a.build_asset({"name": "Furnace", "cost": "1299.99"}, now=NOW)
    assert asset["cost"] == pytest.approx(1299.99)
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"name": "Furnace", "cost": "free"}, now=NOW)


def test_negative_cost_raises():
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"name": "Furnace", "cost": "-5"}, now=NOW)


def test_documents_default_empty_and_link_normalized():
    # No documents -> empty list (every asset carries the key).
    assert a.build_asset({"name": "Furnace"}, now=NOW)["documents"] == []
    asset = a.build_asset(
        {
            "name": "Furnace",
            "documents": [
                {"kind": "link", "name": "Manual", "url": "https://ex.com/m.pdf"}
            ],
        },
        now=NOW,
    )
    doc = asset["documents"][0]
    assert doc["kind"] == "link"
    assert doc["name"] == "Manual"
    assert doc["url"] == "https://ex.com/m.pdf"
    assert doc["id"]  # an id is assigned


def test_document_link_name_falls_back_to_host():
    asset = a.build_asset(
        {"name": "Furnace", "documents": [{"kind": "link", "url": "https://ex.com/m"}]},
        now=NOW,
    )
    assert asset["documents"][0]["name"] == "ex.com"


def test_document_link_rejects_non_http_scheme():
    for bad in ("javascript:alert(1)", "ftp://example.com", "/relative"):
        with pytest.raises(a.AssetValidationError):
            a.build_asset(
                {"name": "Furnace", "documents": [{"kind": "link", "url": bad}]},
                now=NOW,
            )


def test_document_file_validated_and_unsafe_filename_rejected():
    # File documents arrive via the upload path (append_document), not a generic write.
    asset = a.build_asset({"name": "Furnace"}, now=NOW)
    doc = a.append_document(
        asset,
        {
            "kind": "file",
            "filename": "manual.pdf",
            "content_type": "application/pdf",
            "size": 1234,
        },
        created="2026-06-13T10:00:00",
    )
    assert doc["kind"] == "file"
    assert doc["filename"] == "manual.pdf"
    assert doc["content_type"] == "application/pdf"
    assert doc["size"] == 1234
    assert doc["name"] == "manual.pdf"  # name falls back to filename
    # Path-traversal / unsafe filenames and disallowed content types are rejected.
    for bad in (
        {
            "kind": "file",
            "filename": "../escape.pdf",
            "content_type": "application/pdf",
        },
        {
            "kind": "file",
            "filename": "ok.exe",
            "content_type": "application/x-msdownload",
        },
    ):
        with pytest.raises(a.AssetValidationError):
            a.append_document(asset, bad, created="")


def test_build_asset_strips_file_documents():
    # A create payload can only seed link documents (a brand-new asset has no blobs);
    # any file entry is dropped rather than becoming a phantom (blob-less) document.
    asset = a.build_asset(
        {
            "name": "Furnace",
            "documents": [
                {"kind": "link", "url": "https://ex.com/m"},
                {
                    "kind": "file",
                    "filename": "ghost.pdf",
                    "content_type": "application/pdf",
                },
            ],
        },
        now=NOW,
    )
    kinds = [d["kind"] for d in asset["documents"]]
    assert kinds == ["link"]


def test_merge_update_documents_are_upload_only_for_files():
    # Seed an asset with one link and one (uploaded) file document.
    asset = a.build_asset({"name": "Furnace"}, now=NOW)
    a.append_document(asset, {"kind": "link", "url": "https://ex.com/a"}, created="")
    file_doc = a.append_document(
        asset,
        {"kind": "file", "filename": "m.pdf", "content_type": "application/pdf"},
        created="",
    )
    # A generic update that resends only a link must preserve the file document
    # (no orphaned blob) and cannot inject a phantom file entry.
    merged = a.merge_update(
        asset,
        {
            "documents": [
                {"kind": "link", "url": "https://ex.com/b"},
                {
                    "kind": "file",
                    "filename": "phantom.pdf",
                    "content_type": "application/pdf",
                },
            ]
        },
        now=NOW,
    )
    files = [d for d in merged["documents"] if d["kind"] == "file"]
    links = [d for d in merged["documents"] if d["kind"] == "link"]
    assert [d["id"] for d in files] == [
        file_doc["id"]
    ]  # original file kept, phantom dropped
    assert [d["url"] for d in links] == ["https://ex.com/b"]  # link replaced
    # Omitting documents entirely preserves the whole list unchanged.
    untouched = a.merge_update(asset, {"name": "Boiler"}, now=NOW)
    assert untouched["documents"] == asset["documents"]


def test_documents_count_is_capped():
    too_many = [{"kind": "link", "url": f"https://ex.com/{i}"} for i in range(51)]
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"name": "Furnace", "documents": too_many}, now=NOW)


def test_merge_update_caps_merged_documents_total():
    # _normalize_documents caps only the incoming payload; _merge_documents then
    # prepends the stored *file* documents, so a payload that is itself under the cap
    # can push the merged total over it. The merged result must be re-checked.
    asset = a.build_asset({"name": "Furnace"}, now=NOW)
    # Seed the asset with 30 uploaded file documents (upload-only; carried through).
    for i in range(30):
        a.append_document(
            asset,
            {
                "kind": "file",
                "filename": f"m{i}.pdf",
                "content_type": "application/pdf",
            },
            created="",
        )
    # A generic edit sending 30 links: 30 files + 30 links = 60 > _MAX_DOCUMENTS (50).
    incoming = [{"kind": "link", "url": f"https://ex.com/{i}"} for i in range(30)]
    with pytest.raises(a.AssetValidationError):
        a.merge_update(asset, {"documents": incoming}, now=NOW)
    # A payload that keeps the merged total within the cap is accepted (30 + 15 = 45).
    fifteen = [{"kind": "link", "url": f"https://ex.com/{i}"} for i in range(15)]
    ok = a.merge_update(asset, {"documents": fifteen}, now=NOW)
    assert len(ok["documents"]) == 45


def test_duplicate_document_ids_are_regenerated():
    asset = a.build_asset(
        {
            "name": "Furnace",
            "documents": [
                {"id": "dup", "kind": "link", "url": "https://ex.com/1"},
                {"id": "dup", "kind": "link", "url": "https://ex.com/2"},
            ],
        },
        now=NOW,
    )
    ids = [d["id"] for d in asset["documents"]]
    assert len(set(ids)) == 2


def test_merge_update_validates_documents_and_cost():
    asset = a.build_asset({"name": "Furnace"}, now=NOW)
    with pytest.raises(a.AssetValidationError):
        a.merge_update(
            asset, {"documents": [{"kind": "link", "url": "javascript:bad"}]}, now=NOW
        )
    with pytest.raises(a.AssetValidationError):
        a.merge_update(asset, {"cost": -1}, now=NOW)
    ok = a.merge_update(
        asset, {"documents": [{"kind": "link", "url": "http://ok.example"}]}, now=NOW
    )
    assert ok["documents"][0]["url"] == "http://ok.example"
    # Omitting documents on an update preserves the existing list.
    preserved = a.merge_update(ok, {"name": "Boiler"}, now=NOW)
    assert preserved["documents"] == ok["documents"]


def test_append_and_remove_document():
    asset = a.build_asset({"name": "Furnace"}, now=NOW)
    entry = a.append_document(
        asset,
        {"kind": "link", "url": "https://ex.com/m"},
        created="2026-06-13T10:00:00",
    )
    assert entry["created"] == "2026-06-13T10:00:00"
    assert asset["documents"] == [entry]
    removed = a.remove_document(asset, entry["id"])
    assert removed == entry
    assert asset["documents"] == []
    assert a.remove_document(asset, "missing") is None


def test_update_document_link_changes_name_and_url():
    asset = a.build_asset({"name": "Furnace"}, now=NOW)
    entry = a.append_document(
        asset,
        {"kind": "link", "name": "Manual", "url": "https://ex.com/m"},
        created="2026-06-13T10:00:00",
    )
    updated = a.update_document(
        asset, entry["id"], {"name": "Owner's manual", "url": "https://ex.com/new.pdf"}
    )
    assert updated is not None
    assert updated["name"] == "Owner's manual"
    assert updated["url"] == "https://ex.com/new.pdf"
    # id/kind/created are preserved; the stored list reflects the edit.
    assert updated["id"] == entry["id"]
    assert updated["kind"] == "link"
    assert updated["created"] == "2026-06-13T10:00:00"
    assert asset["documents"] == [updated]


def test_update_document_file_renames_but_keeps_blob_fields():
    asset = a.build_asset({"name": "Furnace"}, now=NOW)
    doc = a.append_document(
        asset,
        {
            "kind": "file",
            "filename": "manual.pdf",
            "content_type": "application/pdf",
            "size": 1234,
        },
        created="2026-06-13T10:00:00",
    )
    # A file is upload-only: only its display name is editable; a url change is ignored.
    updated = a.update_document(
        asset, doc["id"], {"name": "Warranty", "url": "https://evil.example/x"}
    )
    assert updated is not None
    assert updated["name"] == "Warranty"
    assert updated["filename"] == "manual.pdf"
    assert updated["content_type"] == "application/pdf"
    assert updated["size"] == 1234
    assert "url" not in updated


def test_update_document_rejects_bad_url_and_missing_id():
    asset = a.build_asset({"name": "Furnace"}, now=NOW)
    entry = a.append_document(
        asset, {"kind": "link", "url": "https://ex.com/m"}, created=""
    )
    with pytest.raises(a.AssetValidationError):
        a.update_document(asset, entry["id"], {"url": "javascript:alert(1)"})
    # A non-dict change set is rejected; an unknown document id returns None.
    with pytest.raises(a.AssetValidationError):
        a.update_document(asset, entry["id"], "nope")
    assert a.update_document(asset, "missing", {"name": "x"}) is None


def test_migrate_documents_from_manual_url():
    # Legacy manual_url folds into a single link document and is dropped.
    asset = {"name": "Furnace", "manual_url": "https://ex.com/old.pdf"}
    assert a.migrate_documents_from_manual_url(asset) is True
    assert "manual_url" not in asset
    assert asset["documents"] == [
        {
            "id": asset["documents"][0]["id"],
            "kind": "link",
            "name": "ex.com",
            "url": "https://ex.com/old.pdf",
            "created": "",
        }
    ]
    # Idempotent: a second pass with no manual_url leaves it unchanged.
    assert a.migrate_documents_from_manual_url(asset) is False
    # An asset that never had manual_url still gains an empty documents list once.
    bare: dict = {"name": "Boiler"}
    assert a.migrate_documents_from_manual_url(bare) is True
    assert bare["documents"] == []


def test_merge_update_changes_metadata_preserves_anchors():
    asset = a.build_asset({"name": "Fridge"}, now=NOW)
    asset["device_id"] = "provisioned_dev_1"  # simulate post-provisioning
    updated = a.merge_update(
        asset,
        {
            "manufacturer": "LG",
            "metadata": [
                {"type": "date", "label": "Warranty expiry", "value": "2031-06-01"}
            ],
        },
        now=NOW,
    )
    assert updated["manufacturer"] == "LG"
    assert updated["metadata"][0]["value"] == "2031-06-01"
    # Immutable anchors survive an edit.
    assert updated["kind"] == "virtual"
    assert updated["identifiers"] == asset["identifiers"]
    assert updated["device_id"] == "provisioned_dev_1"


def test_merge_update_existing_can_retarget_device():
    asset = a.build_asset({"kind": "existing", "device_id": "dev_a"}, now=NOW)
    updated = a.merge_update(asset, {"device_id": "dev_b"}, now=NOW)
    assert updated["device_id"] == "dev_b"
    assert updated["kind"] == "existing"


# ── Phase 0/1/3: icon, parts, relationships, migration ─────────────────────────


def test_icon_valid_and_invalid():
    assert (
        a.build_asset({"name": "Piano", "icon": "mdi:piano"}, now=NOW)["icon"]
        == "mdi:piano"
    )
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
                {
                    "name": "Shade material",
                    "type": "wear",
                    "replace_interval": 10,
                    "replace_unit": "months",
                    "cost": "120",
                    "url": "https://example.com/shade-material",
                },
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
    assert parts[0]["url"] == "https://example.com/shade-material"
    assert parts[1]["type"] == "consumable"
    assert parts[1]["replace_interval"] is None
    assert parts[1]["url"] == ""


def test_part_url_rejects_non_http_scheme_and_allows_empty():
    for bad in ("javascript:alert(1)", "ftp://example.com", "not a url"):
        with pytest.raises(a.AssetValidationError):
            a.build_asset(
                {"name": "Furnace", "parts": [{"name": "Filter", "url": bad}]},
                now=NOW,
            )
    asset = a.build_asset(
        {"name": "Furnace", "parts": [{"name": "Filter", "url": ""}]}, now=NOW
    )
    assert asset["parts"][0]["url"] == ""


def test_part_requires_name_and_valid_type():
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"name": "X", "parts": [{"name": ""}]}, now=NOW)
    with pytest.raises(a.AssetValidationError):
        a.build_asset({"name": "X", "parts": [{"name": "p", "type": "bogus"}]}, now=NOW)


def test_part_bad_interval_unit_rejected():
    with pytest.raises(a.AssetValidationError):
        a.build_asset(
            {
                "name": "X",
                "parts": [{"name": "p", "replace_interval": 1, "replace_unit": "eons"}],
            },
            now=NOW,
        )


def test_merge_update_preserves_part_last_replaced():
    asset = a.build_asset(
        {
            "name": "Shades",
            "parts": [
                {
                    "name": "Material",
                    "type": "wear",
                    "replace_interval": 6,
                    "replace_unit": "months",
                }
            ],
        },
        now=NOW,
    )
    pid = asset["parts"][0]["id"]
    asset["parts"][0]["last_replaced"] = "2025-01-01"  # simulate a completion stamp
    # The panel re-submits the part without last_replaced; merge must keep it.
    updated = a.merge_update(
        asset,
        {
            "parts": [
                {
                    "id": pid,
                    "name": "Material",
                    "type": "wear",
                    "replace_interval": 12,
                    "replace_unit": "months",
                }
            ]
        },
        now=NOW,
    )
    assert updated["parts"][0]["last_replaced"] == "2025-01-01"
    assert updated["parts"][0]["replace_interval"] == 12


def test_set_and_clear_part_file():
    asset = a.build_asset(
        {"name": "Furnace", "parts": [{"name": "Filter"}]}, now=NOW
    )
    pid = asset["parts"][0]["id"]
    updated = a.set_part_file(
        asset, pid, {"filename": "f.pdf", "content_type": "application/pdf", "size": 100}
    )
    assert updated["file_name"] == "f.pdf"
    assert asset["parts"][0]["file_name"] == "f.pdf"
    assert asset["parts"][0]["file_content_type"] == "application/pdf"
    assert asset["parts"][0]["file_size"] == 100

    prior = a.clear_part_file(asset, pid)
    assert prior == {"filename": "f.pdf", "content_type": "application/pdf", "size": 100}
    assert asset["parts"][0]["file_name"] is None
    assert asset["parts"][0]["file_content_type"] is None
    assert asset["parts"][0]["file_size"] is None

    # Clearing an already-fileless part, or acting on an unknown part id, is a no-op.
    assert a.clear_part_file(asset, pid) is None
    assert a.set_part_file(asset, "bogus", {"filename": "x", "content_type": "x", "size": 1}) is None
    assert a.clear_part_file(asset, "bogus") is None


def test_merge_update_cannot_inject_or_clear_part_file():
    asset = a.build_asset(
        {"name": "Furnace", "parts": [{"name": "Filter"}]}, now=NOW
    )
    pid = asset["parts"][0]["id"]
    a.set_part_file(
        asset, pid, {"filename": "f.pdf", "content_type": "application/pdf", "size": 100}
    )
    # A generic update can't clear the attached file by omitting it...
    preserved = a.merge_update(
        asset, {"parts": [{"id": pid, "name": "Filter"}]}, now=NOW
    )
    assert preserved["parts"][0]["file_name"] == "f.pdf"
    # ...nor inject one by sending the (unvalidated) key directly.
    fileless = a.build_asset({"name": "Fridge", "parts": [{"name": "Bulb"}]}, now=NOW)
    fid = fileless["parts"][0]["id"]
    injected = a.merge_update(
        fileless,
        {"parts": [{"id": fid, "name": "Bulb", "file_name": "hacked.pdf"}]},
        now=NOW,
    )
    assert injected["parts"][0]["file_name"] is None


def test_migrate_legacy_part_numbers():
    legacy = {
        "id": "x",
        "kind": "virtual",
        "name": "WH",
        "part_numbers": "anode rod AR-1",
    }
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
    # "Future" is measured against the injected clock (``now``), not the wall clock:
    # a date one day past NOW is rejected deterministically regardless of when the
    # test runs.
    future = (NOW.date() + timedelta(days=1)).isoformat()
    with pytest.raises(a.AssetValidationError):
        a.build_asset(
            {"name": "Boiler", "parts": [{"name": "Anode", "last_replaced": future}]},
            now=NOW,
        )


def test_part_last_replaced_validated_against_injected_now_not_wall_clock():
    # A date well in the past of any plausible wall clock but *after* the injected
    # ``now`` must still be rejected — proving validation uses ``now``, not
    # ``date.today()``. Symmetrically it is accepted when ``now`` is advanced past it.
    day_after_now = (NOW.date() + timedelta(days=1)).isoformat()
    payload = {
        "name": "Boiler",
        "parts": [{"name": "Anode", "last_replaced": day_after_now}],
    }
    with pytest.raises(a.AssetValidationError):
        a.build_asset(payload, now=NOW)
    # Advancing ``now`` past that date makes the same payload valid.
    asset = a.build_asset(payload, now=NOW + timedelta(days=2))
    assert asset["parts"][0]["last_replaced"] == day_after_now


def test_part_allows_today_last_replaced():
    # ``now``'s own date is allowed (the boundary is inclusive).
    today = NOW.date().isoformat()
    asset = a.build_asset(
        {"name": "Boiler", "parts": [{"name": "Anode", "last_replaced": today}]},
        now=NOW,
    )
    assert asset["parts"][0]["last_replaced"] == today


def test_merge_update_rejects_future_part_last_replaced():
    # The merge_update entry point threads the injected clock too.
    asset = a.build_asset({"name": "Boiler"}, now=NOW)
    future = (NOW.date() + timedelta(days=5)).isoformat()
    with pytest.raises(a.AssetValidationError):
        a.merge_update(
            asset,
            {"parts": [{"name": "Anode", "last_replaced": future}]},
            now=NOW,
        )


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
            {
                "name": "Box",
                "parts": [{"name": "A", "type": "wear", "replace_interval": 10**9}],
            },
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
        {
            "name": "Furnace",
            "parts": [{"name": "Filter", "stock": "4", "reorder_at": "1"}],
        },
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


def test_part_tracks_stock_keys_on_stock_presence():
    # ``stock`` present (even zero) opts the part into a stock number entity.
    assert a.part_tracks_stock({"stock": 0}) is True
    assert a.part_tracks_stock({"stock": 4, "reorder_at": 1}) is True
    # No ``stock`` -> not counted, regardless of a stray reorder threshold.
    assert a.part_tracks_stock({"stock": None, "reorder_at": 2}) is False
    assert a.part_tracks_stock({}) is False


def test_part_has_reorder_requires_both_stock_and_threshold():
    assert a.part_has_reorder({"stock": 1, "reorder_at": 2}) is True
    assert a.part_has_reorder({"stock": 0, "reorder_at": 0}) is True
    # A low-stock sensor needs both halves of the comparison.
    assert a.part_has_reorder({"stock": 4, "reorder_at": None}) is False
    assert a.part_has_reorder({"stock": None, "reorder_at": 2}) is False


def test_stock_transition_classifies_crossings():
    # No threshold -> untracked, never transitions.
    assert a.stock_transition(5, 4, None) == a.STOCK_NONE
    # Crossing into low.
    assert a.stock_transition(2, 1, 1) == a.STOCK_LOW
    # Reaching zero wins over "low" (more specific) even from an already-low part.
    assert a.stock_transition(1, 0, 1) == a.STOCK_OUT
    assert a.stock_transition(3, 0, 5) == a.STOCK_OUT
    # Restock lifts back above the threshold.
    assert a.stock_transition(1, 4, 1) == a.STOCK_RESTOCKED
    # Restock that's still at/below threshold is not a recovery.
    assert a.stock_transition(0, 2, 2) == a.STOCK_NONE
    # No crossing while comfortably above, or already low without reaching zero.
    assert a.stock_transition(3, 2, 1) == a.STOCK_NONE
    assert a.stock_transition(2, 1, 3) == a.STOCK_NONE


def test_consume_part_stock_flags_low_only_on_crossing():
    part = {"stock": 3, "reorder_at": 1}
    # 3 -> 2, still above the threshold of 1.
    assert a.consume_part_stock(part) == a.STOCK_NONE
    assert part["stock"] == 2
    # 2 -> 1 crosses from not-low into low.
    assert a.consume_part_stock(part) == a.STOCK_LOW
    assert part["stock"] == 1
    # 1 -> 0, already low: reaching zero is now reported as out-of-stock (the old
    # bare boolean stayed silent here).
    assert a.consume_part_stock(part) == a.STOCK_OUT
    assert part["stock"] == 0


def test_consume_part_stock_floors_at_zero_without_refiring():
    # Already at zero: consuming again clamps at zero and does not re-fire.
    part = {"stock": 0, "reorder_at": 0}
    assert a.consume_part_stock(part) == a.STOCK_NONE
    assert part["stock"] == 0


def test_consume_part_stock_noop_when_untracked():
    part = {"stock": None, "reorder_at": 2}
    assert a.consume_part_stock(part) == a.STOCK_NONE
    assert part["stock"] is None


def test_adjust_part_stock_restock_and_clamp():
    part = {"stock": 1, "reorder_at": 1}
    # Restock by 3 -> 4, recovers above the threshold.
    assert a.adjust_part_stock(part, 3) == a.STOCK_RESTOCKED
    assert part["stock"] == 4
    # Consume 5 -> clamps at 0: out of stock.
    assert a.adjust_part_stock(part, -5) == a.STOCK_OUT
    assert part["stock"] == 0


def test_adjust_part_stock_begins_tracking_from_zero():
    part = {"stock": None, "reorder_at": None}
    a.adjust_part_stock(part, 2)
    assert part["stock"] == 2


def test_adjust_part_stock_to_zero_reports_out():
    # Decreasing while already low to exactly zero reports out-of-stock.
    part = {"stock": 1, "reorder_at": 2}
    assert a.adjust_part_stock(part, -1) == a.STOCK_OUT
    assert part["stock"] == 0
    # Restocking back up to (still <=) the threshold is not a recovery.
    assert a.adjust_part_stock(part, 2) == a.STOCK_NONE
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
    updated = a.merge_update(asset, {"parts": [{"id": pid, "name": "Filter"}]}, now=NOW)
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
