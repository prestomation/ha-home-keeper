"""To-do list entity for Home Keeper.

Exposes every live task as an item in a single native HA to-do list, so users can
view and complete them from HA's built-in To-do card and the mobile app. Checking
an item off routes into the recurrence engine: the task's clock advances and the
item reappears with its new due date (native TodoListEntity has no recurrence of
its own).

A task that has gone *dormant* carries no ``next_due`` — a do-once task that is
finished, a triggered or sensor task that is not armed — and is off the list until
it is armed again.
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

from .const import DOMAIN, REC_ONE_OFF, REC_SENSOR, REC_TRIGGERED
from .coordinator import HomeKeeperCoordinator
from .devices import service_device_info
from .models import TaskValidationError
from .recurrence import one_off_completed
from .task_entities import entity_set_key


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

    # The entity is on the "Home Keeper" service device, so the translated name
    # composes to "Home Keeper Tasks" and the entity_id is todo.home_keeper_tasks
    # (X13-4).
    _attr_has_entity_name = True
    _attr_translation_key = "tasks"
    _attr_icon = "mdi:home-clock"
    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM

    def __init__(self, coordinator: HomeKeeperCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_tasks"
        self._attr_device_info = service_device_info()

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return one item per enabled, non-dormant task, dated by next_due."""
        items: list[TodoItem] = []
        for task in self.coordinator.data.values():
            if not task.get("enabled", True):
                continue
            due_iso = task.get("next_due")
            # A dormant task (next_due == None) is off every time surface: a completed
            # one-off is permanently done, and a triggered or sensor task is "armed but
            # not due". Keep both off the to-do list entirely rather than showing them
            # as undated items that can never be cleared. Each reappears the moment it
            # is (re-)armed — a one-off when its completion is undone, the other two
            # when their condition fires again. Not a bare `not due_iso` check: a
            # floating or fixed task always carries a next_due, so a missing one there
            # is malformed data that should stay visible rather than silently vanish.
            rec_type = task.get("recurrence_type")
            # REC_USE is deliberately **absent** from this tuple. A use task is
            # dateless for its whole life and that is exactly why it belongs here: the
            # to-do list is the one-tap surface a household already has on its phone,
            # and ticking the item is how a use gets counted. It reappears immediately
            # (the list is rebuilt from the tasks), which is the correct behaviour for
            # a thing you use again tomorrow.
            if rec_type in (REC_ONE_OFF, REC_TRIGGERED, REC_SENSOR) and not due_iso:
                continue
            due = dt_util.parse_datetime(due_iso) if due_iso else None
            items.append(
                TodoItem(
                    uid=task["id"],
                    summary=task["name"],
                    status=TodoItemStatus.NEEDS_ACTION,
                    # ``as_local`` before ``date()``, never ``due.date()`` (#250). A
                    # stored ``next_due`` carries whatever offset it was written with —
                    # a completion made "now" gets the local one, one entered through
                    # the panel's date picker gets UTC — and ``.date()`` takes the
                    # calendar date *in that offset*. A task due at local midnight then
                    # reads as the previous day here while the panel reads it right,
                    # and everything downstream of the entity inherits the shift.
                    due=dt_util.as_local(due).date() if due else None,
                    description=task.get("notes") or None,
                )
            )
        return items

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Handle a to-do item edit from HA's card.

        * Checking it off routes into the recurrence engine (completing a
          problem-sensor-synced task is rejected by the store — the originating
          integration must clear the underlying problem — surfaced as a
          ``HomeAssistantError`` so the card shows the reason and leaves it
          checked-pending).
        * A completion aimed at an already-completed do-once task is ignored. It is
          dormant and off the list, so the only thing a second check-off could do is
          duplicate the record of work done exactly once.
        * Editing the summary/notes in the detail dialog applies as a task update.
          The entity declares ``UPDATE_TODO_ITEM``, so a rename must actually persist
          rather than silently revert on the next render. A rename that comes in the
          same save as the check-off is applied after the completion (X07-3).
        """
        if not item.uid:
            return
        task = self.coordinator.store.get_task(item.uid)
        if item.status == TodoItemStatus.COMPLETED:
            if task is not None and one_off_completed(task):
                await self._async_apply_edits(item, task)
                return
            try:
                await self.coordinator.store.complete_task(item.uid)
            except TaskValidationError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="complete_failed",
                    translation_placeholders={"error": str(err)},
                ) from err
            # Completing an auto-buy task bumps stock (restocked) → its reminder is
            # removed; settle so those device entities are (un)registered.
            await self.coordinator.async_settle_buy_tasks()
            # The completion can delete the task (a buy reminder), so read it again.
            task = self.coordinator.store.get_task(item.uid)

        # Persist summary/notes edits made in the card detail dialog.
        if task is None:
            return
        await self._async_apply_edits(item, task)

    async def _async_apply_edits(self, item: TodoItem, task: dict) -> None:
        """Write the summary and notes of *item* to *task* if they changed."""
        updates: dict[str, str] = {}
        if item.summary is not None and item.summary != task.get("name"):
            updates["name"] = item.summary
        new_notes = item.description or ""
        if new_notes != (task.get("notes") or ""):
            updates["notes"] = new_notes
        if not updates:
            return
        before = entity_set_key(task)
        try:
            updated = await self.coordinator.store.update_task(str(task["id"]), updates)
        except TaskValidationError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="invalid_task",
                translation_placeholders={"error": str(err)},
            ) from err
        if updated.get("device_id") and entity_set_key(updated) != before:
            # A rename changes the names of the device-page entities, and only a
            # reload makes them again (B15-6). A task with no device has no such
            # entities. The reload removes this entity too, so it runs as a
            # separate task after this call returns.
            hass = self.coordinator.hass
            hass.async_create_task(
                hass.config_entries.async_reload(self.coordinator.entry.entry_id)
            )
            return
        await self.coordinator.async_request_refresh()
