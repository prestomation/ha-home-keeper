"""Shared base for Home Keeper's per-task device-page entities.

The mark-done button, next-due sensor, and overdue binary sensor are all created
per device-attached task. Each lives on a device page, so when several tasks are
attached to the same existing device their entity names would otherwise collide
("Mark done", "Mark done", …). This base prefixes the translated name with the
task name in that case (and leaves it bare for a self-owned task device, which is
already named after the task).

The prefix is fixed at construction via the supported ``_attr_translation_placeholders``
attribute. Home Assistant caches an entity's computed ``name``, so a rename takes
effect by reloading the config entry (see :func:`coordinator.entity_set_key`),
which recreates these entities with the new name.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import HomeKeeperCoordinator


class HomeKeeperTaskEntity(CoordinatorEntity[HomeKeeperCoordinator]):
    """A per-task entity whose translated name disambiguates by task name."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HomeKeeperCoordinator, task_id: str) -> None:
        super().__init__(coordinator)
        self._task_id = task_id
        task = coordinator.data.get(task_id, {})
        if coordinator.task_uses_existing_device(task):
            name = task.get("name") or ""
            prefix = f"{name}: " if name else ""
        else:
            prefix = ""
        self._attr_translation_placeholders = {"task_name": prefix}

    @property
    def _task(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._task_id, {})
