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
