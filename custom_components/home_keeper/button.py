"""Per-task "mark done" button for device-attached Home Keeper tasks.

Tasks linked to an existing device get a button on that device's page so the
maintenance action lives right next to the device it concerns. Pressing it
completes the task and advances its recurrence.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HomeKeeperCoordinator
from .entity import HomeKeeperTaskEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a mark-done button for each device-attached task."""
    coordinator: HomeKeeperCoordinator = entry.runtime_data
    async_add_entities(
        HomeKeeperMarkDoneButton(coordinator, task_id)
        for task_id in coordinator.device_attached_task_ids()
    )


class HomeKeeperMarkDoneButton(HomeKeeperTaskEntity, ButtonEntity):
    """Marks a task complete from its device page."""

    _attr_translation_key = "mark_done"
    _attr_icon = "mdi:check-circle"

    def __init__(self, coordinator: HomeKeeperCoordinator, task_id: str) -> None:
        super().__init__(coordinator, task_id)
        self._attr_unique_id = f"{DOMAIN}_{task_id}_done"
        self._attr_device_info = coordinator.device_info_for_task(
            coordinator.data[task_id]
        )

    async def async_press(self) -> None:
        await self.coordinator.store.complete_task(self._task_id)
        await self.coordinator.async_request_refresh()
