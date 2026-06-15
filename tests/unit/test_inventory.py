"""Unit tests for the pure home-inventory aggregation (insurance export).

These exercise ``inventory.build_inventory`` / ``inventory_to_csv`` directly — no
Home Assistant runtime. Area names and "today" are injected (the websocket
handler supplies them in production).
"""

import csv
import io
from datetime import date

import hk_inventory as inv


def _asset(**kw):
    base = {
        "id": "a1",
        "kind": "virtual",
        "name": "Water heater",
        "area_id": None,
        "manufacturer": "Rheem",
        "model": "XE50",
        "serial_number": "SN-1",
        "purchase_date": "2024-01-01",
        "install_date": "2024-01-05",
        "warranty_expiry": "2030-01-01",
        "warranty_provider": "Rheem",
        "vendor": "Home Depot",
        "cost": 900.0,
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
    assert row["serial_number"] == "SN-1"
    assert row["cost"] == 900.0
    assert row["part_count"] == 0


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
    a = _asset(id="a1", name="A", cost=100.0, parts=[{"name": "p", "cost": 10.0, "stock": 2}])
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


def test_warranty_active_flagged_against_today():
    today = date(2026, 6, 15)
    active = _asset(id="1", name="A", warranty_expiry="2030-01-01")
    expired = _asset(id="2", name="B", warranty_expiry="2020-01-01")
    none = _asset(id="3", name="C", warranty_expiry=None)
    report = inv.build_inventory([active, expired, none], today=today)
    by_name = {r["name"]: r for r in report["assets"]}
    assert by_name["A"]["warranty_active"] is True
    assert by_name["B"]["warranty_active"] is False
    assert by_name["C"]["warranty_active"] is None


def test_warranty_active_none_without_today():
    report = inv.build_inventory([_asset()])  # today not supplied
    assert report["assets"][0]["warranty_active"] is None


def test_warranty_active_none_for_malformed_date():
    report = inv.build_inventory(
        [_asset(warranty_expiry="not-a-date")], today=date(2026, 6, 15)
    )
    assert report["assets"][0]["warranty_active"] is None


def test_csv_has_header_rows_and_total():
    report = inv.build_inventory(
        [
            _asset(id="1", name="Apple", cost=100.0, parts=[{"name": "p", "cost": 5.0, "stock": 2}]),
            _asset(id="2", name="Box", cost=50.0, parts=[]),
        ]
    )
    text = inv.inventory_to_csv(report)
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0][0] == "Name"
    # Two data rows, sorted by name.
    assert rows[1][0] == "Apple"
    assert rows[2][0] == "Box"
    # A blank spacer row, then the TOTAL row with cost + spares in the last columns.
    total = rows[-1]
    assert total[0] == "TOTAL"
    assert total[-2] == "150.0"
    assert total[-1] == "10.0"
