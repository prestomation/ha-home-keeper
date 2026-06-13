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


def test_build_task_rejects_missing_name():
    with pytest.raises(m.TaskValidationError):
        m.build_task({"recurrence_type": "floating", "interval": 1, "unit": "days"}, now=NOW)


def test_build_task_rejects_bad_unit():
    with pytest.raises(m.TaskValidationError):
        m.build_task({"name": "x", "recurrence_type": "floating", "interval": 1, "unit": "lightyears"}, now=NOW)


def test_build_task_rejects_bad_interval():
    with pytest.raises(m.TaskValidationError):
        m.build_task({"name": "x", "recurrence_type": "floating", "interval": 0, "unit": "days"}, now=NOW)


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
