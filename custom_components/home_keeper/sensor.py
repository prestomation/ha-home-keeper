"""Home Keeper sensors.

Two kinds, both living on a device page:

* ``HomeKeeperNextDueSensor`` — per-task "next due" timestamp, for tasks attached
  to a device.
* ``HomeKeeperAssetDateSensor`` — a tracked ``date`` metadata entry on an asset, so
  temporal attributes are automatable natively (e.g. "warranty expiring in 30 days
  -> notify") and show in state history. Only metadata dates the user opts into
  tracking (``track``) get a sensor; the rest are display-only.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import HomeKeeperCoordinator
from .entity import HomeKeeperTaskEntity

# Default icon for a tracked-date sensor when the asset has no custom icon.
_DATE_ICON = "mdi:calendar-clock"


def _tracked_dates(asset: dict[str, Any]) -> list[dict[str, Any]]:
    """The asset's metadata entries that are tracked dates with a value set."""
    return [
        entry
        for entry in (asset.get("metadata") or [])
        if entry.get("type") == "date" and entry.get("track") and entry.get("value")
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create next-due sensors for device-attached tasks and asset date sensors."""
    coordinator: HomeKeeperCoordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        HomeKeeperNextDueSensor(coordinator, task_id)
        for task_id in coordinator.device_attached_task_ids()
    ]
    for asset in coordinator.store.list_assets():
        device_info = coordinator.device_info_for_device_id(asset.get("device_id"))
        if device_info is None:
            continue
        for meta in _tracked_dates(asset):
            entities.append(
                HomeKeeperAssetDateSensor(coordinator, asset["id"], meta, device_info)
            )
    async_add_entities(entities)


class HomeKeeperNextDueSensor(HomeKeeperTaskEntity, SensorEntity):
    """Timestamp sensor reporting when a task is next due."""

    _attr_translation_key = "next_due"
    _attr_icon = "mdi:calendar-clock"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: HomeKeeperCoordinator, task_id: str) -> None:
        super().__init__(coordinator, task_id)
        self._attr_unique_id = f"{DOMAIN}_{task_id}_next_due"
        self._attr_device_info = coordinator.device_info_for_task(
            coordinator.data[task_id]
        )

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


class HomeKeeperAssetDateSensor(CoordinatorEntity[HomeKeeperCoordinator], SensorEntity):
    """A single tracked ``date`` metadata entry for an asset, on its device page.

    The value lives in the asset's free-form ``metadata`` list (not the task map);
    asset edits reload the config entry, which recreates these entities, so a plain
    coordinator read is enough to stay current. The entity is named from the entry's
    user-supplied ``label`` (not a translation, since labels are free-form).
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(
        self,
        coordinator: HomeKeeperCoordinator,
        asset_id: str,
        entry: dict[str, Any],
        device_info,
    ) -> None:
        super().__init__(coordinator)
        self._asset_id = asset_id
        self._entry_id = entry["id"]
        # Name is the user's free-form label (no localization for custom fields).
        self._attr_name = entry.get("label")
        # A user-chosen appliance icon overrides the default.
        asset = coordinator.store.get_asset(asset_id) or {}
        self._attr_icon = asset.get("icon") or _DATE_ICON
        self._attr_unique_id = f"{DOMAIN}_asset_{asset_id}_meta_{entry['id']}"
        self._attr_device_info = device_info

    def _entry(self) -> dict[str, Any] | None:
        asset = self.coordinator.store.get_asset(self._asset_id) or {}
        for entry in asset.get("metadata") or []:
            if entry.get("id") == self._entry_id:
                return entry
        return None

    @property
    def native_value(self) -> date | None:
        entry = self._entry()
        value = entry.get("value") if entry else None
        if not value:
            return None
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
