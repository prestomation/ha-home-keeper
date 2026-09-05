"""Pure evaluation logic for sensor-based tasks (usage meters / numeric thresholds).

A sensor-based task (``recurrence_type == "sensor"``) carries a ``sensor`` binding
(see :func:`models.normalize_sensor`) and derives its armed/dormant state from a
live numeric reading. This module turns "the task's stored state + the current
reading + the prior edge state" into a single **decision** the store/watcher then
applies. It imports nothing from Home Assistant, so every branch — the comparison
operators, the meter delta, the rising-edge + hold detection, the meter-reset
re-baseline — is unit-testable with plain dicts and an injected ``now`` (the
HA-aware reading enumeration and state subscription live in ``sensor_watcher.py``).

Three modes:

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
* ``state`` — the same rising edge, but the condition is ``entity state == state``
  rather than a numeric comparison. This is what makes a **binary sensor** usable: a
  robot vacuum's "water tank low" or a device's ``battery_almost_empty`` report
  ``on``/``off``, so the numeric modes can never see them. Because it compares the
  state *string* it is not binary-only — ``vacuum.x == "docked"`` works the same way.

``threshold`` and ``state`` differ only in how "is the condition true right now" is
computed, so the edge machinery they share — rising-edge detection, the hold timer,
consuming a crossing so a steady-true sensor never re-arms, and the optional
``clear_on_recover`` — lives once in :func:`_evaluate_edge` and both delegate to it.

Every edge decision also reports **when its pending hold completes**
(:func:`hold_due_at`). A hold ends in its own time, so the watcher books one
re-evaluation for that moment. It does not wait for a state change, which a quiet — or
absent — entity never sends.
"""

from __future__ import annotations

from datetime import datetime, timedelta
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
    SENSOR_MODE_AVAILABILITY,
    SENSOR_MODE_STATE,
    SENSOR_MODE_THRESHOLD,
    SENSOR_MODE_USAGE,
)

# Decision actions returned by the evaluators (the store/watcher dispatches on these):
ACTION_ARM = "arm"  # set next_due = now and fire EVENT_TASK_TRIGGERED
ACTION_REBASELINE = "rebaseline"  # persist a new usage baseline (silent bookkeeping)
# Clear an armed threshold/state task because its condition recovered and the binding
# opted into ``clear_on_recover``. The watcher applies it as a real completion.
ACTION_CLEAR = "clear"


# The modes whose decision needs carried edge state (was the condition true last
# tick, when did it cross). ``usage`` is the odd one out: it compares the live
# reading against a persisted ``baseline``, so it carries no edge at all.
_EDGE_MODES = (SENSOR_MODE_THRESHOLD, SENSOR_MODE_STATE, SENSOR_MODE_AVAILABILITY)


def holds_edge_state(mode: Any) -> bool:
    """Whether a binding in *mode* carries rising-edge state between evaluations.

    The watcher baselines that edge state on startup so an already-true condition
    does not replay as a fresh crossing. A task made after the last baseline pass
    must be left out of it, and this is the test that says which tasks have an edge
    to leave out. An unknown mode reads as ``usage`` everywhere else, so it reads as
    "no edge" here too.
    """
    return mode in _EDGE_MODES


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


def baseline_after_delete(
    task: dict[str, Any],
    removed_entry: dict[str, Any] | None,
    *,
    was_latest: bool,
) -> tuple[bool, float | None]:
    """Decide a usage meter's baseline after a completion is undone.

    Completing a usage task moves ``sensor.baseline`` forward to the completion
    reading (see ``store._reset_usage_baseline``), so undoing that completion must
    put the baseline back where it was — otherwise the partial progress the user had
    (3,000 of 10,000 miles) stays lost at zero. Only the **latest** completion
    anchors the meter, so undoing an older row is pure bookkeeping and leaves the
    baseline alone.

    *task* is the task **after** the entry was removed (its ``completions`` no longer
    include *removed_entry*); *removed_entry* is the entry that was deleted; and
    *was_latest* is whether that entry was the anchor (its ``ts`` equalled
    ``last_completed``) before removal.

    Returns ``(should_set, new_baseline)``:

    * ``(False, None)`` — leave ``sensor.baseline`` untouched (not a usage task, or
      an older row was undone).
    * ``(True, value)`` — set ``sensor.baseline`` to *value*. The value is the
      baseline the undone completion had replaced, recorded on it as ``meter_start``
      when it was completed. A completion recorded before that field existed has no
      ``meter_start``; fall back to the now-latest remaining completion's ``reading``
      (which is what the baseline would have been anchored to), or ``None`` when no
      completion remains — clearing the baseline so the watcher re-anchors on its
      next valid reading rather than measuring from a stale figure.
    """
    cfg = sensor_config(task)
    if cfg is None or cfg.get("mode") != SENSOR_MODE_USAGE or not was_latest:
        return (False, None)
    if removed_entry is not None and "meter_start" in removed_entry:
        return (True, removed_entry.get("meter_start"))
    # Backward compatibility: an entry stamped before ``meter_start`` existed. The
    # baseline was anchored to the reading at the previous completion, which is the
    # latest one still in the history now.
    latest_ts = task.get("last_completed")
    latest = next(
        (c for c in task.get("completions", []) if c.get("ts") == latest_ts), None
    )
    return (True, (latest or {}).get("reading"))


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


def hold_due_at(
    task: dict[str, Any], *, crossed_at: datetime | None, now: datetime
) -> datetime | None:
    """When a pending ``for_seconds`` hold completes, or ``None`` if none is pending.

    A hold is pending when the task carries an unconsumed crossing (*crossed_at*), is
    still dormant, and that crossing is younger than ``for_seconds``. The caller books
    one re-evaluation for the returned moment, because the hold ends in its own time.
    A bound entity that has gone quiet — or gone away, which is the very thing the
    ``availability`` mode watches for — sends no further state change, so without that
    booking the task waits for whatever periodic pass comes next.

    A hold that is already due returns ``None``. A timer cannot help there: the same
    evaluation arms the task if it can, so only new information about the entity moves
    a task that stayed dormant. This is what keeps an indeterminate reading (see
    :func:`evaluate_state` and :func:`evaluate_availability`) from booking the same
    past moment again and again.
    """
    cfg = sensor_config(task)
    if cfg is None or crossed_at is None or task.get("next_due") is not None:
        return None
    due = crossed_at + timedelta(seconds=int(cfg.get("for_seconds") or 0))
    return due if due > now else None


def _evaluate_edge(
    task: dict[str, Any],
    cfg: dict[str, Any],
    *,
    met: bool,
    condition_met_prev: bool,
    crossed_at: datetime | None,
    now: datetime,
) -> dict[str, Any]:
    """Shared rising-edge + hold machinery for the ``threshold`` and ``state`` modes.

    Both modes answer the same question — "has the condition just become true, and has
    it stayed true long enough?" — and differ only in how *met* was computed, so the
    edge logic lives here once rather than in two copies that can drift.

    Returns ``{"action": "arm" | "clear" | None, "condition_met": bool,
    "crossed_at": dt|None, "hold_due_at": dt|None}``. ``hold_due_at`` is when the
    caller must evaluate this task again for its hold to complete (see
    :func:`hold_due_at`).

    ``crossed_at`` tracks an *unconsumed* rising edge: it is set when the condition
    goes ``false -> true`` and cleared the moment the task arms (or the condition
    recovers). So the task arms once per genuine crossing, after the optional
    ``for_seconds`` hold, and never re-arms while the condition merely stays true
    (including the steady-true state after a completion) — only a fresh false -> true
    crossing arms it again. ``condition_met``/``crossed_at`` are the caller's carried
    edge state (in coordinator memory, baselined on startup so an already-true sensor
    at boot — recorded as ``condition_met=True, crossed_at=None`` — does not arm).

    When the binding sets ``clear_on_recover``, a *falling* edge on an armed task also
    clears it (problem-sensor-mirror behaviour), so "fill the water tank" resolves
    itself if the tank is refilled without anyone pressing Done.
    """
    for_seconds = int(cfg.get("for_seconds") or 0)
    armed = task.get("next_due") is not None

    if not met:
        # Condition false: clear the hold so the next crossing starts fresh. An armed
        # task also clears itself if it opted in — the work stopped being needed.
        action = ACTION_CLEAR if armed and cfg.get("clear_on_recover") else None
        return {
            "action": action,
            "condition_met": False,
            "crossed_at": None,
            "hold_due_at": None,
        }

    # Condition is true. A rising edge starts a fresh (unconsumed) hold timer; a
    # continuation keeps whatever timer we had (``None`` once consumed/baselined).
    new_crossed_at = now if not condition_met_prev else crossed_at
    action = None
    if not armed and new_crossed_at is not None:
        held = (now - new_crossed_at).total_seconds()
        if held >= for_seconds:
            action = ACTION_ARM
            new_crossed_at = None  # consume this crossing so we don't re-arm on it
    return {
        "action": action,
        "condition_met": True,
        "crossed_at": new_crossed_at,
        "hold_due_at": hold_due_at(task, crossed_at=new_crossed_at, now=now),
    }


def evaluate_threshold(
    task: dict[str, Any],
    *,
    reading: float,
    condition_met_prev: bool,
    crossed_at: datetime | None,
    now: datetime,
) -> dict[str, Any]:
    """Decide the action for a threshold task and return the next edge state.

    The condition is the binding's numeric ``comparison`` against ``value``; see
    :func:`_evaluate_edge` for the edge/hold semantics and the returned shape.
    """
    cfg = sensor_config(task)
    assert cfg is not None
    return _evaluate_edge(
        task,
        cfg,
        met=compare(reading, cfg["comparison"], float(cfg["value"])),
        condition_met_prev=condition_met_prev,
        crossed_at=crossed_at,
        now=now,
    )


def evaluate_state(
    task: dict[str, Any],
    *,
    state: str | None,
    condition_met_prev: bool,
    crossed_at: datetime | None,
    now: datetime,
) -> dict[str, Any]:
    """Decide the action for a ``state`` task and return the next edge state.

    The condition is ``state == cfg["state"]`` — a plain string comparison, which is
    what lets a binary sensor (``on``/``off``) drive a task at all. See
    :func:`_evaluate_edge` for the edge/hold semantics and the returned shape.

    ``state`` is ``None`` when the bound entity is missing, ``unavailable`` or
    ``unknown``. That is **not** a recovery: treating a Zigbee dropout as "the
    condition went away" would silently complete every ``clear_on_recover`` task the
    first time its device fell off the mesh. A ``None`` state therefore holds the
    carried edge state exactly as it was and decides nothing.
    """
    cfg = sensor_config(task)
    assert cfg is not None
    if state is None:
        return {
            "action": None,
            "condition_met": condition_met_prev,
            "crossed_at": crossed_at,
            "hold_due_at": hold_due_at(task, crossed_at=crossed_at, now=now),
        }
    return _evaluate_edge(
        task,
        cfg,
        met=state == cfg["state"],
        condition_met_prev=condition_met_prev,
        crossed_at=crossed_at,
        now=now,
    )


# Availability statuses computed by ``sensor_watcher._availability_status`` and fed
# to :func:`evaluate_availability`. Kept as string constants (not a bool) because a
# missing entity (``"missing"``) is neither available nor unavailable — it's the
# "not yet loaded" indeterminate state that must not trigger a transition.
AVAILABILITY_AVAILABLE = "available"
AVAILABILITY_UNAVAILABLE = "unavailable"
AVAILABILITY_MISSING = "missing"


def evaluate_availability(
    task: dict[str, Any],
    *,
    status: str,
    condition_met_prev: bool,
    crossed_at: datetime | None,
    now: datetime,
) -> dict[str, Any]:
    """Decide the action for an ``availability`` task and return the next edge state.

    The condition is "the entity is unavailable" (``status == "unavailable"``). This
    is the mirror of :func:`evaluate_state` — same edge/hold machinery, opposite
    interpretation of "no reading": unavailability is the *signal*, not something to
    ignore. See :func:`_evaluate_edge` for the returned shape.

    ``status == "missing"`` is indeterminate (the entity is not yet loaded — e.g.
    early in HA startup) and holds the carried edge state exactly as it was, so a
    boot-time gap can never fabricate a spurious arm or clear. Mirrors the
    ``problem_sync`` "indeterminate does not fabricate" invariant.
    """
    cfg = sensor_config(task)
    assert cfg is not None
    if status == AVAILABILITY_MISSING:
        return {
            "action": None,
            "condition_met": condition_met_prev,
            "crossed_at": crossed_at,
            "hold_due_at": hold_due_at(task, crossed_at=crossed_at, now=now),
        }
    return _evaluate_edge(
        task,
        cfg,
        met=status == AVAILABILITY_UNAVAILABLE,
        condition_met_prev=condition_met_prev,
        crossed_at=crossed_at,
        now=now,
    )
