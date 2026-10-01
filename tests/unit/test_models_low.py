"""Low-severity review findings in the pure task model (group B).

Each test names the finding it pins.
"""

from datetime import datetime, timedelta, timezone

import hk_models as m
import pytest
from asserts import raises_exactly

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)


def test_b05_6_infinite_interval_is_a_validation_error():
    with raises_exactly(m.TaskValidationError, "interval must be a valid integer"):
        m.build_task(
            {
                "name": "Filter",
                "recurrence_type": "floating",
                "interval": float("inf"),
                "unit": "days",
            },
            now=NOW,
        )


@pytest.mark.parametrize(
    ("sensor", "message"),
    [
        (
            {
                "mode": "threshold",
                "entity_id": "sensor.salt",
                "comparison": "<=",
                "value": 10,
                "for_seconds": float("inf"),
            },
            "sensor.for_seconds must be an integer",
        ),
        (
            {
                "mode": "usage",
                "entity_id": "sensor.hours",
                "target": 300,
                "also_every": {"interval": float("inf"), "unit": "days"},
            },
            "sensor.also_every.interval must be a valid integer",
        ),
    ],
)
def test_b05_6_infinite_sensor_integer_is_a_validation_error(sensor, message):
    with raises_exactly(m.TaskValidationError, message):
        m.normalize_sensor(sensor)


# ── B08-5: a usage baseline is carried only for the same meter ──────────────


def _usage_task(**sensor):
    task = m.build_task(
        {
            "name": "Robo",
            "recurrence_type": "sensor",
            "sensor": {
                "entity_id": "vacuum.robo",
                "attribute": "cleaning_time",
                "mode": "usage",
                "target": 5000,
                **sensor,
            },
        },
        now=NOW,
    )
    task["sensor"]["baseline"] = 1200.0
    return task


def _rebind(**over):
    return {
        "entity_id": "vacuum.robo",
        "attribute": "cleaning_time",
        "mode": "usage",
        "target": 5000,
        **over,
    }


def test_b08_5_the_same_meter_keeps_its_baseline():
    out = m.merge_update(_usage_task(), {"sensor": _rebind(target=6000)}, now=NOW)
    assert out["sensor"]["baseline"] == 1200.0


def test_b08_5_another_attribute_does_not_carry_the_baseline():
    out = m.merge_update(
        _usage_task(), {"sensor": _rebind(attribute="total_cleaned_area")}, now=NOW
    )
    assert "baseline" not in out["sensor"]


def test_b08_5_another_entity_does_not_carry_the_baseline():
    out = m.merge_update(
        _usage_task(), {"sensor": _rebind(entity_id="vacuum.other")}, now=NOW
    )
    assert "baseline" not in out["sensor"]


def test_b08_5_an_explicit_baseline_wins():
    out = m.merge_update(
        _usage_task(),
        {"sensor": _rebind(attribute="total_cleaned_area", baseline=10)},
        now=NOW,
    )
    assert out["sensor"]["baseline"] == 10.0


def test_b08_5_a_threshold_binding_does_not_give_a_baseline():
    task = _usage_task()
    task["sensor"] = {
        "entity_id": "vacuum.robo",
        "attribute": "cleaning_time",
        "mode": "threshold",
        "comparison": "<=",
        "value": 10,
        "baseline": 1200.0,
    }
    out = m.merge_update(task, {"sensor": _rebind()}, now=NOW)
    assert "baseline" not in out["sensor"]


def test_b08_5_a_stale_block_from_an_earlier_type_is_not_carried():
    task = _usage_task()
    floating = m.merge_update(
        task,
        {"recurrence_type": "floating", "interval": 1, "unit": "days"},
        now=NOW,
    )
    # The type change removes the stale block (B08-7).
    assert "sensor" not in floating
    # A stored task from an older release that still has one does not give its
    # baseline.
    floating["sensor"] = dict(task["sensor"])
    back = m.merge_update(
        floating, {"recurrence_type": "sensor", "sensor": _rebind()}, now=NOW
    )
    assert "baseline" not in back["sensor"]
    assert back["next_due"] is None


# ── B08-7: a type change drops the old type's schedule fields ───────────────


def _one_off():
    return m.build_task(
        {
            "name": "Paint",
            "recurrence_type": "one-off",
            "due": "2026-01-10T09:00:00-04:00",
        },
        now=NOW,
    )


def test_b08_7_converting_away_from_one_off_drops_due():
    out = m.merge_update(
        _one_off(),
        {"recurrence_type": "floating", "interval": 2, "unit": "days"},
        now=NOW,
    )
    assert "due" not in out
    assert out["interval"] == 2
    assert out["unit"] == "days"


def test_b08_7_converting_back_to_one_off_defaults_to_now():
    task = _one_off()
    floating = m.merge_update(
        task, {"recurrence_type": "floating", "interval": 2, "unit": "days"}, now=NOW
    )
    # A task stored by an older release keeps the stale due date.
    floating["due"] = task["due"]
    back = m.merge_update(floating, {"recurrence_type": "one-off"}, now=NOW)
    assert back["due"] == NOW.isoformat()
    assert back["next_due"] == NOW.isoformat()
    assert "interval" not in back
    assert "unit" not in back


def test_b08_7_a_due_in_the_update_is_used():
    floating = m.build_task({"name": "x", "interval": 2, "unit": "days"}, now=NOW)
    out = m.merge_update(
        floating,
        {"recurrence_type": "one-off", "due": "2026-07-01T09:00:00-04:00"},
        now=NOW,
    )
    assert out["due"] == "2026-07-01T09:00:00-04:00"


def test_b08_7_an_edit_without_a_type_change_keeps_the_fields():
    task = _one_off()
    out = m.merge_update(task, {"name": "Paint the fence"}, now=NOW)
    assert out["due"] == task["due"]
    # Sending the same type is not a change either.
    out = m.merge_update(task, {"recurrence_type": "one-off"}, now=NOW)
    assert out["due"] == task["due"]


def test_b08_7_converting_fixed_to_floating_drops_anchor_and_freq():
    fixed = m.build_task(
        {
            "name": "Bins",
            "recurrence_type": "fixed",
            "interval": 1,
            "freq": "WEEKLY",
            "anchor": "2026-06-01T08:00:00-04:00",
        },
        now=NOW,
    )
    out = m.merge_update(
        fixed, {"recurrence_type": "floating", "unit": "weeks"}, now=NOW
    )
    assert "anchor" not in out
    assert "freq" not in out
    assert out["interval"] == 1
