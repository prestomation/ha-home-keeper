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


def entity_set_key(task: dict[str, Any] | None) -> tuple:
    """Identity of a task's per-task entity set.

    Per-task entities (button/sensor/binary_sensor) exist only for an enabled,
    device-attached task. When this key changes between an update's before/after,
    the entry must be reloaded so entities are created/removed; otherwise a plain
    coordinator refresh is enough.
    """
    if not task:
        return (None, False)
    return (task.get("device_id"), bool(task.get("enabled", True)))


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

    def device_attached_task_ids(self) -> list[str]:
        """Enabled task ids attached to a device (so get per-task entities)."""
        return [
            tid
            for tid, task in self.data.items()
            if task.get("device_id") and task.get("enabled", True)
        ]

    def device_info_for_device_id(self, device_id: str | None) -> DeviceInfo | None:
        """DeviceInfo that merges entities onto an existing registry device.

        Reuses the device's own identifiers/connections so HA attaches our entities
        to that device page rather than creating a new device. Returns ``None`` when
        the device cannot be resolved (the entity should then be skipped).
        """
        if not device_id:
            return None
        device = dr.async_get(self.hass).async_get(device_id)
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
