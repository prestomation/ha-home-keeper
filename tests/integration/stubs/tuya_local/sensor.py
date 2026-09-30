"""One filter-life sensor on the stub's device."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
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
    async_add_entities([StubFilterLifeSensor()])


class StubFilterLifeSensor(SensorEntity):
    """A static filter life, below the preset's 10% limit."""

    _attr_has_entity_name = True
    _attr_name = "Filter life"
    # The key the real Tuya Local integration gives this entity, and the one the
    # ``tuya_local_percent_low`` preset selects.
    _attr_translation_key = "filter_life"
    _attr_unique_id = "e2e_air_purifier_filter_life"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_value = 5

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={DEVICE_IDENTIFIER}, name=DEVICE_NAME)
