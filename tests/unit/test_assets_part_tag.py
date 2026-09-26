"""A wear part's NFC/RFID binding: validation, and which derived task it reaches."""

from datetime import UTC, datetime

import hk_assets as assets
import pytest
from asserts import raises_exactly

NOW = datetime(2026, 6, 13, 10, tzinfo=UTC)


def _part(**extra):
    raw = {"id": "p1", "name": "Anode", "type": "wear", **extra}
    return assets._normalize_part(raw)


# ── tag_id ────────────────────────────────────────────────────────────────────
def test_a_part_has_no_tag_by_default():
    part = _part()
    assert part["tag_id"] is None
    assert part["require_tag_scan"] is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("anode-tag", "anode-tag"),
        ("  anode-tag \n", "anode-tag"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_tag_id_is_stripped_and_blank_means_none(raw, expected):
    assert _part(tag_id=raw)["tag_id"] == expected


@pytest.mark.parametrize("raw", [True, 7, ["anode-tag"], {"id": "x"}])
def test_a_non_string_tag_id_is_refused(raw):
    """Junk here could never match a scan; refuse it at the edge, as a task does."""
    with raises_exactly(assets.AssetValidationError, "tag_id must be a string"):
        _part(tag_id=raw)


# ── require_tag_scan ──────────────────────────────────────────────────────────
def test_require_tag_scan_needs_a_tag():
    """A task that demands a scan with nothing to scan can never be completed."""
    with raises_exactly(assets.AssetValidationError, "require_tag_scan needs a tag_id"):
        _part(require_tag_scan=True)


def test_require_tag_scan_with_a_blank_tag_is_still_refused():
    with pytest.raises(assets.AssetValidationError, match="require_tag_scan"):
        _part(tag_id="  ", require_tag_scan=True)


def test_require_tag_scan_is_kept_beside_a_tag():
    part = _part(tag_id="anode-tag", require_tag_scan=True)
    assert part["tag_id"] == "anode-tag"
    assert part["require_tag_scan"] is True


@pytest.mark.parametrize("raw", [None, False, "", 0])
def test_a_falsy_flag_reads_as_false(raw):
    assert _part(tag_id="anode-tag", require_tag_scan=raw)["require_tag_scan"] is False


def test_a_consumable_keeps_its_tag():
    """The backend stores it whatever the type: no task reads it until the part is a
    wear item again. The panel clears it when a part stops being a wear item
    (``mergePartForm``), as it clears the schedule."""
    part = _part(type="consumable", tag_id="anode-tag", require_tag_scan=True)
    assert part["tag_id"] == "anode-tag"
    assert part["require_tag_scan"] is True


def test_build_asset_carries_the_binding_on_its_parts():
    asset = assets.build_asset(
        {
            "name": "Heater",
            "parts": [
                {
                    "name": "Anode",
                    "type": "wear",
                    "replace_interval": 12,
                    "replace_unit": "months",
                    "tag_id": "anode-tag",
                    "require_tag_scan": True,
                }
            ],
        },
        now=NOW,
    )
    (part,) = asset["parts"]
    assert part["tag_id"] == "anode-tag"
    assert part["require_tag_scan"] is True


# ── part_tag_role ─────────────────────────────────────────────────────────────
def test_a_time_measured_part_tags_its_maintenance_task():
    part = _part(replace_interval=12, replace_unit="months", tag_id="anode-tag")
    assert assets.part_tag_role(part) == "replace"


def test_a_counted_part_tags_its_use_task():
    """The sticker is on the thing that is used, so a scan records 1 use."""
    part = _part(replace_interval=25, replace_unit="uses", tag_id="jacket-tag")
    assert assets.part_tag_role(part) == "use"


def test_a_wear_part_with_no_interval_tags_its_maintenance_task():
    assert assets.part_tag_role(_part(tag_id="anode-tag")) == "replace"


def test_a_consumable_with_a_stray_uses_unit_is_not_counted():
    part = {"type": "consumable", "replace_unit": "uses", "replace_interval": 25}
    assert assets.part_tag_role(part) == "replace"
