"""Per-task "next due" sensor for device-attached Home Keeper tasks."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import HomeKeeperCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a next-due sensor for each device-attached task."""
    coordinator: HomeKeeperCoordinator = entry.runtime_data
    entities = [
        HomeKeeperNextDueSensor(coordinator, task_id)
        for task_id, task in coordinator.data.items()
        if task.get("device_id")
    ]
    async_add_entities(entities)


class HomeKeeperNextDueSensor(
    CoordinatorEntity[HomeKeeperCoordinator], SensorEntity
):
    """Timestamp sensor reporting when a task is next due."""

    _attr_has_entity_name = True
    _attr_name = "Next due"
    _attr_icon = "mdi:calendar-clock"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: HomeKeeperCoordinator, task_id: str) -> None:
        super().__init__(coordinator)
        self._task_id = task_id
        self._attr_unique_id = f"{DOMAIN}_{task_id}_next_due"
        self._attr_device_info = coordinator.device_info_for_task(
            coordinator.data[task_id]
        )

    @property
    def _task(self) -> dict:
        return self.coordinator.data.get(self._task_id, {})

    @property
    def native_value(self) -> datetime | None:
        due = self._task.get("next_due")
        return dt_util.parse_datetime(due) if due else None

    @property
    def extra_state_attributes(self) -> dict:
        task = self._task
        return {
            "task_id": self._task_id,
            "task_name": task.get("name"),
            "recurrence_type": task.get("recurrence_type"),
            "last_completed": task.get("last_completed"),
            "completions_count": len(task.get("completions", [])),
        }
