"""Diagnostics support for Home Keeper.

Provides a downloadable snapshot (from a device or the config entry) of the tasks
and assets Home Keeper manages, to make support/debugging easier. Diagnostics are
routinely attached to public GitHub issues, so potentially personal fields are
redacted: appliance serial numbers, free-form notes/metadata, and per-completion
``who`` (a person entity id) / ``photo`` (an image reference). Schedules and
structural data are kept so the dump is still useful for debugging.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from . import assets as asset_model
from .const import ASSET_IDENTIFIER_PREFIX, DOMAIN
from .coordinator import HomeKeeperCoordinator

# Redacted by key anywhere in the tasks/assets structure (recursively) before the
# snapshot leaves the instance — these can carry personal or identifying data.
# Structural/schedule fields (recurrence, due dates, thresholds) are kept so the
# dump stays useful for debugging.
TO_REDACT = {"serial_number", "notes", "who", "photo"}


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
        "tasks": async_redact_data(tasks, TO_REDACT),
        "assets": async_redact_data(assets, TO_REDACT),
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return the Home Keeper tasks/assets associated with a single device.

    Scopes the config-entry dump to the device whose page the download was started
    from — its appliance (a virtual asset whose ``asset_<id>`` identifier or
    ``device_id`` matches) and every task that lives on it (attached by ``device_id``,
    a self-owned task device keyed on the bare task id, or derived from one of the
    appliance's parts).
    """
    coordinator: HomeKeeperCoordinator = entry.runtime_data
    tasks = coordinator.store.list_tasks()
    assets = coordinator.store.list_assets()

    hk_idents = {ident for domain, ident in device.identifiers if domain == DOMAIN}
    device_assets = [
        asset
        for asset in assets
        if asset.get("device_id") == device.id
        or f"{ASSET_IDENTIFIER_PREFIX}_{asset.get('id')}" in hk_idents
    ]
    device_tasks = [
        task
        for task in tasks
        if task.get("device_id") == device.id
        or task.get("id") in hk_idents
        or any(
            asset_model.task_relates_to_asset(task, asset) for asset in device_assets
        )
    ]
    return {
        "device": {
            "id": device.id,
            "name": device.name,
            "identifiers": list(hk_idents),
        },
        "counts": {
            "tasks": len(device_tasks),
            "assets": len(device_assets),
            "parts": sum(len(a.get("parts", [])) for a in device_assets),
        },
        "tasks": async_redact_data(device_tasks, TO_REDACT),
        "assets": async_redact_data(device_assets, TO_REDACT),
    }
