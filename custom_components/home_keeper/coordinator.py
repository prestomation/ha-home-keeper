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

from .const import DOMAIN
from .store import HomeKeeperStore

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)


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

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        return self.store.get_tasks()

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
        if device_id:
            registry = dr.async_get(self.hass)
            device = registry.async_get(device_id)
            if device is not None:
                return DeviceInfo(
                    identifiers=device.identifiers,
                    connections=device.connections,
                )
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
