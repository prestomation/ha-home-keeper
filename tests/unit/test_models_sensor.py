"""Unit tests for sensor-based task construction / validation in models."""

from datetime import datetime, timedelta, timezone

import hk_models as m
import pytest
from asserts import raises_exactly

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)


def test_build_usage_sensor_task_starts_dormant():
    task = m.build_task(
        {
            "name": "Oil change",
            "recurrence_type": "sensor",
            "sensor": {
                "entity_id": "sensor.odometer",
                "mode": "usage",
                "target": 15000,
            },
        },
        now=NOW,
    )
    assert task["recurrence_type"] == "sensor"
    # Born dormant — the watcher arms it once the meter is past target.
    assert task["next_due"] is None
    assert task["sensor"]["target"] == 15000
    # No baseline yet (the watcher stamps it from the first live reading).
    assert "baseline" not in task["sensor"]


def test_build_threshold_sensor_task():
    task = m.build_task(
        {
            "name": "Replace filter",
            "recurrence_type": "sensor",
            "sensor": {
                "entity_id": "sensor.airflow",
                "mode": "threshold",
                "comparison": "<",
                "value": 60,
                "for_seconds": 120,
            },
        },
        now=NOW,
    )
    assert task["next_due"] is None
    assert task["sensor"] == {
        "entity_id": "sensor.airflow",
        "mode": "threshold",
        "comparison": "<",
        "value": 60.0,
        "for_seconds": 120,
    }


def test_usage_carries_baseline_and_attribute():
    cfg = m.normalize_sensor(
        {
            "entity_id": "climate.lr",
            "mode": "usage",
            "attribute": "current_temperature",
            "target": "500",
            "baseline": "41.5",
        }
    )
    assert cfg["attribute"] == "current_temperature"
    assert cfg["target"] == 500.0
    assert cfg["baseline"] == 41.5


@pytest.mark.parametrize(
    "sensor",
    [
        {},  # missing everything
        {"mode": "usage", "target": 10},  # missing entity_id
        {"entity_id": "sensor.x", "mode": "bogus"},  # bad mode
        {"entity_id": "sensor.x", "mode": "usage"},  # missing target
        {"entity_id": "sensor.x", "mode": "usage", "target": 0},  # non-positive
        {"entity_id": "sensor.x", "mode": "usage", "target": "abc"},  # non-numeric
        {"entity_id": "sensor.x", "mode": "threshold", "value": 5},  # missing cmp
        {"entity_id": "sensor.x", "mode": "threshold", "comparison": "≥", "value": 5},
        {"entity_id": "sensor.x", "mode": "threshold", "comparison": ">"},  # no value
        {
            "entity_id": "sensor.x",
            "mode": "threshold",
            "comparison": ">",
            "value": 5,
            "for_seconds": -1,
        },
    ],
)
def test_invalid_sensor_config_rejected(sensor):
    with pytest.raises(m.TaskValidationError):
        m.build_task(
            {"name": "T", "recurrence_type": "sensor", "sensor": sensor}, now=NOW
        )


def test_missing_sensor_block_rejected():
    with raises_exactly(
        m.TaskValidationError, "a sensor task requires a sensor configuration"
    ):
        m.build_task({"name": "T", "recurrence_type": "sensor"}, now=NOW)


def test_update_sensor_target_does_not_rearm():
    task = m.build_task(
        {
            "name": "Oil",
            "recurrence_type": "sensor",
            "sensor": {"entity_id": "sensor.odo", "mode": "usage", "target": 15000},
        },
        now=NOW,
    )
    # Simulate the watcher having armed it and stamped a baseline.
    task["next_due"] = NOW.isoformat()
    task["sensor"]["baseline"] = 1000
    updated = m.merge_update(
        task,
        {"sensor": {"entity_id": "sensor.odo", "mode": "usage", "target": 20000}},
        now=NOW + timedelta(days=1),
    )
    # Editing the binding must not recompute/clear next_due (still armed).
    assert updated["next_due"] == NOW.isoformat()
    assert updated["sensor"]["target"] == 20000
    # The accumulated meter baseline must survive an edit that doesn't carry one
    # (the panel rebuilds the binding from form fields, omitting baseline).
    assert updated["sensor"]["baseline"] == 1000


def test_update_usage_task_preserves_baseline_only_for_same_entity():
    task = m.build_task(
        {
            "name": "Oil",
            "recurrence_type": "sensor",
            "sensor": {"entity_id": "sensor.odo", "mode": "usage", "target": 15000},
        },
        now=NOW,
    )
    task["sensor"]["baseline"] = 41000
    # Re-pointing at a different entity (a genuinely new meter) must NOT carry the old
    # baseline over — it re-anchors to the new meter's first reading (None for now).
    rebound = m.merge_update(
        task,
        {"sensor": {"entity_id": "sensor.other_odo", "mode": "usage", "target": 15000}},
        now=NOW,
    )
    assert "baseline" not in rebound["sensor"]
    # An explicit baseline in the update is respected over the old one.
    explicit = m.merge_update(
        task,
        {
            "sensor": {
                "entity_id": "sensor.odo",
                "mode": "usage",
                "target": 15000,
                "baseline": 50000,
            }
        },
        now=NOW,
    )
    assert explicit["sensor"]["baseline"] == 50000


def test_convert_floating_to_sensor():
    task = m.build_task(
        {"name": "T", "recurrence_type": "floating", "interval": 3, "unit": "months"},
        now=NOW,
    )
    updated = m.merge_update(
        task,
        {
            "recurrence_type": "sensor",
            "sensor": {
                "entity_id": "sensor.h",
                "mode": "threshold",
                "comparison": ">",
                "value": 90,
            },
        },
        now=NOW,
    )
    assert updated["recurrence_type"] == "sensor"
    assert updated["sensor"]["comparison"] == ">"
    # Converting to a sensor task leaves it dormant (no schedule-driven due date).
    assert updated["next_due"] is None


# ── time backstop / unit label ───────────────────────────────────────────────
def test_usage_accepts_time_backstop_and_unit_label():
    cfg = m.normalize_sensor(
        {
            "entity_id": "sensor.printer_hours",
            "mode": "usage",
            "target": 300,
            "unit": "h",
            "also_every": {"interval": "6", "unit": "months"},
        }
    )
    assert cfg["unit"] == "h"
    assert cfg["also_every"] == {"interval": 6, "unit": "months"}
    # Combinator defaults to "whichever comes first" — the common service interval.
    assert cfg["combinator"] == "any"


def test_usage_backstop_combinator_all_is_kept():
    cfg = m.normalize_sensor(
        {
            "entity_id": "sensor.engine_hours",
            "mode": "usage",
            "target": 100,
            "also_every": {"interval": 1, "unit": "months"},
            "combinator": "all",
        }
    )
    assert cfg["combinator"] == "all"


def test_backstop_absent_leaves_no_keys():
    cfg = m.normalize_sensor(
        {"entity_id": "sensor.x", "mode": "usage", "target": 10, "also_every": None}
    )
    assert "also_every" not in cfg
    assert "combinator" not in cfg


@pytest.mark.parametrize(
    "sensor",
    [
        # Backstop shape errors.
        {"entity_id": "s.x", "mode": "usage", "target": 1, "also_every": "6 months"},
        {"entity_id": "s.x", "mode": "usage", "target": 1, "also_every": {"unit": "x"}},
        {
            "entity_id": "s.x",
            "mode": "usage",
            "target": 1,
            "also_every": {"interval": 0, "unit": "months"},
        },
        {
            "entity_id": "s.x",
            "mode": "usage",
            "target": 1,
            "also_every": {"interval": 1, "unit": "months"},
            "combinator": "either",
        },
        # A unit label longer than the cap.
        {"entity_id": "s.x", "mode": "usage", "target": 1, "unit": "x" * 17},
        # Usage-only fields on a threshold binding.
        {
            "entity_id": "s.x",
            "mode": "threshold",
            "comparison": ">",
            "value": 1,
            "also_every": {"interval": 1, "unit": "months"},
        },
        {
            "entity_id": "s.x",
            "mode": "threshold",
            "comparison": ">",
            "value": 1,
            "unit": "h",
        },
    ],
)
def test_invalid_backstop_rejected(sensor):
    with pytest.raises(m.TaskValidationError):
        m.normalize_sensor(sensor)


def test_adding_a_backstop_preserves_the_accumulated_baseline():
    task = m.build_task(
        {
            "name": "Nozzle",
            "recurrence_type": "sensor",
            "sensor": {"entity_id": "sensor.hrs", "mode": "usage", "target": 300},
        },
        now=NOW,
    )
    task["sensor"]["baseline"] = 660
    updated = m.merge_update(
        task,
        {
            "sensor": {
                "entity_id": "sensor.hrs",
                "mode": "usage",
                "target": 300,
                "also_every": {"interval": 6, "unit": "months"},
            }
        },
        now=NOW + timedelta(days=1),
    )
    # Adding the calendar half must not zero the hours already accumulated.
    assert updated["sensor"]["baseline"] == 660
    assert updated["sensor"]["also_every"] == {"interval": 6, "unit": "months"}


def test_sensor_task_accepts_a_seeded_last_completed_without_arming():
    task = m.build_task(
        {
            "name": "Nozzle",
            "recurrence_type": "sensor",
            "sensor": {
                "entity_id": "sensor.hrs",
                "mode": "usage",
                "target": 300,
                "also_every": {"interval": 6, "unit": "months"},
            },
            "last_completed": NOW - timedelta(days=90),
        },
        now=NOW,
    )
    # The seed anchors the backstop clock (and shows in history) but must not arm it —
    # only the watcher does that, once a half of the condition is actually met.
    assert task["next_due"] is None
    assert task["last_completed"] is not None
    assert len(task["completions"]) == 1
