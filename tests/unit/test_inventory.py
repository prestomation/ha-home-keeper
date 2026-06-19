"""Unit tests for the pure home-inventory aggregation (insurance export).

These exercise ``inventory.build_inventory`` / ``inventory_to_csv`` directly — no
Home Assistant runtime. Area names and "today" are injected (the websocket
handler supplies them in production).
"""

import csv
import io

import hk_inventory as inv


def _asset(**kw):
    base = {
        "id": "a1",
        "kind": "virtual",
        "name": "Water heater",
        "area_id": None,
        "manufacturer": "Rheem",
        "model": "XE50",
        "cost": 900.0,
        # Descriptive/temporal facts are free-form metadata now.
        "metadata": [
            {"id": "m1", "type": "text", "label": "Serial", "value": "SN-1"},
            {
                "id": "m2",
                "type": "date",
                "label": "Warranty expiry",
                "value": "2030-01-01",
            },
        ],
        "parts": [],
    }
    base.update(kw)
    return base


def test_empty_inventory_has_zero_totals():
    report = inv.build_inventory([])
    assert report["assets"] == []
    assert report["totals"] == {
        "asset_count": 0,
        "total_cost": 0.0,
        "spares_value": 0.0,
        "grand_total": 0.0,
    }


def test_row_carries_insurance_fields_and_area_name():
    report = inv.build_inventory(
        [_asset(area_id="garage")], area_names={"garage": "Garage"}
    )
    row = report["assets"][0]
    assert row["name"] == "Water heater"
    assert row["area"] == "Garage"
    assert row["manufacturer"] == "Rheem"
    assert row["cost"] == 900.0
    assert row["part_count"] == 0
    # Free-form metadata is flattened into the details summary.
    assert "Serial: SN-1" in row["details"]
    assert "Warranty expiry: 2030-01-01" in row["details"]


def test_unknown_area_id_yields_none_area():
    report = inv.build_inventory([_asset(area_id="ghost")], area_names={})
    assert report["assets"][0]["area"] is None


def test_spares_value_is_cost_times_stock():
    asset = _asset(
        parts=[
            {"name": "Anode", "cost": 30.0, "stock": 2},  # 60
            {"name": "Filter", "cost": 12.5, "stock": 4},  # 50
            {"name": "No-stock", "cost": 99.0, "stock": None},  # 0 (untracked)
            {"name": "No-cost", "cost": None, "stock": 5},  # 0 (no unit cost)
        ]
    )
    report = inv.build_inventory([asset])
    row = report["assets"][0]
    assert row["spares_value"] == 110.0
    assert row["part_count"] == 4


def test_totals_roll_up_cost_and_spares():
    a = _asset(
        id="a1", name="A", cost=100.0, parts=[{"name": "p", "cost": 10.0, "stock": 2}]
    )
    b = _asset(id="b1", name="B", cost=50.0, parts=[])
    report = inv.build_inventory([a, b])
    assert report["totals"] == {
        "asset_count": 2,
        "total_cost": 150.0,
        "spares_value": 20.0,
        "grand_total": 170.0,
    }


def test_missing_cost_treated_as_zero_not_error():
    report = inv.build_inventory([_asset(cost=None)])
    assert report["totals"]["total_cost"] == 0.0
    assert report["assets"][0]["cost"] is None  # raw value preserved on the row


def test_rows_sorted_by_name_case_insensitive():
    report = inv.build_inventory(
        [_asset(id="1", name="zebra"), _asset(id="2", name="Apple")]
    )
    assert [r["name"] for r in report["assets"]] == ["Apple", "zebra"]


def test_metadata_details_flattened_into_summary():
    asset = _asset(
        metadata=[
            {"id": "m1", "type": "text", "label": "Serial", "value": "SN-9"},
            {
                "id": "m2",
                "type": "link",
                "label": "Manual",
                "value": "https://ex/m.pdf",
            },
            {
                "id": "m3",
                "type": "text",
                "label": "Blank",
                "value": "",
            },  # dropped (no value)
        ]
    )
    row = inv.build_inventory([asset])["assets"][0]
    assert row["details"] == "Serial: SN-9; Manual: https://ex/m.pdf"


def test_csv_has_header_rows_and_total():
    report = inv.build_inventory(
        [
            _asset(
                id="1",
                name="Apple",
                cost=100.0,
                parts=[{"name": "p", "cost": 5.0, "stock": 2}],
            ),
            _asset(id="2", name="Box", cost=50.0, parts=[]),
        ]
    )
    text = inv.inventory_to_csv(report)
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    assert header[0] == "Name"
    # Two data rows, sorted by name.
    assert rows[1][0] == "Apple"
    assert rows[2][0] == "Box"
    # A blank spacer row, then the TOTAL row with cost + spares under their columns.
    total = rows[-1]
    assert total[0] == "TOTAL"
    assert total[header.index("Cost")] == "150.0"
    assert total[header.index("Spares value")] == "10.0"


def test_csv_neutralizes_formula_injection():
    # A field a spreadsheet would treat as a formula is prefixed with ' so it renders
    # as literal text (CSV/formula injection guard).
    report = inv.build_inventory(
        [_asset(id="1", name='=HYPERLINK("http://evil")', manufacturer="@SUM(A1)")]
    )
    text = inv.inventory_to_csv(report)
    row = next(
        r for r in csv.reader(io.StringIO(text)) if r and r[0].endswith('evil")')
    )
    assert row[0].startswith("'="), (
        "a formula-like name must be prefixed with an apostrophe"
    )
    assert row[2].startswith("'@"), "a formula-like manufacturer must be neutralized"


def test_spares_total_does_not_drift_from_per_row_rounding():
    # Per-row spares are rounded for display, but the grand total accumulates the raw
    # values and rounds once, so it can't drift from summing rounded rows.
    a = _asset(
        id="1", name="A", cost=0.0, parts=[{"name": "p", "cost": 0.005, "stock": 1}]
    )
    b = _asset(
        id="2", name="B", cost=0.0, parts=[{"name": "q", "cost": 0.005, "stock": 1}]
    )
    report = inv.build_inventory([a, b])
    # Each row rounds 0.005 -> 0.01 (banker's rounding may give 0.0), but the total is
    # round(0.005 + 0.005) == 0.01 regardless.
    assert report["totals"]["spares_value"] == 0.01
