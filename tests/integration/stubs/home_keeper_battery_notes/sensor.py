"""One battery sensor on the stub's device.

The device needs at least one entity of its own so assertions can tell "Home Keeper
attached its entities to the foreign device" apart from "the foreign device only
ever held Home Keeper entities". It also mirrors the real Battery Notes shape
closely enough that the glue-facing assertions read the same.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DEVICE_IDENTIFIER, DEVICE_NAME


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([StubBatterySensor()])


class StubBatterySensor(SensorEntity):
    """A static battery level, so the sensor never goes unavailable mid-suite."""

    _attr_has_entity_name = True
    _attr_name = "Battery"
    _attr_unique_id = "e2e_battery_device_battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_value = 42

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={DEVICE_IDENTIFIER}, name=DEVICE_NAME)
