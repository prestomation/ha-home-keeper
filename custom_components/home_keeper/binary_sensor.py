"""Per-task "overdue" binary sensor for device-attached Home Keeper tasks."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import recurrence
from .const import DOMAIN
from .coordinator import HomeKeeperCoordinator

DUE_SOON_WINDOW = timedelta(days=3)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create an overdue binary sensor for each device-attached task."""
    coordinator: HomeKeeperCoordinator = entry.runtime_data
    entities = [
        HomeKeeperOverdueBinarySensor(coordinator, task_id)
        for task_id, task in coordinator.data.items()
        if task.get("device_id")
    ]
    async_add_entities(entities)


class HomeKeeperOverdueBinarySensor(
    CoordinatorEntity[HomeKeeperCoordinator], BinarySensorEntity
):
    """On when a task is overdue."""

    _attr_has_entity_name = True
    _attr_name = "Overdue"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: HomeKeeperCoordinator, task_id: str) -> None:
        super().__init__(coordinator)
        self._task_id = task_id
        self._attr_unique_id = f"{DOMAIN}_{task_id}_overdue"
        self._attr_device_info = coordinator.device_info_for_task(
            coordinator.data[task_id]
        )

    @property
    def _task(self) -> dict:
        return self.coordinator.data.get(self._task_id, {})

    @property
    def is_on(self) -> bool:
        return recurrence.is_overdue(self._task, now=dt_util.now())

    @property
    def extra_state_attributes(self) -> dict:
        now = dt_util.now()
        return {
            "task_id": self._task_id,
            "due_soon": recurrence.is_due_soon(self._task, DUE_SOON_WINDOW, now=now),
            "next_due": self._task.get("next_due"),
        }
