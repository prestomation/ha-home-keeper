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
    ASSET_KIND_EXISTING,
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


def _split_successor(
    registry: dr.DeviceRegistry,
    device_id: str,
    entry_id: str,
    *,
    snapshot: dict[str, Any] | None = None,
) -> dr.DeviceEntry | None:
    """The live device a pre-2026.8 *composite* device id should now point at.

    Home Assistant keeps the old id resolvable: ``async_get`` synthesizes a read-only
    composite for it, which is why a stale id looks perfectly healthy and why this asks
    ``async_get_devices_for_composite_device_id`` instead — that returns the real, live
    devices the id was split into, and an empty list for an ordinary id.

    Of those, the one to adopt is the split that is **not ours**: our half is an
    artefact of the old identifier copy, and the task is about the other integration's
    device. Where several remain, the composite's former ``primary_config_entry`` names
    the successor Home Assistant itself treats as primary; the sorted fallback keeps
    repeated runs deterministic.

    Once every half has been re-homed Home Assistant garbage-collects the composite,
    and ``async_get_devices_for_composite_device_id`` then answers the same empty list
    it gives an ordinary id — the composite is gone, so there is nothing left to ask.
    A caller that holds an identifiers/connections *snapshot* of the original device
    can still resolve it, so pass one and the lookup falls back to matching that
    snapshot against the live registry (``_resolve_by_snapshot``). Assets keep such a
    snapshot; tasks do not.

    Returns ``None`` on Home Assistant versions with no composite concept (pre-2026.8),
    where there is nothing to heal.
    """
    resolve = getattr(registry, "async_get_devices_for_composite_device_id", None)
    if resolve is None:
        return None
    splits = [d for d in resolve(device_id) if entry_id not in d.config_entries]
    if not splits:
        # An empty answer means one of two very different things: a collected
        # composite, or an ordinary id that was never split. Only the first is ours
        # to repair, and ``async_get`` separates them — a composite is synthesized
        # from the devices still pointing at it, so once they are all re-homed there
        # is nothing left to synthesize and this returns None, while a live device
        # answers for itself. Without the check a healthy asset whose snapshot has
        # drifted (identifiers moved to another device, and the heal runs before
        # ``_reconcile_existing`` refreshes them) would be silently repointed onto
        # whatever the stale snapshot happened to match.
        if snapshot is not None and registry.async_get(device_id) is None:
            return _resolve_by_snapshot(registry, snapshot, prefer_not_entry=entry_id)
        return None
    if len(splits) > 1:
        composite = registry.async_get(device_id)
        primary = getattr(composite, "primary_config_entry", None)
        if primary:
            preferred = [d for d in splits if primary in d.config_entries]
            if preferred:
                return preferred[0]
        # Three or more foreign splits with no primary named: nothing in the registry
        # says which one the task meant, so this is an arbitrary pick — sorted only so
        # that repeated setups keep choosing the same one instead of flip-flopping the
        # task between devices. A two-way split, which is what the merge this repairs
        # actually produces, never reaches here.
        return sorted(splits, key=lambda d: d.id)[0]
    return splits[0]


async def async_heal_split_device_ids(
    hass: HomeAssistant, entry: ConfigEntry, store: HomeKeeperStore
) -> None:
    """Re-point tasks whose device Home Assistant 2026.8 split apart (#183).

    An install that upgraded Home Assistant before Home Keeper has, per attached thing,
    a device id that is now a *composite*: Home Assistant split the merged device into
    one per config entry and handed us our own half. Left alone that shows a raw
    identifier where a device name belongs, splits a device's tasks across two entries,
    and makes companion integrations create duplicate tasks.

    It does **not** present as a missing device. Home Assistant answers ``async_get``
    for the old id with a synthesized composite, so a naive "does this still resolve?"
    check finds nothing wrong — it only refuses to *link an entity* to it, which is the
    visible symptom and the reason this repair exists.

    Assets of kind ``existing`` carry the same kind of reference and are healed in the
    same pass, against the same mapping. Sharing one mapping is what keeps a device's
    task and its asset together: only the asset keeps an identifiers/connections
    snapshot, so a composite Home Assistant has already garbage-collected is resolvable
    *only* from the asset — and a task on that same device has to inherit the answer or
    it stays pointing at the dead id while the asset moves on without it.

    Runs before the platforms set up, so entities are created against the healed id
    straight away. Our old half then holds none of our entities and
    ``async_prune_orphaned_devices`` removes it at the end of setup. Idempotent: once
    healed nothing resolves to a composite and this does no writes.
    """
    registry = dr.async_get(hass)
    # One mapping (dead id -> live id) for tasks and assets alike.
    mapping: dict[str, str] = {}
    # Ids the snapshot-less pass could not resolve, so a hundred tasks on one dead
    # device cost one lookup rather than a hundred. Assets still retry these: a
    # snapshot is exactly the extra information that can resolve them.
    unresolved: set[str] = set()

    def _record(device_id: str | None, snapshot: dict[str, Any] | None = None) -> None:
        """Resolve *device_id*'s successor into the shared mapping, if it has one."""
        if not device_id or device_id in mapping:
            return
        if snapshot is None and device_id in unresolved:
            return
        successor = _split_successor(
            registry, device_id, entry.entry_id, snapshot=snapshot
        )
        # A successor equal to the id we started from is not a repair; skipping it
        # keeps the pass a genuine no-op once everything is healed.
        if successor is not None and successor.id != device_id:
            mapping[device_id] = successor.id
        elif snapshot is None:
            unresolved.add(device_id)

    for task in store.get_tasks().values():
        # No snapshot: a task stores only the id. A GC'd composite is unresolvable
        # from here, and gets picked up below if an asset shares the device.
        _record(task.get("device_id"))
    for asset in store.list_assets():
        if asset.get("kind") == ASSET_KIND_EXISTING:
            # The asset dict doubles as the snapshot — ``_reconcile_existing`` keeps
            # its identifiers/connections refreshed from the live device.
            _record(asset.get("device_id"), asset)

    if mapping:
        changed_tasks = await store.async_repoint_device_ids(mapping)
        changed_assets = await store.async_repoint_asset_device_ids(mapping)
        _LOGGER.info(
            "Repaired %s task and %s asset device reference(s) across %s device(s) "
            "that Home Assistant 2026.8 split into one device per config entry",
            changed_tasks,
            changed_assets,
            len(mapping),
        )

    # Healing the ids stops contributors duplicating from here on, but a duplicate
    # already created while the ids were broken is still sitting there, and the user
    # can't remove it — contributed tasks are deletion-protected. Merging needs to know
    # which live devices came from the same original, or the two copies look unrelated:
    # they point at different halves of the same split.
    canonical: dict[str, str] = {}
    for device in registry.devices.values():
        # Explicit loop rather than a comprehension: composite_device_id is
        # `str | None`, and a truthiness guard inside a comprehension doesn't narrow
        # the value expression for the type checker.
        composite_id = getattr(device, "composite_device_id", None)
        if composite_id:
            canonical[device.id] = composite_id
    merged = await store.async_merge_split_duplicates(canonical)
    if merged:
        _LOGGER.info("Merged %s duplicate contributed task(s) after the split", merged)


async def async_detach_legacy_merged_devices(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Drop our config entry from devices an older Home Keeper merged onto.

    Before HA 2026.8, attaching a task copied the target device's identifiers into a
    ``DeviceInfo``, which merged our entities onto that device **and** added our config
    entry to it. This version links entities instead (see
    ``coordinator.device_link_for_task``) and never needs to be on a device it doesn't
    own, but the old association survives in the registry on its own.

    That association is what makes Home Assistant split the device on upgrade, so
    clearing it is what lets someone still on a pre-2026.8 Home Assistant update Home
    Keeper first and then upgrade cleanly. Measured in
    ``tests/upgrade/test_upgrade_order.py``: without this, every upgrade order is
    damaged identically, and there is no advice worth giving.

    Deliberately limited to devices that have **another** config entry besides ours.
    Removing the last entry from a device deletes it, which would strand the entities
    sitting on it — that case is the already-split leftover, and repairing it needs the
    entities re-pointed first (still open; see ``docs/DEVICE_REGISTRY_2026_8_PLAN.md``).

    That check and the update below are not atomic: nothing stops another integration
    removing its own entry in between, which would make ours the last one after all.
    Home Assistant's registry offers no remove-if-not-last, and the window is a few
    synchronous statements during our setup, so this is the best the API allows.
    Our own devices are skipped: they carry a ``home_keeper`` identifier, and we are
    supposed to own those.
    """
    dev_reg = dr.async_get(hass)
    for device in list(dr.async_entries_for_config_entry(dev_reg, entry.entry_id)):
        if any(domain == DOMAIN for domain, _ in device.identifiers):
            continue  # one of ours (virtual asset or self-owned task device)
        others = set(device.config_entries) - {entry.entry_id}
        if not others:
            continue  # sole owner: removing us would delete the device and its entities
        _LOGGER.debug(
            "Detaching Home Keeper from %s: linked, not owned (legacy merge)", device.id
        )
        dev_reg.async_update_device(device.id, remove_config_entry_id=entry.entry_id)


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
    registry: dr.DeviceRegistry,
    snapshot: dict[str, Any],
    *,
    prefer_not_entry: str | None = None,
) -> dr.DeviceEntry | None:
    """Find a live device matching a snapshot's stored identifiers/connections.

    *snapshot* is an asset dict (or any mapping with ``identifiers`` and
    ``connections`` keys). Serves two callers:

    * ``_reconcile_existing`` recovering an asset whose device its owning integration
      re-created under a new id — no preference, first match wins.
    * ``_split_successor`` resolving a composite Home Assistant has already
      garbage-collected. There, ``prefer_not_entry`` names *our* config entry, and a
      matching device that isn't ours wins: after a 2026.8 split the identifiers were
      copied onto our half too, and the one worth adopting is the other integration's
      real device, not the artefact. The sorted tie-break only keeps repeated setups
      choosing the same device rather than flip-flopping between them.
    """
    candidates: list[dr.DeviceEntry] = []
    seen: set[str] = set()

    def _add(device: dr.DeviceEntry | None) -> None:
        if device is not None and device.id not in seen:
            seen.add(device.id)
            candidates.append(device)

    for ident in snapshot.get("identifiers", []):
        _add(registry.async_get_device(identifiers={tuple(ident)}))
        # With no preference there is nothing a second candidate could change, so
        # stop at the first hit rather than finishing the sweep.
        if prefer_not_entry is None and candidates:
            return candidates[0]
    connections = {tuple(c) for c in snapshot.get("connections", [])}
    if connections:
        _add(registry.async_get_device(connections=connections))

    if not candidates:
        return None
    if prefer_not_entry is None:
        return candidates[0]
    foreign = [d for d in candidates if prefer_not_entry not in d.config_entries]
    return sorted(foreign or candidates, key=lambda d: d.id)[0]


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
