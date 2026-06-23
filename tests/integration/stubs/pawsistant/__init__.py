"""Test-only stub of a Home Keeper companion (push self-registration).

Lives under ``tests/integration/stubs/`` and is bind-mounted into the e2e Home
Assistant container's ``custom_components`` — it is **not** part of the shipped
integration. On setup it self-registers with Home Keeper through the public
``home_keeper.register_companion`` service (the same push path a real companion
uses), so the panel's Settings → Companions section renders a real *connected*
companion in e2e and screenshot runs. Pawsistant is deliberately not in Home
Keeper's catalog, so it exercises the self-registration (push) path; the Battery
Notes stub exercises the catalog-detection (pull) path.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

DOMAIN = "pawsistant"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register this stub with Home Keeper as a connected companion."""
    await hass.services.async_call(
        "home_keeper",
        "register_companion",
        {
            "domain": DOMAIN,
            "name": "Pawsistant",
            "icon": "mdi:paw",
            "description": (
                "Pet care tracker — logs walks, meals, meds and weight, and can "
                "schedule recurring pet-care chores as Home Keeper tasks."
            ),
            "config_entry_id": entry.entry_id,
            "docs_url": "https://github.com/prestomation/Pawsistant",
            "capabilities": ["care_schedules"],
        },
        blocking=True,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Nothing to tear down — the in-memory registry is reconciled by Home Keeper."""
    return True
