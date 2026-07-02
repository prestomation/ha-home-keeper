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
from .entity import HomeKeeperTaskEntity, async_prune_platform_entities
from .problem_tasks import problem_source


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a mark-done button for each device-attached task.

    Problem-sensor-synced tasks are skipped: they can't be completed in Home Keeper
    (the originating integration clears them), so a mark-done button would only ever
    error. Their next-due sensor / overdue binary sensor still appear on the device.
    """
    coordinator: HomeKeeperCoordinator = entry.runtime_data

    # Remove entity-registry entries for per-task buttons whose task no longer
    # exists (e.g. after disabling Problem Sensor Sync or deleting a task).
    task_ids = coordinator.device_attached_task_ids()
    live_ids = set(task_ids)
    prefix, suffix = f"{DOMAIN}_", "_done"

    def _is_stale(uid: str) -> bool:
        if uid.startswith(prefix) and uid.endswith(suffix):
            return uid[len(prefix) : -len(suffix)] not in live_ids
        return False

    async_prune_platform_entities(hass, entry, "button", _is_stale)

    async_add_entities(
        HomeKeeperMarkDoneButton(coordinator, task_id)
        for task_id in task_ids
        if problem_source(coordinator.data[task_id]) is None
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
