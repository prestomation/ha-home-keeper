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


def _is_asset_device(device: dr.DeviceEntry) -> bool:
    """True if *device* is one of our provisioned virtual asset devices.

    Virtual asset devices carry an ``asset_``-prefixed identifier; per-task
    self-owned devices key on the bare (uuid) task id, so they never match.
    """
    return any(
        domain == DOMAIN and ident.startswith(f"{ASSET_IDENTIFIER_PREFIX}_")
        for domain, ident in device.identifiers
    )


def _supports_kwarg(func: Any, name: str) -> bool:
    try:
        return name in inspect.signature(func).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins without signatures
        # Be conservative: if we can't confirm support, don't pass the kwarg.
        return False


async def async_apply_asset_change(
    hass: HomeAssistant, entry: ConfigEntry, store: HomeKeeperStore
) -> None:
    """Reconcile devices then reload the entry after an asset mutation.

    Shared by the service and websocket handlers so both refresh the registry and
    the per-asset/per-task entity set identically. The reload re-runs setup
    reconciliation, but that pass is idempotent (get_or_create returns the existing
    device; snapshot writes are skipped when unchanged).
    """
    await async_reconcile_assets(hass, entry, store)
    await hass.config_entries.async_reload(entry.entry_id)


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
    dirty = False

    for asset in store.list_assets():
        if asset.get("kind") == ASSET_KIND_VIRTUAL:
            # _reconcile_virtual persists its own device_id write-back.
            await _reconcile_virtual(hass, entry, store, registry, asset)
            wanted_identifiers.add(asset_model.asset_device_identifier(asset["id"]))
        elif _reconcile_existing(registry, asset):
            dirty = True

    # In-place edits to existing-device assets (recovered device_id, refreshed
    # identifiers/connections snapshot) must be flushed to disk or they're lost on
    # restart and snapshot recovery can never work.
    if dirty:
        await store.async_persist()

    # Prune asset devices we own that no longer correspond to an asset. Guard
    # against ever removing a per-task self-owned device — those key on the bare
    # task id — by excluding any device that matches a current task's identifier,
    # even in the (uuid-impossible) case a task id collides with the asset prefix.
    task_identifiers = {(DOMAIN, tid) for tid in store.get_tasks()}
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            _is_asset_device(device)
            and not (device.identifiers & wanted_identifiers)
            and not (device.identifiers & task_identifiers)
        ):
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
    # Note the absence of a truthy guard on area_id: passing None propagates an
    # area *clear* to the device (a truthy-only check would strand the old area).
    area_id = asset.get("area_id") or None
    if area_id != device.area_id:
        updates["area_id"] = area_id
    if updates:
        device = registry.async_update_device(device.id, **updates)

    await store.set_asset_device_id(asset["id"], device.id)


def _reconcile_existing(registry: dr.DeviceRegistry, asset: dict[str, Any]) -> bool:
    """Resolve an existing-device asset and refresh its snapshot in place.

    Returns ``True`` if the asset dict was mutated (so the caller persists it).
    """
    device_id = asset.get("device_id")
    device = registry.async_get(device_id) if device_id else None
    changed = False
    if device is None:
        # The referenced device may have been recreated under a new id by its
        # owning integration; try to recover it from the stored snapshot.
        device = _resolve_by_snapshot(registry, asset)
        if device is None:
            _LOGGER.warning(
                "Home Keeper asset %s references missing device %s; metadata "
                "entities will not appear until the device returns",
                asset["id"],
                device_id,
            )
            return False
        asset["device_id"] = device.id
        changed = True
    # Refresh the reconciliation snapshot from the live device (only marking the
    # asset dirty when it actually changed, to avoid needless writes).
    identifiers = [list(i) for i in device.identifiers]
    connections = [list(c) for c in device.connections]
    if asset.get("identifiers") != identifiers:
        asset["identifiers"] = identifiers
        changed = True
    if asset.get("connections") != connections:
        asset["connections"] = connections
        changed = True
    return changed


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
