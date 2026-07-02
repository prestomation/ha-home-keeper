"""Home-Assistant-aware driver for sensor-based tasks.

Subscribes to the entities that sensor-based tasks are bound to, reads their live
numeric values, and feeds the pure evaluators in ``sensor_tasks.py`` to arm a task
(via ``store.trigger_task``) or stamp/reset a usage baseline (via
``store.set_sensor_baseline``). Unlike ``problem_sync.py`` this is **evaluation
only**: sensor tasks are user-created, so there is no registry enumeration,
auto-creation/deletion, exclusion options, or entry reload — the watcher never
changes which tasks exist, only their armed/dormant state and meter baseline.

Edge state for threshold tasks (was-the-condition-true, when-it-crossed) lives in
this object's memory and is baselined on startup (``async_baseline``) so a restart
never replays a spurious arm — mirroring how the coordinator baselines the
overdue/due-soon transitions. Completion (the only thing that clears a sensor task)
flows through the normal user surfaces; the watcher does not clear tasks.
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
from .const import REC_SENSOR, SENSOR_MODE_THRESHOLD, SENSOR_MODE_USAGE

if TYPE_CHECKING:
    from .coordinator import HomeKeeperCoordinator

_LOGGER = logging.getLogger(__name__)


def read_sensor_value(hass: HomeAssistant, cfg: dict[str, Any] | None) -> float | None:
    """Read the live numeric value a sensor binding points at, or ``None``.

    Honours the optional ``attribute`` (reads that attribute instead of the state) and
    returns ``None`` for a missing / unavailable / non-numeric entity so callers skip
    evaluation rather than arm on bad data.
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
    raw = state.attributes.get(attribute) if attribute else state.state
    return sensor_tasks.parse_reading(raw)


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
            reading = read_sensor_value(self._hass, cfg)
            if cfg.get("mode") == SENSOR_MODE_THRESHOLD:
                met = reading is not None and sensor_tasks.compare(
                    reading, cfg["comparison"], float(cfg["value"])
                )
                self._edge[tid] = {"condition_met": met, "crossed_at": None}
            elif reading is not None and cfg.get("baseline") is None:
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
        armed_any = False
        for tid, task in self._sensor_tasks().items():
            cfg = sensor_tasks.sensor_config(task)
            if cfg is None:
                continue
            reading = read_sensor_value(self._hass, cfg)
            if reading is None:
                continue  # unavailable / non-numeric — never arm on bad data
            if cfg.get("mode") == SENSOR_MODE_USAGE:
                if await self._evaluate_usage(tid, task, reading=reading, now=now):
                    armed_any = True
            else:
                if await self._evaluate_threshold(tid, task, reading=reading, now=now):
                    armed_any = True
        # Drop edge state for tasks that no longer exist so it can't leak.
        live = set(self._sensor_tasks())
        for stale in [tid for tid in self._edge if tid not in live]:
            del self._edge[stale]
        for stale in [tid for tid in self._usage_reset if tid not in live]:
            del self._usage_reset[stale]
        if armed_any and refresh:
            await self._coordinator.async_request_refresh()

    async def _evaluate_usage(
        self, tid: str, task: dict[str, Any], *, reading: float, now: Any
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
        edge = self._edge.get(tid, {"condition_met": False, "crossed_at": None})
        decision = sensor_tasks.evaluate_threshold(
            task,
            reading=reading,
            condition_met_prev=bool(edge.get("condition_met")),
            crossed_at=edge.get("crossed_at"),
            now=now,
        )
        self._edge[tid] = {
            "condition_met": decision["condition_met"],
            "crossed_at": decision["crossed_at"],
        }
        if decision["action"] == sensor_tasks.ACTION_ARM:
            await self._coordinator.store.trigger_task(tid)
            return True
        return False
