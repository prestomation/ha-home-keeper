"""Per-task "overdue" binary sensor for device-attached Home Keeper tasks."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import recurrence
from .const import DOMAIN
from .coordinator import HomeKeeperCoordinator
from .entity import HomeKeeperTaskEntity
from .transitions import DUE_SOON_WINDOW  # shared so the event and entity agree


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create an overdue binary sensor for each device-attached task."""
    coordinator: HomeKeeperCoordinator = entry.runtime_data

    # Remove entity-registry entries for per-task binary sensors whose task no
    # longer exists (e.g. after disabling Problem Sensor Sync or deleting a task).
    live_ids = set(coordinator.device_attached_task_ids())
    reg = er.async_get(hass)
    _prefix = f"{DOMAIN}_"
    _suffix = "_overdue"
    for entity_entry in list(reg.entities.get_entries_for_config_entry_id(entry.entry_id)):
        uid = entity_entry.unique_id or ""
        if (
            entity_entry.entity_id.split(".", 1)[0] == "binary_sensor"
            and uid.startswith(_prefix)
            and uid.endswith(_suffix)
        ):
            task_id = uid[len(_prefix) : -len(_suffix)]
            if task_id not in live_ids:
                reg.async_remove(entity_entry.entity_id)

    async_add_entities(
        HomeKeeperOverdueBinarySensor(coordinator, task_id)
        for task_id in coordinator.device_attached_task_ids()
    )


class HomeKeeperOverdueBinarySensor(HomeKeeperTaskEntity, BinarySensorEntity):
    """On when a task is overdue."""

    _attr_translation_key = "overdue"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: HomeKeeperCoordinator, task_id: str) -> None:
        super().__init__(coordinator, task_id)
        self._attr_unique_id = f"{DOMAIN}_{task_id}_overdue"
        self._attr_device_info = coordinator.device_info_for_task(
            coordinator.data[task_id]
        )

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
