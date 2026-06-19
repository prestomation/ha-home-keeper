"""Home-Assistant-aware orchestration for problem-sensor syncing.

Enumerates the eligible ``device_class: problem`` binary sensors (honouring the
options-flow exclusions and skipping Home Keeper's *own* entities so our per-task
overdue sensors can't feed back into the sync), drives the store reconciler, and
keeps the mirror live by listening for sensor state changes and entity-registry
updates. The pure create/arm/clear/orphan diff lives in ``problem_tasks.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    DOMAIN,
    OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS,
    OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS,
    OPTION_SYNC_PROBLEM_SENSORS,
)

_LOGGER = logging.getLogger(__name__)

_BINARY_SENSOR_DOMAIN = "binary_sensor"


class ProblemSensorSync:
    """Maintains the triggered tasks mirroring problem binary sensors."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, coordinator: Any
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._unsub_state: CALLBACK_TYPE | None = None
        self._tracked: tuple[str, ...] = ()
        self._reload_scheduled = False

    @property
    def _enabled(self) -> bool:
        return bool(self._entry.options.get(OPTION_SYNC_PROBLEM_SENSORS, False))

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def async_initial_reconcile(self) -> None:
        """Reconcile once during setup (before platforms forward; never reloads)."""
        await self._coordinator.store.reconcile_problem_sensor_tasks(
            self._eligible(), config_entry_id=self._entry.entry_id
        )

    @callback
    def async_start_listeners(self) -> None:
        """Begin reacting to sensor state changes and registry updates.

        Subscriptions are registered via ``entry.async_on_unload`` so they are torn
        down automatically on unload/reload — no explicit stop needed.
        """
        self._entry.async_on_unload(self._unsubscribe_state)
        self._entry.async_on_unload(
            self._hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._handle_registry_update
            )
        )
        self._resubscribe_state()

    @callback
    def _unsubscribe_state(self) -> None:
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None

    @callback
    def _resubscribe_state(self) -> None:
        """(Re)point the state listener at the current eligible entity set."""
        tracked = tuple(sorted(self._eligible())) if self._enabled else ()
        if tracked == self._tracked:
            return
        self._unsubscribe_state()
        self._tracked = tracked
        if tracked:
            self._unsub_state = async_track_state_change_event(
                self._hass, list(tracked), self._handle_state_change
            )

    # ── eligibility ──────────────────────────────────────────────────────────
    def _eligible(self) -> dict[str, dict[str, Any]]:
        """Map ``entity_id`` -> sync metadata for every sensor we should mirror.

        Empty when syncing is off (so a reconcile removes all synced tasks).
        """
        if not self._enabled:
            return {}
        opts = self._entry.options
        exclude_entities = set(opts.get(OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES, []))
        exclude_areas = set(opts.get(OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS, []))
        exclude_labels = set(opts.get(OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS, []))

        ent_reg = er.async_get(self._hass)
        dev_reg = dr.async_get(self._hass)
        eligible: dict[str, dict[str, Any]] = {}
        for entry in ent_reg.entities.values():
            if entry.domain != _BINARY_SENSOR_DOMAIN:
                continue
            # Loop guard: never mirror Home Keeper's own entities (a per-task overdue
            # binary sensor could itself carry device_class problem).
            if entry.platform == DOMAIN:
                continue
            device_class = entry.device_class or entry.original_device_class
            if device_class != BinarySensorDeviceClass.PROBLEM:
                continue
            if entry.disabled or entry.entity_id in exclude_entities:
                continue
            device = dev_reg.async_get(entry.device_id) if entry.device_id else None
            area_id = entry.area_id or (device.area_id if device else None)
            if area_id in exclude_areas:
                continue
            labels = set(entry.labels) | (set(device.labels) if device else set())
            if labels & exclude_labels:
                continue
            eligible[entry.entity_id] = {
                "name": self._task_name(entry),
                "device_id": entry.device_id,
                "area_id": area_id,
                "is_problem": self._is_problem(entry.entity_id),
            }
        return eligible

    def _task_name(self, entry: er.RegistryEntry) -> str:
        """Friendly task name: prefer the live state's friendly_name."""
        state = self._hass.states.get(entry.entity_id)
        if state is not None:
            friendly = state.attributes.get("friendly_name")
            if friendly:
                return str(friendly)
        return entry.name or entry.original_name or entry.entity_id

    def _is_problem(self, entity_id: str) -> bool:
        state = self._hass.states.get(entity_id)
        return state is not None and state.state == STATE_ON

    # ── live updates ─────────────────────────────────────────────────────────
    @callback
    def _handle_state_change(self, event: Event) -> None:
        # A tracked sensor flipped on/off — re-sync (arm/clear). Cheap dict diff.
        self._hass.async_create_task(self._async_reconcile())

    @callback
    def _handle_registry_update(self, event: Event) -> None:
        # A binary sensor was added/removed/relabeled/re-homed — recompute the
        # eligible set, resubscribe, and reconcile (may create/remove tasks).
        if event.data.get("entity_id", "").split(".")[0] not in (
            "",
            _BINARY_SENSOR_DOMAIN,
        ):
            return
        self._resubscribe_state()
        self._hass.async_create_task(self._async_reconcile())

    async def _async_reconcile(self) -> None:
        entity_set_changed = (
            await self._coordinator.store.reconcile_problem_sensor_tasks(
                self._eligible(), config_entry_id=self._entry.entry_id
            )
        )
        if entity_set_changed:
            # A synced task was created/removed: its per-task device entities must be
            # (un)registered, which needs a full entry reload (mirrors the add/delete
            # service handlers). Guard against piling up reloads if several sensors
            # change at once.
            if not self._reload_scheduled:
                self._reload_scheduled = True
                self._hass.async_create_task(self._async_reload())
        else:
            await self._coordinator.async_request_refresh()

    async def _async_reload(self) -> None:
        try:
            await self._hass.config_entries.async_reload(self._entry.entry_id)
        finally:
            self._reload_scheduled = False
