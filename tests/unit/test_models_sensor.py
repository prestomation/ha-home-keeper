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


# ── state mode (binary sensors) ──────────────────────────────────────────────
def test_build_state_sensor_task():
    task = m.build_task(
        {
            "name": "Fill the vacuum's water tank",
            "recurrence_type": "sensor",
            "sensor": {
                "entity_id": "binary_sensor.rosie_water_tank_low",
                "mode": "state",
                "state": "on",
                "for_seconds": 60,
            },
        },
        now=NOW,
    )
    # Born dormant like every sensor task — the watcher arms it on the crossing.
    assert task["next_due"] is None
    assert task["sensor"] == {
        "entity_id": "binary_sensor.rosie_water_tank_low",
        "mode": "state",
        "state": "on",
        "for_seconds": 60,
    }


def test_state_keeps_only_the_keys_it_was_given():
    # No hold, no clear_on_recover -> neither key is stored, so a binding round-trips
    # to exactly what the user configured.
    assert m.normalize_sensor(
        {"entity_id": "binary_sensor.x", "mode": "state", "state": "on"}
    ) == {"entity_id": "binary_sensor.x", "mode": "state", "state": "on"}


def test_state_is_trimmed_and_accepts_any_state_string():
    cfg = m.normalize_sensor(
        {"entity_id": "vacuum.rosie", "mode": "state", "state": "  docked  "}
    )
    assert cfg["state"] == "docked"


def test_state_reads_an_attribute_when_asked():
    cfg = m.normalize_sensor(
        {
            "entity_id": "vacuum.rosie",
            "mode": "state",
            "state": "low",
            "attribute": "water_level",
        }
    )
    assert cfg["attribute"] == "water_level"


def test_state_clear_on_recover_is_stored_only_when_on():
    binding = {"entity_id": "binary_sensor.x", "mode": "state", "state": "on"}
    assert "clear_on_recover" not in m.normalize_sensor(binding)
    assert "clear_on_recover" not in m.normalize_sensor(
        {**binding, "clear_on_recover": False}
    )
    assert (
        m.normalize_sensor({**binding, "clear_on_recover": True})["clear_on_recover"]
        is True
    )


def test_threshold_clear_on_recover_is_stored_only_when_on():
    binding = {
        "entity_id": "sensor.airflow",
        "mode": "threshold",
        "comparison": "<",
        "value": 60,
    }
    assert "clear_on_recover" not in m.normalize_sensor(binding)
    assert (
        m.normalize_sensor({**binding, "clear_on_recover": True})["clear_on_recover"]
        is True
    )


@pytest.mark.parametrize(
    "state",
    [None, "", "   "],
)
def test_state_is_required(state):
    with raises_exactly(m.TaskValidationError, "sensor.state is required"):
        m.normalize_sensor(
            {"entity_id": "binary_sensor.x", "mode": "state", "state": state}
        )


def test_state_over_length_rejected():
    # Home Assistant caps a state at 255 chars, so a longer one could never match.
    with raises_exactly(
        m.TaskValidationError, "sensor.state must be <= 255 characters"
    ):
        m.normalize_sensor(
            {"entity_id": "binary_sensor.x", "mode": "state", "state": "x" * 256}
        )
    # The boundary itself is fine.
    assert (
        m.normalize_sensor(
            {"entity_id": "binary_sensor.x", "mode": "state", "state": "x" * 255}
        )["state"]
        == "x" * 255
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("also_every", {"interval": 6, "unit": "months"}),
        ("combinator", "all"),
        ("unit", "h"),
        ("target", 500),
        ("baseline", 12),
        ("comparison", ">"),
        ("value", 5),
    ],
)
def test_state_rejects_fields_from_the_other_modes(field, value):
    # Storing them silently would let the panel save an "every 300 h" target onto a
    # state task and leave the user believing it applies.
    with raises_exactly(
        m.TaskValidationError,
        f"sensor.{field} is not valid for a state-mode sensor task",
    ):
        m.normalize_sensor(
            {
                "entity_id": "binary_sensor.x",
                "mode": "state",
                "state": "on",
                field: value,
            }
        )


@pytest.mark.parametrize("field", ["also_every", "combinator", "unit", "target"])
def test_threshold_still_rejects_usage_only_fields(field):
    with raises_exactly(
        m.TaskValidationError,
        f"sensor.{field} is not valid for a threshold-mode sensor task",
    ):
        m.normalize_sensor(
            {
                "entity_id": "sensor.x",
                "mode": "threshold",
                "comparison": ">",
                "value": 5,
                field: (
                    "6" if field != "also_every" else {"interval": 6, "unit": "days"}
                ),
            }
        )


@pytest.mark.parametrize(
    ("for_seconds", "message"),
    [
        (-1, "sensor.for_seconds must be >= 0"),
        ("abc", "sensor.for_seconds must be an integer"),
        ({"a": 1}, "sensor.for_seconds must be an integer"),
    ],
)
def test_state_rejects_a_bad_hold(for_seconds, message):
    with raises_exactly(m.TaskValidationError, message):
        m.normalize_sensor(
            {
                "entity_id": "binary_sensor.x",
                "mode": "state",
                "state": "on",
                "for_seconds": for_seconds,
            }
        )


def test_state_hold_is_stored_only_when_non_zero():
    binding = {"entity_id": "binary_sensor.x", "mode": "state", "state": "on"}
    assert "for_seconds" not in m.normalize_sensor({**binding, "for_seconds": 0})
    assert m.normalize_sensor({**binding, "for_seconds": 45})["for_seconds"] == 45
    # Strings coerce, so a form posting "45" stores the same integer.
    assert m.normalize_sensor({**binding, "for_seconds": "45"})["for_seconds"] == 45
    # A fractional hold truncates rather than failing — sub-second precision is
    # meaningless for a debounce, and threshold mode has always behaved this way.
    assert m.normalize_sensor({**binding, "for_seconds": 1.5})["for_seconds"] == 1


def test_unknown_sensor_mode_rejected():
    with raises_exactly(m.TaskValidationError, "invalid sensor mode: 'count'"):
        m.normalize_sensor(
            {"entity_id": "binary_sensor.x", "mode": "count", "state": "on"}
        )


def test_converting_a_usage_task_to_state_drops_the_meter():
    task = m.build_task(
        {
            "name": "T",
            "recurrence_type": "sensor",
            "sensor": {"entity_id": "sensor.hours", "mode": "usage", "target": 300},
        },
        now=NOW,
    )
    updated = m.merge_update(
        task,
        {
            "sensor": {
                "entity_id": "binary_sensor.service_due",
                "mode": "state",
                "state": "on",
            }
        },
        now=NOW,
    )
    assert updated["sensor"] == {
        "entity_id": "binary_sensor.service_due",
        "mode": "state",
        "state": "on",
    }
    # Still dormant: switching how a task is driven must not arm it.
    assert updated["next_due"] is None


# ── an explicit starting reading (issue #235) ────────────────────────────────
#
# A usage task anchors at whatever the sensor reads when it is created, which puts
# every task made for an already-serviced machine a full interval late. An explicit
# ``baseline`` says "the last service happened at this reading" instead.


def _oil_change(**sensor):
    binding = {"entity_id": "sensor.odometer", "mode": "usage", "target": 10000}
    binding.update(sensor)
    return {"name": "Oil change", "recurrence_type": "sensor", "sensor": binding}


def test_an_explicit_baseline_is_stored_and_leaves_the_task_dormant():
    # The reporter's case: odometer at 48,000, last change at 45,000, 10,000-mile
    # interval. 3,000 already used, due at 55,000 — not 58,000.
    task = m.build_task(_oil_change(baseline=45000), now=NOW)
    assert task["sensor"]["baseline"] == 45000.0
    # Storing an anchor is not arming: the watcher decides that from a live reading.
    assert task["next_due"] is None


def test_a_baseline_of_zero_is_kept_rather_than_treated_as_absent():
    # A brand-new hour meter genuinely starts at 0, and 0 is falsy — the exact value
    # a truthiness check would silently drop, leaving the watcher to re-anchor.
    task = m.build_task(_oil_change(baseline=0), now=NOW)
    assert task["sensor"]["baseline"] == 0.0


def test_no_baseline_leaves_the_key_unset_for_the_watcher_to_stamp():
    task = m.build_task(_oil_change(), now=NOW)
    assert "baseline" not in task["sensor"]


def test_a_baseline_is_rejected_for_the_edge_driven_modes():
    # ``baseline`` is meaningless without a target to count towards. Rejecting beats
    # dropping: the panel keeps flat sensor_* state across a mode switch, so a user
    # who types a baseline and then picks Threshold must be told, not ignored.
    for mode, extra in (
        ("threshold", {"comparison": ">=", "value": 90}),
        ("state", {"state": "on"}),
    ):
        with raises_exactly(
            m.TaskValidationError,
            f"sensor.baseline is not valid for a {mode}-mode sensor task",
        ):
            m.build_task(
                {
                    "name": "T",
                    "recurrence_type": "sensor",
                    "sensor": {
                        "entity_id": "sensor.x",
                        "mode": mode,
                        "baseline": 5,
                        **extra,
                    },
                },
                now=NOW,
            )


def test_an_explicit_baseline_on_update_overrides_the_accumulated_one():
    # merge_update carries the watcher's baseline forward across an edit so a rename
    # can't reset "12,000 of 15,000" — but an explicitly sent one is a correction and
    # must win over that carry-forward.
    task = m.build_task(_oil_change(baseline=45000), now=NOW)
    updated = m.merge_update(
        task, {"sensor": {**task["sensor"], "baseline": 44000}}, now=NOW
    )
    assert updated["sensor"]["baseline"] == 44000.0


def test_an_omitted_baseline_on_update_keeps_the_accumulated_one():
    task = m.build_task(_oil_change(baseline=45000), now=NOW)
    binding = {k: v for k, v in task["sensor"].items() if k != "baseline"}
    updated = m.merge_update(task, {"sensor": binding}, now=NOW)
    assert updated["sensor"]["baseline"] == 45000.0


# ── seeding "last serviced" on a sensor task ─────────────────────────────────


def test_a_seeded_last_completed_anchors_the_backstop_without_arming():
    # The calendar half of "every 10,000 mi or 12 months" measures from the last
    # completion, so a task for a machine serviced in March starts three months in.
    seed = datetime(2026, 3, 13, 10, tzinfo=TZ)
    task = m.build_task(
        {
            **_oil_change(also_every={"interval": 12, "unit": "months"}),
            "last_completed": seed.isoformat(),
        },
        now=NOW,
    )
    assert task["last_completed"] == seed.isoformat()
    assert len(task["completions"]) == 1
    # Recording history is not arming — the meter still decides that.
    assert task["next_due"] is None


def test_a_seeded_completion_records_the_starting_reading():
    # The date and the baseline describe one event ("serviced then, at that
    # reading"), so the seeded history row carries both. That makes the feature's
    # invariant true from the first row: a usage task's baseline IS the reading on
    # its latest completion, which is what lets a history edit re-anchor the meter.
    seed = datetime(2026, 3, 13, 10, tzinfo=TZ)
    task = m.build_task(
        {**_oil_change(baseline=45000), "last_completed": seed.isoformat()}, now=NOW
    )
    assert task["completions"][0]["reading"] == 45000.0


def test_a_seeded_completion_without_a_baseline_records_no_reading():
    seed = datetime(2026, 3, 13, 10, tzinfo=TZ)
    task = m.build_task({**_oil_change(), "last_completed": seed.isoformat()}, now=NOW)
    assert "reading" not in task["completions"][0]


def test_a_baseline_alone_records_no_history():
    # Setting only a starting reading says where the meter is, not that a service
    # happened on a particular day — fabricating a completion would put a phantom
    # row in the maintenance log and move the time backstop.
    task = m.build_task(_oil_change(baseline=45000), now=NOW)
    assert task["completions"] == []
    assert task["last_completed"] is None


def test_a_state_mode_seed_records_no_reading():
    # A state binding has no number to record, and carries no baseline to record it
    # from — the seed still anchors the history, just without a reading.
    seed = datetime(2026, 3, 13, 10, tzinfo=TZ)
    task = m.build_task(
        {
            "name": "T",
            "recurrence_type": "sensor",
            "sensor": {
                "entity_id": "binary_sensor.tank_low",
                "mode": "state",
                "state": "on",
            },
            "last_completed": seed.isoformat(),
        },
        now=NOW,
    )
    assert task["completions"][0] == {"ts": seed.isoformat()}


def test_a_naive_seed_on_a_sensor_task_is_qualified_with_the_configured_zone():
    # AGENTS.md: every stored datetime is timezone-aware. A naive `last_completed`
    # (the service accepts offset-less strings) that reached the store unqualified
    # would poison it — every later aware-vs-naive comparison raises TypeError until
    # the storage file is hand-edited. The sensor branch builds its own
    # apply_completion call, so it needs its own proof that it passes the zone on.
    task = m.build_task(
        {**_oil_change(baseline=45000), "last_completed": "2026-03-13T10:00:00"},
        now=NOW,
    )
    assert datetime.fromisoformat(task["last_completed"]).tzinfo is not None
    assert datetime.fromisoformat(task["last_completed"]).utcoffset() == TZ.utcoffset(
        None
    )
    assert datetime.fromisoformat(task["completions"][0]["ts"]).tzinfo is not None


def test_a_blank_seed_is_not_treated_as_a_date():
    # "" reaches here from a cleared form field, and must mean "no seed" rather than
    # an unparseable date.
    task = m.build_task({**_oil_change(), "last_completed": ""}, now=NOW)
    assert task["completions"] == []
    assert task["last_completed"] is None


def test_a_sensor_task_records_when_it_was_created():
    task = m.build_task(_oil_change(), now=NOW)
    assert task["created"] == NOW.isoformat()


# ── availability mode ────────────────────────────────────────────────────────
def test_availability_mode_normalizes_with_defaults():
    """Availability is the fourth mode; clear_on_recover defaults to True."""
    cfg = m.normalize_sensor(
        {"entity_id": "sensor.zwave_node", "mode": "availability"}
    )
    assert cfg == {
        "entity_id": "sensor.zwave_node",
        "mode": "availability",
        "clear_on_recover": True,
    }


def test_availability_carries_for_seconds():
    cfg = m.normalize_sensor(
        {
            "entity_id": "sensor.node",
            "mode": "availability",
            "for_seconds": 3600,
        }
    )
    assert cfg["for_seconds"] == 3600


def test_availability_clear_on_recover_can_be_disabled():
    cfg = m.normalize_sensor(
        {
            "entity_id": "sensor.node",
            "mode": "availability",
            "clear_on_recover": False,
        }
    )
    assert "clear_on_recover" not in cfg


@pytest.mark.parametrize(
    "sensor",
    [
        # Threshold-only fields are meaningless for availability.
        {"entity_id": "sensor.x", "mode": "availability", "comparison": ">"},
        {"entity_id": "sensor.x", "mode": "availability", "value": 10},
        # State fields likewise.
        {"entity_id": "sensor.x", "mode": "availability", "state": "on"},
        # Usage-only fields.
        {"entity_id": "sensor.x", "mode": "availability", "target": 100},
    ],
)
def test_availability_rejects_cross_mode_fields(sensor):
    with pytest.raises(m.TaskValidationError):
        m.normalize_sensor(sensor)


# ── allow_missing_entity kwarg ──────────────────────────────────────────────
def test_normalize_sensor_requires_entity_id_by_default():
    with pytest.raises(m.TaskValidationError):
        m.normalize_sensor(
            {"mode": "state", "state": "on"}, allow_missing_entity=False
        )


def test_normalize_sensor_allows_missing_entity_id_when_opted_in():
    """Declarative-companion specs use this to validate a trigger template."""
    cfg = m.normalize_sensor(
        {"mode": "state", "state": "on"}, allow_missing_entity=True
    )
    assert "entity_id" not in cfg
    assert cfg["mode"] == "state"
    assert cfg["state"] == "on"


def test_normalize_sensor_allow_missing_still_carries_entity_when_present():
    cfg = m.normalize_sensor(
        {"entity_id": "sensor.x", "mode": "state", "state": "on"},
        allow_missing_entity=True,
    )
    assert cfg["entity_id"] == "sensor.x"
