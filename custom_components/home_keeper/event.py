"""Event entities that mirror the Home Keeper bus events.

Home Assistant's "Event received" trigger targets ``event`` entities by entity,
device, area, floor or label, and then filters on the event type. The bus events
(``home_keeper_*``) are not entities, so the automation editor cannot find them.
This platform adds 2 kinds of entity:

* **Device events**: 1 for each device that has a Home Keeper task or appliance.
  It gets each task, part and appliance event whose payload has that
  ``device_id``. A user can then target the device, its area or a label.
* **Home Keeper events**: 1 on the Home Keeper service device. It gets every
  event that has a payload, also for a standalone task (no device) and for
  companions.

The event type is the bus name without ``home_keeper_`` (``task_completed``). The
list comes from :func:`api_surface.event_entity_events`, so a new bus event is
mirrored with no change here. The attributes are the bus payload without the keys
in :data:`api_surface.EVENT_ENTITY_DROPPED_FIELDS`, because the recorder keeps
each event.

The entities listen on the bus. They do not change the bus events, so an
automation with ``platform: event`` works as before. An event that fires while
the config entry reloads can be lost here; the bus event is still fired.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api_surface import (
    EVENT_ENTITY_DROPPED_FIELDS,
    event_entity_events,
    event_entity_type,
)
from .const import DOMAIN
from .coordinator import HomeKeeperCoordinator
from .entity import prune_registry_entries
from .service_device import service_device_info

DEVICE_EVENTS = event_entity_events("device")
GLOBAL_EVENTS = event_entity_events("global")

GLOBAL_UNIQUE_ID = f"{DOMAIN}_events"
_DEVICE_PREFIX = f"{DOMAIN}_device_"
_DEVICE_SUFFIX = "_events"


def device_unique_id(device_id: str) -> str:
    """The unique id of the event entity on one device."""
    return f"{_DEVICE_PREFIX}{device_id}{_DEVICE_SUFFIX}"


def event_attributes(data: dict[str, Any]) -> dict[str, Any]:
    """The bus payload without the keys an event entity does not keep."""
    return {
        key: value
        for key, value in data.items()
        if key not in EVENT_ENTITY_DROPPED_FIELDS
    }


def event_devices(coordinator: HomeKeeperCoordinator) -> list[dr.DeviceEntry]:
    """The registry devices that get a device event entity.

    A device qualifies when an enabled task is attached to it or an appliance
    uses it, and the device id resolves in the registry. A task with an unknown
    device gets its other entities on a self-owned device; its events go to the
    global entity only, because the payload carries the unknown id.
    """
    candidates = [
        coordinator.data[task_id].get("device_id")
        for task_id in coordinator.device_attached_task_ids()
    ]
    candidates += [asset.get("device_id") for asset in coordinator.store.list_assets()]
    devices: dict[str, dr.DeviceEntry] = {}
    for device_id in candidates:
        if not device_id or device_id in devices:
            continue
        device = coordinator.device_entry_for_device_id(device_id)
        if device is not None:
            devices[device_id] = device
    return list(devices.values())


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the global event entity and 1 event entity for each device."""
    coordinator: HomeKeeperCoordinator = entry.runtime_data
    devices = event_devices(coordinator)
    live = {device_unique_id(device.id) for device in devices}

    def keep(uid: str) -> bool | None:
        if uid == GLOBAL_UNIQUE_ID:
            return True
        if uid.startswith(_DEVICE_PREFIX) and uid.endswith(_DEVICE_SUFFIX):
            return uid in live
        return None

    prune_registry_entries(hass, entry, "event", keep)

    entities: list[HomeKeeperEventEntity] = [HomeKeeperGlobalEventEntity()]
    entities += [HomeKeeperDeviceEventEntity(device) for device in devices]
    async_add_entities(entities)


class HomeKeeperEventEntity(EventEntity):
    """Mirrors a set of bus events onto this entity."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _unrecorded_attributes = frozenset({"changed_fields", "labels"})

    def __init__(self, events: dict[str, str]) -> None:
        self._events = events
        self._attr_event_types = list(events)

    def _wants(self, data: dict[str, Any]) -> bool:
        """True when this entity mirrors an event with this payload."""
        return True

    async def async_added_to_hass(self) -> None:
        """Listen on the bus for each event that this entity mirrors."""
        await super().async_added_to_hass()
        for event_name in self._events.values():
            self.async_on_remove(
                self.hass.bus.async_listen(event_name, self._async_handle_event)
            )

    @callback
    def _async_handle_event(self, event: Event) -> None:
        data = dict(event.data)
        if not self._wants(data):
            return
        event_type = event_entity_type(str(event.event_type))
        if event_type not in self._events:
            return
        self._trigger_event(event_type, event_attributes(data))
        self.async_write_ha_state()


class HomeKeeperGlobalEventEntity(HomeKeeperEventEntity):
    """Gets every Home Keeper event, on the Home Keeper service device."""

    _attr_translation_key = "home_keeper_events"
    _attr_unique_id = GLOBAL_UNIQUE_ID

    def __init__(self) -> None:
        super().__init__(GLOBAL_EVENTS)
        self._attr_device_info = service_device_info()


class HomeKeeperDeviceEventEntity(HomeKeeperEventEntity):
    """Gets the task, part and appliance events of one device."""

    _attr_translation_key = "device_events"

    def __init__(self, device: dr.DeviceEntry) -> None:
        super().__init__(DEVICE_EVENTS)
        self._device_id = device.id
        self._attr_unique_id = device_unique_id(device.id)
        # Linked, not owned: the device can belong to another integration.
        self.device_entry = device

    def _wants(self, data: dict[str, Any]) -> bool:
        return data.get("device_id") == self._device_id
