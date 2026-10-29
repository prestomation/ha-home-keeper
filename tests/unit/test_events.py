"""Unit tests for the shared completion-event payload builder.

This is the single source of the ``home_keeper_task_completed`` payload, used by
both the real store and the test fake, so the contract can't drift.
"""

from datetime import UTC, datetime, timedelta, timezone

import hk_events as ev
import pytest

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
        "task_chips": [],
        "tag_id": None,
        "active_season": None,
        "entity_id": None,
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
    assert data["task_chips"] == []  # defaults to empty for a chip-less task
    assert data["tag_id"] is None  # defaults to None for a task with no tag linked
    assert data["changed_fields"] == ["name"]


def test_spine_carries_the_linked_tag():
    # A listener mirroring completions needs to know which tag a task answers to —
    # e.g. to tell a scan-driven completion apart from a tap on the same task.
    data = ev.task_event_data({"id": "t1", "tag_id": "coffee"})
    assert data["tag_id"] == "coffee"


def test_uncompleted_spine_carries_ts_and_origin():
    """The undo payload names the completion it removed, and who removed it.

    Without ``ts`` a listener can't tell which mirrored record to drop, and without
    ``origin`` it can't ignore the echo of an undo it initiated itself.
    """
    task = {
        "id": "t1",
        "name": "Medicine",
        "source": {"pawsistant": {"schedule_id": "s1"}},
    }
    data = ev.task_event_data(
        task, extra={"ts": WHEN.isoformat(), "origin": "pawsistant"}
    )
    assert data["ts"] == WHEN.isoformat()
    assert data["origin"] == "pawsistant"
    assert data["source"] == {"pawsistant": {"schedule_id": "s1"}}
    # No completion-only fields leak in — undo is not a completion.
    assert "completed_at" not in data


def test_asset_event_data_shape():
    data = ev.asset_event_data(
        {"id": "a1", "name": "Furnace", "device_id": "dev1"},
        extra={"changed_fields": ["model"]},
    )
    assert data == {
        "asset_id": "a1",
        "asset_name": "Furnace",
        "device_id": "dev1",
        "source": None,
        "managed_by": None,
        "changed_fields": ["model"],
    }
    # Tolerates a missing name.
    assert ev.asset_event_data({"id": "a2"})["asset_name"] == ""


def test_asset_event_data_echoes_ownership():
    # An integration that owns an appliance reads its own namespace back off the
    # event, instead of calling list_assets to find out whether it still owns it.
    managed_by = {"integration": "battery_notes", "display_name": "Battery Notes"}
    source = {"battery_notes": {"role": "battery_stock"}}
    data = ev.asset_event_data(
        {"id": "a1", "name": "Batteries", "source": source, "managed_by": managed_by}
    )
    assert data["source"] == source
    assert data["managed_by"] == managed_by


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
        "unit": "",
        "asset_id": "a1",
        "asset_name": "Furnace",
        "device_id": "dev1",
        "part_id": "p1",
        "part_name": "Filter",
        "part_number": "FX-1",
        "vendor": "Acme",
        "stock": 1,
        "reorder_at": 1,
        "source": None,
        "managed_by": None,
    }


def test_stock_payload_names_the_owner_of_the_appliance():
    # An integration that manages an appliance tells its own stock events from the
    # rest by these two, the same way it reads its asset events.
    source = {"pawsistant": {"role": "supplies"}}
    managed_by = {"integration": "pawsistant", "display_name": "Pawsistant"}
    asset = {
        "id": "a1",
        "name": "Pet supplies",
        "source": source,
        "managed_by": managed_by,
    }
    data = ev.stock_event_data(asset, {"id": "p1", "name": "Rolls", "stock": 1})
    assert data["source"] == source
    assert data["managed_by"] == managed_by


def test_low_stock_payload_tolerates_missing_fields():
    data = ev.low_stock_event_data({}, {})
    assert data["asset_name"] == "" and data["part_name"] == ""
    assert data["device_id"] is None and data["stock"] is None
    assert data["unit"] == ""


def test_low_stock_payload_carries_fractional_stock_and_its_unit():
    # A part measured in millilitres reports both the fraction and the unit, so an
    # automation can say "250 ml left" without looking the part up.
    data = ev.low_stock_event_data(
        {"id": "a1"},
        {"id": "p1", "stock": 250.5, "reorder_at": 500, "stock_unit": "ml"},
    )
    assert data["stock"] == 250.5
    assert data["reorder_at"] == 500
    assert data["unit"] == "ml"


# ── declarative-companion spec events ───────────────────────────────────────
def test_declarative_companion_event_carries_identity_and_preset():
    data = ev.declarative_companion_event_data(
        {
            "id": "spec-1",
            "name": "Device Pulse",
            "enabled": True,
            "preset_id": "device_pulse",
        }
    )
    assert data == {
        "spec_id": "spec-1",
        "name": "Device Pulse",
        "enabled": True,
        "preset_id": "device_pulse",
    }


def test_declarative_companion_event_omits_match_count_by_default():
    data = ev.declarative_companion_event_data(
        {"id": "spec-1", "name": "x", "enabled": True, "preset_id": None}
    )
    assert "match_count" not in data


def test_declarative_companion_event_carries_match_count_when_set():
    data = ev.declarative_companion_event_data(
        {"id": "spec-1", "name": "x", "enabled": True, "preset_id": None},
        match_count=7,
    )
    assert data["match_count"] == 7


def test_declarative_companion_event_tolerates_missing_enabled():
    data = ev.declarative_companion_event_data(
        {"id": "spec-1", "name": "x", "preset_id": None}
    )
    # Defaults to enabled=True so an automation never sees ``None`` for a bool.
    assert data["enabled"] is True


def test_declarative_companion_event_reads_enabled_from_the_spec():
    # A stored ``enabled=False`` must survive to the event; the paired
    # ``missing`` test above catches the mirror mutation that hard-codes True.
    # Together they prove ``spec.get("enabled", True)`` reads the key rather
    # than always taking the default.
    data = ev.declarative_companion_event_data(
        {"id": "spec-1", "name": "x", "preset_id": None, "enabled": False}
    )
    assert data["enabled"] is False


# ── Logbook rows ─────────────────────────────────────────────────────────────


def test_spine_carries_the_to_do_entity_id():
    assert ev.task_event_data({})["entity_id"] is None
    data = ev.task_event_data({"id": "t1"}, entity_id="todo.home_keeper_tasks")
    assert data["entity_id"] == "todo.home_keeper_tasks"


def test_completion_event_passes_the_entity_id_on():
    data = ev.completion_event_data({}, WHEN, None, entity_id="todo.tasks")
    assert data["entity_id"] == "todo.tasks"


def test_every_logbook_event_has_an_icon():
    assert all(icon.startswith("mdi:") for icon in ev.LOGBOOK_ICONS.values())


def test_created_updated_and_deleted_get_no_row():
    assert "home_keeper_task_created" not in ev.LOGBOOK_EVENTS
    assert "home_keeper_task_updated" not in ev.LOGBOOK_EVENTS
    assert "home_keeper_task_deleted" not in ev.LOGBOOK_EVENTS


@pytest.mark.parametrize(
    ("event", "data", "message"),
    [
        ("home_keeper_task_completed", {}, "was completed"),
        ("home_keeper_task_completed", {"who": "Ann"}, "was completed by Ann"),
        (
            "home_keeper_task_completed",
            {"who": "Ann", "origin": "home_keeper_tag_scan"},
            "was completed by Ann with a tag scan",
        ),
        (
            "home_keeper_task_completed",
            {"origin": "home_keeper_tag_scan"},
            "was completed with a tag scan",
        ),
        (
            "home_keeper_task_completed",
            {"who": "Ann", "origin": "home_keeper_problem_sensor_sync"},
            "was completed by its sensor",
        ),
        (
            "home_keeper_task_completed",
            {"origin": "home_keeper_sensor_recover"},
            "was completed by its sensor",
        ),
        ("home_keeper_task_completed", {"origin": "pawsistant"}, "was completed"),
        ("home_keeper_task_uncompleted", {}, "had a completion removed"),
        ("home_keeper_task_skipped", {}, "was skipped"),
        (
            "home_keeper_task_snoozed",
            {"snoozed_until": "2026-10-20T09:00:00-04:00"},
            "was snoozed until 2026-10-20",
        ),
        ("home_keeper_task_snoozed", {}, "was snoozed until ?"),
        ("home_keeper_task_overdue", {"days_overdue": 3}, "became overdue"),
        (
            "home_keeper_task_overdue_resolved",
            {"days_overdue": 3},
            "is no longer overdue",
        ),
        ("home_keeper_task_due_soon", {"due_in_hours": 12.0}, "is due in 12 hours"),
        ("home_keeper_task_due_soon", {"due_in_hours": 2.5}, "is due in 2.5 hours"),
        ("home_keeper_task_due_soon", {"due_in_hours": 1.0}, "is due in 1 hour"),
        ("home_keeper_task_due_soon", {"due_in_hours": 0.5}, "is due in 0.5 hours"),
        ("home_keeper_task_due_soon", {}, "is due in 0 hours"),
        ("home_keeper_task_triggered", {}, "became due"),
        ("home_keeper_task_due_today_set", {}, "was set to due today"),
        (
            "home_keeper_task_occurrence_moved",
            {"occurrence": "2026-11-01T08:00:00-04:00", "to": "2026-11-03"},
            "has its occurrence on 2026-11-01 moved to 2026-11-03",
        ),
        (
            "home_keeper_task_occurrence_moved",
            {"occurrence": "2026-11-01", "to": "2026-11-01T08:00:00-04:00"},
            "has its occurrence on 2026-11-01 back on its date",
        ),
        ("home_keeper_other", {}, "home_keeper_other"),
    ],
)
def test_logbook_message(event: str, data: dict, message: str):
    assert ev.logbook_message(event, data) == message


def test_spine_copies_enabled_chips_and_season_from_the_task():
    season = [{"start": "04-01", "end": "09-30"}]
    chips = [{"label": "Pet"}]
    data = ev.task_event_data(
        {"enabled": False, "task_chips": chips, "active_season": season}
    )
    assert data["enabled"] is False
    assert data["task_chips"] == chips
    assert data["active_season"] == season


# ── The completion day in the logbook row ────────────────────────────────────

# 2026-10-26 09:00 in UTC-4, the day the event fires.
FIRED = datetime(2026, 10, 26, 9, tzinfo=TZ).timestamp()


@pytest.mark.parametrize(
    ("event", "data", "message"),
    [
        (
            "home_keeper_task_completed",
            {"completed_at": "2026-10-26T08:00:00-04:00"},
            "was completed",
        ),
        (
            "home_keeper_task_completed",
            {"completed_at": "2026-10-20T08:00:00-04:00", "who": "Ann"},
            "was completed by Ann on 2026-10-20",
        ),
        (
            "home_keeper_task_completed",
            {
                "completed_at": "2026-10-20T08:00:00-04:00",
                "origin": "home_keeper_tag_scan",
            },
            "was completed on 2026-10-20 with a tag scan",
        ),
        (
            "home_keeper_task_completed",
            {
                "completed_at": "2026-10-20T08:00:00-04:00",
                "origin": "home_keeper_sensor_recover",
            },
            "was completed by its sensor on 2026-10-20",
        ),
        # 02:00 UTC on the 27th is still the 26th in UTC-4.
        (
            "home_keeper_task_completed",
            {"completed_at": "2026-10-27T02:00:00+00:00"},
            "was completed",
        ),
        # 23:30 on the 25th in UTC-4 is the 26th in UTC, but the row uses UTC-4.
        (
            "home_keeper_task_completed",
            {"completed_at": "2026-10-25T23:30:00-04:00"},
            "was completed on 2026-10-25",
        ),
        ("home_keeper_task_completed", {"completed_at": "not a date"}, "was completed"),
        (
            "home_keeper_task_uncompleted",
            {"ts": "2026-10-26T07:00:00-04:00"},
            "had a completion removed",
        ),
        (
            "home_keeper_task_uncompleted",
            {"ts": "2026-10-20T07:00:00-04:00"},
            "had its completion on 2026-10-20 removed",
        ),
        ("home_keeper_task_uncompleted", {"ts": None}, "had a completion removed"),
        # 02:00 UTC on the 27th, but the 26th in UTC-4.
        (
            "home_keeper_task_uncompleted",
            {"ts": "2026-10-26T22:00:00-04:00"},
            "had a completion removed",
        ),
        (
            "home_keeper_task_skipped",
            {"ts": "2026-10-20T07:00:00-04:00"},
            "was skipped",
        ),
    ],
)
def test_logbook_message_names_a_completion_on_another_day(
    event: str, data: dict, message: str
):
    assert ev.logbook_message(event, data, fired_ts=FIRED, tz=TZ) == message


def test_logbook_message_names_the_day_when_the_fire_time_is_not_known():
    data = {"completed_at": "2026-10-26T08:00:00-04:00"}
    message = ev.logbook_message("home_keeper_task_completed", data, tz=TZ)
    assert message == "was completed on 2026-10-26"


def test_the_fire_day_is_in_the_given_time_zone():
    """01:00 UTC on the 27th is 21:00 on the 26th in UTC-4, the completion day."""
    fired = datetime(2026, 10, 27, 1, tzinfo=UTC).timestamp()
    data = {"completed_at": "2026-10-26T20:00:00-04:00"}
    message = ev.logbook_message(
        "home_keeper_task_completed", data, fired_ts=fired, tz=TZ
    )
    assert message == "was completed"


@pytest.mark.parametrize(
    ("event", "data", "message"),
    [
        # The panel sends a UTC instant. 01:00 UTC on the 21st is the 20th in UTC-4.
        (
            "home_keeper_task_snoozed",
            {"snoozed_until": "2026-10-21T01:00:00+00:00"},
            "was snoozed until 2026-10-20",
        ),
        (
            "home_keeper_task_snoozed",
            {"snoozed_until": "2026-10-21"},
            "was snoozed until 2026-10-21",
        ),
        (
            "home_keeper_task_snoozed",
            {"snoozed_until": "not a date"},
            "was snoozed until ?",
        ),
        (
            "home_keeper_task_occurrence_moved",
            {
                "occurrence": "2026-11-01T08:00:00-04:00",
                "to": "2026-11-04T01:00:00+00:00",
            },
            "has its occurrence on 2026-11-01 moved to 2026-11-03",
        ),
        # An undo: the occurrence is local and the target is the same day in UTC.
        (
            "home_keeper_task_occurrence_moved",
            {
                "occurrence": "2026-11-01T20:00:00-04:00",
                "to": "2026-11-02T00:00:00+00:00",
            },
            "has its occurrence on 2026-11-01 back on its date",
        ),
    ],
)
def test_logbook_message_names_the_local_day(event: str, data: dict, message: str):
    assert ev.logbook_message(event, data, fired_ts=FIRED, tz=TZ) == message
