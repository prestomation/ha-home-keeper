"""Shared bases and registry helpers for Home Keeper's device-page entities.

Two families live on a device page, and each has a base here:

* :class:`HomeKeeperTaskEntity` — per-task (mark-done button, next-due sensor,
  overdue binary sensor). Each lives on a device page, so when several tasks are
  attached to the same existing device their entity names would otherwise collide
  ("Mark done", "Mark done", …). This base prefixes the translated name with the
  task name in that case (and leaves it bare for a self-owned task device, which is
  already named after the task).
* :class:`HomeKeeperPartEntity` — per-part on a virtual appliance (spare-stock
  number, low-stock binary sensor). Part names are free-form, so the translated
  name carries the part name as a placeholder rather than localizing it.

The name placeholder is fixed at construction via the supported
``_attr_translation_placeholders`` attribute. Home Assistant caches an entity's
computed ``name``, so a rename takes effect by reloading the config entry (see
:func:`coordinator.entity_set_key`), which recreates these entities with the new name.

:func:`prune_registry_entries` is the other half of the platforms' shared shape: every
one of them drops the registry entries whose source (task, part, metadata entry) is
gone before adding the live ones.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import assets as asset_model
from .coordinator import HomeKeeperCoordinator


class HomeKeeperTaskEntity(CoordinatorEntity[HomeKeeperCoordinator]):
    """A per-task entity whose translated name disambiguates by task name."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HomeKeeperCoordinator, task_id: str) -> None:
        super().__init__(coordinator)
        self._task_id = task_id
        task = coordinator.data.get(task_id, {})
        # Set here rather than in each platform so the three per-task entities can't
        # drift apart on which device they land on. Exactly one of these is non-None:
        # a self-owned device we describe, or an existing device we link to without
        # claiming it. See coordinator.device_link_for_task.
        self._attr_device_info, self.device_entry = coordinator.device_link_for_task(
            task
        )
        if coordinator.task_uses_existing_device(task):
            name = task.get("name") or ""
            prefix = f"{name}: " if name else ""
        else:
            prefix = ""
        self._attr_translation_placeholders = {"task_name": prefix}

    @property
    def _task(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._task_id, {})


class HomeKeeperPartEntity(CoordinatorEntity[HomeKeeperCoordinator]):
    """An entity for one wear part of a virtual appliance, on the appliance's page.

    Subclasses differ only in their unique-id shape (passed in, since it is also
    what ``async_setup_entry`` prunes against) and in what they read off the part.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HomeKeeperCoordinator,
        asset_id: str,
        part: dict[str, Any],
        device: dr.DeviceEntry,
        *,
        unique_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._asset_id = asset_id
        self._part_id = part["id"]
        # Part names are free-form, so the translated name carries the name as a
        # placeholder ("Anode rod spares") rather than localizing the part itself.
        self._attr_translation_placeholders = {"part": part.get("name") or ""}
        self._attr_unique_id = unique_id
        # Linked, not owned: the appliance device belongs to whoever created it.
        self.device_entry = device

    def _part(self) -> dict[str, Any] | None:
        """The part's stored record, or None once it (or its appliance) is gone."""
        asset = self.coordinator.store.get_asset(self._asset_id) or {}
        return asset_model.find_part(asset, self._part_id)


def prune_registry_entries(
    hass: HomeAssistant,
    entry: ConfigEntry,
    domain: str,
    keep: Callable[[str], bool | None],
) -> None:
    """Remove this entry's *domain* registry entries whose source no longer exists.

    Every platform does this before adding its live entities: a task deleted or
    detached, a part removed, a metadata entry un-tracked all leave an orphan behind
    otherwise. *keep* classifies one unique id — ``True`` to keep it, ``False`` to
    remove it, and ``None`` when the id belongs to no family this platform owns, which
    must be left strictly alone (several platforms share a config entry, and a domain
    can carry more than one unique-id shape).
    """
    reg = er.async_get(hass)
    for entity_entry in reg.entities.get_entries_for_config_entry_id(entry.entry_id):
        if entity_entry.domain != domain:
            continue
        if keep(entity_entry.unique_id or "") is False:
            reg.async_remove(entity_entry.entity_id)
