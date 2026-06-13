"""Registry-device provisioning for Home Keeper assets.

This is the *virtual-device* half of the asset feature (see ``IDEAS.md`` /
``docs/DESIGN.md``): when an appliance has no Home Assistant device to attach
maintenance tasks to, Home Keeper registers a real device-registry entry for it so
tasks, future batteries, and asset metadata all converge on one device page.

Devices we create are tied to our config entry, so Home Assistant removes them
automatically when the integration is removed — no residue. Reconciliation is
idempotent: it can run on every setup and after every asset mutation.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from . import assets as asset_model
from .const import ASSET_IDENTIFIER_PREFIX, ASSET_KIND_VIRTUAL, DOMAIN
from .store import HomeKeeperStore

_LOGGER = logging.getLogger(__name__)

# Registry fields we keep in sync from a virtual asset's editable attributes.
_SYNCED_FIELDS = ("name", "manufacturer", "model", "serial_number")


def _is_asset_device(device: dr.DeviceEntry) -> bool:
    """True if *device* is one of our provisioned virtual asset devices."""
    return any(
        domain == DOMAIN and ident.startswith(f"{ASSET_IDENTIFIER_PREFIX}_")
        for domain, ident in device.identifiers
    )


def _supports_kwarg(func: Any, name: str) -> bool:
    try:
        return name in inspect.signature(func).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins without signatures
        return True


async def async_reconcile_assets(
    hass: HomeAssistant, entry: ConfigEntry, store: HomeKeeperStore
) -> None:
    """Make the device registry match the current set of assets.

    * Virtual assets get a registry device created (idempotently) and kept in sync
      with their editable fields; the assigned ``device.id`` is written back to the
      asset so tasks/metadata entities can resolve it.
    * Existing-device assets get their identifiers/connections snapshotted for
      reconciliation, and a warning if the referenced device has gone away.
    * Orphan asset devices (ours, but no longer backed by an asset) are removed.
    """
    registry = dr.async_get(hass)
    wanted_identifiers: set[tuple[str, str]] = set()

    for asset in store.list_assets():
        if asset.get("kind") == ASSET_KIND_VIRTUAL:
            await _reconcile_virtual(hass, entry, store, registry, asset)
            wanted_identifiers.add(asset_model.asset_device_identifier(asset["id"]))
        else:
            _reconcile_existing(store, registry, asset)

    # Prune asset devices we own that no longer correspond to an asset.
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if _is_asset_device(device) and not (device.identifiers & wanted_identifiers):
            _LOGGER.debug("Removing orphaned asset device %s", device.id)
            registry.async_remove_device(device.id)


async def _reconcile_virtual(
    hass: HomeAssistant,
    entry: ConfigEntry,
    store: HomeKeeperStore,
    registry: dr.DeviceRegistry,
    asset: dict[str, Any],
) -> None:
    identifier = asset_model.asset_device_identifier(asset["id"])
    device = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={identifier},
        name=asset["name"],
        manufacturer=asset.get("manufacturer") or None,
        model=asset.get("model") or None,
        serial_number=asset.get("serial_number") or None,
    )

    # Keep the registry in sync with subsequent edits.
    updates: dict[str, Any] = {}
    if device.name != asset["name"]:
        updates["name"] = asset["name"]
    for field in ("manufacturer", "model", "serial_number"):
        desired = asset.get(field) or None
        if getattr(device, field, None) != desired and _supports_kwarg(
            registry.async_update_device, field
        ):
            updates[field] = desired
    area_id = asset.get("area_id") or None
    if area_id and device.area_id != area_id:
        updates["area_id"] = area_id
    if updates:
        device = registry.async_update_device(device.id, **updates)

    await store.set_asset_device_id(asset["id"], device.id)


def _reconcile_existing(
    store: HomeKeeperStore, registry: dr.DeviceRegistry, asset: dict[str, Any]
) -> None:
    device_id = asset.get("device_id")
    device = registry.async_get(device_id) if device_id else None
    if device is None:
        # The referenced device may have been recreated under a new id by its
        # owning integration; try to recover it from the stored snapshot.
        device = _resolve_by_snapshot(registry, asset)
        if device is not None:
            asset["device_id"] = device.id
        else:
            _LOGGER.warning(
                "Home Keeper asset %s references missing device %s; metadata "
                "entities will not appear until the device returns",
                asset["id"],
                device_id,
            )
            return
    # Refresh the reconciliation snapshot from the live device.
    asset["identifiers"] = [list(i) for i in device.identifiers]
    asset["connections"] = [list(c) for c in device.connections]


def _resolve_by_snapshot(
    registry: dr.DeviceRegistry, asset: dict[str, Any]
) -> dr.DeviceEntry | None:
    """Find a device matching the asset's stored identifiers/connections."""
    for ident in asset.get("identifiers", []):
        device = registry.async_get_device(identifiers={tuple(ident)})
        if device is not None:
            return device
    connections = {tuple(c) for c in asset.get("connections", [])}
    if connections:
        return registry.async_get_device(connections=connections)
    return None


async def async_remove_asset_device(
    hass: HomeAssistant, asset: dict[str, Any]
) -> str | None:
    """Remove the virtual device backing *asset*; returns its device id if removed.

    No-op for existing-device assets (we never owned that device). Tasks attached
    to a removed virtual device should be detached by the caller.
    """
    if asset.get("kind") != ASSET_KIND_VIRTUAL:
        return None
    registry = dr.async_get(hass)
    identifier = asset_model.asset_device_identifier(asset["id"])
    device = registry.async_get_device(identifiers={identifier})
    if device is not None:
        registry.async_remove_device(device.id)
        return device.id
    return asset.get("device_id")
