"""To-do list entity for Home Keeper.

Exposes all tasks as items in a single native HA to-do list, so users can view
and complete them from HA's built-in To-do card and the mobile app. Checking an
item off routes into the recurrence engine: the task's clock advances and the
item reappears with its new due date (native TodoListEntity has no recurrence of
its own).
"""

from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, REC_SENSOR, REC_TRIGGERED
from .coordinator import HomeKeeperCoordinator
from .models import TaskValidationError


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Home Keeper to-do list."""
    coordinator: HomeKeeperCoordinator = entry.runtime_data
    async_add_entities([HomeKeeperTodoListEntity(coordinator)])


class HomeKeeperTodoListEntity(
    CoordinatorEntity[HomeKeeperCoordinator], TodoListEntity
):
    """A single to-do list backed by the Home Keeper task store."""

    # No device for this hub entity, so anchor the entity_id explicitly via the
    # name -> todo.home_keeper_tasks (has_entity_name would yield todo.tasks).
    _attr_has_entity_name = False
    _attr_name = "Home Keeper Tasks"
    _attr_icon = "mdi:home-clock"
    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM

    def __init__(self, coordinator: HomeKeeperCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_tasks"

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return one item per enabled task, dated by next_due."""
        items: list[TodoItem] = []
        for task in self.coordinator.data.values():
            if not task.get("enabled", True):
                continue
            due_iso = task.get("next_due")
            # A dormant triggered or sensor task (next_due == None) is "armed but not
            # due" — keep it off the to-do list entirely rather than showing it as an
            # undated item. It reappears the moment it is armed (next_due set).
            rec_type = task.get("recurrence_type")
            if rec_type in (REC_TRIGGERED, REC_SENSOR) and not due_iso:
                continue
            due = dt_util.parse_datetime(due_iso) if due_iso else None
            items.append(
                TodoItem(
                    uid=task["id"],
                    summary=task["name"],
                    status=TodoItemStatus.NEEDS_ACTION,
                    due=due.date() if due else None,
                    description=task.get("notes") or None,
                )
            )
        return items

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Handle a checkbox toggle: completing advances the recurrence.

        Completing a problem-sensor-synced task is rejected by the store (the
        originating integration must clear the underlying problem); surface that as a
        ``HomeAssistantError`` so the to-do card shows the reason and leaves it
        checked-pending rather than silently swallowing it.
        """
        if item.status == TodoItemStatus.COMPLETED and item.uid:
            try:
                await self.coordinator.store.complete_task(item.uid)
            except TaskValidationError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="complete_failed",
                    translation_placeholders={"error": str(err)},
                ) from err
            await self.coordinator.async_request_refresh()
