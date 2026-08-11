"""Test-only stub of the Battery Notes ↔ Home Keeper glue integration.

Bind-mounted into the e2e container's ``custom_components`` (not shipped). Battery
Notes is in Home Keeper's companion *catalog* (``companions_catalog.py``), so the
glue simply being installed is enough for Home Keeper to detect and surface it as
a *connected* companion — no registration call needed. This exercises the
catalog-detection (pull) path, complementing the Pawsistant push stub.

The stub also owns **one real registry device** with a battery sensor on it. That
device is what ``test_device_attach.py`` attaches a Home Keeper task to, so the
suite has a *foreign* device (owned by another config entry) to assert against —
previously nothing in the container provided one, which is why the HA 2026.8
device-registry split went unnoticed. See #183.

Note the deliberate simplification: in production the device belongs to the
upstream ``battery_notes`` integration and the glue only *reads* its entities. The
stub collapses the two into one config entry, because what is under test here is
Home Keeper's behaviour when a task points at a device it does not own — not the
glue's own wiring. ``tests/upgrade`` fetches the real glue and its real upstream
when it needs that fidelity.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

DOMAIN = "home_keeper_battery_notes"

PLATFORMS = ["sensor"]

#: Registry identifier of the stub's device. Tests resolve the device id from this
#: rather than hard-coding a uuid, since HA assigns the id at creation time.
DEVICE_IDENTIFIER = (DOMAIN, "e2e_battery_device")
DEVICE_NAME = "E2E Battery Device"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register the stub's device, then set up the sensor that lives on it."""
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={DEVICE_IDENTIFIER},
        name=DEVICE_NAME,
        manufacturer="Home Keeper e2e",
        model="Battery-backed device",
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
