"""Test-only stub: the "physical" devices other integrations attach themselves to.

This stands in for whatever integration actually discovered the hardware — a Zigbee
coordinator, a vendor cloud integration, whatever. It exists so the upgrade suite has
devices that are unambiguously owned by *someone else*, which is the precondition for
every interesting case in #183.

It owns two devices:

* ``kitchen_sensor`` — a battery-powered sensor. The ``battery_notes`` stub merges
  onto this one by copying its identifiers, reproducing the pre-2026.8 shape that
  Home Assistant now splits.
* ``water_heater`` — a plain appliance, used for the Home Keeper asset scenarios.

Nothing here is shipped; it is bind-mounted into the upgrade container only.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

DOMAIN = "hk_upgrade_source"

PLATFORMS = ["sensor"]

KITCHEN_SENSOR = (DOMAIN, "kitchen_sensor")
KITCHEN_SENSOR_NAME = "Kitchen Sensor"
WATER_HEATER = (DOMAIN, "water_heater")
WATER_HEATER_NAME = "Water Heater"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    registry = dr.async_get(hass)
    for identifier, name, model in (
        (KITCHEN_SENSOR, KITCHEN_SENSOR_NAME, "Battery sensor"),
        (WATER_HEATER, WATER_HEATER_NAME, "Water heater"),
    ):
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={identifier},
            name=name,
            manufacturer="Upgrade Fixture Co",
            model=model,
        )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
