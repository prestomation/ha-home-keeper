"""DataUpdateCoordinator for Home Keeper.

Reads tasks from the local :class:`HomeKeeperStore` (no network). A periodic
refresh keeps time-based state (overdue / due-soon) current even when no
mutations occur; every mutation also triggers an immediate refresh.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

try:
    from homeassistant.helpers.device_registry import DeviceInfo
except ImportError:  # pragma: no cover - older HA fallback
    from homeassistant.helpers.entity import DeviceInfo  # type: ignore[no-redef]
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import transitions
from .const import DOMAIN
from .store import HomeKeeperStore

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)


def entity_set_key(task: dict[str, Any] | None) -> tuple:
    """Identity of a task's per-task entity set.

    Per-task entities (button/sensor/binary_sensor) exist only for an enabled,
    device-attached task, and their display name embeds the task name (so several
    tasks on one device page stay distinguishable). When this key changes between
    an update's before/after, the entry must be reloaded so entities are
    created/removed/renamed; otherwise a plain coordinator refresh is enough.

    ``name`` is part of the key because HA caches an entity's computed ``name``;
    recreating the entity on reload is how a rename takes effect on the device
    page (and how a self-owned task device picks up its new name).
    """
    if not task:
        return (None, False, None)
    return (task.get("device_id"), bool(task.get("enabled", True)), task.get("name"))


class HomeKeeperCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Coordinator exposing the current task map to all entities."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, store: HomeKeeperStore
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Home Keeper",
            update_interval=SCAN_INTERVAL,
        )
        self.store = store
        self.entry = entry
        # Edge state for the time-based task events (overdue / due-soon). Carried
        # across refreshes so each is fired at most once per ``next_due``; see
        # transitions.detect_transitions.
        self._edge_state: transitions.StateMap = {}
        # Firing is gated until setup finishes (enable_transition_events) so the
        # several refreshes during async_setup_entry silently *baseline* current state
        # — an HA restart never replays an "overdue" storm for tasks already overdue.
        self._events_enabled = False

    def enable_transition_events(self) -> None:
        """Start firing overdue/due-soon events (called once setup is complete).

        Until this is called, refreshes still update the edge state but fire nothing,
        so the post-restart steady state is baselined silently and only genuine
        transitions observed while running are announced.
        """
        self._events_enabled = True

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        tasks = self.store.get_tasks()
        fired, self._edge_state = transitions.detect_transitions(
            self._edge_state, tasks, now=dt_util.now()
        )
        if self._events_enabled:
            for event_name, payload in fired:
                self.hass.bus.async_fire(event_name, payload)
        return tasks

    def device_attached_task_ids(self) -> list[str]:
        """Enabled task ids attached to a device (so get per-task entities)."""
        return [
            tid
            for tid, task in self.data.items()
            if task.get("device_id") and task.get("enabled", True)
        ]

    def _existing_device(self, device_id: str | None):
        """Resolve ``device_id`` to a registry device, or ``None``.

        Single source of truth for "is this an existing device we can merge onto?"
        so the DeviceInfo and name-prefix decisions can't drift apart.
        """
        if not device_id:
            return None
        return dr.async_get(self.hass).async_get(device_id)

    def task_uses_existing_device(self, task: dict[str, Any]) -> bool:
        """True when the task's per-task entities merge onto an existing device.

        In that case several tasks can share one device page, so each entity's
        name is prefixed with the task name to disambiguate. Self-owned task
        devices (no ``device_id`` or an unknown one) need no prefix because the
        device itself is already named after the task.
        """
        return self._existing_device(task.get("device_id")) is not None

    def device_info_for_device_id(self, device_id: str | None) -> DeviceInfo | None:
        """DeviceInfo that merges entities onto an existing registry device.

        Reuses the device's own identifiers/connections so HA attaches our entities
        to that device page rather than creating a new device. Returns ``None`` when
        the device cannot be resolved (the entity should then be skipped).
        """
        device = self._existing_device(device_id)
        if device is None:
            return None
        return DeviceInfo(
            identifiers=device.identifiers,
            connections=device.connections,
        )

    def device_info_for_task(self, task: dict[str, Any]) -> DeviceInfo:
        """Return the DeviceInfo a per-task entity should use.

        * If the task is attached to an existing device (``device_id``), reuse that
          device's own identifiers/connections so HA merges our entities onto the
          existing device page (the Battery-Notes-style attachment) rather than
          creating a new device.
        * Otherwise, create a self-owned device per task so its entities group
          together under the Home Keeper integration.
        """
        device_id = task.get("device_id")
        device = self._existing_device(device_id)
        if device is not None:
            return DeviceInfo(
                identifiers=device.identifiers,
                connections=device.connections,
            )
        if device_id:
            _LOGGER.warning(
                "Home Keeper task %s references unknown device_id %s; "
                "falling back to a self-owned device",
                task.get("id"),
                device_id,
            )
        return DeviceInfo(
            identifiers={(DOMAIN, task["id"])},
            name=task["name"],
            manufacturer="Home Keeper",
            model="Maintenance task",
        )
