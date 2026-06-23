"""Test-only stub of the Battery Notes ↔ Home Keeper glue integration.

Bind-mounted into the e2e container's ``custom_components`` (not shipped). Battery
Notes is in Home Keeper's companion *catalog* (``companions_catalog.py``), so the
glue simply being installed is enough for Home Keeper to detect and surface it as
a *connected* companion — no registration call needed. This exercises the
catalog-detection (pull) path, complementing the Pawsistant push stub.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

DOMAIN = "home_keeper_battery_notes"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """No-op: Home Keeper detects this glue from its catalog once installed."""
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True
