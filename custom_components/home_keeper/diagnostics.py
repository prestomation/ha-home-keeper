"""Diagnostics support for Home Keeper.

Provides a downloadable snapshot (from a device or the config entry) of the tasks
and assets Home Keeper manages, to make support/debugging easier. The data is local
and non-sensitive (maintenance schedules + appliance metadata), so nothing is
redacted beyond free-form notes being kept as-is.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import HomeKeeperCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the Home Keeper config entry."""
    coordinator: HomeKeeperCoordinator = entry.runtime_data
    tasks = coordinator.store.list_tasks()
    assets = coordinator.store.list_assets()
    return {
        "counts": {
            "tasks": len(tasks),
            "assets": len(assets),
            "parts": sum(len(a.get("parts", [])) for a in assets),
            "virtual_devices": sum(1 for a in assets if a.get("kind") == "virtual"),
        },
        "tasks": tasks,
        "assets": assets,
    }
