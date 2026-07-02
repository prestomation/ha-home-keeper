"""Home Keeper binary sensors.

Two kinds, both on a device page:

* ``HomeKeeperOverdueBinarySensor`` — per-task "overdue" (``device_class: problem``)
  for tasks attached to a device.
* ``HomeKeeperPartLowStockBinarySensor`` — per-part "low stock" for a virtual
  appliance's stock-tracked spares with a reorder threshold, so the *state* (not just
  the ``part_*`` event transition) is visible on the appliance device page.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import assets as asset_model
from . import recurrence
from .const import DOMAIN
from .coordinator import HomeKeeperCoordinator
from .entity import HomeKeeperTaskEntity, async_prune_platform_entities
from .transitions import DUE_SOON_WINDOW  # shared so the event and entity agree

_LOW_STOCK_ICON = "mdi:package-variant-closed-remove"
# unique-id shape: ``{DOMAIN}_asset_<asset_id>_part_<part_id>_low_stock``.
_LOW_UID_PREFIX = f"{DOMAIN}_asset_"
_LOW_UID_INFIX = "_part_"
_LOW_UID_SUFFIX = "_low_stock"


def _low_stock_uid(asset_id: str, part_id: str) -> str:
    """Stable unique id for a part's low-stock sensor."""
    return f"{_LOW_UID_PREFIX}{asset_id}{_LOW_UID_INFIX}{part_id}{_LOW_UID_SUFFIX}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create per-task overdue sensors and per-part low-stock sensors."""
    coordinator: HomeKeeperCoordinator = entry.runtime_data

    task_ids = coordinator.device_attached_task_ids()
    live_task_ids = set(task_ids)

    # Per-part low-stock sensors for stock-tracked parts (with a reorder threshold) on
    # virtual appliances.
    part_rows = coordinator.virtual_asset_parts(asset_model.part_has_reorder)
    live_low_uids: set[str] = set()
    part_entities: list[BinarySensorEntity] = []
    for asset, part, device_info in part_rows:
        uid = _low_stock_uid(asset["id"], part["id"])
        live_low_uids.add(uid)
        part_entities.append(
            HomeKeeperPartLowStockBinarySensor(
                coordinator, asset["id"], part, device_info
            )
        )

    # Remove registry entries for sensors whose source is gone:
    # • per-task overdue sensors for deleted/detached tasks
    # • per-part low-stock sensors for removed parts / dropped reorder thresholds
    task_prefix, task_suffix = f"{DOMAIN}_", "_overdue"

    def _is_stale(uid: str) -> bool:
        if (
            uid.startswith(_LOW_UID_PREFIX)
            and uid.endswith(_LOW_UID_SUFFIX)
            and _LOW_UID_INFIX in uid
        ):
            return uid not in live_low_uids
        if uid.startswith(task_prefix) and uid.endswith(task_suffix):
            return uid[len(task_prefix) : -len(task_suffix)] not in live_task_ids
        return False

    async_prune_platform_entities(hass, entry, "binary_sensor", _is_stale)

    task_entities: list[BinarySensorEntity] = [
        HomeKeeperOverdueBinarySensor(coordinator, task_id) for task_id in task_ids
    ]
    async_add_entities(task_entities + part_entities)


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


class HomeKeeperPartLowStockBinarySensor(
    CoordinatorEntity[HomeKeeperCoordinator], BinarySensorEntity
):
    """On when an appliance part's on-hand spares are at/below its reorder threshold."""

    _attr_has_entity_name = True
    _attr_translation_key = "part_low_stock"
    _attr_icon = _LOW_STOCK_ICON
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        coordinator: HomeKeeperCoordinator,
        asset_id: str,
        part: dict[str, Any],
        device_info: DeviceInfo | None,
    ) -> None:
        super().__init__(coordinator)
        self._asset_id = asset_id
        self._part_id = part["id"]
        # Free-form part name carried as a placeholder ("Anode rod low stock").
        self._attr_translation_placeholders = {"part": part.get("name") or ""}
        self._attr_unique_id = _low_stock_uid(asset_id, part["id"])
        self._attr_device_info = device_info

    def _part(self) -> dict[str, Any] | None:
        return asset_model.find_part(
            self.coordinator.store.get_asset(self._asset_id), self._part_id
        )

    @property
    def is_on(self) -> bool:
        part = self._part()
        return asset_model.part_is_low(part) if part else False

    @property
    def extra_state_attributes(self) -> dict:
        part = self._part() or {}
        return {
            "asset_id": self._asset_id,
            "part_id": self._part_id,
            "stock": part.get("stock"),
            "reorder_at": part.get("reorder_at"),
        }
