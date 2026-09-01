"""Unit tests for asset (appliance) construction / validation / updates.

These exercise the pure ``assets`` model — no Home Assistant runtime. Device
provisioning (``devices.py``) imports HA and is covered by the integration tests.
"""

from datetime import datetime, timedelta, timezone

import hk_assets as a
import pytest
from asserts import raises_exactly

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


def test_notes_normalize_and_round_trip():
    # Appliance notes are free-form prose (rendered as Markdown in the panel), stripped
    # and round-tripped like the other verbatim text fields — but deliberately *not*
    # synced into the device registry the way manufacturer/model/serial_number are.
    asset = a.build_asset(
        {"name": "Water heater", "notes": "  Anode rod is **behind** the top cap.  "},
        now=NOW,
    )
    assert asset["notes"] == "Anode rod is **behind** the top cap."

    updated = a.merge_update(asset, {"notes": "- drain yearly\n- check anode"}, now=NOW)
    assert updated["notes"] == "- drain yearly\n- check anode"

    # Omitted on update -> preserved (read from existing, like the other text fields).
    untouched = a.merge_update(updated, {"model": "XE50"}, now=NOW)
    assert untouched["notes"] == "- drain yearly\n- check anode"

    # Explicitly emptied -> cleared.
    cleared = a.merge_update(untouched, {"notes": ""}, now=NOW)
    assert cleared["notes"] == ""


def test_notes_default_empty_when_absent():
    # Assets stored before this field existed simply normalize to "" — no migration.
    asset = a.build_asset({"name": "No notes"}, now=NOW)
    assert asset["notes"] == ""


def test_notes_preserve_internal_newlines_for_markdown():
    # Only the outer whitespace is stripped: Markdown is line-oriented, so collapsing
    # the interior would destroy list items and paragraph breaks.
    body = "# Steps\n\n1. Shut off water\n2. Drain tank"
    asset = a.build_asset({"name": "WH", "notes": f"\n{body}\n"}, now=NOW)
    assert asset["notes"] == body


def test_notes_are_not_synced_into_device_identity_fields():
    # Guard the separation _PROSE_FIELDS exists to express: notes must never leak into
    # the registry-synced identity fields.
    asset = a.build_asset({"name": "WH", "notes": "some prose"}, now=NOW)
    assert asset["manufacturer"] == ""
    assert asset["model"] == ""
    assert asset["serial_number"] == ""


def test_asset_device_identifier_is_prefixed():
    # Must not collide with a per-task self-owned device (bare task id).
    domain, ident = a.asset_device_identifier("abc-123")
    assert domain == "home_keeper"
    assert ident == "asset_abc-123"


def test_build_virtual_asset_requires_name():
    with raises_exactly(a.AssetValidationError, "missing required field: 'name'"):
        a.build_asset({"manufacturer": "X"}, now=NOW)


def test_build_existing_asset_requires_device_id():
    with raises_exactly(a.AssetValidationError, "missing required field: 'device_id'"):
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
    with raises_exactly(a.AssetValidationError, "invalid kind: 'imaginary'"):
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
    with raises_exactly(a.AssetValidationError, "metadata label must not be empty"):
        a.build_asset(
            {"name": "Furnace", "metadata": [{"type": "text", "value": "orphan"}]},
            now=NOW,
        )


def test_metadata_rejects_bad_type():
    with raises_exactly(a.AssetValidationError, "invalid metadata type: 'number'"):
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
    with raises_exactly(
        a.AssetValidationError,
        "invalid date for 'Warranty': 'not-a-date' (expected YYYY-MM-DD)",
    ):
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
    with raises_exactly(a.AssetValidationError, "Bad must be an http(s) URL"):
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
    with raises_exactly(a.AssetValidationError, "cost must be a number"):
        a.build_asset({"name": "Furnace", "cost": "free"}, now=NOW)


def test_negative_cost_raises():
    with raises_exactly(a.AssetValidationError, "cost must not be negative"):
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
        with raises_exactly(
            a.AssetValidationError, "document url must be an http(s) URL"
        ):
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
    with raises_exactly(
        a.AssetValidationError, "an appliance can have at most 50 documents"
    ):
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
    with raises_exactly(
        a.AssetValidationError, "an appliance can have at most 50 documents"
    ):
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
    with raises_exactly(a.AssetValidationError, "document url must be an http(s) URL"):
        a.merge_update(
            asset, {"documents": [{"kind": "link", "url": "javascript:bad"}]}, now=NOW
        )
    with raises_exactly(a.AssetValidationError, "cost must not be negative"):
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
    with raises_exactly(a.AssetValidationError, "document url must be an http(s) URL"):
        a.update_document(asset, entry["id"], {"url": "javascript:alert(1)"})
    # A non-dict change set is rejected; an unknown document id returns None.
    with raises_exactly(a.AssetValidationError, "document changes must be an object"):
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
    with raises_exactly(a.AssetValidationError, "icon must look like 'mdi:name'"):
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
        with raises_exactly(a.AssetValidationError, "part url must be an http(s) URL"):
            a.build_asset(
                {"name": "Furnace", "parts": [{"name": "Filter", "url": bad}]},
                now=NOW,
            )
    asset = a.build_asset(
        {"name": "Furnace", "parts": [{"name": "Filter", "url": ""}]}, now=NOW
    )
    assert asset["parts"][0]["url"] == ""


def test_part_requires_name_and_valid_type():
    with raises_exactly(a.AssetValidationError, "part name must not be empty"):
        a.build_asset({"name": "X", "parts": [{"name": ""}]}, now=NOW)
    with raises_exactly(a.AssetValidationError, "invalid part type: 'bogus'"):
        a.build_asset({"name": "X", "parts": [{"name": "p", "type": "bogus"}]}, now=NOW)


def test_part_bad_interval_unit_rejected():
    with raises_exactly(a.AssetValidationError, "invalid replace_unit: 'eons'"):
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


def test_find_part_picks_the_matching_part():
    asset = a.build_asset(
        {"name": "Furnace", "parts": [{"name": "Filter"}, {"name": "Igniter"}]},
        now=NOW,
    )
    for index in (0, 1):
        found = a.find_part(asset, asset["parts"][index]["id"])
        # The stored dict itself, not a copy: callers mutate what they get back
        # (``store._stamp_part_replacement`` stamps ``last_replaced`` through it).
        assert found is asset["parts"][index]


def test_find_part_returns_none_for_an_unknown_id():
    asset = a.build_asset({"name": "Furnace", "parts": [{"name": "Filter"}]}, now=NOW)
    assert a.find_part(asset, "bogus") is None


@pytest.mark.parametrize("parts", [None, []])
def test_find_part_handles_an_asset_without_parts(parts):
    assert a.find_part({}, "any") is None
    assert a.find_part({"parts": parts}, "any") is None


def test_set_and_clear_part_file():
    asset = a.build_asset({"name": "Furnace", "parts": [{"name": "Filter"}]}, now=NOW)
    pid = asset["parts"][0]["id"]
    updated = a.set_part_file(
        asset,
        pid,
        {"filename": "f.pdf", "content_type": "application/pdf", "size": 100},
    )
    assert updated["file_name"] == "f.pdf"
    assert asset["parts"][0]["file_name"] == "f.pdf"
    assert asset["parts"][0]["file_content_type"] == "application/pdf"
    assert asset["parts"][0]["file_size"] == 100

    prior = a.clear_part_file(asset, pid)
    assert prior == {
        "filename": "f.pdf",
        "content_type": "application/pdf",
        "size": 100,
    }
    assert asset["parts"][0]["file_name"] is None
    assert asset["parts"][0]["file_content_type"] is None
    assert asset["parts"][0]["file_size"] is None

    # Clearing an already-fileless part, or acting on an unknown part id, is a no-op.
    assert a.clear_part_file(asset, pid) is None
    assert (
        a.set_part_file(
            asset, "bogus", {"filename": "x", "content_type": "x", "size": 1}
        )
        is None
    )
    assert a.clear_part_file(asset, "bogus") is None


def test_merge_update_cannot_inject_or_clear_part_file():
    asset = a.build_asset({"name": "Furnace", "parts": [{"name": "Filter"}]}, now=NOW)
    pid = asset["parts"][0]["id"]
    a.set_part_file(
        asset,
        pid,
        {"filename": "f.pdf", "content_type": "application/pdf", "size": 100},
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


def test_part_notes_edit_preserves_backend_managed_fields():
    """Editing a part's notes must not orphan its file or reset its cadence.

    The panel has no per-part save: changing one field re-submits the whole ``parts``
    array. Now that parts have an editable notes field, that round-trip is reachable
    from a note edit, so pin the fields the backend owns (the upload-only attached
    file, and a ``last_replaced`` stamped by a completion rather than typed).
    """
    asset = a.build_asset(
        {
            "name": "Water heater",
            "parts": [{"name": "Anode rod", "type": "wear", "replace_interval": 12}],
        },
        now=NOW,
    )
    pid = asset["parts"][0]["id"]
    a.set_part_file(
        asset,
        pid,
        {"filename": "receipt.pdf", "content_type": "application/pdf", "size": 4096},
    )
    asset["parts"][0]["last_replaced"] = "2025-05-01"  # stamped by a completion

    # The panel re-submits every part field it knows about, plus the new note.
    updated = a.merge_update(
        asset,
        {
            "parts": [
                {
                    "id": pid,
                    "name": "Anode rod",
                    "type": "wear",
                    "replace_interval": 12,
                    "notes": "Torque to **40 Nm**.",
                }
            ]
        },
        now=NOW,
    )
    part = updated["parts"][0]
    assert part["notes"] == "Torque to **40 Nm**."
    assert part["file_name"] == "receipt.pdf"
    assert part["file_content_type"] == "application/pdf"
    assert part["file_size"] == 4096
    assert part["last_replaced"] == "2025-05-01"


def test_part_notes_normalize_like_asset_notes():
    asset = a.build_asset(
        {"name": "Water heater", "parts": [{"name": "Anode", "notes": "  a **b**  "}]},
        now=NOW,
    )
    assert asset["parts"][0]["notes"] == "a **b**"
    # Absent -> "" (parts stored before the field was editable).
    bare = a.build_asset({"name": "Fridge", "parts": [{"name": "Bulb"}]}, now=NOW)
    assert bare["parts"][0]["notes"] == ""


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
    with raises_exactly(
        a.AssetValidationError, "last_replaced must not be in the future"
    ):
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
    with raises_exactly(
        a.AssetValidationError, "last_replaced must not be in the future"
    ):
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
    with raises_exactly(
        a.AssetValidationError, "last_replaced must not be in the future"
    ):
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
    with raises_exactly(a.AssetValidationError, "replace_interval must be <= 10000"):
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
    with raises_exactly(a.AssetValidationError, "related_device_ids must be a list"):
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
    with raises_exactly(a.AssetValidationError, "stock must not be negative"):
        a.build_asset({"name": "X", "parts": [{"name": "F", "stock": -1}]}, now=NOW)


def test_unparseable_stock_rejected():
    with raises_exactly(a.AssetValidationError, "stock must be a number"):
        a.build_asset({"name": "X", "parts": [{"name": "F", "stock": "lots"}]}, now=NOW)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", float("nan"), float("inf")])
def test_non_finite_stock_rejected(value):
    # NaN and the infinities survive float() and then compare falsely against every
    # bound, so without an explicit guard they'd be stored as a "valid" quantity.
    with raises_exactly(a.AssetValidationError, "stock must be a number"):
        a.build_asset({"name": "X", "parts": [{"name": "F", "stock": value}]}, now=NOW)


def test_oversized_stock_rejected():
    with raises_exactly(a.AssetValidationError, "reorder_at must be <= 10000"):
        a.build_asset(
            {"name": "X", "parts": [{"name": "F", "reorder_at": 10**9}]}, now=NOW
        )


# ── decimal quantities, units and per-completion draw-down (issue #220) ────────
def test_part_stock_accepts_decimals():
    # Stock counted in millilitres (or in thirds of a bottle) is as valid as stock
    # counted in whole spares.
    asset = a.build_asset(
        {
            "name": "Laundry",
            "parts": [
                {
                    "name": "Fabric softener",
                    "stock": "1.5",
                    "reorder_at": 0.5,
                    "stock_unit": " bottles ",
                    "consume_quantity": "0.33",
                }
            ],
        },
        now=NOW,
    )
    part = asset["parts"][0]
    assert part["stock"] == 1.5
    assert part["reorder_at"] == 0.5
    assert part["stock_unit"] == "bottles"
    assert part["consume_quantity"] == 0.33


def test_whole_quantities_stay_integers():
    # The ordinary count-the-filters case must keep round-tripping as an int, not
    # turn into 4.0 in storage, the panel and every event payload.
    asset = a.build_asset(
        {"name": "X", "parts": [{"name": "F", "stock": 4.0, "reorder_at": "1.000"}]},
        now=NOW,
    )
    part = asset["parts"][0]
    assert part["stock"] == 4 and isinstance(part["stock"], int)
    assert part["reorder_at"] == 1 and isinstance(part["reorder_at"], int)


def test_stock_rounds_to_three_places():
    asset = a.build_asset(
        {"name": "X", "parts": [{"name": "F", "stock": 1.23456}]}, now=NOW
    )
    assert asset["parts"][0]["stock"] == 1.235


@pytest.mark.parametrize("unit", [None, ""])
def test_stock_unit_defaults_empty(unit):
    part = {"name": "F"} if unit is None else {"name": "F", "stock_unit": unit}
    asset = a.build_asset({"name": "X", "parts": [part]}, now=NOW)
    assert asset["parts"][0]["stock_unit"] == ""
    assert asset["parts"][0]["consume_quantity"] is None


def test_stock_unit_is_length_capped_at_sixteen():
    # A unit is a short label rendered beside a number, not prose. Exactly the cap
    # is still a unit; one character more is not.
    asset = a.build_asset(
        {"name": "X", "parts": [{"name": "F", "stock_unit": "m" * 16}]}, now=NOW
    )
    assert asset["parts"][0]["stock_unit"] == "m" * 16
    with raises_exactly(
        a.AssetValidationError, "stock_unit must be at most 16 characters"
    ):
        a.build_asset(
            {"name": "X", "parts": [{"name": "F", "stock_unit": "m" * 17}]}, now=NOW
        )


@pytest.mark.parametrize("value", [0, "0", 0.0])
def test_zero_consume_quantity_rejected(value):
    # A completion that consumes nothing is a task that shouldn't be linked at all;
    # accepting it would make the UI promise a draw-down that never happens.
    with raises_exactly(
        a.AssetValidationError, "consume_quantity must be greater than zero"
    ):
        a.build_asset(
            {"name": "X", "parts": [{"name": "F", "consume_quantity": value}]}, now=NOW
        )


@pytest.mark.parametrize("value", [-1, -0.5])
def test_negative_consume_quantity_rejected(value):
    with raises_exactly(
        a.AssetValidationError, "consume_quantity must not be negative"
    ):
        a.build_asset(
            {"name": "X", "parts": [{"name": "F", "consume_quantity": value}]}, now=NOW
        )


def test_unparseable_consume_quantity_names_its_own_field():
    # The shared quantity validator is told which field it is checking, so the error
    # says consume_quantity rather than blaming stock.
    with raises_exactly(a.AssetValidationError, "consume_quantity must be a number"):
        a.build_asset(
            {"name": "X", "parts": [{"name": "F", "consume_quantity": "a third"}]},
            now=NOW,
        )


def test_part_stock_unit_reads_through_missing_and_blank():
    assert a.part_stock_unit({"stock_unit": " ml "}) == "ml"
    assert a.part_stock_unit({"stock_unit": None}) == ""
    assert a.part_stock_unit({}) == ""


@pytest.mark.parametrize(
    ("part", "expected"),
    [
        ({"consume_quantity": 0.25}, 0.25),
        ({"consume_quantity": 2}, 2),
        # Unset, junk, zero and negatives all mean "one whole spare" on read: parts
        # written before the field existed must keep consuming exactly one.
        ({}, 1),
        ({"consume_quantity": None}, 1),
        ({"consume_quantity": "lots"}, 1),
        ({"consume_quantity": 0}, 1),
        ({"consume_quantity": -3}, 1),
        ({"consume_quantity": float("nan")}, 1),
    ],
)
def test_part_consume_quantity_defaults_to_one(part, expected):
    assert a.part_consume_quantity(part) == expected


@pytest.mark.parametrize(
    ("part", "expected"),
    [
        ({"restock_quantity": 4}, 4),
        ({"restock_quantity": 0.5}, 0.5),
        ({}, 1),
        ({"restock_quantity": 0}, 1),
        ({"restock_quantity": -2}, 1),
    ],
)
def test_part_restock_quantity_defaults_to_one(part, expected):
    assert a.part_restock_quantity(part) == expected


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (3, "", "3"),
        (3.0, "", "3"),
        (500, "ml", "500 ml"),
        (0.5, "bottles", "0.5 bottles"),
        # Trailing zeros go, and float noise never reaches the shopper.
        (2.500, "m", "2.5 m"),
        (0.1 + 0.2, "l", "0.3 l"),
        # A unit is a label, not prose: it is stripped, and blank means none.
        (2, "  ml  ", "2 ml"),
        (2, "   ", "2"),
    ],
)
def test_format_quantity_matches_the_panels_rendering(value, unit, expected):
    # The Python twin of frontend/src/utils.ts formatQuantity. The two must agree:
    # "500 ml" in the panel and "500.0 ml" on the shopping list would read as a bug.
    assert a.format_quantity(value, unit) == expected


@pytest.mark.parametrize(
    ("part", "expected"),
    [
        # A measured part names its unit...
        ({"stock_unit": "ml", "restock_quantity": 500}, "500 ml"),
        # ...even when it restocks a single one, because "1 bottle" is still
        # telling the shopper something a bare name doesn't.
        ({"stock_unit": "bottle", "restock_quantity": 1}, "1 bottle"),
        ({"stock_unit": "ml"}, "1 ml"),
        # An unmeasured part only speaks up when it wants more than one.
        ({"restock_quantity": 2}, "×2"),
        ({"restock_quantity": 2.5}, "×2.5"),
        # The ordinary case says nothing at all — that silence is the point.
        ({"restock_quantity": 1}, ""),
        ({}, ""),
        # A stored zero folds to the default one spare, so it stays silent too.
        ({"restock_quantity": 0}, ""),
    ],
)
def test_part_restock_label_speaks_only_when_it_has_something_to_say(part, expected):
    assert a.part_restock_label(part) == expected


def test_consume_part_stock_draws_the_parts_own_amount():
    # The reported case: a bottle topped up a third at a time must last three
    # completions, not one.
    part = {"stock": 1, "reorder_at": 0.5, "consume_quantity": 0.33}
    assert a.consume_part_stock(part) == a.STOCK_NONE
    assert part["stock"] == 0.67
    assert a.consume_part_stock(part) == a.STOCK_LOW
    assert part["stock"] == 0.34
    assert a.consume_part_stock(part) == a.STOCK_NONE
    assert part["stock"] == 0.01


def test_repeated_fractional_draw_down_reaches_exactly_zero():
    # Rounding at each step is what keeps 0.1 taken ten times from leaving a
    # 1.4e-17 remainder that would read as "still in stock" forever.
    part = {"stock": 1, "reorder_at": 0.2, "consume_quantity": 0.1}
    transitions = [a.consume_part_stock(part) for _ in range(10)]
    assert part["stock"] == 0
    assert transitions[-1] == a.STOCK_OUT


def test_adjust_part_stock_accepts_a_fractional_delta():
    part = {"stock": 500, "reorder_at": 250, "stock_unit": "ml"}
    assert a.adjust_part_stock(part, -250.5) == a.STOCK_LOW
    assert part["stock"] == 249.5
    # A fractional top-up back over the threshold is a real recovery.
    assert a.adjust_part_stock(part, 0.75) == a.STOCK_RESTOCKED
    assert part["stock"] == 250.25


def test_stock_transition_handles_fractional_crossings():
    assert a.stock_transition(0.75, 0.5, 0.5) == a.STOCK_LOW
    assert a.stock_transition(0.5, 0.25, 0.5) == a.STOCK_NONE
    assert a.stock_transition(0.25, 0, 0.5) == a.STOCK_OUT
    assert a.stock_transition(0, 0.75, 0.5) == a.STOCK_RESTOCKED


def test_stock_transition_reads_a_negative_new_as_out_of_stock():
    # Both callers clamp at zero, so this is defence in depth rather than a live
    # path: if one ever stopped clamping, "below empty" must still report
    # out-of-stock rather than sliding into the restocked branch.
    assert a.stock_transition(2, -1, 1) == a.STOCK_OUT
    assert a.stock_transition(0, -1, 1) == a.STOCK_NONE


@pytest.mark.parametrize("stock", [3, 0.5, 0])
def test_consume_and_adjust_never_drive_stock_below_zero(stock):
    part = {"stock": stock, "reorder_at": 1, "consume_quantity": 99}
    a.consume_part_stock(part)
    assert part["stock"] == 0
    a.adjust_part_stock(part, -99)
    assert part["stock"] == 0


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


def test_part_auto_buy_fields_normalized():
    asset = a.build_asset(
        {
            "name": "Furnace",
            "parts": [
                {
                    "name": "Filter",
                    "stock": 0,
                    "reorder_at": 1,
                    "create_buy_task": True,
                    "restock_quantity": "4",
                }
            ],
        },
        now=NOW,
    )
    part = asset["parts"][0]
    assert part["create_buy_task"] is True
    assert part["restock_quantity"] == 4


def test_part_auto_buy_defaults_off():
    asset = a.build_asset({"name": "X", "parts": [{"name": "F"}]}, now=NOW)
    part = asset["parts"][0]
    assert part["create_buy_task"] is False
    assert part["restock_quantity"] is None


def test_negative_restock_quantity_rejected():
    with raises_exactly(
        a.AssetValidationError, "restock_quantity must not be negative"
    ):
        a.build_asset(
            {"name": "X", "parts": [{"name": "F", "restock_quantity": -2}]}, now=NOW
        )


@pytest.mark.parametrize("value", [0, "0", 0.0])
def test_zero_restock_quantity_stores_as_unset(value):
    # Zero and unset already behave identically on read (both restock one spare), so
    # a stored zero was a record claiming something the code never did. It is folded
    # rather than rejected: the field predates the validator, so a zero may already
    # be sitting in someone's store, and refusing it would make that part unsaveable.
    asset = a.build_asset(
        {"name": "X", "parts": [{"name": "F", "restock_quantity": value}]}, now=NOW
    )
    assert asset["parts"][0]["restock_quantity"] is None
    assert a.part_restock_quantity(asset["parts"][0]) == 1


def test_part_wants_buy_task_requires_option_and_threshold():
    assert (
        a.part_wants_buy_task({"stock": 0, "reorder_at": 1, "create_buy_task": True})
        is True
    )
    # Option on but no threshold -> no "low" to act on.
    assert a.part_wants_buy_task({"stock": 0, "create_buy_task": True}) is False
    # Threshold set but option off.
    assert (
        a.part_wants_buy_task({"stock": 0, "reorder_at": 1, "create_buy_task": False})
        is False
    )


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


# ── merge_update carry-forward contract ──────────────────────────────────────
# `merge_update` builds a candidate from `updates.get(field, existing.get(field))`
# for every editable field, then re-validates the whole record. Every field a
# caller *omits* therefore has to survive untouched — the panel's edit form sends
# a partial payload and a service caller may send a single key.
#
# Testing one field at a time is what makes this real: merging a full payload
# cannot tell the carry-forward apart from the update itself.

# An asset with every independently-editable field set to a distinctive value.
FULLY_SET_ASSET = {
    "name": "Kitchen fridge",
    "manufacturer": "Frigidaire",
    "model": "FGHB2868TF",
    "serial_number": "SN-12345",
    "notes": "Coils need brushing every spring",
    "area_id": "area-kitchen",
    "cost": 1499.0,
    "icon": "mdi:fridge",
    "metadata": [{"kind": "text", "label": "Provider", "value": "Acme"}],
    "documents": [{"kind": "link", "name": "Manual", "url": "https://example.com/m"}],
}

# (field, new value, expected value after normalization).
ASSET_MERGE_CASES = [
    ("name", "Garage fridge", "Garage fridge"),
    ("manufacturer", "Bosch", "Bosch"),
    ("model", "B36CT80SNS", "B36CT80SNS"),
    ("serial_number", "SN-99999", "SN-99999"),
    ("notes", "Moved to the garage", "Moved to the garage"),
    ("area_id", "area-garage", "area-garage"),
    ("cost", 1799.5, 1799.5),
    ("icon", "mdi:fridge-outline", "mdi:fridge-outline"),
]

# Fields that must be identical before and after a merge that didn't mention them.
ASSET_CARRIED_FIELDS = [
    "name",
    "manufacturer",
    "model",
    "serial_number",
    "notes",
    "area_id",
    "cost",
    "icon",
    "metadata",
    "documents",
    "parts",
]


def test_asset_merge_cases_cover_the_carried_fields():
    # Guard the fixtures: a new editable field must show up here rather than
    # silently going untested on both the update and the carry-forward side.
    assert {field for field, _, _ in ASSET_MERGE_CASES} <= set(ASSET_CARRIED_FIELDS)
    assert set(FULLY_SET_ASSET) <= set(ASSET_CARRIED_FIELDS)


@pytest.mark.parametrize(("field", "value", "expected"), ASSET_MERGE_CASES)
def test_merge_update_applies_one_field_and_carries_the_rest(field, value, expected):
    asset = a.build_asset(FULLY_SET_ASSET, now=NOW)
    updated = a.merge_update(asset, {field: value}, now=NOW)

    assert updated[field] == expected
    for other in ASSET_CARRIED_FIELDS:
        if other != field:
            assert updated[other] == asset[other], f"{other} was not carried forward"


def test_merge_update_with_an_empty_payload_changes_nothing():
    # The degenerate case, and the cheapest proof that every default in the
    # candidate dict reads from `existing`.
    asset = a.build_asset(FULLY_SET_ASSET, now=NOW)
    assert a.merge_update(asset, {}, now=NOW) == asset


def test_merge_update_carries_identity_fields():
    # `id`, `created` and the provisioning anchors are never in the candidate
    # dict; they survive because the merge starts from `dict(existing)`.
    asset = a.build_asset(FULLY_SET_ASSET, now=NOW)
    updated = a.merge_update(asset, {"name": "Renamed"}, now=NOW)
    for field in ("id", "created", "kind", "identifiers"):
        assert updated[field] == asset[field], f"{field} was not preserved"


def test_merge_update_clearing_a_text_field_is_honoured():
    # The carry-forward must not swallow a deliberate blanking: an explicit ""
    # is a value, not an omission.
    asset = a.build_asset(FULLY_SET_ASSET, now=NOW)
    updated = a.merge_update(asset, {"serial_number": "", "notes": ""}, now=NOW)
    assert updated["serial_number"] == ""
    assert updated["notes"] == ""
    assert updated["manufacturer"] == "Frigidaire"  # untouched neighbour


# ── card_projection (what a non-admin is allowed to see) ────────────────────


def _projected_asset():
    """One fully-populated asset, run through the non-admin projection."""
    asset = a.build_asset(
        {
            **FULLY_SET_ASSET,
            "metadata": [
                {"type": "text", "label": "Provider", "value": "Acme"},
                {"type": "date", "label": "Warranty ends", "value": "2030-01-01"},
                {"type": "link", "label": "Product page", "value": "https://ex.com/p"},
            ],
            "parts": [
                {
                    "name": "Water filter",
                    "part_number": "EPTWFU01",
                    "vendor": "Frigidaire",
                    "cost": 49.99,
                    "url": "https://example.com/filter",
                    "notes": "Behind the kick plate",
                    "stock": 2,
                    "reorder_at": 1,
                }
            ],
        },
        now=NOW,
    )
    projected = a.card_projection([asset])
    assert len(projected) == 1
    return asset, projected[0]


def test_card_projection_keeps_what_the_card_renders():
    # The dashboard card resolves a task's card links against documents, link-typed
    # metadata and a part's product URL — all three must survive the projection or
    # the card silently loses its chips for every non-admin.
    asset, projected = _projected_asset()
    assert projected["id"] == asset["id"]
    assert projected["documents"] == asset["documents"]
    assert [m["label"] for m in projected["metadata"]] == ["Product page"]
    assert projected["parts"] == [
        {
            "id": asset["parts"][0]["id"],
            "name": "Water filter",
            "url": "https://example.com/filter",
        }
    ]


def test_card_projection_drops_inventory_value_data():
    # The point of the projection: `export_inventory` is admin-only because costs and
    # serials shouldn't leak, so the un-gated read must not hand them over either.
    _, projected = _projected_asset()
    for field in ("cost", "serial_number", "manufacturer", "model", "notes", "name"):
        assert field not in projected, f"{field} leaked to a non-admin"
    for field in ("cost", "vendor", "stock", "reorder_at", "part_number", "notes"):
        assert field not in projected["parts"][0], f"part {field} leaked to a non-admin"


def test_card_projection_drops_non_link_metadata():
    # Warranty dates and free-text custom fields are where the private detail lives;
    # only `link` entries (a URL the user chose to publish on a card) survive.
    _, projected = _projected_asset()
    assert all(entry["type"] == "link" for entry in projected["metadata"])
    assert "Warranty ends" not in [entry["label"] for entry in projected["metadata"]]


def test_card_projection_is_a_whitelist():
    # A field added to the asset record later must be private until someone adds it
    # here deliberately — the guarantee a blacklist could not make.
    asset = a.build_asset({"name": "Boiler"}, now=NOW)
    asset["secret_new_field"] = "leak me"
    projected = a.card_projection([asset])[0]
    assert set(projected) == {"id", "documents", "metadata", "parts"}


def test_card_projection_tolerates_a_bare_asset():
    # An asset with no documents/metadata/parts still projects to empty lists, so the
    # card's `.find()` calls don't hit undefined.
    projected = a.card_projection([{"id": "abc"}])
    assert projected == [{"id": "abc", "documents": [], "metadata": [], "parts": []}]


def test_card_projection_does_not_mutate_the_stored_assets():
    # The store hands out its live dicts; the projection must copy, or a non-admin
    # read would strip the real records for everyone.
    asset, _ = _projected_asset()
    assert asset["cost"] == 1499.0
    assert len(asset["metadata"]) == 3
    assert asset["parts"][0]["vendor"] == "Frigidaire"
