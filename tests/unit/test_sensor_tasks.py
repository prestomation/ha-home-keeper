"""Unit tests for the pure sensor-task evaluators (usage meter / threshold).

These cover the arming math in isolation (no Home Assistant): the meter delta and
re-baseline on reset, and the threshold rising-edge + hold detection. The HA-aware
reading enumeration and state subscription (sensor_watcher) are exercised by the
integration suite.
"""

from datetime import datetime, timedelta, timezone

import hk_sensor_tasks as s

TZ = timezone(timedelta(hours=-4))


def dt(y, m, d, hh=0, mm=0, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=TZ)


def _usage(target, baseline=None, *, armed=False, **over):
    sensor = {"entity_id": "sensor.odometer", "mode": "usage", "target": target}
    if baseline is not None:
        sensor["baseline"] = baseline
    task = {
        "recurrence_type": "sensor",
        "sensor": sensor,
        "next_due": dt(2026, 1, 1).isoformat() if armed else None,
    }
    task.update(over)
    return task


def _threshold(comparison, value, *, for_seconds=0, armed=False, **over):
    sensor = {
        "entity_id": "sensor.humidity",
        "mode": "threshold",
        "comparison": comparison,
        "value": value,
    }
    if for_seconds:
        sensor["for_seconds"] = for_seconds
    task = {
        "recurrence_type": "sensor",
        "sensor": sensor,
        "next_due": dt(2026, 1, 1).isoformat() if armed else None,
    }
    task.update(over)
    return task


# ── config accessors ─────────────────────────────────────────────────────────
def test_sensor_config_and_bound_entity():
    task = _usage(100)
    assert s.sensor_config(task)["mode"] == "usage"
    assert s.bound_entity_id(task) == "sensor.odometer"
    assert s.sensor_config({"recurrence_type": "floating"}) is None
    assert s.bound_entity_id({"recurrence_type": "floating"}) is None


def test_parse_reading():
    assert s.parse_reading("41230.5") == 41230.5
    assert s.parse_reading(12) == 12.0
    assert s.parse_reading("unavailable") is None
    assert s.parse_reading(None) is None
    assert s.parse_reading("") is None


def test_compare_all_operators():
    assert s.compare(5, ">=", 5)
    assert s.compare(6, ">=", 5)
    assert not s.compare(4, ">=", 5)
    assert s.compare(4, "<=", 5)
    assert s.compare(6, ">", 5)
    assert not s.compare(5, ">", 5)
    assert s.compare(4, "<", 5)
    assert s.compare(5, "==", 5)
    assert s.compare(5, "!=", 6)


# ── usage (meter) ────────────────────────────────────────────────────────────
def test_usage_no_baseline_rebaselines():
    now = dt(2026, 6, 1)
    out = s.evaluate_usage(_usage(15000, baseline=None), reading=41230, now=now)
    assert out == {"action": "rebaseline", "baseline": 41230}


def test_usage_arms_when_delta_reaches_target():
    now = dt(2026, 6, 1)
    task = _usage(15000, baseline=41000)
    assert s.evaluate_usage(task, reading=55999, now=now)["action"] is None
    assert s.evaluate_usage(task, reading=56000, now=now)["action"] == "arm"  # exact
    assert s.evaluate_usage(task, reading=60000, now=now)["action"] == "arm"


def test_usage_already_armed_does_not_rearm():
    now = dt(2026, 6, 1)
    task = _usage(15000, baseline=41000, armed=True)
    assert s.evaluate_usage(task, reading=99000, now=now)["action"] is None


def test_usage_meter_reset_rebaselines_not_arms():
    now = dt(2026, 6, 1)
    # Reading dropped below the baseline (odometer replaced / counter reset).
    task = _usage(15000, baseline=41000)
    out = s.evaluate_usage(task, reading=12, now=now)
    assert out == {"action": "rebaseline", "baseline": 12}


# ── threshold ────────────────────────────────────────────────────────────────
def test_threshold_arms_on_rising_edge_only():
    now = dt(2026, 6, 1, 10)
    task = _threshold("<", 60)  # filter: airflow below 60%
    # Was below 60 last tick? No -> this is the rising edge -> arm.
    out = s.evaluate_threshold(
        task, reading=55, condition_met_prev=False, crossed_at=None, now=now
    )
    assert out["action"] == "arm"
    assert out["condition_met"] is True


def test_threshold_no_rearm_while_still_true():
    now = dt(2026, 6, 1, 10)
    task = _threshold("<", 60)
    # Steady-true (no unconsumed crossing: crossed_at None, as after an arm/completion
    # or a startup baseline) -> no new edge -> no arm.
    out = s.evaluate_threshold(
        task, reading=50, condition_met_prev=True, crossed_at=None, now=now
    )
    assert out["action"] is None
    assert out["condition_met"] is True


def test_threshold_arming_consumes_the_crossing():
    now = dt(2026, 6, 1, 10)
    task = _threshold("<", 60)
    out = s.evaluate_threshold(
        task, reading=55, condition_met_prev=False, crossed_at=None, now=now
    )
    assert out["action"] == "arm"
    # The crossing is consumed so a subsequent still-true tick won't re-arm.
    assert out["crossed_at"] is None


def test_threshold_clears_edge_when_recovers():
    now = dt(2026, 6, 1, 10)
    task = _threshold("<", 60)
    out = s.evaluate_threshold(
        task, reading=70, condition_met_prev=True, crossed_at=now, now=now
    )
    assert out == {"action": None, "condition_met": False, "crossed_at": None}


def test_threshold_armed_stays_armed_no_action():
    now = dt(2026, 6, 1, 10)
    task = _threshold("<", 60, armed=True)
    # Already armed and still met: no further action (it clears on completion).
    out = s.evaluate_threshold(
        task, reading=50, condition_met_prev=True, crossed_at=now, now=now
    )
    assert out["action"] is None


def test_threshold_hold_delays_arming():
    cross = dt(2026, 6, 1, 10, 0, 0)
    task = _threshold(">", 90, for_seconds=300)  # must stay >90 for 5 minutes
    # Rising edge: starts the timer, not yet held long enough.
    out = s.evaluate_threshold(
        task, reading=95, condition_met_prev=False, crossed_at=None, now=cross
    )
    assert out["action"] is None
    assert out["crossed_at"] == cross
    # 4 minutes later, still not enough.
    out = s.evaluate_threshold(
        task,
        reading=95,
        condition_met_prev=True,
        crossed_at=cross,
        now=cross + timedelta(minutes=4),
    )
    assert out["action"] is None
    # 5 minutes later: the hold elapsed -> arm.
    out = s.evaluate_threshold(
        task,
        reading=95,
        condition_met_prev=True,
        crossed_at=cross,
        now=cross + timedelta(minutes=5),
    )
    assert out["action"] == "arm"


def test_threshold_hold_resets_if_it_dips_below():
    cross = dt(2026, 6, 1, 10, 0, 0)
    task = _threshold(">", 90, for_seconds=300)
    # Crossed, then dipped below before the hold elapsed -> edge cleared.
    out = s.evaluate_threshold(
        task,
        reading=80,
        condition_met_prev=True,
        crossed_at=cross,
        now=cross + timedelta(minutes=2),
    )
    assert out["crossed_at"] is None
    # New crossing starts a fresh timer.
    later = cross + timedelta(minutes=10)
    out = s.evaluate_threshold(
        task, reading=95, condition_met_prev=False, crossed_at=None, now=later
    )
    assert out["action"] is None
    assert out["crossed_at"] == later
