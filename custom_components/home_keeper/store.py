"""Persistent task storage for Home Keeper.

A single JSON document under ``.storage/home_keeper`` holds all tasks (there are
typically only a handful, so no partitioning is needed). All mutations funnel
through this class; the coordinator reads from it and is refreshed after each
change so entities stay in sync within the current HA tick.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import assets, models, recurrence
from .const import (
    EVENT_TASK_COMPLETED,
    PART_WEAR,
    STORAGE_KEY,
    STORAGE_VERSION,
    TASK_SOURCE_PART,
)

_LOGGER = logging.getLogger(__name__)


def _part_source(task: dict[str, Any]) -> dict[str, Any] | None:
    """Return a task's ``{asset_id, part_id}`` part provenance, or None."""
    source = task.get("source")
    if isinstance(source, dict) and isinstance(source.get(TASK_SOURCE_PART), dict):
        return source[TASK_SOURCE_PART]
    return None


class HomeKeeperStore:
    """Wrapper around HA's Store helper holding the task dictionary."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._tasks: dict[str, dict[str, Any]] = {}
        self._assets: dict[str, dict[str, Any]] = {}

    async def load(self) -> None:
        """Load tasks and assets from disk (no-op safe on first run).

        The ``assets`` key is additive — documents written before assets existed
        simply lack it, so we default to empty without a storage migration.
        """
        data = await self._store.async_load()
        if data and isinstance(data.get("tasks"), dict):
            self._tasks = data["tasks"]
        else:
            self._tasks = {}
        if data and isinstance(data.get("assets"), dict):
            self._assets = data["assets"]
        else:
            self._assets = {}
        # Additive migrations (no storage-version bump): fold a legacy
        # ``part_numbers`` string into structured ``parts`` and drop links to
        # assets that no longer exist.
        changed = False
        for asset in self._assets.values():
            if assets.migrate_legacy_part_numbers(asset):
                changed = True
        if self._clean_relationship_links():
            changed = True
        if changed:
            await self._save()

    async def _save(self) -> None:
        await self._store.async_save({"tasks": self._tasks, "assets": self._assets})

    async def async_persist(self) -> None:
        """Flush the current in-memory state to disk.

        For callers that mutate task/asset dicts in place (e.g. device-registry
        reconciliation refreshing an asset's identifiers snapshot) and need the
        change persisted without going through a typed mutation method.
        """
        await self._save()

    async def async_remove(self) -> None:
        """Delete the persisted document (used on integration removal)."""
        await self._store.async_remove()
        self._tasks = {}
        self._assets = {}

    # ── reads ────────────────────────────────────────────────────────────────
    def get_tasks(self) -> dict[str, dict[str, Any]]:
        """Return the full task map (id -> task dict)."""
        return self._tasks

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[dict[str, Any]]:
        return list(self._tasks.values())

    # ── mutations ──────────────────────────────────────────────────────────────
    async def add_task(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create and persist a new task; returns the created task dict."""
        task = models.build_task(data, now=dt_util.now())
        self._tasks[task["id"]] = task
        await self._save()
        _LOGGER.debug("Added task %s (%s)", task["id"], task["name"])
        return task

    async def update_task(self, task_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        existing = self._tasks.get(task_id)
        if existing is None:
            raise KeyError(task_id)
        merged = models.merge_update(existing, updates, now=dt_util.now())
        self._tasks[task_id] = merged
        await self._save()
        return merged

    async def delete_task(self, task_id: str) -> None:
        if task_id in self._tasks:
            del self._tasks[task_id]
            await self._save()

    async def detach_tasks_from_device(self, device_id: str) -> list[str]:
        """Clear ``device_id`` on every task pointing at *device_id*.

        Used when a virtual asset device is deleted: its tasks fall back to being
        standalone rather than dangling against a now-removed device. Returns the
        ids of the tasks that changed (so the caller can decide whether the
        per-task entity set needs rebuilding).
        """
        changed: list[str] = []
        for tid, task in self._tasks.items():
            if task.get("device_id") == device_id:
                task["device_id"] = None
                changed.append(tid)
        if changed:
            await self._save()
        return changed

    # ── asset reads ────────────────────────────────────────────────────────────
    def get_assets(self) -> dict[str, dict[str, Any]]:
        """Return the full asset map (id -> asset dict)."""
        return self._assets

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        return self._assets.get(asset_id)

    def list_assets(self) -> list[dict[str, Any]]:
        return list(self._assets.values())

    # ── asset mutations ────────────────────────────────────────────────────────
    async def add_asset(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create and persist a new asset; returns the created asset dict."""
        self._validate_parent(None, data.get("parent_asset_id"))
        asset = assets.build_asset(data, now=dt_util.now())
        self._assets[asset["id"]] = asset
        await self._save()
        _LOGGER.debug("Added asset %s (%s)", asset["id"], asset.get("name"))
        return asset

    async def update_asset(
        self, asset_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        existing = self._assets.get(asset_id)
        if existing is None:
            raise KeyError(asset_id)
        prospective_parent = updates.get(
            "parent_asset_id", existing.get("parent_asset_id")
        )
        self._validate_parent(asset_id, prospective_parent)
        merged = assets.merge_update(existing, updates, now=dt_util.now())
        self._assets[asset_id] = merged
        await self._save()
        return merged

    def _validate_parent(
        self, asset_id: str | None, parent_asset_id: str | None
    ) -> None:
        """Reject a parent link to a missing asset or one that forms a cycle."""
        if not parent_asset_id:
            return
        if parent_asset_id not in self._assets:
            raise assets.AssetValidationError(
                "parent_asset_id is not a known appliance"
            )
        if asset_id and assets.would_create_cycle(
            self._assets, asset_id, parent_asset_id
        ):
            raise assets.AssetValidationError(
                "parent relationship would create a cycle"
            )

    def _clean_relationship_links(self) -> bool:
        """Null any parent_asset_id pointing at an asset that no longer exists."""
        changed = False
        ids = set(self._assets)
        for asset in self._assets.values():
            if asset.get("parent_asset_id") and asset["parent_asset_id"] not in ids:
                asset["parent_asset_id"] = None
                changed = True
        return changed

    async def set_asset_device_id(self, asset_id: str, device_id: str) -> None:
        """Record the registry device id assigned to a provisioned virtual asset."""
        asset = self._assets.get(asset_id)
        if asset is not None and asset.get("device_id") != device_id:
            asset["device_id"] = device_id
            await self._save()

    async def delete_asset(self, asset_id: str) -> dict[str, Any] | None:
        """Remove an asset; returns the removed asset (for device cleanup) or None.

        Also drops tasks derived from this asset's wear parts and detaches any
        child asset that named it as a parent (so the child becomes standalone).
        """
        asset = self._assets.pop(asset_id, None)
        if asset is None:
            return None
        self._tasks = {
            tid: t
            for tid, t in self._tasks.items()
            if _part_source(t) is None or _part_source(t).get("asset_id") != asset_id
        }
        for child in self._assets.values():
            if child.get("parent_asset_id") == asset_id:
                child["parent_asset_id"] = None
        await self._save()
        return asset

    async def reconcile_part_tasks(self) -> bool:
        """Create/update/remove the maintenance tasks derived from wear parts.

        A wear part with a ``replace_interval`` yields a floating task attached to
        the asset's device, so it reuses the existing to-do/calendar/per-task
        entities. The task is keyed by ``source = {"part": {asset_id, part_id}}`` so
        this reconciler exclusively owns it. Returns ``True`` if any task changed.
        """
        now = dt_util.now()
        desired: dict[tuple[str, str], dict[str, Any]] = {}
        for asset in self._assets.values():
            for part in asset.get("parts", []):
                if part.get("type") == PART_WEAR and part.get("replace_interval"):
                    desired[(asset["id"], part["id"])] = (asset, part)

        existing_by_key: dict[tuple[str, str], str] = {}
        for tid, task in self._tasks.items():
            src = _part_source(task)
            if src:
                existing_by_key[(src.get("asset_id"), src.get("part_id"))] = tid

        changed = False
        # Remove orphaned part-tasks.
        for key, tid in list(existing_by_key.items()):
            if key not in desired:
                del self._tasks[tid]
                existing_by_key.pop(key, None)
                changed = True

        # Create or update the rest.
        for key, (asset, part) in desired.items():
            name = f"Replace {part['name']} ({asset.get('name') or 'appliance'})"
            tid = existing_by_key.get(key)
            if tid is None:
                task = models.build_task(
                    {
                        "name": name,
                        "recurrence_type": "floating",
                        "interval": part["replace_interval"],
                        "unit": part["replace_unit"],
                        "device_id": asset.get("device_id"),
                        "area_id": asset.get("area_id"),
                        "source": {
                            "part": {"asset_id": asset["id"], "part_id": part["id"]}
                        },
                    },
                    now=now,
                )
                # Anchor the clock to the last replacement, if known.
                if part.get("last_replaced"):
                    task["last_completed"] = part["last_replaced"]
                    task["next_due"] = recurrence.compute_next_due(
                        task, now=now
                    ).isoformat()
                self._tasks[task["id"]] = task
                changed = True
            else:
                # Only pass fields that actually changed. Passing interval/unit
                # unconditionally would re-trigger a next_due recompute on every
                # reconcile (setup, any asset edit) and, for a task with no
                # last_completed, drift next_due forward to now+interval each time.
                before = self._tasks[tid]
                updates: dict[str, Any] = {}
                if before.get("name") != name:
                    updates["name"] = name
                if before.get("interval") != part["replace_interval"]:
                    updates["interval"] = part["replace_interval"]
                if before.get("unit") != part["replace_unit"]:
                    updates["unit"] = part["replace_unit"]
                if before.get("device_id") != asset.get("device_id"):
                    updates["device_id"] = asset.get("device_id")
                if before.get("area_id") != asset.get("area_id"):
                    updates["area_id"] = asset.get("area_id")
                if updates:
                    self._tasks[tid] = models.merge_update(before, updates, now=now)
                    changed = True

        if changed:
            await self._save()
        return changed

    async def complete_task(
        self, task_id: str, completed_at: Any | None = None, *, origin: str | None = None
    ) -> dict[str, Any]:
        """Mark a task completed and advance its recurrence.

        For a part-derived task, also stamp the part's ``last_replaced`` so the
        appliance record reflects the maintenance.

        Fires the ``home_keeper_task_completed`` event so external integrations can
        mirror the completion. This is the single chokepoint every completion surface
        funnels through (the to-do list, the device mark-done button, and the
        ``complete_task`` service), so firing here — rather than in the service handler
        — is what makes completion observable from anywhere. ``origin`` is an opaque,
        caller-supplied marker echoed back in the event purely so a contributing
        integration can ignore the echo of a completion it initiated; Home Keeper does
        not interpret it.
        """
        existing = self._tasks.get(task_id)
        if existing is None:
            raise KeyError(task_id)
        now = dt_util.now()
        when = completed_at or now
        updated = recurrence.apply_completion(dict(existing), when, now=now)
        self._tasks[task_id] = updated
        self._stamp_part_replacement(updated, when)
        await self._save()
        _LOGGER.debug(
            "Completed task %s; next due %s", task_id, updated.get("next_due")
        )
        self._hass.bus.async_fire(
            EVENT_TASK_COMPLETED,
            {
                "task_id": task_id,
                "name": updated.get("name"),
                "source": updated.get("source"),
                "completed_at": when.isoformat() if hasattr(when, "isoformat") else when,
                "origin": origin,
            },
        )
        return updated

    def _stamp_part_replacement(self, task: dict[str, Any], when: Any) -> None:
        src = _part_source(task)
        if not src:
            return
        asset = self._assets.get(src.get("asset_id"))
        if not asset:
            return
        when_date = when.date().isoformat() if hasattr(when, "date") else str(when)[:10]
        for part in asset.get("parts", []):
            if part.get("id") == src.get("part_id"):
                part["last_replaced"] = when_date
                break
