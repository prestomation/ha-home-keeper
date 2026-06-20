"""Unit tests for task construction / validation / updates."""

from datetime import datetime, timedelta, timezone

import hk_models as m
import pytest

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)


def test_build_floating_task_sets_id_and_is_due_now():
    task = m.build_task(
        {
            "name": "Furnace filter",
            "recurrence_type": "floating",
            "interval": 3,
            "unit": "months",
        },
        now=NOW,
    )
    assert task["id"]
    assert task["name"] == "Furnace filter"
    assert task["last_completed"] is None
    # Never completed -> due immediately, not 3 months out.
    assert task["next_due"] == NOW.isoformat()


def test_build_floating_task_with_last_completed_seed():
    # A "last done" seed records an initial completion and measures next_due from it.
    seed = datetime(2026, 6, 1, 9, tzinfo=TZ)
    task = m.build_task(
        {
            "name": "Nail trim",
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "weeks",
            "last_completed": seed.isoformat(),
        },
        now=NOW,
    )
    assert task["last_completed"] == seed.isoformat()
    assert task["completions"] == [{"ts": seed.isoformat()}]
    # 2 weeks after the seed, not due-now and not measured from NOW.
    assert task["next_due"] == datetime(2026, 6, 15, 9, tzinfo=TZ).isoformat()


def test_build_floating_task_seed_accepts_datetime():
    # The add_task service (cv.datetime) hands build_task an already-parsed datetime,
    # not a string — exercise that path directly.
    seed = datetime(2026, 6, 1, 9, tzinfo=TZ)
    task = m.build_task(
        {
            "name": "Nail trim",
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "weeks",
            "last_completed": seed,
        },
        now=NOW,
    )
    assert task["last_completed"] == seed.isoformat()
    assert task["next_due"] == datetime(2026, 6, 15, 9, tzinfo=TZ).isoformat()


def test_build_floating_task_seed_naive_is_qualified():
    # A naive seed (e.g. from a datetime-local picker) is qualified with the caller tz.
    task = m.build_task(
        {
            "name": "Nail trim",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "weeks",
            "last_completed": "2026-06-01T09:00",  # naive
        },
        now=NOW,
    )
    seeded = datetime.fromisoformat(task["last_completed"])
    assert seeded.tzinfo is not None
    assert seeded.utcoffset() == NOW.utcoffset()
    assert datetime.fromisoformat(task["next_due"]).tzinfo is not None


def test_build_task_rejects_bad_last_completed():
    with pytest.raises(m.TaskValidationError):
        m.build_task(
            {
                "name": "x",
                "recurrence_type": "floating",
                "interval": 1,
                "unit": "days",
                "last_completed": "not-a-date",
            },
            now=NOW,
        )


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
        m.build_task(
            {"recurrence_type": "floating", "interval": 1, "unit": "days"}, now=NOW
        )


def test_build_task_rejects_bad_unit():
    with pytest.raises(m.TaskValidationError):
        m.build_task(
            {
                "name": "x",
                "recurrence_type": "floating",
                "interval": 1,
                "unit": "lightyears",
            },
            now=NOW,
        )


def test_build_task_rejects_bad_interval():
    with pytest.raises(m.TaskValidationError):
        m.build_task(
            {"name": "x", "recurrence_type": "floating", "interval": 0, "unit": "days"},
            now=NOW,
        )


def test_build_task_rejects_oversized_interval():
    # An absurd interval must be a clean validation error, not a timedelta
    # OverflowError that surfaces as a 500.
    with pytest.raises(m.TaskValidationError):
        m.build_task(
            {
                "name": "x",
                "recurrence_type": "floating",
                "interval": 10**9,
                "unit": "days",
            },
            now=NOW,
        )


def test_build_task_rejects_non_numeric_interval():
    # Websocket payloads aren't coerced, so a non-numeric interval must raise a
    # validation error (not a raw ValueError that crashes the command).
    with pytest.raises(m.TaskValidationError):
        m.build_task(
            {
                "name": "x",
                "recurrence_type": "floating",
                "interval": "soon",
                "unit": "days",
            },
            now=NOW,
        )


def test_merge_update_name_only_keeps_schedule():
    task = m.build_task(
        {
            "name": "Filter",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
        },
        now=NOW,
    )
    original_due = task["next_due"]
    updated = m.merge_update(task, {"name": "Renamed filter"}, now=NOW)
    assert updated["name"] == "Renamed filter"
    assert updated["next_due"] == original_due  # schedule untouched


def test_merge_update_interval_recomputes_due():
    # Seed a completion so the recompute measures from a fixed point (a never-completed
    # task would just stay due-now, hiding the interval change).
    task = m.build_task(
        {
            "name": "Filter",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
            "last_completed": NOW.isoformat(),
        },
        now=NOW,
    )
    assert task["next_due"] == datetime(2026, 7, 13, 10, tzinfo=TZ).isoformat()
    updated = m.merge_update(task, {"interval": 2}, now=NOW)
    assert updated["interval"] == 2
    assert updated["next_due"] == datetime(2026, 8, 13, 10, tzinfo=TZ).isoformat()


def test_build_task_carries_opaque_source():
    # ``source`` is opaque provenance owned by a contributing integration; build_task
    # must store it verbatim so the task can be matched/echoed later.
    source = {
        "pawsistant": {"dog_id": "d1", "event_type": "medicine", "schedule_id": "s1"}
    }
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
        {
            "name": "Filter",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
        },
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
        "config_entry_id": "abc123",
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
        {
            "name": "Filter",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
        },
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
    assert updated["name"] == "Buddy: Medicine"  # locked — unchanged
    assert updated["device_id"] == "dev-buddy-123"  # locked — unchanged
    assert updated["interval"] == 4  # not locked — changed


def test_merge_update_without_managed_by_allows_all_fields():
    task = m.build_task(
        {
            "name": "Filter",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
        },
        now=NOW,
    )
    updated = m.merge_update(
        task, {"name": "New name", "device_id": "some-device"}, now=NOW
    )
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


def _protected_task() -> dict:
    return {
        "id": "t1",
        "name": "Buddy: Medicine",
        "managed_by": {
            "integration": "pawsistant",
            "display_name": "Pawsistant",
            "deletion_protected": True,
            "config_entry_id": "abc123",
        },
    }


def test_deletion_blocked_when_owner_present():
    # Protected task whose owner is still loaded → deletion refused.
    assert m.deletion_blocked(_protected_task(), orphaned=False) is True


def test_deletion_allowed_when_orphaned():
    # Owner gone (orphaned) → protection lifts so the user can clean up.
    assert m.deletion_blocked(_protected_task(), orphaned=True) is False


def test_deletion_force_bypasses_protection():
    # The escape hatch: force always wins, even with the owner present.
    assert m.deletion_blocked(_protected_task(), orphaned=False, force=True) is False


def test_deletion_not_blocked_without_protection():
    task = {
        "id": "t1",
        "name": "X",
        "managed_by": {"integration": "p", "display_name": "P"},
    }
    assert m.deletion_blocked(task, orphaned=False) is False


def test_deletion_not_blocked_for_unmanaged_task():
    assert m.deletion_blocked({"id": "t1", "name": "X"}, orphaned=False) is False


def test_build_task_rejects_deletion_protected_without_config_entry_id():
    # Protection without a config_entry_id would be a permanent trap (orphan
    # detection couldn't fire), so creation must be rejected.
    with pytest.raises(m.TaskValidationError):
        m.build_task(
            {
                "name": "Buddy: Medicine",
                "recurrence_type": "floating",
                "interval": 2,
                "unit": "weeks",
                "managed_by": {
                    "integration": "pawsistant",
                    "display_name": "Pawsistant",
                    "deletion_protected": True,
                },
            },
            now=NOW,
        )


def test_build_task_allows_deletion_protected_with_config_entry_id():
    task = m.build_task(
        {
            "name": "Buddy: Medicine",
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "weeks",
            "managed_by": {
                "integration": "pawsistant",
                "display_name": "Pawsistant",
                "deletion_protected": True,
                "config_entry_id": "abc123",
            },
        },
        now=NOW,
    )
    assert task["managed_by"]["config_entry_id"] == "abc123"


def test_build_task_rejects_non_mapping_managed_by():
    with pytest.raises(m.TaskValidationError):
        m.build_task(
            {
                "name": "X",
                "recurrence_type": "floating",
                "interval": 1,
                "unit": "days",
                "managed_by": "not-a-dict",
            },
            now=NOW,
        )


def test_build_task_allows_managed_without_protection_and_no_config_entry_id():
    # A managed task that doesn't request deletion protection needs no config_entry_id.
    task = m.build_task(
        {
            "name": "Buddy: Walk",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "days",
            "managed_by": {"integration": "pawsistant", "display_name": "Pawsistant"},
        },
        now=NOW,
    )
    assert task["managed_by"]["integration"] == "pawsistant"


def test_build_triggered_task_is_created_active_with_no_schedule_fields():
    # A condition-driven task is created armed (due-now) and carries no schedule.
    task = m.build_task(
        {
            "name": "Replace battery: Front door sensor",
            "recurrence_type": "triggered",
            "device_id": "dev_front_door",
            "source": {"home_keeper_battery_notes": {"device_id": "dev_front_door"}},
        },
        now=NOW,
    )
    assert task["recurrence_type"] == "triggered"
    assert task["next_due"] == NOW.isoformat()  # armed
    # No schedule fields are stored on a triggered task.
    for key in ("interval", "unit", "freq", "anchor"):
        assert key not in task


def test_triggered_task_does_not_require_unit_or_freq():
    # normalize_fields must not fall through to the fixed branch (which demands
    # freq/anchor) for a triggered task.
    fields = m.normalize_fields({"name": "Mop up leak", "recurrence_type": "triggered"})
    assert fields["recurrence_type"] == "triggered"
    assert "unit" not in fields and "freq" not in fields and "interval" not in fields


def test_merge_update_preserves_triggered_dormant_state():
    # Editing a dormant triggered task's notes must not re-arm it or add a schedule.
    task = m.build_task(
        {"name": "Replace battery", "recurrence_type": "triggered"}, now=NOW
    )
    task["next_due"] = None  # dormant
    merged = m.merge_update(task, {"notes": "2x AA"}, now=NOW)
    assert merged["next_due"] is None
    assert merged["notes"] == "2x AA"
    assert merged["recurrence_type"] == "triggered"


def test_merge_update_dormant_triggered_survives_realistic_frontend_payload():
    # Regression: the panel's edit form historically sent recurrence_type + interval
    # + freq for every task. For a dormant triggered task that must NOT recompute
    # next_due (which would re-arm a "Monitored" battery as due-now).
    task = m.build_task(
        {"name": "Replace battery", "recurrence_type": "triggered"}, now=NOW
    )
    task["next_due"] = None  # dormant
    merged = m.merge_update(
        task,
        {"recurrence_type": "triggered", "interval": 1, "freq": "DAILY", "notes": "AA"},
        now=NOW,
    )
    assert merged["next_due"] is None  # still dormant


def test_merge_update_keeps_armed_triggered_armed():
    # Symmetrically, editing an armed triggered task must not change its due time.
    task = m.build_task(
        {"name": "Replace battery", "recurrence_type": "triggered"}, now=NOW
    )
    armed = task["next_due"]  # created armed (== NOW)
    merged = m.merge_update(
        task, {"recurrence_type": "triggered", "interval": 1, "notes": "x"}, now=NOW
    )
    assert merged["next_due"] == armed


def test_build_task_normalizes_labels():
    # Labels are de-duplicated and blank-stripped, order preserved.
    task = m.build_task(
        {
            "name": "Vet visit",
            "recurrence_type": "floating",
            "interval": 6,
            "unit": "months",
            "labels": ["dog", "", "dog", " vet "],
        },
        now=NOW,
    )
    assert task["labels"] == ["dog", "vet"]


def test_build_task_defaults_labels_to_empty():
    task = m.build_task(
        {
            "name": "Mow lawn",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "weeks",
        },
        now=NOW,
    )
    assert task["labels"] == []


def test_build_task_rejects_non_list_labels():
    with pytest.raises(m.TaskValidationError):
        m.build_task(
            {
                "name": "Bad",
                "recurrence_type": "floating",
                "interval": 1,
                "unit": "weeks",
                "labels": {"not": "a list"},
            },
            now=NOW,
        )


def test_merge_update_sets_labels_when_provided():
    task = m.build_task(
        {
            "name": "Wash car",
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "weeks",
        },
        now=NOW,
    )
    updated = m.merge_update(task, {"labels": ["car", "car", "exterior"]}, now=NOW)
    assert updated["labels"] == ["car", "exterior"]


def test_merge_update_leaves_labels_untouched_when_absent():
    # A plain rename must not stamp/clear labels (no phantom "labels changed").
    task = m.build_task(
        {
            "name": "Wash car",
            "recurrence_type": "floating",
            "interval": 2,
            "unit": "weeks",
            "labels": ["car"],
        },
        now=NOW,
    )
    updated = m.merge_update(task, {"name": "Wash the car"}, now=NOW)
    assert updated["labels"] == ["car"]
