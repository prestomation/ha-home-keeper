"""Home-Assistant-aware driver for sensor-based tasks.

Subscribes to the entities that sensor-based tasks are bound to, reads their live
values — numeric for ``usage``/``threshold``, the state string for ``state`` — and
feeds the pure evaluators in ``sensor_tasks.py`` to arm a task (via
``store.trigger_task``) or stamp/reset a usage baseline (via
``store.set_sensor_baseline``). Unlike ``problem_sync.py`` this is **evaluation
only**: sensor tasks are user-created, so there is no registry enumeration,
auto-creation/deletion, exclusion options, or entry reload — the watcher never
changes which tasks exist, only their armed/dormant state and meter baseline.

Edge state for the threshold/state modes (was-the-condition-true, when-it-crossed)
lives in this object's memory and is baselined on startup (``async_baseline``) so a
restart never replays a spurious arm — mirroring how the coordinator baselines the
overdue/due-soon transitions. Completion normally flows through the user surfaces; the
one exception is a binding with ``clear_on_recover``, where the watcher completes the
task itself (tagged ``ORIGIN_SENSOR_RECOVER``) once the condition goes away.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from . import sensor_tasks
from .const import (
    ORIGIN_SENSOR_RECOVER,
    REC_SENSOR,
    SENSOR_MODE_AVAILABILITY,
    SENSOR_MODE_STATE,
    SENSOR_MODE_THRESHOLD,
    SENSOR_MODE_USAGE,
)

if TYPE_CHECKING:
    from .coordinator import HomeKeeperCoordinator

_LOGGER = logging.getLogger(__name__)


def _raw_reading(hass: HomeAssistant, cfg: dict[str, Any] | None) -> Any | None:
    """The raw value a sensor binding points at, or ``None`` if there isn't one.

    Resolves the binding to a live value once — honouring the optional ``attribute``
    (read that attribute instead of the state) and rejecting a missing / unavailable /
    unknown entity — so the numeric and state readers can't disagree about what
    "there is no reading" means.
    """
    if not cfg:
        return None
    entity_id = cfg.get("entity_id")
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, "", None):
        return None
    attribute = cfg.get("attribute")
    return state.attributes.get(attribute) if attribute else state.state


def read_sensor_value(hass: HomeAssistant, cfg: dict[str, Any] | None) -> float | None:
    """Read the live numeric value a sensor binding points at, or ``None``.

    Returns ``None`` for a missing / unavailable / non-numeric entity so callers skip
    evaluation rather than arm on bad data.
    """
    return sensor_tasks.parse_reading(_raw_reading(hass, cfg))


def read_sensor_state(hass: HomeAssistant, cfg: dict[str, Any] | None) -> str | None:
    """Read the live **state string** a sensor binding points at, or ``None``.

    The ``state`` mode's counterpart to :func:`read_sensor_value`: a binary sensor
    reports ``on``/``off``, which has no numeric reading at all. An attribute value is
    coerced to ``str`` so an attribute holding a bool/number still compares against the
    binding's stored state.
    """
    raw = _raw_reading(hass, cfg)
    return None if raw is None else str(raw)


def read_availability_status(
    hass: HomeAssistant, cfg: dict[str, Any] | None
) -> str:
    """Classify a binding's *availability*: available / unavailable / missing.

    The ``availability`` mode's counterpart to :func:`read_sensor_value` and
    :func:`read_sensor_state`, and **inverts** the "no reading = do nothing" policy
    those two share: this mode arms *because* the entity is unavailable/unknown,
    so the caller needs to distinguish "entity is unreachable" (arm signal) from
    "entity is not yet loaded" (indeterminate; hold edge state so a boot-time gap
    can never fabricate a spurious arm or clear).

    * ``"missing"`` — the binding has no entity_id, or the entity isn't in the
      state machine yet (restored on boot / never seen). Indeterminate.
    * ``"unavailable"`` — the entity is present but reporting ``unavailable`` /
      ``unknown``; or an attribute binding whose target attribute is missing or
      ``None``. The arm signal.
    * ``"available"`` — the entity has a real state and (if an attribute is
      bound) the attribute has a real value.

    Mirrors ``problem_sync._is_problem``'s three-way discipline.
    """
    if not cfg:
        return sensor_tasks.AVAILABILITY_MISSING
    entity_id = cfg.get("entity_id")
    if not entity_id:
        return sensor_tasks.AVAILABILITY_MISSING
    state = hass.states.get(entity_id)
    if state is None:
        return sensor_tasks.AVAILABILITY_MISSING
    if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, "", None):
        return sensor_tasks.AVAILABILITY_UNAVAILABLE
    attribute = cfg.get("attribute")
    if attribute:
        value = state.attributes.get(attribute)
        if value is None or value == "":
            return sensor_tasks.AVAILABILITY_UNAVAILABLE
    return sensor_tasks.AVAILABILITY_AVAILABLE


class SensorTaskWatcher:
    """Evaluates sensor-based tasks against their bound entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: HomeKeeperCoordinator,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._unsub_state: CALLBACK_TYPE | None = None
        self._tracked: tuple[str, ...] = ()
        # In-memory threshold edge state, keyed by task id:
        #   {"condition_met": bool, "crossed_at": datetime | None}
        self._edge: dict[str, dict[str, Any]] = {}
        # In-memory usage-meter reset-candidate state, keyed by task id: the reading
        # from a prior below-baseline tick, awaiting a second consecutive one before
        # we treat it as a genuine meter reset (debounces a transient dip/blip to 0).
        # Held in memory only — never persisted — so a restart safely re-evaluates
        # from the current reading rather than acting on a half-seen reset.
        self._usage_reset: dict[str, float | None] = {}

    # ── task / entity enumeration ──────────────────────────────────────────────
    def _sensor_tasks(self) -> dict[str, dict[str, Any]]:
        """Enabled sensor-based tasks, keyed by id."""
        return {
            tid: task
            for tid, task in self._coordinator.store.get_tasks().items()
            if task.get("recurrence_type") == REC_SENSOR and task.get("enabled", True)
        }

    def _bound_entities(self) -> tuple[str, ...]:
        ids = {
            eid
            for task in self._sensor_tasks().values()
            if (eid := sensor_tasks.bound_entity_id(task))
        }
        return tuple(sorted(ids))

    # ── lifecycle ──────────────────────────────────────────────────────────────
    async def async_baseline(self) -> None:
        """Baseline edge state and usage baselines without arming anything.

        Called once during setup (before the watcher is attached to the coordinator)
        so the first evaluation only reacts to genuine transitions: a threshold sensor
        already above its limit at boot is recorded as already-met (no rising edge), and
        a usage task with no baseline yet is anchored to the current reading.
        """
        for tid, task in self._sensor_tasks().items():
            cfg = sensor_tasks.sensor_config(task)
            if cfg is None:
                continue
            mode = cfg.get("mode")
            if mode == SENSOR_MODE_THRESHOLD:
                reading = read_sensor_value(self._hass, cfg)
                met = reading is not None and sensor_tasks.compare(
                    reading, cfg["comparison"], float(cfg["value"])
                )
                self._edge[tid] = {"condition_met": met, "crossed_at": None}
            elif mode == SENSOR_MODE_STATE:
                # Record an already-matching sensor as met-without-a-crossing, so a
                # vacuum still reporting "water tank low" across a restart doesn't
                # re-arm a task the user already dealt with.
                self._edge[tid] = {
                    "condition_met": read_sensor_state(self._hass, cfg)
                    == cfg.get("state"),
                    "crossed_at": None,
                }
            elif mode == SENSOR_MODE_AVAILABILITY:
                # Record an already-unavailable entity as met-without-a-crossing:
                # a device that was offline before HA restarted must not fabricate a
                # fresh "gone offline" task the first time we look at it. A ``missing``
                # (not-yet-loaded) entity is indeterminate — treat as not-met so a
                # genuine transition later drives the arm.
                status = read_availability_status(self._hass, cfg)
                self._edge[tid] = {
                    "condition_met": status == sensor_tasks.AVAILABILITY_UNAVAILABLE,
                    "crossed_at": None,
                }
            else:
                reading = read_sensor_value(self._hass, cfg)
                if reading is not None and cfg.get("baseline") is None:
                    await self._coordinator.store.set_sensor_baseline(tid, reading)

    @callback
    def async_start_listeners(self) -> None:
        """Begin reacting to bound-entity state changes (torn down on unload)."""
        self._entry.async_on_unload(self._unsubscribe_state)
        self._resubscribe_state()

    @callback
    def _unsubscribe_state(self) -> None:
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None

    @callback
    def _resubscribe_state(self) -> None:
        """(Re)point the state listener at the currently bound entity set."""
        tracked = self._bound_entities()
        if tracked == self._tracked:
            return
        self._unsubscribe_state()
        self._tracked = tracked
        if tracked:
            self._unsub_state = async_track_state_change_event(
                self._hass, list(tracked), self._handle_state_change
            )

    @callback
    def _handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        # A bound sensor moved — evaluate (and request a refresh so any new arming
        # surfaces as overdue/due-soon immediately, outside the periodic tick).
        self._hass.async_create_task(self.async_evaluate(refresh=True))

    # ── evaluation ─────────────────────────────────────────────────────────────
    async def async_evaluate(self, *, refresh: bool) -> None:
        """Evaluate every sensor task once, applying arm / re-baseline decisions.

        ``refresh`` requests a coordinator refresh when something armed — set from the
        state-change path (which runs outside the coordinator cycle). The periodic
        coordinator tick passes ``refresh=False`` because it runs the transition
        detection itself, immediately after, in the same cycle.
        """
        # Keep the subscription aligned with the live task set (a task may have been
        # added/edited/removed since we last subscribed).
        self._resubscribe_state()
        now = dt_util.now()
        changed_any = False
        for tid, task in self._sensor_tasks().items():
            cfg = sensor_tasks.sensor_config(task)
            if cfg is None:
                continue
            mode = cfg.get("mode")
            if mode == SENSOR_MODE_STATE:
                # A missing state is handled inside the evaluator (it holds the edge
                # state rather than reading a dropout as a recovery), so unlike the
                # numeric modes there's nothing to skip here.
                if await self._evaluate_state(
                    tid, task, state=read_sensor_state(self._hass, cfg), now=now
                ):
                    changed_any = True
                continue
            if mode == SENSOR_MODE_AVAILABILITY:
                # Availability inverts the "no reading" policy: an ``unavailable``
                # entity is the arm signal here, not something to skip. The evaluator
                # holds edge state on ``missing`` (not-yet-loaded), so boot doesn't
                # fabricate transitions.
                if await self._evaluate_availability(
                    tid,
                    task,
                    status=read_availability_status(self._hass, cfg),
                    now=now,
                ):
                    changed_any = True
                continue
            reading = read_sensor_value(self._hass, cfg)
            if mode == SENSOR_MODE_USAGE:
                # A usage task with a time backstop must still be evaluable with no
                # reading — an appliance that's been offline for a year still owes its
                # annual service. Without one there's nothing a missing reading can
                # decide, so skip rather than churn.
                if reading is None and not cfg.get("also_every"):
                    continue
                if await self._evaluate_usage(tid, task, reading=reading, now=now):
                    changed_any = True
            else:
                if reading is None:
                    continue  # unavailable / non-numeric — never arm on bad data
                if await self._evaluate_threshold(tid, task, reading=reading, now=now):
                    changed_any = True
        # Drop edge state for tasks that no longer exist so it can't leak.
        live = set(self._sensor_tasks())
        for stale in [tid for tid in self._edge if tid not in live]:
            del self._edge[stale]
        for stale in [tid for tid in self._usage_reset if tid not in live]:
            del self._usage_reset[stale]
        if changed_any and refresh:
            await self._coordinator.async_request_refresh()

    async def _evaluate_usage(
        self, tid: str, task: dict[str, Any], *, reading: float | None, now: Any
    ) -> bool:
        decision = sensor_tasks.evaluate_usage(
            task,
            reading=reading,
            reset_candidate=self._usage_reset.get(tid),
            now=now,
        )
        self._usage_reset[tid] = decision["reset_candidate"]
        action = decision["action"]
        if action == sensor_tasks.ACTION_REBASELINE:
            await self._coordinator.store.set_sensor_baseline(tid, decision["baseline"])
            return False
        if action == sensor_tasks.ACTION_ARM:
            await self._coordinator.store.trigger_task(tid)
            return True
        return False

    async def _evaluate_threshold(
        self, tid: str, task: dict[str, Any], *, reading: float, now: Any
    ) -> bool:
        return await self._apply_edge(
            tid,
            sensor_tasks.evaluate_threshold(
                task,
                reading=reading,
                condition_met_prev=bool(self._edge.get(tid, {}).get("condition_met")),
                crossed_at=self._edge.get(tid, {}).get("crossed_at"),
                now=now,
            ),
        )

    async def _evaluate_state(
        self, tid: str, task: dict[str, Any], *, state: str | None, now: Any
    ) -> bool:
        return await self._apply_edge(
            tid,
            sensor_tasks.evaluate_state(
                task,
                state=state,
                condition_met_prev=bool(self._edge.get(tid, {}).get("condition_met")),
                crossed_at=self._edge.get(tid, {}).get("crossed_at"),
                now=now,
            ),
        )

    async def _evaluate_availability(
        self, tid: str, task: dict[str, Any], *, status: str, now: Any
    ) -> bool:
        return await self._apply_edge(
            tid,
            sensor_tasks.evaluate_availability(
                task,
                status=status,
                condition_met_prev=bool(self._edge.get(tid, {}).get("condition_met")),
                crossed_at=self._edge.get(tid, {}).get("crossed_at"),
                now=now,
            ),
        )

    async def _apply_edge(self, tid: str, decision: dict[str, Any]) -> bool:
        """Carry an edge decision's state forward and apply its action.

        Returns whether the task's due-state changed. A ``clear_on_recover`` clear
        counts as much as an arming: the task drops off the overdue surfaces, and that
        should show up immediately rather than at the next periodic tick.
        """
        self._edge[tid] = {
            "condition_met": decision["condition_met"],
            "crossed_at": decision["crossed_at"],
        }
        action = decision["action"]
        if action == sensor_tasks.ACTION_ARM:
            await self._coordinator.store.trigger_task(tid)
            return True
        if action == sensor_tasks.ACTION_CLEAR:
            # The condition went away on its own, so the work is done: record a real
            # completion (history, events, the todo/calendar surfaces all follow) and
            # tag it so an automation can tell it apart from someone pressing Done.
            await self._coordinator.store.complete_task(
                tid, origin=ORIGIN_SENSOR_RECOVER
            )
            return True
        return False
