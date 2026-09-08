"""The maximal task and appliance, shared by every test that needs a full record.

``test_transfer_roundtrip.py`` wrote these to prove a field travels; the schema gate in
``test_generate_schema.py`` needs the same records to prove the published schema accepts
everything an export writes. Two copies would drift, and a drifted "maximal" record is a
field nobody checks.

Both are plain payloads: the caller passes them through ``models.build_task`` /
``assets.build_asset``, so a stored record is never described twice.
"""

from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)

AREA_NAMES = {"area_base": "Basement", "area_kitchen": "Kitchen"}
AREA_IDS = {"Basement": "area_base", "Kitchen": "area_kitchen"}


def _maximal_asset() -> dict:
    """An appliance with every optional field, every nested collection populated."""
    return {
        "name": "Furnace",
        "external_id": "centriq-4711",
        "kind": "virtual",
        "area_id": "area_base",
        "manufacturer": "Carrier",
        "model": "59TP6A",
        "serial_number": "1234-5678",
        "notes": "Installed by ABC Heating.",
        "icon": "mdi:fire",
        "cost": 4200.0,
        "metadata": [
            {
                "type": "date",
                "label": "Installed",
                "value": "2019-11-02",
                "track": True,
            },
            {"type": "link", "label": "Vendor", "value": "https://example.com"},
            {"type": "text", "label": "Breaker", "value": "Panel B, 14"},
        ],
        "documents": [
            {"kind": "link", "name": "Manual", "url": "https://example.com/m.pdf"}
        ],
        "parts": [
            {
                "name": "Filter",
                "part_number": "FILXXFCC0021",
                "type": "consumable",
                "vendor": "Acme",
                "cost": 24.5,
                "url": "https://example.com/filter",
                "notes": "MERV 13 only.",
                "replace_interval": 3,
                "replace_unit": "months",
                "last_replaced": "2026-03-04",
                "stock": 2.0,
                "reorder_at": 1.0,
                "stock_unit": "ea",
                "consume_quantity": 1.0,
                "create_buy_task": True,
                "restock_quantity": 4.0,
            }
        ],
        "related_device_ids": ["dev_thermostat"],
    }


def _maximal_task(**overrides) -> dict:
    """A task with every recurrence-independent field set."""
    task = {
        "name": "Replace furnace filter",
        "external_id": "furnace-filter",
        "notes": "MERV 13 only.",
        "recurrence_type": "floating",
        "interval": 3,
        "unit": "months",
        "area_id": "area_base",
        "enabled": True,
        "labels": ["label_hvac", "label_seasonal"],
        "card_links": [{"asset_id": "asset_1", "entry_id": "doc_1"}],
        "task_chips": [{"label": "HVAC", "icon": "mdi:fire"}],
        "tag_id": "tag_furnace",
        "require_tag_scan": False,
        "completion_detail": "optional",
        "completion_required_fields": [],
        "active_season": [{"start": "10-01", "end": "04-30"}],
    }
    task.update(overrides)
    return task


# Every recurrence type, so the schedule fields that only exist for one of them
# (``freq``/``anchor``, ``due``, ``sensor``) are all exercised.
_BY_TYPE = {
    "floating": {},
    "fixed": {
        "recurrence_type": "fixed",
        "interval": 1,
        "freq": "MONTHLY",
        "anchor": "2026-01-15T09:00:00-04:00",
        "unit": None,
    },
    "one-off": {
        "recurrence_type": "one-off",
        "due": "2026-08-01T09:00:00-04:00",
        "interval": None,
        "unit": None,
        "active_season": None,
    },
    "triggered": {
        "recurrence_type": "triggered",
        "interval": None,
        "unit": None,
        "active_season": None,
    },
    "sensor": {
        "recurrence_type": "sensor",
        "interval": None,
        "unit": None,
        "active_season": None,
        "sensor": {
            "entity_id": "sensor.furnace_hours",
            "mode": "usage",
            "target": 1500.0,
            "unit": "h",
            "also_every": {"interval": 6, "unit": "months"},
            "combinator": "any",
        },
    },
}
