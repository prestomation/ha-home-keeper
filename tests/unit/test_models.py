"""Unit tests for task construction / validation / updates."""

from datetime import datetime, timedelta, timezone

import hk_models as m
import pytest
from asserts import raises_exactly

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
    with raises_exactly(
        m.TaskValidationError, "invalid last_completed datetime: 'not-a-date'"
    ):
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
    with raises_exactly(m.TaskValidationError, "missing required field: 'name'"):
        m.build_task(
            {"recurrence_type": "floating", "interval": 1, "unit": "days"}, now=NOW
        )


def test_build_task_rejects_bad_unit():
    with raises_exactly(m.TaskValidationError, "invalid unit: 'lightyears'"):
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
    with raises_exactly(m.TaskValidationError, "interval must be >= 1"):
        m.build_task(
            {"name": "x", "recurrence_type": "floating", "interval": 0, "unit": "days"},
            now=NOW,
        )


def test_build_task_rejects_oversized_interval():
    # An absurd interval must be a clean validation error, not a timedelta
    # OverflowError that surfaces as a 500.
    with raises_exactly(m.TaskValidationError, "interval must be <= 10000"):
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
    with raises_exactly(m.TaskValidationError, "interval must be a valid integer"):
        m.build_task(
            {
                "name": "x",
                "recurrence_type": "floating",
                "interval": "soon",
                "unit": "days",
            },
            now=NOW,
        )


def test_completion_metadata_rejects_nan_infinity_cost():
    # NaN passes every < / <= comparison, so a bare float() would let it persist (and
    # NaN serializes to null on the JSON round-trip). Reject non-finite numbers.
    for bad in (float("nan"), float("inf"), "nan", "inf"):
        with raises_exactly(m.TaskValidationError, "cost must be a finite number"):
            m.normalize_completion_metadata({"cost": bad})


def test_build_sensor_task_rejects_nan_target():
    for bad in (float("nan"), float("inf")):
        with raises_exactly(
            m.TaskValidationError, "sensor.target must be a finite number"
        ):
            m.build_task(
                {
                    "name": "x",
                    "recurrence_type": "sensor",
                    "sensor": {
                        "entity_id": "sensor.hours",
                        "mode": "usage",
                        "target": bad,
                    },
                },
                now=NOW,
            )


def test_build_task_notes_null_becomes_empty_string():
    # An explicit notes=None must clear the field, not store the literal "None".
    task = m.build_task(
        {
            "name": "x",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "days",
            "notes": None,
        },
        now=NOW,
    )
    assert task["notes"] == ""


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
    with raises_exactly(
        m.TaskValidationError,
        "managed_by.deletion_protected requires config_entry_id so the task can "
        "still be cleaned up if the managing integration is removed",
    ):
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
    with raises_exactly(m.TaskValidationError, "managed_by must be a mapping"):
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


def test_merge_update_converts_triggered_to_floating():
    # Regression: a triggered task has no interval, so merge_update's candidate
    # carries interval=None. normalize_fields' `data.get("interval", 1)` returned
    # that None (key present) instead of defaulting to 1, raising "interval must be
    # a valid integer". Converting to floating with just unit must now succeed,
    # defaulting interval to 1 like a fresh creation.
    task = m.build_task(
        {"name": "Replace battery", "recurrence_type": "triggered"}, now=NOW
    )
    merged = m.merge_update(
        task, {"recurrence_type": "floating", "unit": "days"}, now=NOW
    )
    assert merged["recurrence_type"] == "floating"
    assert merged["interval"] == 1
    assert merged["unit"] == "days"
    # A floating task with no completion is due now.
    assert merged["next_due"] == NOW.isoformat()


def test_merge_update_converts_triggered_to_floating_with_explicit_interval():
    # When the conversion does supply an interval, it is honored (not overwritten).
    task = m.build_task(
        {"name": "Replace battery", "recurrence_type": "triggered"}, now=NOW
    )
    merged = m.merge_update(
        task,
        {"recurrence_type": "floating", "unit": "months", "interval": 6},
        now=NOW,
    )
    assert merged["recurrence_type"] == "floating"
    assert merged["interval"] == 6
    assert merged["unit"] == "months"


def test_merge_update_converts_fixed_to_triggered_arms_now_not_stale_date():
    # Regression: converting a scheduled task to ``triggered`` left ``next_due`` at the
    # old schedule date. A triggered task's next_due is an armed-now timestamp (or None
    # when dormant), so a stale future/past date made it render as "armed" at a
    # meaningless instant. It must reset to the fresh-build state (armed == now), like
    # ``build_task`` creates a triggered task. The ``-> sensor`` direction already did
    # this (resetting to None); the ``-> triggered`` direction was missed.
    task = m.build_task(
        {
            "name": "Service boiler",
            "recurrence_type": "fixed",
            "freq": "MONTHLY",
            "interval": 1,
            "anchor": "2026-12-30T08:00:00",
        },
        now=NOW,
    )
    assert task["next_due"] != NOW.isoformat()  # a real future schedule date
    merged = m.merge_update(task, {"recurrence_type": "triggered"}, now=NOW)
    assert merged["recurrence_type"] == "triggered"
    assert merged["next_due"] == NOW.isoformat()  # armed now, not the stale Dec date


def test_merge_update_converts_floating_to_triggered_arms_now():
    task = m.build_task(
        {"name": "Replace filter", "recurrence_type": "floating", "unit": "months"},
        now=NOW,
    )
    # Pretend it was completed so next_due sits a real interval in the future.
    future = datetime(2026, 9, 24, 12, tzinfo=TZ).isoformat()
    task["next_due"] = future
    merged = m.merge_update(task, {"recurrence_type": "triggered"}, now=NOW)
    assert merged["recurrence_type"] == "triggered"
    assert merged["next_due"] == NOW.isoformat()


def test_build_one_off_task_uses_due_date_and_no_schedule_fields():
    due = datetime(2026, 7, 1, 8, tzinfo=TZ)
    task = m.build_task(
        {
            "name": "Renew passport",
            "recurrence_type": "one-off",
            "due": due.isoformat(),
        },
        now=NOW,
    )
    assert task["recurrence_type"] == "one-off"
    assert task["due"] == due.isoformat()
    assert task["next_due"] == due.isoformat()
    assert task["last_completed"] is None
    for key in ("interval", "unit", "freq", "anchor"):
        assert key not in task


def test_build_one_off_task_defaults_due_to_now():
    # A one-off created without an explicit due date is due today (now).
    task = m.build_task({"name": "Call plumber", "recurrence_type": "one-off"}, now=NOW)
    assert task["due"] == NOW.isoformat()
    assert task["next_due"] == NOW.isoformat()


def test_build_one_off_task_qualifies_naive_due():
    # A naive due (from the panel's datetime-local picker) is qualified with caller tz.
    task = m.build_task(
        {"name": "Pay tax", "recurrence_type": "one-off", "due": "2026-07-01T08:00:00"},
        now=NOW,
    )
    assert task["due"] == datetime(2026, 7, 1, 8, tzinfo=TZ).isoformat()


def test_build_one_off_task_rejects_invalid_due():
    with raises_exactly(m.TaskValidationError, "invalid due datetime: 'not-a-date'"):
        m.build_task(
            {"name": "Bad", "recurrence_type": "one-off", "due": "not-a-date"},
            now=NOW,
        )


def test_merge_update_one_off_change_due_rearms():
    task = m.build_task(
        {"name": "Renew passport", "recurrence_type": "one-off"}, now=NOW
    )
    new_due = datetime(2026, 9, 1, 8, tzinfo=TZ)
    merged = m.merge_update(task, {"due": new_due.isoformat()}, now=NOW)
    assert merged["due"] == new_due.isoformat()
    assert merged["next_due"] == new_due.isoformat()


def test_merge_update_convert_to_one_off_without_due_defaults_to_now():
    # A service caller converting a floating task to one-off may not send a due;
    # it defaults to now (due today) instead of failing validation.
    task = m.build_task(
        {
            "name": "Filter",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
        },
        now=NOW,
    )
    merged = m.merge_update(task, {"recurrence_type": "one-off"}, now=NOW)
    assert merged["recurrence_type"] == "one-off"
    assert merged["due"] == NOW.isoformat()
    assert merged["next_due"] == NOW.isoformat()


def test_merge_update_one_off_edit_notes_keeps_completed_dormant():
    # Editing a completed (dormant) one-off's notes must not re-arm it.
    task = m.build_task(
        {"name": "Renew passport", "recurrence_type": "one-off"}, now=NOW
    )
    task["next_due"] = None  # completed -> dormant
    task["last_completed"] = NOW.isoformat()
    merged = m.merge_update(task, {"notes": "done at the post office"}, now=NOW)
    assert merged["next_due"] is None
    assert merged["notes"] == "done at the post office"


def test_merge_update_completed_one_off_survives_realistic_frontend_payload():
    # Regression: the panel's edit form always sends recurrence_type + due, even for a
    # rename. For a completed (dormant) one-off that must NOT recompute next_due from
    # the past ``due`` (which would resurrect the done task as overdue).
    task = m.build_task(
        {
            "name": "Renew passport",
            "recurrence_type": "one-off",
            "due": NOW.isoformat(),
        },
        now=NOW,
    )
    task["next_due"] = None  # completed -> dormant
    task["last_completed"] = NOW.isoformat()
    merged = m.merge_update(
        task,
        # Same recurrence_type + same due, only the name differs.
        {
            "name": "Renew passport (10yr)",
            "recurrence_type": "one-off",
            "due": NOW.isoformat(),
        },
        now=NOW,
    )
    assert merged["next_due"] is None  # still dormant
    assert merged["name"] == "Renew passport (10yr)"


def test_merge_update_name_edit_preserves_snooze():
    # Regression: a snoozed task's next_due is pushed to the snooze instant. The panel
    # rename payload carries recurrence_type/interval/unit at their unchanged values;
    # that must not recompute next_due and silently cancel the snooze.
    task = m.build_task(
        {
            "name": "Water plants",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "weeks",
        },
        now=NOW,
    )
    snoozed_until = datetime(2026, 6, 20, 9, tzinfo=TZ).isoformat()
    task["next_due"] = snoozed_until  # snoozed
    merged = m.merge_update(
        task,
        {
            "name": "Water the plants",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "weeks",
        },
        now=NOW,
    )
    assert merged["next_due"] == snoozed_until  # snooze preserved
    assert merged["name"] == "Water the plants"


def test_merge_update_genuine_interval_change_still_reschedules():
    # The value-change guard must not suppress a real reschedule.
    task = m.build_task(
        {
            "name": "Water plants",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "weeks",
            "last_completed": NOW.isoformat(),
        },
        now=NOW,
    )
    merged = m.merge_update(task, {"interval": 2, "unit": "weeks"}, now=NOW)
    # 2 weeks from the seeded completion (NOW), not 1.
    assert merged["next_due"] == datetime(2026, 6, 27, 10, tzinfo=TZ).isoformat()


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
    with raises_exactly(m.TaskValidationError, "labels must be a list of label ids"):
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


# ── card_links (appliance links surfaced on the dashboard card) ──────────────


def test_normalize_card_links_dedupes_and_strips():
    out = m.normalize_card_links(
        [
            {"asset_id": "a1", "entry_id": "d1"},
            {"asset_id": " a1 ", "entry_id": " d1 "},  # dupe after strip
            {"asset_id": "a1", "entry_id": ""},  # blank entry dropped
            {"asset_id": "a2", "entry_id": "m9"},
        ]
    )
    assert out == [
        {"asset_id": "a1", "entry_id": "d1"},
        {"asset_id": "a2", "entry_id": "m9"},
    ]


def test_normalize_card_links_defaults_empty():
    assert m.normalize_card_links(None) == []
    assert m.normalize_card_links([]) == []


def test_normalize_card_links_rejects_non_list():
    with raises_exactly(m.TaskValidationError, "card_links must be a list"):
        m.normalize_card_links({"asset_id": "a1", "entry_id": "d1"})


def test_normalize_card_links_rejects_non_object_entry():
    with raises_exactly(
        m.TaskValidationError, "each card_links entry must be an object"
    ):
        m.normalize_card_links(["a1:d1"])


def test_build_task_carries_card_links():
    task = m.build_task(
        {
            "name": "Replace filter",
            "recurrence_type": "floating",
            "interval": 3,
            "unit": "months",
            "card_links": [{"asset_id": "a1", "entry_id": "d1"}],
        },
        now=NOW,
    )
    assert task["card_links"] == [{"asset_id": "a1", "entry_id": "d1"}]


def test_build_task_defaults_card_links_to_empty():
    task = m.build_task(
        {
            "name": "Mow lawn",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "weeks",
        },
        now=NOW,
    )
    assert task["card_links"] == []


def test_merge_update_sets_card_links_when_provided():
    task = m.build_task(
        {
            "name": "Replace filter",
            "recurrence_type": "floating",
            "interval": 3,
            "unit": "months",
        },
        now=NOW,
    )
    updated = m.merge_update(
        task, {"card_links": [{"asset_id": "a1", "entry_id": "m2"}]}, now=NOW
    )
    assert updated["card_links"] == [{"asset_id": "a1", "entry_id": "m2"}]


def test_merge_update_leaves_card_links_untouched_when_absent():
    # A plain rename must not wipe a task's chosen card links.
    task = m.build_task(
        {
            "name": "Replace filter",
            "recurrence_type": "floating",
            "interval": 3,
            "unit": "months",
            "card_links": [{"asset_id": "a1", "entry_id": "d1"}],
        },
        now=NOW,
    )
    updated = m.merge_update(task, {"name": "Replace the filter"}, now=NOW)
    assert updated["card_links"] == [{"asset_id": "a1", "entry_id": "d1"}]


# ── task_chips ───────────────────────────────────────────────────────────────


def test_normalize_task_chips_label_only():
    result = m.normalize_task_chips([{"label": "2x AAA"}])
    assert result == [{"label": "2x AAA"}]


def test_normalize_task_chips_with_icon():
    result = m.normalize_task_chips([{"label": "2x AAA", "icon": "mdi:battery"}])
    assert result == [{"label": "2x AAA", "icon": "mdi:battery"}]


def test_normalize_task_chips_with_url():
    result = m.normalize_task_chips(
        [{"label": "CR2032", "url": "https://example.com/battery"}]
    )
    assert result == [{"label": "CR2032", "url": "https://example.com/battery"}]


def test_normalize_task_chips_full():
    result = m.normalize_task_chips(
        [{"label": "CR2032", "icon": "mdi:battery", "url": "https://example.com"}]
    )
    assert result == [
        {"label": "CR2032", "icon": "mdi:battery", "url": "https://example.com"}
    ]


def test_normalize_task_chips_drops_empty_label():
    result = m.normalize_task_chips([{"label": ""}, {"label": "AAA"}])
    assert result == [{"label": "AAA"}]


def test_normalize_task_chips_defaults_empty():
    assert m.normalize_task_chips(None) == []
    assert m.normalize_task_chips([]) == []
    assert m.normalize_task_chips("") == []


def test_normalize_task_chips_rejects_non_list():
    with pytest.raises(m.TaskValidationError, match="must be a list"):
        m.normalize_task_chips("AAA")


def test_normalize_task_chips_rejects_non_object_entry():
    with pytest.raises(m.TaskValidationError, match="must be an object"):
        m.normalize_task_chips(["AAA"])


def test_normalize_task_chips_rejects_invalid_icon():
    with pytest.raises(m.TaskValidationError, match="mdi:"):
        m.normalize_task_chips([{"label": "AAA", "icon": "battery"}])


def test_normalize_task_chips_rejects_invalid_url():
    with pytest.raises(m.TaskValidationError, match="http"):
        m.normalize_task_chips([{"label": "AAA", "url": "ftp://nope"}])


def test_build_task_carries_task_chips():
    chip = {"label": "2x AAA", "icon": "mdi:battery"}
    task = m.build_task(
        {
            "name": "Replace battery",
            "recurrence_type": "triggered",
            "task_chips": [chip],
        },
        now=NOW,
    )
    assert task["task_chips"] == [chip]


def test_build_task_defaults_task_chips_to_empty():
    task = m.build_task(
        {
            "name": "Mow lawn",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "weeks",
        },
        now=NOW,
    )
    assert task["task_chips"] == []


def test_merge_update_sets_task_chips_when_provided():
    task = m.build_task(
        {"name": "Replace battery", "recurrence_type": "triggered"},
        now=NOW,
    )
    chip = {"label": "CR2032", "icon": "mdi:battery"}
    updated = m.merge_update(task, {"task_chips": [chip]}, now=NOW)
    assert updated["task_chips"] == [chip]


def test_merge_update_leaves_task_chips_untouched_when_absent():
    chip = {"label": "2x AAA", "icon": "mdi:battery"}
    task = m.build_task(
        {
            "name": "Replace battery",
            "recurrence_type": "triggered",
            "task_chips": [chip],
        },
        now=NOW,
    )
    updated = m.merge_update(task, {"name": "Replace the battery"}, now=NOW)
    assert updated["task_chips"] == [chip]


def test_merge_update_clears_task_chips_when_sent_empty():
    chip = {"label": "2x AAA", "icon": "mdi:battery"}
    task = m.build_task(
        {
            "name": "Replace battery",
            "recurrence_type": "triggered",
            "task_chips": [chip],
        },
        now=NOW,
    )
    updated = m.merge_update(task, {"task_chips": []}, now=NOW)
    assert updated["task_chips"] == []


def test_normalize_task_chips_rejects_mdi_empty_suffix():
    with pytest.raises(m.TaskValidationError, match="non-empty name"):
        m.normalize_task_chips([{"label": "x", "icon": "mdi:"}])


# ── tag binding (NFC/RFID completion) ────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("abc ", "abc"),
        (" abc", "abc"),
        ("abc", "abc"),
    ],
)
def test_normalize_tag_id_cases(value, expected):
    assert m.normalize_tag_id(value) == expected


@pytest.mark.parametrize("value", [123, 1.5, True, ["a"], {"id": "a"}])
def test_normalize_tag_id_rejects_non_strings(value):
    # A non-string tag id could never match a scan, so it fails at the edge rather
    # than persisting as a task nobody can ever complete.
    with raises_exactly(m.TaskValidationError, "tag_id must be a string"):
        m.normalize_tag_id(value)


def test_build_task_defaults_to_no_tag():
    task = m.build_task(
        {
            "name": "Furnace filter",
            "recurrence_type": "floating",
            "interval": 3,
            "unit": "months",
        },
        now=NOW,
    )
    assert task["tag_id"] is None
    assert task["require_tag_scan"] is False


def test_build_task_stores_tag_binding():
    task = m.build_task(
        {
            "name": "Furnace filter",
            "recurrence_type": "floating",
            "interval": 3,
            "unit": "months",
            "tag_id": "  furnace-tag ",
            "require_tag_scan": 1,  # truthy, stored as a real bool
        },
        now=NOW,
    )
    assert task["tag_id"] == "furnace-tag"
    assert task["require_tag_scan"] is True


def test_build_task_stores_tag_without_requiring_a_scan():
    task = m.build_task(
        {"name": "Descale", "recurrence_type": "triggered", "tag_id": "kettle"},
        now=NOW,
    )
    assert task["tag_id"] == "kettle"
    assert task["require_tag_scan"] is False


@pytest.mark.parametrize("tag_id", [None, "", "   "])
def test_build_task_rejects_require_tag_scan_without_a_tag(tag_id):
    # Requiring a scan with nothing to scan would lock the task out of every
    # completion surface at birth.
    with raises_exactly(m.TaskValidationError, "require_tag_scan needs a linked tag"):
        m.build_task(
            {
                "name": "Descale",
                "recurrence_type": "triggered",
                "tag_id": tag_id,
                "require_tag_scan": True,
            },
            now=NOW,
        )


def test_merge_update_sets_tag_id():
    task = m.build_task({"name": "Descale", "recurrence_type": "triggered"}, now=NOW)
    updated = m.merge_update(task, {"tag_id": " kettle "}, now=NOW)
    assert updated["tag_id"] == "kettle"
    assert updated["require_tag_scan"] is False


def test_merge_update_clears_tag_id_with_none():
    task = m.build_task(
        {"name": "Descale", "recurrence_type": "triggered", "tag_id": "kettle"},
        now=NOW,
    )
    updated = m.merge_update(task, {"tag_id": None}, now=NOW)
    assert updated["tag_id"] is None


def test_merge_update_sets_require_tag_scan():
    task = m.build_task(
        {"name": "Descale", "recurrence_type": "triggered", "tag_id": "kettle"},
        now=NOW,
    )
    updated = m.merge_update(task, {"require_tag_scan": True}, now=NOW)
    assert updated["require_tag_scan"] is True
    assert updated["tag_id"] == "kettle"


def test_merge_update_rejects_require_tag_scan_without_a_tag():
    task = m.build_task({"name": "Descale", "recurrence_type": "triggered"}, now=NOW)
    with raises_exactly(m.TaskValidationError, "require_tag_scan needs a linked tag"):
        m.merge_update(task, {"require_tag_scan": True}, now=NOW)


def test_merge_update_rejects_clearing_the_tag_while_a_scan_is_required():
    # The flag alone is not the only way into the locked-out state: clearing the tag
    # and leaving the flag standing gets there too, so the check reads the merged task.
    task = m.build_task(
        {
            "name": "Descale",
            "recurrence_type": "triggered",
            "tag_id": "kettle",
            "require_tag_scan": True,
        },
        now=NOW,
    )
    with raises_exactly(m.TaskValidationError, "require_tag_scan needs a linked tag"):
        m.merge_update(task, {"tag_id": None}, now=NOW)


def test_merge_update_swaps_the_tag_while_a_scan_is_required():
    # Re-tagging a scan-only task is legitimate — the replacement sticker is a new id.
    task = m.build_task(
        {
            "name": "Descale",
            "recurrence_type": "triggered",
            "tag_id": "kettle",
            "require_tag_scan": True,
        },
        now=NOW,
    )
    updated = m.merge_update(task, {"tag_id": "kettle-2"}, now=NOW)
    assert updated["tag_id"] == "kettle-2"
    assert updated["require_tag_scan"] is True


def test_merge_update_leaves_the_tag_binding_untouched_when_absent():
    task = m.build_task(
        {
            "name": "Descale",
            "recurrence_type": "triggered",
            "tag_id": "kettle",
            "require_tag_scan": True,
        },
        now=NOW,
    )
    updated = m.merge_update(task, {"name": "Descale the kettle"}, now=NOW)
    assert updated["tag_id"] == "kettle"
    assert updated["require_tag_scan"] is True


def test_merge_update_does_not_add_tag_keys_to_a_task_without_them():
    # A pre-tag task edited without the keys must not gain a phantom binding, which
    # would surface as a spurious "tag_id changed" on the update event.
    task = m.build_task({"name": "Descale", "recurrence_type": "triggered"}, now=NOW)
    del task["tag_id"]
    del task["require_tag_scan"]
    updated = m.merge_update(task, {"name": "Descale it"}, now=NOW)
    assert "tag_id" not in updated
    assert "require_tag_scan" not in updated


def test_merge_update_tag_change_does_not_reschedule():
    # The tag is an identity/attachment field, not a cadence one: re-tagging must
    # leave next_due (and a snooze) exactly where it was.
    task = m.build_task(
        {
            "name": "Furnace filter",
            "recurrence_type": "floating",
            "interval": 3,
            "unit": "months",
        },
        now=NOW,
    )
    task["next_due"] = (NOW + timedelta(days=5)).isoformat()
    updated = m.merge_update(
        task, {"tag_id": "furnace", "require_tag_scan": True}, now=NOW
    )
    assert updated["next_due"] == task["next_due"]


# ── merge_update carry-forward contract ──────────────────────────────────────
# `merge_update` builds a candidate from `updates.get(field, existing.get(field))`
# for every editable field, then re-normalizes the whole thing. That means every
# field a caller *omits* has to survive the round trip untouched — the panel's
# edit form sends a partial payload, and a service caller may send a single key.
#
# Testing one field at a time is what makes this real: a suite that only ever
# merges a full payload cannot tell the carry-forward apart from the update.

# A task with every independently-editable field set to a distinctive value.
FULLY_SET_TASK = {
    "name": "Furnace filter",
    "notes": "Behind the return vent",
    "recurrence_type": "floating",
    "interval": 3,
    "unit": "months",
    "device_id": "dev-furnace",
    "area_id": "area-basement",
    "enabled": True,
    "completion_detail": "required",
    "completion_required_fields": ["note", "cost"],
}

# (field, new value, expected value after normalization, other fields the change
# is *supposed* to move). The last element documents a real coupling rather than
# weakening the carry-forward assertion to accommodate it.
MERGE_UPDATE_CASES = [
    ("name", "Renamed filter", "Renamed filter", {}),
    ("notes", "Now in the loft", "Now in the loft", {}),
    ("interval", 6, 6, {}),
    ("unit", "weeks", "weeks", {}),
    ("device_id", "dev-other", "dev-other", {}),
    ("area_id", "area-attic", "area-attic", {}),
    ("enabled", False, False, {}),
    # Turning capture off makes a mandatory-field list meaningless, so it clears.
    ("completion_detail", "optional", "optional", {"completion_required_fields": []}),
    ("completion_detail", "none", "none", {"completion_required_fields": []}),
]

# Fields whose value must be identical before and after a merge that didn't
# mention them. `next_due` is deliberately absent: changing the cadence is
# *supposed* to move it, and that is covered by its own tests.
CARRIED_FIELDS = [
    "name",
    "notes",
    "recurrence_type",
    "interval",
    "unit",
    "device_id",
    "area_id",
    "enabled",
    "completion_detail",
    "completion_required_fields",
]


def test_merge_update_cases_cover_the_carried_fields():
    # Guard the fixtures above: a new editable field must show up here rather
    # than silently going untested on both the update and the carry-forward side.
    assert {case[0] for case in MERGE_UPDATE_CASES} <= set(CARRIED_FIELDS)
    assert set(FULLY_SET_TASK) - {"recurrence_type"} <= set(CARRIED_FIELDS)


@pytest.mark.parametrize(
    ("field", "value", "expected", "also_changes"), MERGE_UPDATE_CASES
)
def test_merge_update_applies_one_field_and_carries_the_rest(
    field, value, expected, also_changes
):
    task = m.build_task(FULLY_SET_TASK, now=NOW)
    updated = m.merge_update(task, {field: value}, now=NOW)

    assert updated[field] == expected
    for other in CARRIED_FIELDS:
        if other == field:
            continue
        if other in also_changes:
            assert updated[other] == also_changes[other], f"{other} coupling changed"
        else:
            assert updated[other] == task[other], f"{other} was not carried forward"


def test_merge_update_with_an_empty_payload_changes_nothing():
    # The degenerate case, and the cheapest possible proof that every default in
    # the candidate dict reads from `existing`.
    task = m.build_task(FULLY_SET_TASK, now=NOW)
    updated = m.merge_update(task, {}, now=NOW)
    assert updated == task


def test_merge_update_carries_identity_and_history_fields():
    # Fields the candidate dict never mentions still have to survive, because the
    # merge starts from `dict(existing)` rather than building a fresh task.
    task = m.build_task(FULLY_SET_TASK, now=NOW)
    task["completions"] = [{"ts": NOW.isoformat()}]
    task["last_completed"] = NOW.isoformat()
    updated = m.merge_update(task, {"name": "Renamed"}, now=NOW)
    assert updated["id"] == task["id"]
    assert updated["completions"] == task["completions"]
    assert updated["last_completed"] == task["last_completed"]


def test_merge_update_locked_fields_leaves_the_rest_of_the_payload_intact():
    # Stripping locked keys must filter `updates`, not discard it: an update
    # carrying both a locked and an unlocked field has to apply the unlocked one.
    task = m.build_task(
        {
            **FULLY_SET_TASK,
            "managed_by": {
                "integration": "x",
                "display_name": "X",
                "locked_fields": ["name"],
            },
        },
        now=NOW,
    )
    updated = m.merge_update(
        task,
        {"name": "Hacked", "notes": "Legitimate edit", "area_id": "area-new"},
        now=NOW,
    )
    assert updated["name"] == "Furnace filter"
    assert updated["notes"] == "Legitimate edit"
    assert updated["area_id"] == "area-new"


def test_merge_update_with_empty_locked_fields_applies_everything():
    task = m.build_task(
        {
            **FULLY_SET_TASK,
            "managed_by": {
                "integration": "x",
                "display_name": "X",
                "locked_fields": [],
            },
        },
        now=NOW,
    )
    updated = m.merge_update(task, {"name": "Renamed"}, now=NOW)
    assert updated["name"] == "Renamed"


def test_a_blank_last_completed_seed_is_treated_as_absent():
    # "" arrives from a cleared form field. Treating it as a date would fail the
    # ISO parse and reject the whole task.
    task = m.build_task(
        {
            "name": "Furnace filter",
            "recurrence_type": "floating",
            "interval": 3,
            "unit": "months",
            "last_completed": "",
        },
        now=NOW,
    )
    assert task["completions"] == []
    assert task["last_completed"] is None
    assert task["next_due"] == NOW.isoformat()


def test_a_seeded_fixed_task_derives_its_next_occurrence_from_now():
    # A fixed schedule is anchor-driven: the seed only becomes its first history
    # entry, and next_due is the next occurrence after *now* — not after the seed.
    # Proves the caller's clock reaches the recurrence engine.
    task = m.build_task(
        {
            "name": "Bin day",
            "recurrence_type": "fixed",
            "interval": 1,
            "freq": "DAILY",
            "anchor": datetime(2026, 1, 1, 7, tzinfo=TZ).isoformat(),
            "last_completed": datetime(2026, 3, 1, 7, tzinfo=TZ).isoformat(),
        },
        now=NOW,
    )
    next_due = datetime.fromisoformat(task["next_due"])
    assert next_due > NOW
    assert next_due == datetime(2026, 6, 14, 7, tzinfo=TZ)


# ── inferring the recurrence type a creation call did not name ───────────────
# `services.yaml` promises `name` is add_task's only required field, but the old
# floating default needed a `unit` that has no default, so `{name: ...}` alone
# failed validation. These pin each arm of `infer_recurrence_type`, including the
# ones that must NOT change — a bare name becoming one-off is only safe if a call
# that passes a cadence still gets that cadence.


def test_bare_name_builds_a_one_off_due_now():
    task = m.build_task({"name": "Take out bins"}, now=NOW)
    assert task["recurrence_type"] == "one-off"
    # The one-off `due` default supplies the date, so the task is actionable today
    # rather than dormant.
    assert task["next_due"] == NOW.isoformat()
    # A one-off carries no cadence at all — `normalize_fields` returns before the
    # interval/unit branch — so the keys are absent rather than None.
    assert "interval" not in task
    assert "unit" not in task


def test_a_named_cadence_still_builds_a_floating_task():
    # The regression this guards: `{name, interval, unit}` works today and must not
    # quietly become a do-once task that discards the cadence it was handed.
    task = m.build_task(
        {"name": "Fridge filter", "interval": 3, "unit": "months"}, now=NOW
    )
    assert task["recurrence_type"] == "floating"
    assert task["interval"] == 3
    assert task["unit"] == "months"
    assert task["next_due"] == NOW.isoformat()


def test_a_unit_alone_still_builds_a_floating_task():
    task = m.build_task({"name": "Water filter", "unit": "weeks"}, now=NOW)
    assert task["recurrence_type"] == "floating"
    assert task["unit"] == "weeks"
    # The interval default (1) applies, so "unit only" means every one of them.
    assert task["interval"] == 1


def test_an_anchor_and_freq_still_build_a_fixed_task():
    task = m.build_task(
        {"name": "Rent", "freq": "MONTHLY", "anchor": "2026-07-01T09:00:00"},
        now=NOW,
    )
    assert task["recurrence_type"] == "fixed"
    assert task["freq"] == "MONTHLY"
    assert task["anchor"] == datetime(2026, 7, 1, 9, tzinfo=TZ).isoformat()


def test_a_partial_cadence_fails_naming_the_missing_field():
    # An interval with no unit is a cadence the caller asked for and under-specified.
    # Inferring one-off would silently drop the interval; say what is missing instead.
    with raises_exactly(m.TaskValidationError, "invalid unit: None"):
        m.build_task({"name": "Half a schedule", "interval": 3}, now=NOW)


def test_an_explicit_recurrence_type_always_wins():
    # Inference only fills a gap; it never overrides what the caller said. A caller
    # who says "floating" and forgets the unit still gets the validation error.
    with raises_exactly(m.TaskValidationError, "invalid unit: None"):
        m.build_task(
            {"name": "Explicitly floating", "recurrence_type": "floating"}, now=NOW
        )
    task = m.build_task(
        {"name": "Explicitly triggered", "recurrence_type": "triggered"}, now=NOW
    )
    assert task["recurrence_type"] == "triggered"
    # And it took the triggered path, not the one-off one: an inferred one-off would
    # have been handed a `due` (defaulted to now), which a triggered task never has.
    assert "due" not in task


def test_inference_does_not_reach_updates():
    # `merge_update` always carries the existing type forward, so an edit that omits
    # `recurrence_type` keeps the task's own kind rather than being re-inferred as a
    # one-off from an updates dict that names no schedule field.
    task = m.build_task(
        {
            "name": "Fridge filter",
            "recurrence_type": "floating",
            "interval": 3,
            "unit": "months",
        },
        now=NOW,
    )
    updated = m.merge_update(task, {"name": "Renamed"}, now=NOW)
    assert updated["recurrence_type"] == "floating"
    assert updated["interval"] == 3
    assert updated["unit"] == "months"
