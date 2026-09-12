"""Unit tests for the pure appliance-report aggregation.

These exercise ``appliance_report.build_report`` / ``report_to_csv`` directly — no
Home Assistant runtime. Area names and "today" are injected (the websocket
handler supplies them in production).
"""

import csv
import io

import hk_appliance_report as report_mod
import pytest


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


def test_empty_report_has_zero_totals():
    report = report_mod.build_report([])
    assert report["assets"] == []
    assert report["totals"] == {
        "asset_count": 0,
        "total_cost": 0.0,
        "spares_value": 0.0,
        "grand_total": 0.0,
    }


def test_row_carries_insurance_fields_and_area_name():
    report = report_mod.build_report(
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
    report = report_mod.build_report([_asset(area_id="ghost")], area_names={})
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
    report = report_mod.build_report([asset])
    row = report["assets"][0]
    assert row["spares_value"] == 110.0
    assert row["part_count"] == 4


def test_spares_value_counts_a_fractional_stock():
    # Cost is per unit of stock, whatever unit the part counts itself in, so half a
    # bottle on the shelf is worth half a bottle — not zero, and not a whole one.
    asset = _asset(
        parts=[
            {"name": "Softener", "cost": 6.0, "stock": 0.5, "stock_unit": "bottles"},
            {"name": "Line", "cost": 0.2, "stock": 12.5, "stock_unit": "m"},
        ]
    )
    assert report_mod.build_report([asset])["assets"][0]["spares_value"] == 5.5


def test_totals_roll_up_cost_and_spares():
    a = _asset(
        id="a1", name="A", cost=100.0, parts=[{"name": "p", "cost": 10.0, "stock": 2}]
    )
    b = _asset(id="b1", name="B", cost=50.0, parts=[])
    report = report_mod.build_report([a, b])
    assert report["totals"] == {
        "asset_count": 2,
        "total_cost": 150.0,
        "spares_value": 20.0,
        "grand_total": 170.0,
    }


def test_missing_cost_treated_as_zero_not_error():
    report = report_mod.build_report([_asset(cost=None)])
    assert report["totals"]["total_cost"] == 0.0
    assert report["assets"][0]["cost"] is None  # raw value preserved on the row


def test_total_cost_rounds_to_cents():
    # The asset costs elsewhere in this file are all whole cents, so nothing there
    # tells `round(total_cost, 2)` apart from rounding to any other precision.
    # 0.125 + 0.25 is 0.375, which is 0.38 at 2dp and 0.375 at 3dp.
    a = _asset(id="1", name="A", cost=0.125, parts=[])
    b = _asset(id="2", name="B", cost=0.25, parts=[])
    report = report_mod.build_report([a, b])
    assert report["totals"]["total_cost"] == 0.38
    assert report["totals"]["grand_total"] == 0.38


def test_rows_sorted_by_name_case_insensitive():
    # "apple"/"Zebra" rather than "zebra"/"Apple": the second pair sorts the same
    # way with or without the ``.lower()``, because every uppercase letter sorts
    # below every lowercase one. Only a lowercase name that must come *first*
    # proves the sort folds case.
    report = report_mod.build_report(
        [_asset(id="1", name="Zebra"), _asset(id="2", name="apple")]
    )
    assert [r["name"] for r in report["assets"]] == ["apple", "Zebra"]


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
    row = report_mod.build_report([asset])["assets"][0]
    assert row["details"] == "Serial: SN-9; Manual: https://ex/m.pdf"


def test_csv_has_header_rows_and_total():
    report = report_mod.build_report(
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
    text = report_mod.report_to_csv(report)
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
    # Every other cell of that row is empty. A spreadsheet reads the row as the
    # totals of the columns the values sit under, so a stray value in one of the
    # descriptive columns would read as a total of names or serial numbers.
    filled = {"TOTAL", "150.0", "10.0"}
    assert [c for c in total if c not in filled] == [""] * (len(header) - 3)


def test_csv_of_a_report_missing_its_sections_still_writes_a_file():
    # ``report_to_csv`` defaults both lookups, so a caller that hands it a report
    # without ``assets`` or ``totals`` gets headers and an empty TOTAL row rather
    # than a TypeError halfway through writing the file.
    rows = list(csv.reader(io.StringIO(report_mod.report_to_csv({}))))
    assert rows[0][0] == "Name"
    assert rows[-1][0] == "TOTAL"
    assert rows[-1][1:] == [""] * (len(rows[0]) - 1)


def test_an_unnamed_appliance_sorts_first_rather_than_failing():
    # ``name`` is required on a stored asset, but the sort key defaults it anyway,
    # and the default has to be the empty string: any other placeholder would sort
    # the nameless row into the middle of the list by whatever letter it started.
    report = report_mod.build_report(
        [_asset(id="1", name="Apple"), _asset(id="2", name="")]
    )
    assert [r["name"] for r in report["assets"]] == ["", "Apple"]


def test_csv_headers_and_total_are_localized():
    # Both export surfaces (the ``export_appliance_report`` service and the panel's
    # websocket command) pass ``hass.config.language`` through — the CSV a
    # Spanish-speaking household saves should not carry English headers.
    report = report_mod.build_report(
        [_asset(id="1", name="Apple", cost=100.0, parts=[])]
    )
    rows = list(csv.reader(io.StringIO(report_mod.report_to_csv(report, lang="es"))))
    assert rows[0][0] == "Nombre"
    assert rows[-1][0] == "TOTAL"  # es.json spells the total row label the same way
    # German, because it spells *both* apart from English: a language whose TOTAL
    # label happens to match (es, fr, ca, pt-BR) cannot tell a localized total row
    # from one that resolved the label against the wrong language.
    rows = list(csv.reader(io.StringIO(report_mod.report_to_csv(report, lang="de"))))
    assert rows[-1][0] == "GESAMT"
    # An unknown language falls back to English rather than failing the export.
    rows = list(csv.reader(io.StringIO(report_mod.report_to_csv(report, lang="xx"))))
    assert rows[0][0] == "Name"


def test_csv_neutralizes_formula_injection():
    # A field a spreadsheet would treat as a formula is prefixed with ' so it renders
    # as literal text (CSV/formula injection guard).
    report = report_mod.build_report(
        [_asset(id="1", name='=HYPERLINK("http://evil")', manufacturer="@SUM(A1)")]
    )
    text = report_mod.report_to_csv(report)
    row = next(
        r for r in csv.reader(io.StringIO(text)) if r and r[0].endswith('evil")')
    )
    assert row[0].startswith("'="), (
        "a formula-like name must be prefixed with an apostrophe"
    )
    assert row[2].startswith("'@"), "a formula-like manufacturer must be neutralized"


@pytest.mark.parametrize("lead", ["=", "+", "-", "@", "\t", "\r"])
def test_every_formula_lead_character_is_neutralized(lead):
    # The guard names 6 lead characters. Only 2 of them were ever asserted on, so
    # dropping any of the other 4 from the set went unnoticed.
    report = report_mod.build_report([_asset(id="1", name=f"{lead}danger")])
    assert report_mod._cell(report["assets"][0]["name"]) == f"'{lead}danger"


@pytest.mark.parametrize(
    "text",
    [
        "Water heater",
        "zebra",
        "1998 furnace",
        "N/A",
        # A real model number from the fixture above. Any letter would do, but a
        # leading "X" is the one a widened guard is most likely to swallow, and a
        # model number is exactly the kind of cell that starts with one.
        "XE50",
    ],
)
def test_an_ordinary_cell_is_not_quoted(text):
    # The other half of the guard, and the half nothing asserted: widening the
    # dangerous set to catch an ordinary name would quietly put an apostrophe in
    # front of a value the user reads in every row of their spreadsheet.
    assert report_mod._cell(text) == text


def test_spares_total_does_not_drift_from_per_row_rounding():
    # Per-row spares are rounded for display, but the grand total accumulates the raw
    # values and rounds once, so it can't drift from summing rounded rows.
    a = _asset(
        id="1", name="A", cost=0.0, parts=[{"name": "p", "cost": 0.005, "stock": 1}]
    )
    b = _asset(
        id="2", name="B", cost=0.0, parts=[{"name": "q", "cost": 0.005, "stock": 1}]
    )
    report = report_mod.build_report([a, b])
    # Each row rounds 0.005 -> 0.01 (banker's rounding may give 0.0), but the total is
    # round(0.005 + 0.005) == 0.01 regardless.
    assert report["totals"]["spares_value"] == 0.01


def test_row_is_exactly_the_documented_shape():
    # The row dict *is* the export contract — the CSV writer and the panel both
    # index it by key, and an insurance export is the one artefact a user hands
    # to a third party. Asserting a handful of fields lets a renamed or dropped
    # key through, so assert the whole dict.
    report = report_mod.build_report(
        [
            _asset(
                area_id="garage",
                serial_number="SN-TOP",
                parts=[{"name": "Anode rod", "cost": 30.0, "stock": 2}],
            )
        ],
        area_names={"garage": "Garage"},
    )
    assert report["assets"] == [
        {
            "id": "a1",
            "name": "Water heater",
            "kind": "virtual",
            "area": "Garage",
            "manufacturer": "Rheem",
            "model": "XE50",
            "serial_number": "SN-TOP",
            "cost": 900.0,
            "spares_value": 60.0,
            "part_count": 1,
            "details": "Serial: SN-1; Warranty expiry: 2030-01-01",
        }
    ]


def test_absent_text_fields_become_empty_strings_not_none():
    # A CSV cell of "None" would be visible nonsense in the export, so the row
    # coalesces missing text to "". `cost` deliberately stays None — blank is
    # meaningfully different from zero for an insurance value.
    report = report_mod.build_report(
        [
            {
                "id": "a2",
                "kind": "virtual",
                "name": None,
                "metadata": [],
                "parts": [],
            }
        ]
    )
    row = report["assets"][0]
    assert row["name"] == ""
    assert row["manufacturer"] == ""
    assert row["model"] == ""
    assert row["serial_number"] == ""
    assert row["cost"] is None
    assert row["area"] is None


@pytest.mark.parametrize(
    ("unit_cost", "stock", "expected"),
    [
        # Chosen so the answer differs at 2dp from both 0dp and 3dp: the row is
        # money, so "round to cents" has to be exactly that.
        (1.0625, 2, 2.12),  # 2.125 -> 2.12, not 2 and not 2.125
        (0.625, 3, 1.88),  # 1.875 -> 1.88, not 2 and not 1.875
    ],
)
def test_spares_value_rounds_to_cents(unit_cost, stock, expected):
    report = report_mod.build_report(
        [
            _asset(
                cost=None, parts=[{"name": "Filter", "cost": unit_cost, "stock": stock}]
            )
        ]
    )
    assert report["assets"][0]["spares_value"] == expected
    # The totals round independently of the row, so pin them too.
    assert report["totals"]["spares_value"] == expected
    assert report["totals"]["grand_total"] == expected


def test_area_is_looked_up_by_id_not_carried_through():
    # The row must carry the resolved *name*; leaking the raw id into an export
    # a human reads would be a regression even though both are strings.
    report = report_mod.build_report(
        [_asset(area_id="garage")], area_names={"garage": "Garage"}
    )
    assert report["assets"][0]["area"] == "Garage"
    assert report["assets"][0].get("area_id") is None
