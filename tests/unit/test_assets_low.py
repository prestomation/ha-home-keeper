"""Low-severity review findings in the pure ``assets`` model (group B).

Each test names the finding it pins. They cover non-finite numbers, null text
values and document id collisions.
"""

import uuid
from datetime import datetime, timedelta, timezone

import hk_assets as a
import pytest
from asserts import raises_exactly

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)


@pytest.mark.parametrize("bad", [float("nan"), "nan", float("inf"), "-inf"])
def test_b05_7_cost_refuses_non_finite(bad):
    # NaN passed the ``< 0`` check and made the appliance report totals NaN.
    with raises_exactly(a.AssetValidationError, "cost must be a number"):
        a.build_asset({"name": "Fridge", "cost": bad}, now=NOW)
    with raises_exactly(a.AssetValidationError, "cost must be a number"):
        a.build_asset(
            {"name": "Fridge", "parts": [{"name": "F", "cost": bad}]}, now=NOW
        )


def test_b05_7_finite_cost_still_accepted():
    assert a.build_asset({"name": "Fridge", "cost": "12.5"}, now=NOW)["cost"] == 12.5
    assert a.build_asset({"name": "Fridge", "cost": 0}, now=NOW)["cost"] == 0.0
    # An empty box is no cost, not an error.
    assert a.build_asset({"name": "Fridge", "cost": ""}, now=NOW)["cost"] is None


def test_b05_6_an_empty_replace_interval_is_unset():
    asset = a.build_asset(
        {"name": "Fridge", "parts": [{"name": "F", "replace_interval": ""}]}, now=NOW
    )
    assert asset["parts"][0]["replace_interval"] is None


def test_b05_8_a_metadata_entry_must_be_an_object():
    with raises_exactly(
        a.AssetValidationError, "each metadata entry must be an object"
    ):
        a.build_asset({"name": "Fridge", "metadata": ["Warranty"]}, now=NOW)


def test_b05_8_metadata_null_value_is_empty_not_none_text():
    asset = a.build_asset(
        {
            "name": "Fridge",
            "metadata": [{"type": "text", "label": "Warranty", "value": None}],
        },
        now=NOW,
    )
    assert asset["metadata"][0]["value"] == ""


def test_b05_8_metadata_keeps_a_falsy_number_as_text():
    asset = a.build_asset(
        {"name": "Fridge", "metadata": [{"type": "text", "label": 0, "value": 0}]},
        now=NOW,
    )
    assert asset["metadata"][0]["label"] == "0"
    assert asset["metadata"][0]["value"] == "0"


def test_b05_8_metadata_null_label_is_refused():
    with raises_exactly(a.AssetValidationError, "metadata label must not be empty"):
        a.build_asset(
            {"name": "Fridge", "metadata": [{"type": "text", "label": None}]},
            now=NOW,
        )


@pytest.mark.parametrize("field", ["label", "value"])
def test_b05_8_metadata_refuses_a_yaml_boolean(field):
    entry = {"type": "text", "label": "Warranty", "value": "2 years", field: False}
    with raises_exactly(
        a.AssetValidationError,
        f"metadata {field} must be text. YAML reads a bare yes, no, on and off as "
        "true or false, so put quotation marks around the value.",
    ):
        a.build_asset({"name": "Fridge", "metadata": [entry]}, now=NOW)


@pytest.mark.parametrize(
    ("part", "message"),
    [
        ({"replace_interval": float("inf")}, "replace_interval must be an integer"),
        (
            {
                "replace_interval": 10,
                "replace_unit": "uses",
                "carried_uses": float("inf"),
            },
            "carried_uses must be an integer",
        ),
        (
            {
                "replace_interval": 10,
                "replace_unit": "uses",
                "replace_also_every": {"interval": float("inf"), "unit": "months"},
            },
            "replace_also_every.interval must be an integer",
        ),
    ],
)
def test_b05_6_infinite_integer_part_field_is_a_validation_error(part, message):
    with raises_exactly(a.AssetValidationError, message):
        a.build_asset({"name": "Fridge", "parts": [{"name": "F", **part}]}, now=NOW)


def test_b05_6_infinite_document_size_is_a_validation_error():
    asset = a.build_asset({"name": "Fridge"}, now=NOW)
    with raises_exactly(a.AssetValidationError, "document size must be an integer"):
        a.append_document(
            asset,
            {
                "kind": "file",
                "filename": "m.pdf",
                "content_type": "application/pdf",
                "size": float("inf"),
            },
            created="",
        )


def test_b05_4_link_cannot_take_the_id_of_a_stored_file():
    asset = a.build_asset({"name": "Fridge"}, now=NOW)
    file_doc = a.append_document(
        asset,
        {"kind": "file", "filename": "m.pdf", "content_type": "application/pdf"},
        created="",
    )
    other_link = a.append_document(
        asset, {"kind": "link", "url": "https://ex.com/old"}, created=""
    )
    merged = a.merge_update(
        asset,
        {
            "documents": [
                {"id": file_doc["id"], "kind": "link", "url": "https://ex.com/new"},
                {"id": other_link["id"], "kind": "link", "url": "https://ex.com/k"},
            ]
        },
        now=NOW,
    )
    ids = [d["id"] for d in merged["documents"]]
    assert len(set(ids)) == 3
    assert merged["documents"][0] == file_doc
    # A link with a free id keeps it.
    assert merged["documents"][2]["id"] == other_link["id"]
    link = merged["documents"][1]
    assert link["url"] == "https://ex.com/new"
    assert link["id"] != file_doc["id"]
    # A real new uuid, not None or the text "None".
    assert str(uuid.UUID(link["id"])) == link["id"]
    # A removal by the file id now removes the file, and only the file.
    removed = a.remove_document(merged, file_doc["id"])
    assert removed is not None
    assert removed["kind"] == "file"
    assert [d["url"] for d in merged["documents"]] == [
        "https://ex.com/new",
        "https://ex.com/k",
    ]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_b05_5_adjust_part_stock_refuses_non_finite_delta(bad):
    part = {"stock": 3, "reorder_at": 1}
    with raises_exactly(a.AssetValidationError, "delta must be a number"):
        a.adjust_part_stock(part, bad)
    assert part["stock"] == 3
