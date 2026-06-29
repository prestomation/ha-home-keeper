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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
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

    task_ids = coordinator.device_attached_task_ids()
    live_task_ids = set(task_ids)

    # Build the set of live asset-date sensor unique-ids (only for assets that have
    # a resolvable device and tracked date entries with a value set).
    live_asset_meta_uids: set[str] = set()
    asset_entities: list[SensorEntity] = []
    for asset in coordinator.store.list_assets():
        device_info = coordinator.device_info_for_device_id(asset.get("device_id"))
        if device_info is None:
            continue
        for meta in _tracked_dates(asset):
            uid = f"{DOMAIN}_asset_{asset['id']}_meta_{meta['id']}"
            live_asset_meta_uids.add(uid)
            asset_entities.append(
                HomeKeeperAssetDateSensor(coordinator, asset["id"], meta, device_info)
            )

    # Remove entity-registry entries for sensors whose source no longer exists:
    # • per-task next-due sensors for deleted/detached tasks
    # • asset date sensors for removed or un-tracked metadata entries
    reg = er.async_get(hass)
    task_prefix = f"{DOMAIN}_"
    task_suffix = "_next_due"
    asset_prefix = f"{DOMAIN}_asset_"
    asset_infix = "_meta_"
    for entity_entry in reg.entities.get_entries_for_config_entry_id(entry.entry_id):
        if entity_entry.domain != "sensor":
            continue
        uid = entity_entry.unique_id or ""
        if uid.startswith(task_prefix) and uid.endswith(task_suffix):
            task_id = uid[len(task_prefix) : -len(task_suffix)]
            if task_id not in live_task_ids:
                reg.async_remove(entity_entry.entity_id)
        elif uid.startswith(asset_prefix) and asset_infix in uid:
            if uid not in live_asset_meta_uids:
                reg.async_remove(entity_entry.entity_id)

    async_add_entities(
        [HomeKeeperNextDueSensor(coordinator, task_id) for task_id in task_ids]
        + asset_entities
    )


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
        completions = task.get("completions", [])
        attrs: dict[str, Any] = {
            "task_id": self._task_id,
            "task_name": task.get("name"),
            "recurrence_type": task.get("recurrence_type"),
            "last_completed": task.get("last_completed"),
            "completions_count": len(completions),
        }
        # Surface the most recent completion's metadata so automations/dashboards can
        # read "who did it / what did it cost / the note / the photo" without parsing
        # the history array. Keys are only present when that completion recorded them.
        if completions:
            # Match ``last_completed`` (the chronologically latest), not merely the
            # last appended, so an out-of-order seed can't shadow a real completion.
            latest = max(completions, key=lambda c: c.get("ts") or "")
            for key in ("note", "cost", "photo", "who"):
                if key in latest:
                    attrs[f"last_completion_{key}"] = latest[key]
        return attrs


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
        device_info: DeviceInfo | None,
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
