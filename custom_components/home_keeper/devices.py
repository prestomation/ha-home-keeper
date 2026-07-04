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
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from . import assets as asset_model
from .const import (
    ASSET_IDENTIFIER_PREFIX,
    ASSET_KIND_VIRTUAL,
    DOMAIN,
    PANEL_URL_PATH,
)
from .store import HomeKeeperStore

_LOGGER = logging.getLogger(__name__)


def _asset_configuration_url(asset_id: str) -> str:
    """Deep-link the device page straight to this appliance's panel detail page.

    The panel is route-driven (``parseRoute``/``buildPath``): an appliance detail lives
    at ``/home-keeper/appliances/<asset_id>``, so the device page's "Visit" link lands
    on that appliance — its documents/inventory/history — rather than the panel root.

    The device page renders a ``homeassistant://`` ``configuration_url`` by replacing
    the scheme with ``/`` (``homeassistant://X`` -> ``/X``) — there is **no**
    ``navigate/`` action segment on the web frontend, so the URL must be the bare in-app
    path. ``homeassistant://navigate/...`` produces a dead ``/navigate/...`` link that
    bounces to the default dashboard.
    """
    return f"homeassistant://{PANEL_URL_PATH}/appliances/{asset_id}"


def area_exists(hass: HomeAssistant, area_id: str | None) -> bool:
    """True if *area_id* is empty/None or a real HA area (boundary validation)."""
    if not area_id:
        return True
    return ar.async_get(hass).async_get_area(area_id) is not None


def area_names(hass: HomeAssistant) -> dict[str, str]:
    """Map ``area_id`` -> human-readable name (for the inventory export)."""
    return {area.id: area.name for area in ar.async_get(hass).async_list_areas()}


def _ancestor_depth(store: HomeKeeperStore, asset: dict[str, Any]) -> int:
    """Number of parent links above *asset* (used to provision parents first)."""
    depth = 0
    seen: set[str] = {asset["id"]}
    cursor = asset.get("parent_asset_id")
    while cursor and cursor not in seen:
        seen.add(cursor)
        depth += 1
        parent = store.get_asset(cursor)
        cursor = parent.get("parent_asset_id") if parent else None
    if cursor:  # would_create_cycle should prevent this; surface corrupt storage.
        _LOGGER.error("Cyclic parent chain detected at asset %s", asset["id"])
    return depth


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
    # Wear parts may have created/removed derived maintenance tasks, and an edit may
    # have turned auto-buy on/off or changed a threshold; sync both before the reload
    # rebuilds the per-task entity set.
    await store.reconcile_part_tasks()
    await store.reconcile_buy_tasks()
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

    # Provision parents before children so a subdevice's via_device parent already
    # has a resolved device id when we link it.
    for asset in sorted(store.list_assets(), key=lambda a: _ancestor_depth(store, a)):
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


async def async_prune_orphaned_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop Home Keeper from devices that no longer carry any of our entities.

    Per-task entities (``sensor.*_next_due``, ``binary_sensor.*_overdue``) attach to
    the task's device — an existing/shared device, or a self-owned device we create
    when the task has none. When the task goes away (Problem Sensor Sync disabled, an
    entity/device/area/label excluded, or an ordinary delete) the platforms remove
    those entities, but Home Assistant keeps the device/association — so the device
    lingers under **Settings → Devices & Services → Home Keeper** with zero entities.

    Call this *after* ``async_forward_entry_setups`` so the entity registry already
    reflects the current set, then drop our config-entry link from any non-asset
    device we no longer have an entity on. ``async_update_device`` removes a
    self-owned device outright (we were its last config entry) and merely detaches us
    from a shared device (its real owner keeps it). Virtual asset devices may be
    legitimately entity-less and are reconciled by ``async_reconcile_assets``, so
    they are skipped here.
    """
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    for device in list(dr.async_entries_for_config_entry(dev_reg, entry.entry_id)):
        if _is_asset_device(device):
            continue
        has_our_entity = any(
            entity.config_entry_id == entry.entry_id
            for entity in er.async_entries_for_device(
                ent_reg, device.id, include_disabled_entities=True
            )
        )
        if not has_our_entity:
            _LOGGER.debug("Pruning Home Keeper from orphaned device %s", device.id)
            dev_reg.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )


async def _reconcile_virtual(
    hass: HomeAssistant,
    entry: ConfigEntry,
    store: HomeKeeperStore,
    registry: dr.DeviceRegistry,
    asset: dict[str, Any],
) -> None:
    identifier = asset_model.asset_device_identifier(asset["id"])

    # Resolve the native via_device parent (only our own virtual subdevices).
    parent_asset_id = asset.get("parent_asset_id") or None
    via_device = (
        asset_model.asset_device_identifier(parent_asset_id)
        if parent_asset_id
        else None
    )
    parent = store.get_asset(parent_asset_id) if parent_asset_id else None
    parent_device_id = parent.get("device_id") if parent else None

    configuration_url = _asset_configuration_url(asset["id"])
    create_kwargs: dict[str, Any] = {
        "config_entry_id": entry.entry_id,
        "identifiers": {identifier},
        "name": asset["name"],
        "manufacturer": asset.get("manufacturer") or None,
        "model": asset.get("model") or None,
        "configuration_url": configuration_url,
    }
    # serial_number reached DeviceInfo/async_get_or_create later than the others; only
    # seed it on create when this HA version accepts it (the update loop below is
    # likewise guarded), so an older core still provisions the device cleanly.
    if _supports_kwarg(registry.async_get_or_create, "serial_number"):
        create_kwargs["serial_number"] = asset.get("serial_number") or None
    if via_device is not None:
        create_kwargs["via_device"] = via_device
    device = registry.async_get_or_create(**create_kwargs)

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
    # Guard against a dangling area_id (the area was deleted in HA after it was
    # assigned): async_update_device rejects an unknown area, so self-heal to None.
    area_id = asset.get("area_id") or None
    if area_id and not area_exists(hass, area_id):
        area_id = None
    if area_id != device.area_id:
        updates["area_id"] = area_id
    if device.configuration_url != configuration_url:
        updates["configuration_url"] = configuration_url
    # Re-parent / un-parent after creation (via_device on create only applies the
    # first time). via_device_id is the parent's *device id*, which parents-first
    # ordering has already resolved.
    if _supports_kwarg(registry.async_update_device, "via_device_id"):
        if device.via_device_id != parent_device_id:
            updates["via_device_id"] = parent_device_id
    elif parent_asset_id and device.via_device_id is None:
        _LOGGER.warning(
            "This Home Assistant version can't update a device's parent after "
            "creation; subdevice %s may not nest under its parent",
            asset["id"],
        )
    if updates:
        updated = registry.async_update_device(device.id, **updates)
        if updated is not None:
            device = updated

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
