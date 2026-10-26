"""The global event entity that mirrors the Home Keeper bus events.

``event.home_keeper_events`` is on the Home Keeper service device. It gets every
bus event that has a payload, also for a standalone task and for companions. It
gives a history of the events, and a target for Home Assistant's "Event received"
trigger. To target 1 task, part, appliance, device, area or label, use the Home
Keeper triggers in ``trigger.py``.

The event type is the bus name without ``home_keeper_`` (``task_completed``). The
list comes from :func:`api_surface.event_entity_events`, so a new bus event is
mirrored with no change here. The attributes are the bus payload without the keys
in :data:`api_surface.EVENT_ENTITY_DROPPED_FIELDS`, because the recorder keeps
each event.

The entity listens on the bus. It does not change the bus events, so an
automation with ``platform: event`` works as before. An event that fires while
the config entry reloads can be lost here; the bus event is still fired.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api_surface import (
    EVENT_ENTITY_DROPPED_FIELDS,
    event_entity_events,
    event_entity_type,
)
from .const import DOMAIN
from .entity import prune_registry_entries
from .service_device import service_device_info

GLOBAL_EVENTS = event_entity_events()

GLOBAL_UNIQUE_ID = f"{DOMAIN}_events"
_OLD_DEVICE_PREFIX = f"{DOMAIN}_device_"


def event_attributes(data: dict[str, Any]) -> dict[str, Any]:
    """The bus payload without the keys the event entity does not keep."""
    return {
        key: value
        for key, value in data.items()
        if key not in EVENT_ENTITY_DROPPED_FIELDS
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the global event entity."""

    def keep(uid: str) -> bool | None:
        # A beta gave each device an event entity. Remove those.
        if uid == GLOBAL_UNIQUE_ID:
            return True
        return False if uid.startswith(_OLD_DEVICE_PREFIX) else None

    prune_registry_entries(hass, entry, "event", keep)
    async_add_entities([HomeKeeperGlobalEventEntity()])


class HomeKeeperGlobalEventEntity(EventEntity):
    """Gets every Home Keeper event, on the Home Keeper service device."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "home_keeper_events"
    _attr_unique_id = GLOBAL_UNIQUE_ID
    _unrecorded_attributes = frozenset({"changed_fields", "labels"})

    def __init__(self) -> None:
        self._events = GLOBAL_EVENTS
        self._attr_event_types = list(GLOBAL_EVENTS)
        self._attr_device_info = service_device_info()

    async def async_added_to_hass(self) -> None:
        """Listen on the bus for each event that this entity mirrors."""
        await super().async_added_to_hass()
        for event_name in self._events.values():
            self.async_on_remove(
                self.hass.bus.async_listen(event_name, self._async_handle_event)
            )

    @callback
    def _async_handle_event(self, event: Event) -> None:
        event_type = event_entity_type(str(event.event_type))
        if event_type not in self._events:
            return
        self._trigger_event(event_type, event_attributes(dict(event.data)))
        self.async_write_ha_state()
