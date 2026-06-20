"""Unit tests for the shared completion-event payload builder.

This is the single source of the ``home_keeper_task_completed`` payload, used by
both the real store and the test fake, so the contract can't drift.
"""

from datetime import datetime, timedelta, timezone

import hk_events as ev

TZ = timezone(timedelta(hours=-4))
WHEN = datetime(2026, 6, 14, 10, tzinfo=TZ)


def test_payload_has_contract_fields():
    task = {
        "id": "t1",
        "name": "Medicine",
        "device_id": "dev1",
        "area_id": "kitchen",
        "recurrence_type": "floating",
        "next_due": "2026-07-01T10:00:00-04:00",
        "enabled": True,
        "labels": ["dog"],
        "source": {"pawsistant": {"schedule_id": "s1"}},
    }
    data = ev.completion_event_data(task, WHEN, origin="pawsistant")
    assert data == {
        "task_id": "t1",
        "name": "Medicine",
        "device_id": "dev1",
        "area_id": "kitchen",
        "recurrence_type": "floating",
        "next_due": "2026-07-01T10:00:00-04:00",
        "enabled": True,
        "labels": ["dog"],
        "source": {"pawsistant": {"schedule_id": "s1"}},
        "managed_by": None,
        "completed_at": WHEN.isoformat(),
        "origin": "pawsistant",
    }


def test_task_event_spine_defaults_and_extra():
    data = ev.task_event_data({"id": "t9"}, extra={"changed_fields": ["name"]})
    assert data["task_id"] == "t9"
    # Sensible defaults for a sparse task dict.
    assert data["device_id"] is None and data["area_id"] is None
    assert data["enabled"] is True and data["next_due"] is None
    assert data["source"] is None and data["managed_by"] is None
    assert data["labels"] == []  # defaults to empty for a label-less task
    assert data["changed_fields"] == ["name"]


def test_asset_event_data_shape():
    data = ev.asset_event_data(
        {"id": "a1", "name": "Furnace", "device_id": "dev1"},
        extra={"changed_fields": ["model"]},
    )
    assert data == {
        "asset_id": "a1",
        "asset_name": "Furnace",
        "device_id": "dev1",
        "changed_fields": ["model"],
    }
    # Tolerates a missing name.
    assert ev.asset_event_data({"id": "a2"})["asset_name"] == ""


def test_stock_event_data_alias_matches_low_stock():
    asset = {"id": "a1", "name": "Furnace", "device_id": "dev1"}
    part = {"id": "p1", "name": "Filter", "stock": 0, "reorder_at": 1}
    assert ev.stock_event_data(asset, part) == ev.low_stock_event_data(asset, part)


def test_payload_carries_managed_by():
    managed_by = {"integration": "pawsistant", "display_name": "Pawsistant"}
    task = {
        "id": "t1",
        "name": "Medicine",
        "source": {"pawsistant": {"schedule_id": "s1"}},
        "managed_by": managed_by,
    }
    data = ev.completion_event_data(task, WHEN, origin=None)
    assert data["managed_by"] == managed_by


def test_source_defaults_to_none_and_origin_passthrough():
    data = ev.completion_event_data({"id": "t2", "name": "X"}, WHEN, origin=None)
    assert data["source"] is None
    assert data["managed_by"] is None
    assert data["origin"] is None


def test_accepts_iso_string_when():
    iso = WHEN.isoformat()
    data = ev.completion_event_data({"id": "t3", "name": "X"}, iso, origin=None)
    assert data["completed_at"] == iso


def test_low_stock_payload_has_reorder_fields():
    asset = {"id": "a1", "name": "Furnace", "device_id": "dev1"}
    part = {
        "id": "p1",
        "name": "Filter",
        "part_number": "FX-1",
        "vendor": "Acme",
        "stock": 1,
        "reorder_at": 1,
    }
    data = ev.low_stock_event_data(asset, part)
    assert data == {
        "asset_id": "a1",
        "asset_name": "Furnace",
        "device_id": "dev1",
        "part_id": "p1",
        "part_name": "Filter",
        "part_number": "FX-1",
        "vendor": "Acme",
        "stock": 1,
        "reorder_at": 1,
    }


def test_low_stock_payload_tolerates_missing_fields():
    data = ev.low_stock_event_data({}, {})
    assert data["asset_name"] == "" and data["part_name"] == ""
    assert data["device_id"] is None and data["stock"] is None
