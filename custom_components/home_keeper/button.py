"""Per-task "mark done" button for device-attached Home Keeper tasks.

Tasks linked to an existing device get a button on that device's page so the
maintenance action lives right next to the device it concerns. Pressing it
completes the task and advances its recurrence.

A task that nothing in Home Keeper can mark done gets no button: a problem-sensor
task, and a recipe task that clears itself when its condition recovers (#377).
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HomeKeeperCoordinator
from .entity import HomeKeeperTaskEntity, prune_registry_entries
from .notifications import is_completion_blocked
from .problem_tasks import problem_source


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a mark-done button for each device-attached task.

    A task that can't be completed in Home Keeper is skipped, so its button would
    only ever error: a problem-sensor-synced task (the originating integration
    clears it) and a recipe task that clears itself when its condition recovers
    (``managed_by.completion_blocked``). Their next-due sensor and overdue binary
    sensor still appear on the device.
    """
    coordinator: HomeKeeperCoordinator = entry.runtime_data

    button_ids = [
        task_id
        for task_id in coordinator.device_attached_task_ids()
        if problem_source(coordinator.data[task_id]) is None
        and not is_completion_blocked(coordinator.data[task_id])
    ]

    # Remove entity-registry entries for per-task buttons whose task no longer
    # exists or no longer gets a button (e.g. after disabling Problem Sensor Sync,
    # deleting a task, or a recipe that now clears its tasks itself).
    live_ids = set(button_ids)
    prefix = f"{DOMAIN}_"
    suffix = "_done"

    def keep(uid: str) -> bool | None:
        if not (uid.startswith(prefix) and uid.endswith(suffix)):
            return None
        return uid[len(prefix) : -len(suffix)] in live_ids

    prune_registry_entries(hass, entry, "button", keep)

    async_add_entities(
        HomeKeeperMarkDoneButton(coordinator, task_id) for task_id in button_ids
    )


class HomeKeeperMarkDoneButton(HomeKeeperTaskEntity, ButtonEntity):
    """Marks a task complete from its device page."""

    _attr_translation_key = "mark_done"
    _attr_icon = "mdi:check-circle"

    def __init__(self, coordinator: HomeKeeperCoordinator, task_id: str) -> None:
        super().__init__(coordinator, task_id)
        self._attr_unique_id = f"{DOMAIN}_{task_id}_done"

    async def async_press(self) -> None:
        await self.coordinator.store.complete_task(self._task_id)
        # Completing an auto-buy task bumps stock (restocked) → its reminder is removed;
        # settle so those device entities are (un)registered (else a plain refresh).
        await self.coordinator.async_settle_buy_tasks()
