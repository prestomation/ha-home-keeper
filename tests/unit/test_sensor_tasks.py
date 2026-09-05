"""Unit tests for the pure sensor-task evaluators (usage meter / threshold / state).

These cover the arming math in isolation (no Home Assistant): the meter delta and
re-baseline on reset, the threshold rising-edge + hold detection, and the ``state``
mode that lets a binary sensor drive a task. The HA-aware reading enumeration and
state subscription (sensor_watcher) are exercised by the integration suite.
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


def _state(
    state,
    *,
    entity_id="binary_sensor.vacuum_water_tank_low",
    for_seconds=0,
    clear_on_recover=False,
    armed=False,
    **over,
):
    sensor = {"entity_id": entity_id, "mode": "state", "state": state}
    if for_seconds:
        sensor["for_seconds"] = for_seconds
    if clear_on_recover:
        sensor["clear_on_recover"] = True
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
    assert out == {"action": "rebaseline", "baseline": 41230, "reset_candidate": None}


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
    # Debounced: a single below-baseline reading only records a candidate; a second
    # consecutive one confirms the reset and re-baselines.
    task = _usage(15000, baseline=41000)
    first = s.evaluate_usage(task, reading=12, now=now)
    assert first == {"action": None, "reset_candidate": 12}
    out = s.evaluate_usage(
        task, reading=12, reset_candidate=first["reset_candidate"], now=now
    )
    assert out == {"action": "rebaseline", "baseline": 12, "reset_candidate": None}


def test_usage_single_low_reading_does_not_rebaseline():
    now = dt(2026, 6, 1)
    # A momentary blip to 0 (or any transient dip) below the baseline must NOT
    # re-anchor on its own — it only arms a candidate.
    task = _usage(15000, baseline=41000)
    out = s.evaluate_usage(task, reading=0, now=now)
    assert out == {"action": None, "reset_candidate": 0}


def test_usage_low_then_recovered_clears_candidate():
    now = dt(2026, 6, 1)
    # Below-baseline once, then the reading recovers to/above the baseline: the
    # candidate is cleared, so no rebaseline (it was a blip).
    task = _usage(15000, baseline=41000)
    first = s.evaluate_usage(task, reading=0, now=now)
    assert first["reset_candidate"] == 0
    recovered = s.evaluate_usage(
        task, reading=41500, reset_candidate=first["reset_candidate"], now=now
    )
    assert recovered == {"action": None, "reset_candidate": None}


def test_usage_two_consecutive_low_readings_rebaseline():
    now = dt(2026, 6, 1)
    # Two consecutive below-baseline readings confirm a genuine meter reset.
    task = _usage(15000, baseline=41000)
    first = s.evaluate_usage(task, reading=100, now=now)
    assert first == {"action": None, "reset_candidate": 100}
    second = s.evaluate_usage(
        task, reading=150, reset_candidate=first["reset_candidate"], now=now
    )
    assert second == {"action": "rebaseline", "baseline": 150, "reset_candidate": None}


def test_usage_arm_clears_reset_candidate():
    now = dt(2026, 6, 1)
    # Arming (at/above baseline, delta reached) also carries a cleared candidate.
    task = _usage(15000, baseline=41000)
    out = s.evaluate_usage(task, reading=60000, reset_candidate=None, now=now)
    assert out == {"action": "arm", "reset_candidate": None}


# ── usage with a time backstop ("or every N months, whichever first") ────────
def _backstop(target, baseline, interval, unit, *, combinator="any", **over):
    task = _usage(target, baseline, **over)
    task["sensor"]["also_every"] = {"interval": interval, "unit": unit}
    task["sensor"]["combinator"] = combinator
    return task


def test_backstop_due_anchors_to_last_completed_then_created():
    task = _backstop(300, 660, 6, "months", created=dt(2026, 1, 15).isoformat())
    # Never completed: the clock runs from creation.
    assert s.backstop_due(task, task["sensor"]) == dt(2026, 7, 15)
    # Once completed, that wins — the backstop measures time since the last service.
    task["last_completed"] = dt(2026, 3, 31).isoformat()
    # September has 30 days, so the March 31 anchor clamps to September 30.
    assert s.backstop_due(task, task["sensor"]) == dt(2026, 9, 30)


def test_backstop_due_is_none_without_also_every():
    task = _usage(300, 660, created=dt(2026, 1, 15).isoformat())
    assert s.backstop_due(task, task["sensor"]) is None


def test_backstop_arms_on_time_alone_when_meter_has_not_moved():
    task = _backstop(300, 660, 6, "months", created=dt(2026, 1, 15).isoformat())
    # Meter has barely moved, but six months have passed -> "whichever comes first".
    assert s.evaluate_usage(task, reading=662, now=dt(2026, 7, 14))["action"] is None
    assert s.evaluate_usage(task, reading=662, now=dt(2026, 7, 15))["action"] == "arm"


def test_backstop_arms_with_no_reading_at_all():
    # The printer has been unplugged for a year; its annual service is still due.
    task = _backstop(300, 660, 6, "months", created=dt(2026, 1, 15).isoformat())
    out = s.evaluate_usage(task, reading=None, now=dt(2027, 1, 1))
    assert out == {"action": "arm", "reset_candidate": None}


def test_no_reading_leaves_baseline_and_candidate_alone():
    task = _backstop(300, 660, 6, "months", created=dt(2026, 1, 15).isoformat())
    out = s.evaluate_usage(task, reading=None, reset_candidate=12.0, now=dt(2026, 2, 1))
    assert out == {"action": None, "reset_candidate": 12.0}


def test_backstop_any_still_arms_on_the_meter_before_the_clock():
    task = _backstop(300, 660, 6, "months", created=dt(2026, 1, 15).isoformat())
    assert s.evaluate_usage(task, reading=960, now=dt(2026, 2, 1))["action"] == "arm"


def test_backstop_all_requires_both():
    task = _backstop(
        300, 660, 1, "months", combinator="all", created=dt(2026, 1, 15).isoformat()
    )
    # Meter reached, clock not: not yet.
    assert s.evaluate_usage(task, reading=960, now=dt(2026, 1, 20))["action"] is None
    # Clock reached, meter not: not yet either.
    assert s.evaluate_usage(task, reading=662, now=dt(2026, 3, 1))["action"] is None
    # Both: arm.
    assert s.evaluate_usage(task, reading=960, now=dt(2026, 3, 1))["action"] == "arm"


def test_backstop_does_not_rearm_while_armed():
    task = _backstop(
        300, 660, 6, "months", armed=True, created=dt(2026, 1, 15).isoformat()
    )
    assert s.evaluate_usage(task, reading=None, now=dt(2030, 1, 1))["action"] is None


def test_meter_reset_still_wins_over_the_backstop():
    # A confirmed meter reset re-baselines rather than arming, even though the
    # backstop has elapsed — otherwise one tick would both reset and fire.
    task = _backstop(300, 660, 6, "months", created=dt(2026, 1, 15).isoformat())
    out = s.evaluate_usage(task, reading=5, reset_candidate=5.0, now=dt(2027, 1, 1))
    assert out == {"action": "rebaseline", "baseline": 5, "reset_candidate": None}


def test_backstop_ignores_unparseable_anchor():
    task = _backstop(300, 660, 6, "months", created="not-a-timestamp")
    assert s.backstop_due(task, task["sensor"]) is None
    assert s.evaluate_usage(task, reading=662, now=dt(2030, 1, 1))["action"] is None


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
    assert out == {
        "action": None,
        "condition_met": False,
        "crossed_at": None,
        "hold_due_at": None,
    }


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


# ── state mode (binary sensors) ──────────────────────────────────────────────
def test_state_arms_on_rising_edge_only():
    now = dt(2026, 6, 1, 10)
    task = _state("on")  # robot vacuum: "water tank low"
    out = s.evaluate_state(
        task, state="on", condition_met_prev=False, crossed_at=None, now=now
    )
    assert out["action"] == "arm"
    assert out["condition_met"] is True
    # And the crossing is consumed, so a still-on tick can't re-arm it.
    assert out["crossed_at"] is None


def test_state_no_rearm_while_still_on():
    now = dt(2026, 6, 1, 10)
    task = _state("on")
    out = s.evaluate_state(
        task, state="on", condition_met_prev=True, crossed_at=None, now=now
    )
    assert out["action"] is None
    assert out["condition_met"] is True


def test_state_non_matching_state_clears_the_edge():
    now = dt(2026, 6, 1, 10)
    task = _state("on")
    out = s.evaluate_state(
        task, state="off", condition_met_prev=True, crossed_at=now, now=now
    )
    assert out == {
        "action": None,
        "condition_met": False,
        "crossed_at": None,
        "hold_due_at": None,
    }


def test_state_matches_any_state_string_not_just_on_off():
    # The mode compares the state *string*, so it is not binary-sensor-only.
    now = dt(2026, 6, 1, 10)
    task = _state("docked", entity_id="vacuum.rosie")
    assert (
        s.evaluate_state(
            task, state="docked", condition_met_prev=False, crossed_at=None, now=now
        )["action"]
        == "arm"
    )
    assert (
        s.evaluate_state(
            task, state="cleaning", condition_met_prev=False, crossed_at=None, now=now
        )["action"]
        is None
    )


def test_state_armed_stays_armed_without_clear_on_recover():
    now = dt(2026, 6, 1, 10)
    task = _state("on", armed=True)
    # Recovered, but the binding didn't opt in: it waits to be completed by hand.
    out = s.evaluate_state(
        task, state="off", condition_met_prev=True, crossed_at=None, now=now
    )
    assert out["action"] is None
    assert out["condition_met"] is False


def test_state_hold_delays_arming():
    cross = dt(2026, 6, 1, 10, 0, 0)
    task = _state("on", for_seconds=600)  # door open for 10 minutes
    out = s.evaluate_state(
        task, state="on", condition_met_prev=False, crossed_at=None, now=cross
    )
    assert out["action"] is None
    assert out["crossed_at"] == cross
    # Still on once the hold has elapsed -> arm.
    later = cross + timedelta(minutes=10)
    out = s.evaluate_state(
        task, state="on", condition_met_prev=True, crossed_at=cross, now=later
    )
    assert out["action"] == "arm"
    assert out["crossed_at"] is None


def test_state_hold_resets_if_it_recovers_first():
    cross = dt(2026, 6, 1, 10, 0, 0)
    task = _state("on", for_seconds=600)
    out = s.evaluate_state(
        task,
        state="off",
        condition_met_prev=True,
        crossed_at=cross,
        now=cross + timedelta(minutes=2),
    )
    assert out["crossed_at"] is None


# ── the unavailable / dropout trap ───────────────────────────────────────────
def test_state_none_holds_the_edge_and_decides_nothing():
    # `unavailable`/`unknown`/missing arrives as None. It is neither a match nor a
    # recovery: the carried edge state must survive untouched so a dropout mid-hold
    # doesn't restart the timer or fabricate a crossing.
    cross = dt(2026, 6, 1, 10, 0, 0)
    task = _state("on", for_seconds=600)
    out = s.evaluate_state(
        task,
        state=None,
        condition_met_prev=True,
        crossed_at=cross,
        now=cross + timedelta(minutes=2),
    )
    assert out == {
        "action": None,
        "condition_met": True,
        "crossed_at": cross,
        # The hold is still pending, so the booked re-evaluation survives the dropout.
        "hold_due_at": cross + timedelta(minutes=10),
    }


def test_state_none_never_arms_a_dormant_task():
    now = dt(2026, 6, 1, 10)
    task = _state("on")
    out = s.evaluate_state(
        task, state=None, condition_met_prev=False, crossed_at=None, now=now
    )
    assert out["action"] is None


def test_state_none_never_clears_an_armed_clear_on_recover_task():
    # The trap this guards: reading a Zigbee dropout as "the condition went away"
    # would silently complete the task the first time the device fell off the mesh.
    now = dt(2026, 6, 1, 10)
    task = _state("on", armed=True, clear_on_recover=True)
    out = s.evaluate_state(
        task, state=None, condition_met_prev=True, crossed_at=None, now=now
    )
    assert out["action"] is None
    assert out["condition_met"] is True


# ── clear_on_recover ─────────────────────────────────────────────────────────
def test_state_clear_on_recover_clears_an_armed_task():
    now = dt(2026, 6, 1, 10)
    task = _state("on", armed=True, clear_on_recover=True)
    out = s.evaluate_state(
        task, state="off", condition_met_prev=True, crossed_at=None, now=now
    )
    assert out["action"] == "clear"
    assert out["condition_met"] is False
    assert out["crossed_at"] is None


def test_state_clear_on_recover_is_a_no_op_while_dormant():
    # Nothing to clear: a dormant task recovering is just the ordinary false branch.
    now = dt(2026, 6, 1, 10)
    task = _state("on", clear_on_recover=True)
    out = s.evaluate_state(
        task, state="off", condition_met_prev=True, crossed_at=None, now=now
    )
    assert out["action"] is None


def test_state_clear_on_recover_does_not_fire_while_still_matching():
    now = dt(2026, 6, 1, 10)
    task = _state("on", armed=True, clear_on_recover=True)
    out = s.evaluate_state(
        task, state="on", condition_met_prev=True, crossed_at=None, now=now
    )
    assert out["action"] is None


def test_threshold_clear_on_recover_clears_an_armed_task():
    # The flag lives in the shared edge helper, so threshold mode gets it too.
    now = dt(2026, 6, 1, 10)
    task = _threshold(">", 90, armed=True)
    task["sensor"]["clear_on_recover"] = True
    out = s.evaluate_threshold(
        task, reading=70, condition_met_prev=True, crossed_at=None, now=now
    )
    assert out["action"] == "clear"


def test_threshold_without_clear_on_recover_still_stays_armed():
    now = dt(2026, 6, 1, 10)
    task = _threshold(">", 90, armed=True)
    out = s.evaluate_threshold(
        task, reading=70, condition_met_prev=True, crossed_at=None, now=now
    )
    assert out["action"] is None


# ── availability mode ────────────────────────────────────────────────────────
def _availability(*, armed=False, for_seconds=0, clear_on_recover=True):
    sensor = {"entity_id": "sensor.zwave_node", "mode": "availability"}
    if for_seconds:
        sensor["for_seconds"] = for_seconds
    if clear_on_recover:
        sensor["clear_on_recover"] = True
    return {
        "recurrence_type": "sensor",
        "sensor": sensor,
        "next_due": dt(2026, 1, 1).isoformat() if armed else None,
    }


def test_availability_arms_on_unavailable_with_no_hold():
    now = dt(2026, 6, 1, 10)
    task = _availability()
    out = s.evaluate_availability(
        task,
        status=s.AVAILABILITY_UNAVAILABLE,
        condition_met_prev=False,
        crossed_at=None,
        now=now,
    )
    assert out["action"] == "arm"
    assert out["condition_met"] is True
    # Crossing consumed so a steady-unavailable entity never re-arms.
    assert out["crossed_at"] is None


def test_availability_waits_for_hold():
    now = dt(2026, 6, 1, 10)
    task = _availability(for_seconds=300)
    # First tick: unavailable observed.
    out = s.evaluate_availability(
        task,
        status=s.AVAILABILITY_UNAVAILABLE,
        condition_met_prev=False,
        crossed_at=None,
        now=now,
    )
    assert out["action"] is None
    assert out["crossed_at"] == now
    # Second tick 60 s later: hold not yet met.
    out = s.evaluate_availability(
        task,
        status=s.AVAILABILITY_UNAVAILABLE,
        condition_met_prev=True,
        crossed_at=now,
        now=now + timedelta(seconds=60),
    )
    assert out["action"] is None
    # Third tick past the hold: arms.
    out = s.evaluate_availability(
        task,
        status=s.AVAILABILITY_UNAVAILABLE,
        condition_met_prev=True,
        crossed_at=now,
        now=now + timedelta(seconds=301),
    )
    assert out["action"] == "arm"


def test_availability_clears_on_recover_when_armed():
    now = dt(2026, 6, 1, 10)
    task = _availability(armed=True, clear_on_recover=True)
    out = s.evaluate_availability(
        task,
        status=s.AVAILABILITY_AVAILABLE,
        condition_met_prev=True,
        crossed_at=None,
        now=now,
    )
    assert out["action"] == "clear"
    assert out["condition_met"] is False


def test_availability_missing_status_is_indeterminate():
    """A not-yet-restored entity must never fabricate an arm or clear."""
    now = dt(2026, 6, 1, 10)
    task = _availability(armed=True, clear_on_recover=True)
    prior_cross = dt(2026, 5, 30, 10)
    out = s.evaluate_availability(
        task,
        status=s.AVAILABILITY_MISSING,
        condition_met_prev=True,
        crossed_at=prior_cross,
        now=now,
    )
    # The whole return dict is asserted so a mutated key name (e.g. ``crossed_at`` →
    # ``CROSSED_AT``) fails the equality even without a direct key read.
    assert out == {
        "action": None,
        "condition_met": True,
        "crossed_at": prior_cross,
        # The task is armed already, so no hold waits on a re-evaluation.
        "hold_due_at": None,
    }


def test_availability_missing_keeps_a_pending_hold():
    # The entity left the state machine part-way through the hold. That decides
    # nothing, so the booked re-evaluation stands: the entity may come back, and the
    # hold still ends when it ends.
    cross = dt(2026, 6, 1, 10, 0, 0)
    task = _availability(for_seconds=600)
    out = s.evaluate_availability(
        task,
        status=s.AVAILABILITY_MISSING,
        condition_met_prev=True,
        crossed_at=cross,
        now=cross + timedelta(minutes=2),
    )
    assert out == {
        "action": None,
        "condition_met": True,
        "crossed_at": cross,
        "hold_due_at": cross + timedelta(minutes=10),
    }


def test_availability_dormant_missing_never_arms():
    now = dt(2026, 6, 1, 10)
    task = _availability()
    out = s.evaluate_availability(
        task,
        status=s.AVAILABILITY_MISSING,
        condition_met_prev=False,
        crossed_at=None,
        now=now,
    )
    assert out == {
        "action": None,
        "condition_met": False,
        "crossed_at": None,
        "hold_due_at": None,
    }


# ── the hold's own timer (a hold ends while the entity is quiet) ─────────────


def test_hold_due_at_reports_the_moment_a_pending_hold_completes():
    # The watcher books a re-evaluation for this moment. Without it a hold only ran
    # out when the entity happened to send another state change.
    cross = dt(2026, 6, 1, 10, 0, 0)
    task = _threshold(">", 90, for_seconds=300)
    assert s.hold_due_at(task, crossed_at=cross, now=cross) == cross + timedelta(
        seconds=300
    )
    # Still pending one second before it is due.
    late = cross + timedelta(seconds=299)
    assert s.hold_due_at(task, crossed_at=cross, now=late) == cross + timedelta(
        seconds=300
    )


def test_hold_due_at_is_none_for_a_hold_that_is_already_due():
    # Exactly due counts as due: the same evaluation arms the task, so a timer for a
    # moment that has arrived would only re-book itself.
    cross = dt(2026, 6, 1, 10, 0, 0)
    task = _threshold(">", 90, for_seconds=300)
    due = cross + timedelta(seconds=300)
    assert s.hold_due_at(task, crossed_at=cross, now=due) is None
    assert s.hold_due_at(task, crossed_at=cross, now=due + timedelta(hours=2)) is None


def test_hold_due_at_is_none_without_a_hold_or_a_crossing():
    now = dt(2026, 6, 1, 10, 0, 0)
    # A mode with no hold: the crossing arms the task at once, so nothing waits.
    assert s.hold_due_at(_state("on"), crossed_at=now, now=now) is None
    assert s.hold_due_at(_threshold(">", 90), crossed_at=now, now=now) is None
    # No crossing to hold, and no sensor binding at all.
    task = _state("on", for_seconds=300)
    assert s.hold_due_at(task, crossed_at=None, now=now) is None
    assert (
        s.hold_due_at({"recurrence_type": "floating"}, crossed_at=now, now=now) is None
    )


def test_hold_due_at_is_none_for_an_armed_task():
    # An armed task cannot arm again on this crossing, so it needs no timer.
    cross = dt(2026, 6, 1, 10, 0, 0)
    task = _state("on", for_seconds=300, armed=True)
    assert s.hold_due_at(task, crossed_at=cross, now=cross) is None


def test_a_pending_hold_rides_on_the_edge_decision():
    # Each mode reports the hold on its own decision, which is what the watcher books.
    cross = dt(2026, 6, 1, 10, 0, 0)
    due = cross + timedelta(seconds=300)
    out = s.evaluate_threshold(
        _threshold(">", 90, for_seconds=300),
        reading=95,
        condition_met_prev=False,
        crossed_at=None,
        now=cross,
    )
    assert out["action"] is None and out["hold_due_at"] == due
    out = s.evaluate_state(
        _state("on", for_seconds=300),
        state="on",
        condition_met_prev=False,
        crossed_at=None,
        now=cross,
    )
    assert out["action"] is None and out["hold_due_at"] == due
    out = s.evaluate_availability(
        _availability(for_seconds=300),
        status=s.AVAILABILITY_UNAVAILABLE,
        condition_met_prev=False,
        crossed_at=None,
        now=cross,
    )
    assert out["action"] is None and out["hold_due_at"] == due


def test_arming_leaves_no_hold_to_wait_for():
    # The arm consumes the crossing, so the booked re-evaluation is dropped with it.
    cross = dt(2026, 6, 1, 10, 0, 0)
    out = s.evaluate_availability(
        _availability(for_seconds=300),
        status=s.AVAILABILITY_UNAVAILABLE,
        condition_met_prev=True,
        crossed_at=cross,
        now=cross + timedelta(seconds=300),
    )
    assert out["action"] == "arm"
    assert out["crossed_at"] is None
    assert out["hold_due_at"] is None


# ── baseline_after_delete (undoing a usage completion) ───────────────────────


def _completion(ts, *, reading=None, meter_start=..., **extra):
    entry = {"ts": ts}
    if reading is not None:
        entry["reading"] = reading
    if meter_start is not ...:
        entry["meter_start"] = meter_start
    entry.update(extra)
    return entry


def test_baseline_after_delete_restores_meter_start_of_only_completion():
    # 45,000-start task, completed at 48,000 (meter_start recorded the 45,000). Undo
    # must revert the baseline to 45,000, not leave it at 48,000 (progress back to
    # "3,000 of 10,000", not stuck at zero). This is the reported bug.
    ts = dt(2026, 6, 1, 10).isoformat()
    task = _usage(10_000, baseline=48_000, completions=[], last_completed=None)
    removed = _completion(ts, reading=48_000, meter_start=45_000)
    assert s.baseline_after_delete(task, removed, was_latest=True) == (True, 45_000)


def test_baseline_after_delete_restores_prior_completion_baseline():
    # Two completions; undoing the latest reverts to the baseline it replaced, which
    # equals the earlier completion's reading.
    ts1 = dt(2026, 5, 1, 10).isoformat()
    task = _usage(
        10_000,
        baseline=55_000,
        completions=[_completion(ts1, reading=48_000, meter_start=45_000)],
        last_completed=ts1,
    )
    removed = _completion(
        dt(2026, 6, 1, 10).isoformat(), reading=55_000, meter_start=48_000
    )
    assert s.baseline_after_delete(task, removed, was_latest=True) == (True, 48_000)


def test_baseline_after_delete_leaves_older_row_alone():
    # Undoing a non-anchor (older) completion must not touch the meter.
    ts_latest = dt(2026, 6, 1, 10).isoformat()
    task = _usage(
        10_000,
        baseline=55_000,
        completions=[_completion(ts_latest, reading=55_000, meter_start=48_000)],
        last_completed=ts_latest,
    )
    removed = _completion(
        dt(2026, 5, 1, 10).isoformat(), reading=48_000, meter_start=45_000
    )
    assert s.baseline_after_delete(task, removed, was_latest=False) == (False, None)


def test_baseline_after_delete_ignores_non_usage_task():
    task = _threshold(">", 90)
    removed = _completion(dt(2026, 6, 1, 10).isoformat(), reading=95)
    assert s.baseline_after_delete(task, removed, was_latest=True) == (False, None)


def test_baseline_after_delete_falls_back_to_latest_remaining_reading():
    # A pre-``meter_start`` entry (recorded before the field existed). Fall back to
    # the now-latest remaining completion's reading.
    ts1 = dt(2026, 5, 1, 10).isoformat()
    task = _usage(
        10_000,
        baseline=55_000,
        completions=[_completion(ts1, reading=48_000)],
        last_completed=ts1,
    )
    removed = _completion(dt(2026, 6, 1, 10).isoformat(), reading=55_000)
    assert s.baseline_after_delete(task, removed, was_latest=True) == (True, 48_000)


def test_baseline_after_delete_clears_when_no_completion_remains():
    # No ``meter_start`` and nothing left in history: clear the baseline (None) so the
    # watcher re-anchors on its next reading rather than measuring from a stale figure.
    task = _usage(10_000, baseline=48_000, completions=[], last_completed=None)
    removed = _completion(dt(2026, 6, 1, 10).isoformat(), reading=48_000)
    assert s.baseline_after_delete(task, removed, was_latest=True) == (True, None)


def test_baseline_after_delete_restores_none_meter_start():
    # A completion whose meter_start was itself None (entity was unavailable at
    # creation) clears the baseline, distinct from the missing-key fallback.
    task = _usage(10_000, baseline=48_000, completions=[], last_completed=None)
    removed = _completion(
        dt(2026, 6, 1, 10).isoformat(), reading=48_000, meter_start=None
    )
    assert s.baseline_after_delete(task, removed, was_latest=True) == (True, None)


# ── which modes carry edge state ─────────────────────────────────────────────


def test_holds_edge_state_is_true_for_every_rising_edge_mode():
    # The watcher baselines edge state on startup, and skips that baseline for a task
    # made after the last pass. This is the test that says which tasks have an edge to
    # skip, so each mode has to answer for itself.
    assert s.holds_edge_state("threshold") is True
    assert s.holds_edge_state("state") is True
    assert s.holds_edge_state("availability") is True


def test_holds_edge_state_is_false_for_a_usage_meter():
    # A usage meter compares the live reading against a persisted baseline, so it
    # carries nothing between evaluations and the baseline pass must still anchor it.
    assert s.holds_edge_state("usage") is False


def test_holds_edge_state_treats_an_unknown_mode_as_a_meter():
    # The watcher's baseline pass reads an unknown mode as ``usage`` (it is the else
    # branch), so this must agree — otherwise a malformed binding would be skipped by
    # one and anchored by the other.
    assert s.holds_edge_state("banana") is False
    assert s.holds_edge_state(None) is False
    assert s.holds_edge_state("") is False
