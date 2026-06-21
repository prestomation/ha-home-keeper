"""Unit tests for sensor-based task construction / validation in models."""

from datetime import datetime, timedelta, timezone

import hk_models as m
import pytest

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
    with pytest.raises(m.TaskValidationError):
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
