"""Home Keeper sensors.

Two kinds, both living on a device page:

* ``HomeKeeperNextDueSensor`` — per-task "next due" timestamp, for tasks attached
  to a device.
* ``HomeKeeperAssetDateSensor`` — per-asset metadata dates (purchase / install /
  manufacture / warranty expiry) so temporal attributes are automatable natively
  (e.g. "warranty expiring in 30 days -> notify") and show in state history.
"""

from __future__ import annotations

from datetime import date, datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .assets import DATE_FIELDS
from .const import DOMAIN
from .coordinator import HomeKeeperCoordinator

# Default icon for each asset date sensor. The display name is resolved from the
# integration's translations via each entity's ``translation_key`` (the field
# name), so it localizes with the user's Home Assistant language.
ASSET_DATE_ICONS: dict[str, str] = {
    "manufacture_date": "mdi:factory",
    "purchase_date": "mdi:cart",
    "install_date": "mdi:wrench-clock",
    "warranty_expiry": "mdi:shield-check",
}


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
        for field in DATE_FIELDS:
            if asset.get(field):
                entities.append(
                    HomeKeeperAssetDateSensor(coordinator, asset["id"], field, device_info)
                )
    async_add_entities(entities)


class HomeKeeperNextDueSensor(
    CoordinatorEntity[HomeKeeperCoordinator], SensorEntity
):
    """Timestamp sensor reporting when a task is next due."""

    _attr_has_entity_name = True
    _attr_translation_key = "next_due"
    _attr_icon = "mdi:calendar-clock"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: HomeKeeperCoordinator, task_id: str) -> None:
        super().__init__(coordinator)
        self._task_id = task_id
        self._attr_unique_id = f"{DOMAIN}_{task_id}_next_due"
        self._attr_device_info = coordinator.device_info_for_task(
            coordinator.data[task_id]
        )
        self._prefix_name = coordinator.task_uses_existing_device(
            coordinator.data[task_id]
        )

    @property
    def _task(self) -> dict:
        return self.coordinator.data.get(self._task_id, {})

    @property
    def translation_placeholders(self) -> dict[str, str]:
        """Disambiguate this sensor among a device's tasks by its task name."""
        if not self._prefix_name:
            return {"task_name": ""}
        name = self._task.get("name", "")
        return {"task_name": f"{name}: " if name else ""}

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


class HomeKeeperAssetDateSensor(
    CoordinatorEntity[HomeKeeperCoordinator], SensorEntity
):
    """A single ``date`` metadata value for an asset, on its device page.

    The value lives in stored asset metadata (not the task map); asset edits reload
    the config entry, which recreates these entities, so a plain coordinator read is
    enough to stay current.
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(
        self,
        coordinator: HomeKeeperCoordinator,
        asset_id: str,
        field: str,
        device_info,
    ) -> None:
        super().__init__(coordinator)
        self._asset_id = asset_id
        self._field = field
        # Name comes from translations keyed by the field name (localized).
        self._attr_translation_key = field
        # A user-chosen appliance icon overrides the per-field default.
        asset = coordinator.store.get_asset(asset_id) or {}
        self._attr_icon = asset.get("icon") or ASSET_DATE_ICONS.get(field)
        self._attr_unique_id = f"{DOMAIN}_asset_{asset_id}_{field}"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> date | None:
        asset = self.coordinator.store.get_asset(self._asset_id) or {}
        value = asset.get(self._field)
        if not value:
            return None
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
