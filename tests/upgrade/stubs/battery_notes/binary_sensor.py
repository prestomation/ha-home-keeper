"""The battery-low sensor the Home Keeper glue watches.

Starts ``on`` (battery low) so the glue creates its task during phase 1 of the
upgrade run, before the Home Assistant version changes underneath it.
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

from . import SOURCE_IDENTIFIER, SOURCE_NAME


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([StubBatteryLow()])


class StubBatteryLow(BinarySensorEntity):
    """Battery low on the kitchen sensor."""

    _attr_has_entity_name = True
    _attr_name = "Battery low"
    _attr_unique_id = "kitchen_sensor_battery_low"
    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _attr_is_on = True

    @property
    def device_info(self) -> DeviceInfo:
        # Deliberately the *source* device's identifiers — the pre-2026.8 merge that
        # Home Assistant now splits. See this package's module docstring.
        return DeviceInfo(identifiers={SOURCE_IDENTIFIER}, name=SOURCE_NAME)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # The glue reads its task notes from these.
        return {
            "battery_type": "AA",
            "battery_quantity": 2,
            "battery_level": 8,
        }
