"""Unit tests for task construction / validation / updates."""

from datetime import datetime, timedelta, timezone

import hk_models as m
import pytest

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)


def test_build_floating_task_sets_id_and_next_due():
    task = m.build_task(
        {"name": "Furnace filter", "recurrence_type": "floating", "interval": 3, "unit": "months"},
        now=NOW,
    )
    assert task["id"]
    assert task["name"] == "Furnace filter"
    assert task["last_completed"] is None
    # 3 months from now.
    assert task["next_due"] == datetime(2026, 9, 13, 10, tzinfo=TZ).isoformat()


def test_build_fixed_task_requires_anchor_and_freq():
    task = m.build_task(
        {
            "name": "Medicine",
            "recurrence_type": "fixed",
            "interval": 1,
            "freq": "DAILY",
            "anchor": datetime(2026, 1, 1, 8, tzinfo=TZ).isoformat(),
        },
        now=NOW,
    )
    assert task["next_due"] == datetime(2026, 6, 14, 8, tzinfo=TZ).isoformat()


def test_build_fixed_task_normalizes_naive_anchor():
    # The panel's datetime-local input has no timezone; build_task must make the
    # anchor tz-aware so recurrence math doesn't compare naive vs aware datetimes.
    task = m.build_task(
        {
            "name": "Medicine",
            "recurrence_type": "fixed",
            "interval": 1,
            "freq": "DAILY",
            "anchor": "2026-01-01T08:00",  # naive
        },
        now=NOW,
    )
    anchor = datetime.fromisoformat(task["anchor"])
    assert anchor.tzinfo is not None
    # The naive wall-clock time is qualified with the caller-provided tz (NOW's),
    # not shifted, so the time-of-day is preserved.
    assert anchor.utcoffset() == NOW.utcoffset()
    assert (anchor.hour, anchor.minute) == (8, 0)
    # next_due must be computable (no crash) and be a parseable aware datetime.
    assert datetime.fromisoformat(task["next_due"]).tzinfo is not None


def test_build_task_rejects_missing_name():
    with pytest.raises(m.TaskValidationError):
        m.build_task({"recurrence_type": "floating", "interval": 1, "unit": "days"}, now=NOW)


def test_build_task_rejects_bad_unit():
    with pytest.raises(m.TaskValidationError):
        m.build_task({"name": "x", "recurrence_type": "floating", "interval": 1, "unit": "lightyears"}, now=NOW)


def test_build_task_rejects_bad_interval():
    with pytest.raises(m.TaskValidationError):
        m.build_task({"name": "x", "recurrence_type": "floating", "interval": 0, "unit": "days"}, now=NOW)


def test_build_task_rejects_oversized_interval():
    # An absurd interval must be a clean validation error, not a timedelta
    # OverflowError that surfaces as a 500.
    with pytest.raises(m.TaskValidationError):
        m.build_task(
            {"name": "x", "recurrence_type": "floating", "interval": 10**9, "unit": "days"},
            now=NOW,
        )


def test_build_task_rejects_non_numeric_interval():
    # Websocket payloads aren't coerced, so a non-numeric interval must raise a
    # validation error (not a raw ValueError that crashes the command).
    with pytest.raises(m.TaskValidationError):
        m.build_task(
            {"name": "x", "recurrence_type": "floating", "interval": "soon", "unit": "days"},
            now=NOW,
        )


def test_merge_update_name_only_keeps_schedule():
    task = m.build_task(
        {"name": "Filter", "recurrence_type": "floating", "interval": 1, "unit": "months"},
        now=NOW,
    )
    original_due = task["next_due"]
    updated = m.merge_update(task, {"name": "Renamed filter"}, now=NOW)
    assert updated["name"] == "Renamed filter"
    assert updated["next_due"] == original_due  # schedule untouched


def test_merge_update_interval_recomputes_due():
    task = m.build_task(
        {"name": "Filter", "recurrence_type": "floating", "interval": 1, "unit": "months"},
        now=NOW,
    )
    updated = m.merge_update(task, {"interval": 2}, now=NOW)
    assert updated["interval"] == 2
    assert updated["next_due"] == datetime(2026, 8, 13, 10, tzinfo=TZ).isoformat()


def test_build_task_carries_opaque_source():
    # ``source`` is opaque provenance owned by a contributing integration; build_task
    # must store it verbatim so the task can be matched/echoed later.
    source = {"pawsistant": {"dog_id": "d1", "event_type": "medicine", "schedule_id": "s1"}}
    task = m.build_task(
        {
            "name": "Medicine",
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "weeks",
            "source": source,
        },
        now=NOW,
    )
    assert task["source"] == source


def test_build_task_source_defaults_to_none():
    task = m.build_task(
        {"name": "Filter", "recurrence_type": "floating", "interval": 1, "unit": "months"},
        now=NOW,
    )
    assert task["source"] is None


def test_merge_update_preserves_source():
    # Editing other fields must not drop the provenance a contributor relies on.
    source = {"pawsistant": {"schedule_id": "s1"}}
    task = m.build_task(
        {
            "name": "Medicine",
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "weeks",
            "source": source,
        },
        now=NOW,
    )
    updated = m.merge_update(task, {"name": "Renamed", "interval": 3}, now=NOW)
    assert updated["source"] == source


def test_build_task_carries_managed_by():
    managed_by = {
        "integration": "pawsistant",
        "display_name": "Pawsistant",
        "icon": "mdi:paw",
        "locked_fields": ["device_id", "name"],
        "deletion_protected": True,
    }
    task = m.build_task(
        {
            "name": "Medicine",
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "weeks",
            "managed_by": managed_by,
        },
        now=NOW,
    )
    assert task["managed_by"] == managed_by


def test_build_task_managed_by_defaults_to_none():
    task = m.build_task(
        {"name": "Filter", "recurrence_type": "floating", "interval": 1, "unit": "months"},
        now=NOW,
    )
    assert task["managed_by"] is None


def test_merge_update_respects_locked_fields():
    managed_by = {
        "integration": "pawsistant",
        "display_name": "Pawsistant",
        "locked_fields": ["device_id", "name"],
    }
    task = m.build_task(
        {
            "name": "Buddy: Medicine",
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "weeks",
            "device_id": "dev-buddy-123",
            "managed_by": managed_by,
        },
        now=NOW,
    )
    # Locked fields silently ignored; unlocked fields applied normally.
    updated = m.merge_update(
        task,
        {"name": "Hacked name", "device_id": "evil-device", "interval": 4},
        now=NOW,
    )
    assert updated["name"] == "Buddy: Medicine"     # locked — unchanged
    assert updated["device_id"] == "dev-buddy-123"  # locked — unchanged
    assert updated["interval"] == 4                 # not locked — changed


def test_merge_update_without_managed_by_allows_all_fields():
    task = m.build_task(
        {"name": "Filter", "recurrence_type": "floating", "interval": 1, "unit": "months"},
        now=NOW,
    )
    updated = m.merge_update(task, {"name": "New name", "device_id": "some-device"}, now=NOW)
    assert updated["name"] == "New name"
    assert updated["device_id"] == "some-device"


def test_merge_update_preserves_managed_by():
    # managed_by must survive a merge just like source does.
    managed_by = {"integration": "pawsistant", "display_name": "Pawsistant"}
    task = m.build_task(
        {
            "name": "Medicine",
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "weeks",
            "managed_by": managed_by,
        },
        now=NOW,
    )
    updated = m.merge_update(task, {"notes": "new note"}, now=NOW)
    assert updated["managed_by"] == managed_by
