"""Pure aggregation for the appliance report.

Rolls the appliance records (and their spare parts) up into a flat report plus
rolled-up totals — the descriptive/ownership facts an insurance claim needs
(make/model/serial, replacement cost, the value of the spares on hand) — and
renders the same report as CSV for download.

This is the *report*, not the backup. ``transfer.py`` already exports every raw
field this module reads, so what earns this one its place is the arithmetic
(``spares_value`` per asset and the totals block) and the CSV rendering. Add a
descriptive field to an asset and it travels through ``transfer.py`` for free;
add one here only when the report should *total* or *print* it.

Imports nothing from Home Assistant so it stays unit-testable; the websocket
handler injects the area-name lookup and the current date.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any

from .backend_i18n import resolve_string


def _num(value: Any) -> float:
    """Best-effort float, treating unset / unparseable values as 0."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _spares_value(part: dict[str, Any]) -> float:
    """On-hand value of a part: unit cost * stock (0 when either is unknown).

    Stock can be fractional (half a bottle of softener), so the cost is per *unit of
    stock* — whatever unit the part counts itself in — and half a unit is worth half.
    """
    cost = part.get("cost")
    stock = part.get("stock")
    if cost is None or stock is None:
        return 0.0
    return _num(cost) * _num(stock)


def _metadata_details(asset: dict[str, Any]) -> str:
    """Flatten an asset's free-form metadata into a ``label: value; …`` summary.

    Keeps the descriptive facts (warranty, purchase date, provider…) — now
    user-defined rather than fixed columns — discoverable in the export without a
    prescriptive column per field. Serial number has its own first-class column; a
    legacy free-form "Serial" *metadata* entry (if the user added one before the field
    existed) still rides here too, so it can appear in both places.
    """
    parts = []
    for entry in asset.get("metadata") or []:
        value = entry.get("value")
        label = entry.get("label")
        if label and value:
            parts.append(f"{label}: {value}")
    return "; ".join(parts)


def build_report(
    assets: list[dict[str, Any]],
    *,
    area_names: dict[str, str] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Return a flat appliance report: one row per appliance plus rolled-up totals.

    ``area_names`` maps ``area_id`` -> human-readable name. Rows are sorted by name
    so the export is stable. ``today`` is accepted for signature stability but no
    longer used (warranty is free-form metadata now, not a fixed column).
    """
    area_names = area_names or {}
    rows: list[dict[str, Any]] = []
    total_cost = 0.0
    total_spares = 0.0
    for asset in assets:
        parts = asset.get("parts") or []
        # Accumulate the raw spares sum into the total (round once at the end), so the
        # grand total can't drift a cent from re-rounding already-rounded rows.
        raw_spares = sum(_spares_value(p) for p in parts)
        spares_value = round(raw_spares, 2)
        cost = asset.get("cost")
        area_id = asset.get("area_id")
        rows.append(
            {
                "id": asset.get("id"),
                "name": asset.get("name") or "",
                "kind": asset.get("kind"),
                "area": area_names.get(area_id) if area_id else None,
                "manufacturer": asset.get("manufacturer") or "",
                "model": asset.get("model") or "",
                "serial_number": asset.get("serial_number") or "",
                "cost": cost,
                "spares_value": spares_value,
                "part_count": len(parts),
                "details": _metadata_details(asset),
            }
        )
        total_cost += _num(cost)
        total_spares += raw_spares
    rows.sort(key=lambda r: (r["name"] or "").lower())
    totals = {
        "asset_count": len(rows),
        "total_cost": round(total_cost, 2),
        "spares_value": round(total_spares, 2),
        "grand_total": round(total_cost + total_spares, 2),
    }
    return {"assets": rows, "totals": totals}


# (row key, backend_strings header key) — the columns most useful on an insurance
# schedule. ``serial_number`` is a first-class identity column; the remaining
# free-form descriptive facts (warranty, dates, provider…) ride in the trailing
# Details column rather than a fixed column each.
_CSV_COLUMNS = (
    ("name", "report.csv.name"),
    ("area", "report.csv.area"),
    ("manufacturer", "report.csv.manufacturer"),
    ("model", "report.csv.model"),
    ("serial_number", "report.csv.serial_number"),
    ("cost", "report.csv.cost"),
    ("spares_value", "report.csv.spares_value"),
    ("details", "report.csv.details"),
)


def _cell(value: Any) -> str:
    """Stringify a CSV cell, neutralizing spreadsheet formula injection.

    A cell that a spreadsheet would treat as a formula (leading ``= + - @`` or a
    leading tab/CR) is prefixed with an apostrophe so Excel/Sheets/LibreOffice show
    it as literal text rather than evaluating it. Our numeric columns are
    non-negative, so this never mangles a real number.
    """
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in "=+-@\t\r":
        return "'" + text
    return text


def report_to_csv(
    report: dict[str, Any],
    *,
    # Equivalent mutant: ``resolve_string`` falls back to English for any language
    # it cannot resolve, so a mutated default behaves exactly like "en".
    lang: str = "en",  # pragma: no mutate
) -> str:
    """Render :func:`build_report` output as CSV (a row per asset + a TOTAL row).

    Column headers and the ``TOTAL`` row label are localized to *lang* (the
    caller's ``hass.config.language``) via ``backend_strings/<lang>.json`` — this
    module has no HA import, so the resolved language is threaded in as a plain
    string rather than read from ``hass`` directly.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    headers = [resolve_string(lang, key) for _key, key in _CSV_COLUMNS]
    writer.writerow(headers)
    for row in report.get("assets", []):
        writer.writerow([_cell(row.get(key)) for key, _header_key in _CSV_COLUMNS])
    totals = report.get("totals", {})
    # Blank spacer, then a TOTAL row with the totals placed under their own columns.
    keys = [key for key, _header_key in _CSV_COLUMNS]
    total_row = [""] * len(_CSV_COLUMNS)
    total_row[0] = resolve_string(lang, "report.csv.total")
    total_row[keys.index("cost")] = _cell(totals.get("total_cost"))
    total_row[keys.index("spares_value")] = _cell(totals.get("spares_value"))
    writer.writerow([])
    writer.writerow(total_row)
    return buf.getvalue()
