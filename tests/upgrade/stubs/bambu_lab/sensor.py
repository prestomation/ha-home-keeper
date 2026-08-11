"""Cumulative usage hours — the second half of the glue's maintenance tasks.

Without this the glue still creates calendar-based maintenance tasks, just without
the hours component. Including it exercises the fuller path.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DEVICE_IDENTIFIER, DEVICE_NAME, SERIAL


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([StubUsageHours()])


class StubUsageHours(SensorEntity):
    """A constant total, so the value can't drift between the two boots."""

    _attr_has_entity_name = True
    _attr_name = "Total usage hours"
    _attr_unique_id = f"{SERIAL}_total_usage_hours"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_native_value = 780

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={DEVICE_IDENTIFIER}, name=DEVICE_NAME)
