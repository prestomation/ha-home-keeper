"""Integration coverage for sensor-based tasks (real HA container).

Exercises the HA-aware sensor watcher end to end: a sensor task bound to the
``input_number.hk_demo_meter`` helper is armed by Home Keeper when the helper's
value crosses the task's condition (a threshold crossing, or a usage meter passing
its target), and cleared again when the task is completed. Driving a real
``input_number`` produces genuine state-change events, so this covers the watcher's
subscription + evaluation path that the pure unit tests can't.
"""

import time
from datetime import UTC, datetime, timedelta

from conftest import HA_URL, call_service

METER = "input_number.hk_demo_meter"


def _list_tasks(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def _set_meter(ha, value):
    call_service(ha, "input_number", "set_value", {"entity_id": METER, "value": value})


def _add_sensor_task(ha, sensor):
    resp = call_service(
        ha,
        "home_keeper",
        "add_task",
        {"name": "Sensor watcher test", "recurrence_type": "sensor", "sensor": sensor},
        return_response=True,
    )
    return resp.get("service_response", resp)["task_id"]


def _get_task(ha, task_id):
    """Return the task dict by id, tolerating transient mid-reload 500s."""
    try:
        for task in _list_tasks(ha):
            if task.get("id") == task_id:
                return task
    except Exception:
        pass
    return None


def _poll_task(ha, task_id, predicate, timeout=40):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = _get_task(ha, task_id)
        if last is not None and predicate(last):
            return last
        time.sleep(1)
    raise AssertionError(f"task {task_id} never satisfied predicate; last={last}")


def _delete(ha, task_id):
    try:
        call_service(ha, "home_keeper", "delete_task", {"task_id": task_id})
    except Exception:
        pass


def test_usage_sensor_task_arms_when_meter_advances(ha):
    # Anchor the meter, then create a usage task with target 50 so its baseline is
    # stamped at the current reading on setup.
    _set_meter(ha, 1000)
    task_id = _add_sensor_task(ha, {"entity_id": METER, "mode": "usage", "target": 50})
    try:
        # Born dormant (the meter hasn't advanced past the baseline yet).
        task = _poll_task(
            ha, task_id, lambda t: t.get("sensor", {}).get("baseline") is not None
        )
        assert task["recurrence_type"] == "sensor"
        assert task["next_due"] is None

        # Advance the meter past the target -> the watcher arms the task.
        _set_meter(ha, 1100)
        armed = _poll_task(ha, task_id, lambda t: t.get("next_due") is not None)
        assert armed["next_due"] is not None

        # Completing it clears the task and resets the meter baseline to "now".
        call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
        cleared = _poll_task(ha, task_id, lambda t: t.get("next_due") is None)
        assert cleared["sensor"]["baseline"] == 1100
    finally:
        _delete(ha, task_id)


def test_threshold_sensor_task_arms_on_crossing(ha):
    # Start below the threshold so the task is created with the condition false.
    _set_meter(ha, 10)
    task_id = _add_sensor_task(
        ha, {"entity_id": METER, "mode": "threshold", "comparison": ">", "value": 50}
    )
    try:
        task = _poll_task(ha, task_id, lambda t: t.get("recurrence_type") == "sensor")
        assert task["next_due"] is None  # condition not yet met

        # Cross the threshold -> rising edge arms the task.
        _set_meter(ha, 100)
        armed = _poll_task(ha, task_id, lambda t: t.get("next_due") is not None)
        assert armed["next_due"] is not None

        # A user completion clears it back to dormant.
        call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
        cleared = _poll_task(ha, task_id, lambda t: t.get("next_due") is None)
        assert cleared["next_due"] is None
    finally:
        _delete(ha, task_id)
        _set_meter(ha, 0)


def test_sensor_task_completable_unlike_problem_sync(ha):
    # Unlike a synced problem task, a sensor task is user-completable (no managed_by
    # completion block) — completing it must succeed, not 4xx.
    _set_meter(ha, 0)
    task_id = _add_sensor_task(
        ha, {"entity_id": METER, "mode": "threshold", "comparison": ">=", "value": 0}
    )
    try:
        _poll_task(ha, task_id, lambda t: t.get("recurrence_type") == "sensor")
        r = ha.post(
            f"{HA_URL}/api/services/home_keeper/complete_task",
            json={"task_id": task_id},
        )
        assert r.status_code < 400, (
            f"sensor task should be completable, got {r.status_code}"
        )
    finally:
        _delete(ha, task_id)


def _add_backstop_task(ha, *, target, also_every, combinator, last_completed=None):
    payload = {
        "name": "Backstop test",
        "recurrence_type": "sensor",
        "sensor": {
            "entity_id": METER,
            "mode": "usage",
            "target": target,
            "unit": "h",
            "also_every": also_every,
            "combinator": combinator,
        },
    }
    if last_completed:
        payload["last_completed"] = last_completed
    resp = call_service(ha, "home_keeper", "add_task", payload, return_response=True)
    return resp.get("service_response", resp)["task_id"]


def test_time_backstop_arms_without_the_meter_moving(ha):
    # Seed "last serviced two days ago" against a one-day backstop, so the calendar
    # half is already elapsed at creation. The meter never advances: only the time
    # half can arm this task.
    _set_meter(ha, 500)
    stale = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    task_id = _add_backstop_task(
        ha,
        target=100000,  # unreachable by the meter within the test
        also_every={"interval": 1, "unit": "days"},
        combinator="any",
        last_completed=stale,
    )
    try:
        # Two nudges, both far below target. A usage task created *after* Home Keeper
        # started has no meter baseline yet — the first evaluation of the bound sensor
        # stamps it (and does nothing else), so it takes a second state change to reach
        # the arming branch. Neither nudge comes close to the target, so if the task
        # arms it can only be the backstop that did it.
        _set_meter(ha, 501)
        _poll_task(ha, task_id, lambda t: t.get("sensor", {}).get("baseline") == 501)
        _set_meter(ha, 502)
        armed = _poll_task(ha, task_id, lambda t: t.get("next_due") is not None)
        assert armed["sensor"]["also_every"] == {"interval": 1, "unit": "days"}
        assert armed["sensor"]["unit"] == "h"

        # Completing it re-anchors both halves: dormant again, baseline at the reading.
        call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
        cleared = _poll_task(ha, task_id, lambda t: t.get("next_due") is None)
        assert cleared["sensor"]["baseline"] == 502
    finally:
        _delete(ha, task_id)
        _set_meter(ha, 0)


def test_combinator_all_holds_the_task_until_both_halves_are_met(ha):
    # Meter target is trivially reachable, but the calendar half is a year out, so
    # "both must be met" keeps it dormant.
    _set_meter(ha, 0)
    task_id = _add_backstop_task(
        ha,
        target=10,
        also_every={"interval": 12, "unit": "months"},
        combinator="all",
    )
    try:
        _poll_task(
            ha, task_id, lambda t: t.get("sensor", {}).get("baseline") is not None
        )
        _set_meter(ha, 100)  # meter half satisfied several times over
        # Give the watcher time to see it and (correctly) do nothing.
        time.sleep(5)
        task = _get_task(ha, task_id)
        assert task is not None and task["next_due"] is None, (
            "combinator 'all' must not arm on the meter alone"
        )
    finally:
        _delete(ha, task_id)
        _set_meter(ha, 0)


def test_set_task_meter_reanchors_without_recording_a_completion(ha):
    _set_meter(ha, 1000)
    task_id = _add_sensor_task(ha, {"entity_id": METER, "mode": "usage", "target": 50})
    try:
        _poll_task(ha, task_id, lambda t: t.get("sensor", {}).get("baseline") == 1000)
        # Re-anchor explicitly (as if the work was done before Home Keeper watched).
        call_service(
            ha, "home_keeper", "set_task_meter", {"task_id": task_id, "baseline": 900}
        )
        moved = _poll_task(ha, task_id, lambda t: t["sensor"].get("baseline") == 900)
        assert moved["completions"] == []  # no completion was recorded
        assert moved["last_completed"] is None

        # Omitting the baseline anchors to the sensor's live reading instead.
        call_service(ha, "home_keeper", "set_task_meter", {"task_id": task_id})
        live = _poll_task(ha, task_id, lambda t: t["sensor"].get("baseline") == 1000)
        assert live["completions"] == []
    finally:
        _delete(ha, task_id)
        _set_meter(ha, 0)


def _a_seeded_device_id(ha):
    """A device_id from a seeded task, so ours can own per-task entities.

    Home Keeper creates the per-task ``sensor.*_next_due`` entity only for a
    device-attached task (``coordinator.task_has_entities``), which is where the usage
    attributes ride. Rather than hard-code a registry id, reuse whatever device the
    seeded fixtures already attached a task to.
    """
    for task in _list_tasks(ha):
        if task.get("device_id"):
            return task["device_id"]
    raise AssertionError("no seeded device-attached task to borrow a device from")


def test_usage_progress_attributes_land_on_the_next_due_sensor(ha):
    _set_meter(ha, 1000)
    device_id = _a_seeded_device_id(ha)
    resp = call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": "Usage attributes test",
            "recurrence_type": "sensor",
            "device_id": device_id,
            "sensor": {
                "entity_id": METER,
                "mode": "usage",
                "target": 200,
                "unit": "h",
                "also_every": {"interval": 6, "unit": "months"},
                "combinator": "any",
            },
        },
        return_response=True,
    )
    task_id = resp.get("service_response", resp)["task_id"]
    try:
        _poll_task(ha, task_id, lambda t: t.get("sensor", {}).get("baseline") == 1000)
        _set_meter(ha, 1050)  # 50 of 200 used

        def _attrs():
            for state in ha.get(f"{HA_URL}/api/states").json():
                attrs = state.get("attributes", {})
                if attrs.get("task_id") == task_id and state["entity_id"].startswith(
                    "sensor."
                ):
                    return attrs
            return None

        deadline = time.monotonic() + 60
        attrs = None
        while time.monotonic() < deadline:
            attrs = _attrs()
            if attrs and attrs.get("usage_consumed") == 50:
                break
            time.sleep(1)
        assert attrs is not None, "no next-due sensor found for the task"
        assert attrs["usage_target"] == 200
        assert attrs["usage_consumed"] == 50
        assert attrs["usage_remaining"] == 150
        assert attrs["usage_percent"] == 25.0
        assert attrs["usage_unit"] == "h"
        assert attrs["backstop_due"]  # a real projected timestamp
    finally:
        _delete(ha, task_id)
        _set_meter(ha, 0)


# ── state mode (binary sensors) ──────────────────────────────────────────────
# `binary_sensor.hk_demo_water_tank_low` is a template sensor following
# `input_boolean.hk_demo_flag` (see ha_config/configuration.yaml), so flipping the
# boolean produces a genuine off -> on state-change event on a real binary sensor.
# That is the contract a unit test with a mocked state machine cannot see: an `on`
# state has no numeric reading, so before state mode existed the watcher skipped
# these entities entirely.
TANK = "binary_sensor.hk_demo_water_tank_low"
FLAG = "input_boolean.hk_demo_flag"


def _set_flag(ha, on):
    call_service(
        ha, "input_boolean", "turn_on" if on else "turn_off", {"entity_id": FLAG}
    )


def test_state_sensor_task_arms_when_a_binary_sensor_turns_on(ha):
    # Start clear so the task is created with the condition false.
    _set_flag(ha, False)
    task_id = _add_sensor_task(ha, {"entity_id": TANK, "mode": "state", "state": "on"})
    try:
        task = _poll_task(ha, task_id, lambda t: t.get("recurrence_type") == "sensor")
        assert task["next_due"] is None  # dormant while the tank is fine
        assert task["sensor"]["state"] == "on"

        # The tank empties -> rising edge arms the task.
        _set_flag(ha, True)
        armed = _poll_task(ha, task_id, lambda t: t.get("next_due") is not None)
        assert armed["next_due"] is not None

        # Filling it is a user action: the task is completable by hand and clears.
        call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
        cleared = _poll_task(ha, task_id, lambda t: t.get("next_due") is None)
        assert cleared["next_due"] is None
    finally:
        _delete(ha, task_id)
        _set_flag(ha, False)


def test_state_task_does_not_rearm_while_the_sensor_stays_on(ha):
    # The task arms once per *event*, not once per tick — otherwise "fill the water
    # tank" would come back the moment you completed it, since the tank is still
    # empty until you actually fill it.
    _set_flag(ha, False)
    task_id = _add_sensor_task(ha, {"entity_id": TANK, "mode": "state", "state": "on"})
    try:
        _poll_task(ha, task_id, lambda t: t.get("recurrence_type") == "sensor")
        _set_flag(ha, True)
        _poll_task(ha, task_id, lambda t: t.get("next_due") is not None)

        call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
        _poll_task(ha, task_id, lambda t: t.get("next_due") is None)

        # Still on, and it must stay dormant: no fresh crossing has happened.
        time.sleep(5)
        assert _get_task(ha, task_id)["next_due"] is None

        # Recover then trip again -> that *is* a fresh crossing, so it re-arms.
        _set_flag(ha, False)
        time.sleep(2)
        _set_flag(ha, True)
        rearmed = _poll_task(ha, task_id, lambda t: t.get("next_due") is not None)
        assert rearmed["next_due"] is not None
    finally:
        _delete(ha, task_id)
        _set_flag(ha, False)


def test_state_task_bound_to_a_non_binary_entity_matches_its_state(ha):
    # State mode compares the state string, so it is not binary-sensor-only. Bind to
    # the input_boolean itself and match "on".
    _set_flag(ha, False)
    task_id = _add_sensor_task(ha, {"entity_id": FLAG, "mode": "state", "state": "on"})
    try:
        task = _poll_task(ha, task_id, lambda t: t.get("recurrence_type") == "sensor")
        assert task["next_due"] is None
        _set_flag(ha, True)
        armed = _poll_task(ha, task_id, lambda t: t.get("next_due") is not None)
        assert armed["next_due"] is not None
    finally:
        _delete(ha, task_id)
        _set_flag(ha, False)


def test_clear_on_recover_completes_the_task_when_the_sensor_goes_back(ha):
    _set_flag(ha, False)
    task_id = _add_sensor_task(
        ha,
        {"entity_id": TANK, "mode": "state", "state": "on", "clear_on_recover": True},
    )
    try:
        _poll_task(ha, task_id, lambda t: t.get("recurrence_type") == "sensor")
        _set_flag(ha, True)
        _poll_task(ha, task_id, lambda t: t.get("next_due") is not None)

        # Somebody else filled the tank: the task clears itself, and records a real
        # completion so the history still shows the work happened.
        _set_flag(ha, False)
        cleared = _poll_task(ha, task_id, lambda t: t.get("next_due") is None)
        assert cleared["next_due"] is None
        assert cleared["last_completed"] is not None
        assert len(cleared.get("completions") or []) >= 1
    finally:
        _delete(ha, task_id)
        _set_flag(ha, False)


def test_without_clear_on_recover_the_task_stays_armed(ha):
    # The default: a task you have to go and do doesn't un-need doing because the
    # sensor recovered.
    _set_flag(ha, False)
    task_id = _add_sensor_task(ha, {"entity_id": TANK, "mode": "state", "state": "on"})
    try:
        _poll_task(ha, task_id, lambda t: t.get("recurrence_type") == "sensor")
        _set_flag(ha, True)
        _poll_task(ha, task_id, lambda t: t.get("next_due") is not None)

        _set_flag(ha, False)
        time.sleep(5)
        assert _get_task(ha, task_id)["next_due"] is not None
    finally:
        _delete(ha, task_id)
        _set_flag(ha, False)


def test_a_reload_with_the_sensor_already_on_does_not_rearm(ha):
    # The startup-baseline contract, and the reason `async_baseline` exists: an
    # already-matching sensor at setup is recorded as met *without* a crossing, so
    # restarting Home Assistant while the tank is still empty must not resurrect a
    # task you already dealt with. Reloading the config entry re-runs setup, which is
    # the same code path a restart takes.
    _set_flag(ha, False)
    task_id = _add_sensor_task(ha, {"entity_id": TANK, "mode": "state", "state": "on"})
    try:
        _poll_task(ha, task_id, lambda t: t.get("recurrence_type") == "sensor")
        _set_flag(ha, True)
        _poll_task(ha, task_id, lambda t: t.get("next_due") is not None)
        call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
        _poll_task(ha, task_id, lambda t: t.get("next_due") is None)

        # Reload with the sensor still on. No fresh crossing -> still dormant.
        call_service(
            ha,
            "homeassistant",
            "reload_config_entry",
            {"entity_id": "todo.home_keeper_tasks"},
        )
        time.sleep(10)
        assert _get_task(ha, task_id)["next_due"] is None
    finally:
        _delete(ha, task_id)
        _set_flag(ha, False)


# ── an explicit starting reading, and the reading recorded on completion (#235) ──


def test_an_explicit_baseline_is_not_overwritten_and_shows_progress_immediately(ha):
    # The reporter's case, in miniature: the meter is already at 100 and the last
    # service happened at 70, so a target of 50 must read "30 used" from the moment
    # the task exists and arm at 120 — not at 150.
    _set_meter(ha, 100)
    task_id = _add_sensor_task(
        ha,
        {"entity_id": METER, "mode": "usage", "target": 50, "baseline": 70},
    )
    try:
        # The watcher stamps a baseline only when there isn't one; an explicit
        # anchor has to survive both startup baselining and ordinary evaluation.
        task = _poll_task(
            ha, task_id, lambda t: t.get("sensor", {}).get("baseline") == 70
        )
        assert task["next_due"] is None, "30 of 50 used must not arm the task"

        # 119 is 49 past the anchor — still short.
        _set_meter(ha, 119)
        time.sleep(3)
        task = _get_task(ha, task_id)
        assert task["sensor"]["baseline"] == 70
        assert task["next_due"] is None

        # 120 is exactly target past the anchor.
        _set_meter(ha, 120)
        _poll_task(ha, task_id, lambda t: t.get("next_due") is not None)
    finally:
        _delete(ha, task_id)


def test_completing_a_usage_task_records_the_meter_reading_in_history(ha):
    _set_meter(ha, 200)
    task_id = _add_sensor_task(ha, {"entity_id": METER, "mode": "usage", "target": 10})
    try:
        _poll_task(ha, task_id, lambda t: t.get("sensor", {}).get("baseline") == 200)
        _set_meter(ha, 215)
        _poll_task(ha, task_id, lambda t: t.get("next_due") is not None)

        call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
        task = _poll_task(ha, task_id, lambda t: len(t.get("completions") or []) == 1)
        # The log says where the meter stood, and the anchor is the same number —
        # they are resolved once, so they cannot drift.
        assert task["completions"][0]["reading"] == 215
        assert task["sensor"]["baseline"] == 215
        assert task["next_due"] is None
    finally:
        _delete(ha, task_id)


def test_a_caller_supplied_reading_wins_over_the_live_one(ha):
    # Back-dating: the work happened at 300 but the meter has since moved to 340.
    # Recording today's reading would put an obviously wrong number in the log and
    # anchor the next interval 40 units late.
    _set_meter(ha, 250)
    task_id = _add_sensor_task(ha, {"entity_id": METER, "mode": "usage", "target": 10})
    try:
        _poll_task(ha, task_id, lambda t: t.get("sensor", {}).get("baseline") == 250)
        _set_meter(ha, 340)
        _poll_task(ha, task_id, lambda t: t.get("next_due") is not None)

        call_service(
            ha,
            "home_keeper",
            "complete_task",
            {
                "task_id": task_id,
                "completed_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
                "reading": 300,
            },
        )
        task = _poll_task(ha, task_id, lambda t: len(t.get("completions") or []) == 1)
        assert task["completions"][0]["reading"] == 300
        assert task["sensor"]["baseline"] == 300
    finally:
        _delete(ha, task_id)


def test_editing_the_latest_readings_re_anchors_the_meter(ha):
    # Ask #3: correcting the reading in the history has to move the anchor, or the
    # correction is cosmetic and the task still comes due at the wrong point.
    _set_meter(ha, 400)
    task_id = _add_sensor_task(ha, {"entity_id": METER, "mode": "usage", "target": 100})
    try:
        _poll_task(ha, task_id, lambda t: t.get("sensor", {}).get("baseline") == 400)
        call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
        task = _poll_task(ha, task_id, lambda t: len(t.get("completions") or []) == 1)
        ts = task["completions"][0]["ts"]
        assert task["completions"][0]["reading"] == 400

        call_service(
            ha,
            "home_keeper",
            "update_completion",
            {"task_id": task_id, "ts": ts, "reading": 350},
        )
        task = _poll_task(ha, task_id, lambda t: t["sensor"].get("baseline") == 350)
        assert task["completions"][0]["reading"] == 350
        # The timestamp itself is untouched — that is what move_completion is for.
        assert task["completions"][0]["ts"] == ts
    finally:
        _delete(ha, task_id)


def test_editing_an_older_completion_leaves_the_meter_alone(ha):
    # Only the latest completion defines the anchor, so amending an older row is
    # pure bookkeeping.
    _set_meter(ha, 500)
    task_id = _add_sensor_task(ha, {"entity_id": METER, "mode": "usage", "target": 100})
    try:
        _poll_task(ha, task_id, lambda t: t.get("sensor", {}).get("baseline") == 500)
        older = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        call_service(
            ha,
            "home_keeper",
            "complete_task",
            {"task_id": task_id, "completed_at": older, "reading": 450},
        )
        _set_meter(ha, 520)
        call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
        task = _poll_task(ha, task_id, lambda t: len(t.get("completions") or []) == 2)
        assert task["sensor"]["baseline"] == 520

        older_ts = min(c["ts"] for c in task["completions"])
        call_service(
            ha,
            "home_keeper",
            "update_completion",
            {"task_id": task_id, "ts": older_ts, "reading": 440},
        )
        time.sleep(3)
        task = _get_task(ha, task_id)
        assert task["sensor"]["baseline"] == 520, (
            "an older row must not move the anchor"
        )
        edited = next(c for c in task["completions"] if c["ts"] == older_ts)
        assert edited["reading"] == 440
    finally:
        _delete(ha, task_id)


def test_a_state_mode_task_records_no_reading(ha):
    # "on" is not a number, so there is nothing to log — and the field never appears.
    task_id = _add_sensor_task(
        ha,
        {
            "entity_id": "binary_sensor.hk_demo_water_tank_low",
            "mode": "state",
            "state": "on",
        },
    )
    try:
        call_service(ha, "home_keeper", "complete_task", {"task_id": task_id})
        task = _poll_task(ha, task_id, lambda t: len(t.get("completions") or []) == 1)
        assert "reading" not in task["completions"][0]
    finally:
        _delete(ha, task_id)
