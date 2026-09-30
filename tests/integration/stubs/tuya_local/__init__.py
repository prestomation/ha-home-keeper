"""Test-only stub of the Tuya Local integration.

Bind-mounted into the test container's ``custom_components`` (not shipped). It owns
one device with one sensor that carries the ``filter_life`` entity key, the key the
``tuya_local_percent_low`` integration preset selects. With it, the preset picker has
one preset that really matches an entity, so the tests and the screenshots can show
a preset in the *For your devices* group. The value is low, so a companion made from
the preset opens a task.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

DOMAIN = "tuya_local"

PLATFORMS = ["sensor"]

DEVICE_IDENTIFIER = (DOMAIN, "e2e_air_purifier")
DEVICE_NAME = "E2E Air Purifier"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register the stub's device, then set up the sensor that lives on it."""
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={DEVICE_IDENTIFIER},
        name=DEVICE_NAME,
        manufacturer="Home Keeper e2e",
        model="Air purifier",
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
