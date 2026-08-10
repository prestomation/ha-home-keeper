"""Pure evaluation logic for sensor-based tasks (usage meters / numeric thresholds).

A sensor-based task (``recurrence_type == "sensor"``) carries a ``sensor`` binding
(see :func:`models.normalize_sensor`) and derives its armed/dormant state from a
live numeric reading. This module turns "the task's stored state + the current
reading + the prior edge state" into a single **decision** the store/watcher then
applies. It imports nothing from Home Assistant, so every branch — the comparison
operators, the meter delta, the rising-edge + hold detection, the meter-reset
re-baseline — is unit-testable with plain dicts and an injected ``now`` (the
HA-aware reading enumeration and state subscription live in ``sensor_watcher.py``).

Two modes:

* ``usage`` (a meter) — generalizes ``floating`` from elapsed *time* to elapsed
  sensor *units*: armed when ``reading - baseline >= target``. ``baseline`` is the
  reading captured at creation / last completion (the store resets it on completion);
  a reading below the baseline means the meter was reset/replaced, so we re-baseline
  rather than stay stuck. Stateless beyond the persisted ``baseline``. An optional
  ``also_every`` adds a **time backstop** so a usage task can express a real service
  interval — "every 300 hours *or* 6 months, whichever comes first" — with
  ``combinator`` choosing whichever-first (``any``) or both-required (``all``).
* ``threshold`` — armed on the ``false -> true`` rising edge of a comparison against
  a fixed value, after an optional ``for_seconds`` hold. The "was the condition true
  last tick" flag and the crossing timestamp are carried by the caller (held in
  coordinator memory, baselined on startup) so a restart never replays a spurious arm.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import recurrence
from .const import (
    REC_SENSOR,
    SENSOR_CMP_EQ,
    SENSOR_CMP_GE,
    SENSOR_CMP_GT,
    SENSOR_CMP_LE,
    SENSOR_CMP_LT,
    SENSOR_CMP_NE,
    SENSOR_COMBINATOR_ALL,
)

# Decision actions returned by the evaluators (the store/watcher dispatches on these):
ACTION_ARM = "arm"  # set next_due = now and fire EVENT_TASK_TRIGGERED
ACTION_REBASELINE = "rebaseline"  # persist a new usage baseline (silent bookkeeping)


def sensor_config(task: dict[str, Any]) -> dict[str, Any] | None:
    """Return the ``sensor`` binding of a sensor task, or ``None``."""
    if task.get("recurrence_type") != REC_SENSOR:
        return None
    cfg = task.get("sensor")
    return cfg if isinstance(cfg, dict) else None


def bound_entity_id(task: dict[str, Any]) -> str | None:
    """The entity id a sensor task is bound to, or ``None``."""
    cfg = sensor_config(task)
    return cfg.get("entity_id") if cfg else None


def parse_reading(raw: Any) -> float | None:
    """Coerce a raw state / attribute value to ``float``, or ``None`` if not numeric.

    ``unknown`` / ``unavailable`` / empty values come through as non-numeric and are
    reported as ``None`` so the caller skips evaluation (never arming/clearing on a
    missing reading).
    """
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def compare(reading: float, comparison: str, value: float) -> bool:
    """Evaluate ``reading <comparison> value`` for a threshold task."""
    if comparison == SENSOR_CMP_GE:
        return reading >= value
    if comparison == SENSOR_CMP_LE:
        return reading <= value
    if comparison == SENSOR_CMP_GT:
        return reading > value
    if comparison == SENSOR_CMP_LT:
        return reading < value
    if comparison == SENSOR_CMP_EQ:
        return reading == value
    if comparison == SENSOR_CMP_NE:
        return reading != value
    raise ValueError(f"unknown comparison: {comparison!r}")


def backstop_due(task: dict[str, Any], cfg: dict[str, Any]) -> datetime | None:
    """When a usage task's time backstop comes due, or ``None`` if it has none.

    The backstop measures time **since the last service**, so it is anchored to
    ``last_completed`` and falls back to the task's ``created`` timestamp while it has
    never been completed. (It is deliberately *not* anchored to the meter baseline: a
    meter reset — a replaced controller, a rolled-over counter — is not a service, and
    must not silently push the calendar half of the interval out.)
    """
    also_every = cfg.get("also_every")
    if not isinstance(also_every, dict):
        return None
    raw_anchor = task.get("last_completed") or task.get("created")
    if not raw_anchor:
        return None
    try:
        anchor = recurrence._parse(raw_anchor)
    except ValueError:
        return None
    if anchor is None:
        return None
    return recurrence.add_interval(
        anchor, int(also_every["interval"]), str(also_every["unit"])
    )


def evaluate_usage(
    task: dict[str, Any],
    *,
    reading: float | None,
    reset_candidate: float | None = None,
    now: datetime,
) -> dict[str, Any]:
    """Decide the action for a usage (meter) task given the live ``reading``.

    Returns a decision dict carrying both the action and the next
    ``reset_candidate`` edge state (the caller holds it across ticks, mirroring the
    threshold evaluator's carried edge state):

    * ``{"action": "rebaseline", "baseline": <reading>, "reset_candidate": None}`` —
      no baseline yet (fresh task), or a **second consecutive** below-baseline
      reading (a debounced meter reset / replacement); stamp the current reading and
      clear the candidate.
    * ``{"action": None, "reset_candidate": <reading>}`` — a *first* below-baseline
      reading. Don't re-baseline yet: a momentary sensor blip to 0 (or any transient
      dip) looks identical to a real reset, so we require it to persist for two ticks.
    * ``{"action": "arm", "reset_candidate": None}`` — dormant and the task's condition
      is met: the meter advanced ``target`` units past the baseline, and/or the time
      backstop elapsed, per ``combinator``.
    * ``{"action": None, "reset_candidate": None}`` — nothing to do; any pending
      reset candidate is cleared because this reading is at/above the baseline.

    Re-baselining is checked before arming, so a meter reset can never both reset and
    arm in the same evaluation.

    ``reading`` is **optional**: a task carrying a time backstop must still be able to
    come due while its bound entity is unavailable (a printer that's been unplugged for
    a year still needs its annual service). With no reading, the meter half simply can't
    be met and the baseline is left alone.
    """
    cfg = sensor_config(task)
    assert cfg is not None
    target = float(cfg["target"])
    raw_baseline = cfg.get("baseline")
    if reading is not None:
        if raw_baseline is None:
            return {
                "action": ACTION_REBASELINE,
                "baseline": reading,
                "reset_candidate": None,
            }
        if reading < float(raw_baseline):
            # Meter reset / rolled over / part replaced — but debounce it: a single
            # below-baseline reading may be a transient blip. Only re-anchor once a
            # prior tick already saw a below-baseline reading.
            if reset_candidate is not None:
                return {
                    "action": ACTION_REBASELINE,
                    "baseline": reading,
                    "reset_candidate": None,
                }
            return {"action": None, "reset_candidate": reading}
        # At/above baseline: any pending reset candidate was a blip — clear it.
        reset_candidate = None

    usage_met = (
        reading is not None
        and raw_baseline is not None
        and (reading - float(raw_baseline)) >= target
    )
    due_at = backstop_due(task, cfg)
    time_met = due_at is not None and now >= due_at
    if due_at is None:
        met = usage_met
    elif cfg.get("combinator") == SENSOR_COMBINATOR_ALL:
        met = usage_met and time_met
    else:
        met = usage_met or time_met

    armed = task.get("next_due") is not None
    if not armed and met:
        return {"action": ACTION_ARM, "reset_candidate": None}
    return {"action": None, "reset_candidate": reset_candidate}


def evaluate_threshold(
    task: dict[str, Any],
    *,
    reading: float,
    condition_met_prev: bool,
    crossed_at: datetime | None,
    now: datetime,
) -> dict[str, Any]:
    """Decide the action for a threshold task and return the next edge state.

    Returns ``{"action": "arm" | None, "condition_met": bool, "crossed_at": dt|None}``.

    ``crossed_at`` tracks an *unconsumed* rising edge: it is set when the comparison
    goes ``false -> true`` and cleared the moment the task arms (or the condition
    recovers). So the task arms once per genuine crossing, after the optional
    ``for_seconds`` hold, and never re-arms while the condition merely stays true
    (including the steady-true state after a completion) — only a fresh false -> true
    crossing arms it again. ``condition_met``/``crossed_at`` are the caller's carried
    edge state (in coordinator memory, baselined on startup so an already-true sensor
    at boot — recorded as ``condition_met=True, crossed_at=None`` — does not arm).
    """
    cfg = sensor_config(task)
    assert cfg is not None
    met = compare(reading, cfg["comparison"], float(cfg["value"]))
    for_seconds = int(cfg.get("for_seconds") or 0)
    armed = task.get("next_due") is not None

    if not met:
        # Below threshold: clear the hold so the next crossing starts fresh.
        return {"action": None, "condition_met": False, "crossed_at": None}

    # Condition is true. A rising edge starts a fresh (unconsumed) hold timer; a
    # continuation keeps whatever timer we had (``None`` once consumed/baselined).
    new_crossed_at = now if not condition_met_prev else crossed_at
    action = None
    if not armed and new_crossed_at is not None:
        held = (now - new_crossed_at).total_seconds()
        if held >= for_seconds:
            action = ACTION_ARM
            new_crossed_at = None  # consume this crossing so we don't re-arm on it
    return {"action": action, "condition_met": True, "crossed_at": new_crossed_at}
