"""One sensor per source device, so neither device is entity-less."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import KITCHEN_SENSOR, KITCHEN_SENSOR_NAME, WATER_HEATER, WATER_HEATER_NAME


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [
            SourceTemperature(KITCHEN_SENSOR, KITCHEN_SENSOR_NAME, "kitchen", 21),
            SourceTemperature(WATER_HEATER, WATER_HEATER_NAME, "water_heater", 55),
        ]
    )


class SourceTemperature(SensorEntity):
    """A constant temperature — static so nothing goes unavailable mid-run."""

    _attr_has_entity_name = True
    _attr_name = "Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self, identifier: tuple[str, str], device_name: str, slug: str, value: int
    ) -> None:
        self._identifier = identifier
        self._device_name = device_name
        self._attr_unique_id = f"{slug}_temperature"
        self._attr_native_value = value

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={self._identifier}, name=self._device_name)
