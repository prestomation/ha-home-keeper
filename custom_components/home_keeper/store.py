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

from . import assets, events, models, recurrence
from .const import (
    EVENT_PART_LOW_STOCK,
    EVENT_TASK_COMPLETED,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .reconcile import part_source as _part_source
from .reconcile import reconcile_part_tasks as _reconcile_part_tasks

_LOGGER = logging.getLogger(__name__)


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
        task = self._tasks.get(task_id)
        if task is not None and _part_source(task):
            # Derived from a wear part; deleting it here would just be recreated by
            # the next reconcile. Direct the user to manage the part instead.
            raise models.TaskValidationError(
                "This task is managed by an appliance wear part; remove or change "
                "the part to delete it."
            )
        if task_id in self._tasks:
            self._archive_task_history(self._tasks[task_id])
            del self._tasks[task_id]
            await self._save()

    def _archive_task_history(self, task: dict[str, Any]) -> None:
        """Preserve a deleted task's completion history on its appliance, if any.

        Reference-counting retention: a task's history outlives the task only while
        an appliance still references it. A standalone task's history is dropped
        with it (``find_archiving_asset`` returns None). Mutates the asset in place;
        the caller persists via ``_save``.
        """
        asset = assets.find_archiving_asset(self._assets, task)
        if asset is None:
            return
        entry = assets.build_archived_history(
            task, archived_at=dt_util.now().isoformat()
        )
        assets.append_task_history(asset, entry)

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

        Delegates the (pure) computation to :func:`reconcile.reconcile_part_tasks`
        and persists the result. Returns ``True`` if any task changed.
        """
        new_tasks, changed = _reconcile_part_tasks(
            self._assets, self._tasks, now=dt_util.now()
        )
        if changed:
            # A part-derived task dropped here means its wear part was removed while
            # the appliance remains; preserve its history on the appliance. (Deleting
            # the whole appliance drops its derived tasks via delete_asset, before any
            # reconcile, so this only archives part removals — not appliance deletes.)
            for tid, task in self._tasks.items():
                if tid not in new_tasks and _part_source(task):
                    self._archive_task_history(task)
            self._tasks = new_tasks
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
            events.completion_event_data(updated, when, origin),
        )
        return updated

    async def delete_completion(self, task_id: str, ts: str) -> dict[str, Any]:
        """Remove one completion from a task (undo an accidental "done").

        Re-derives ``last_completed``/``next_due`` from the remaining history and
        persists. Returns the updated task.
        """
        existing = self._tasks.get(task_id)
        if existing is None:
            raise KeyError(task_id)
        updated = recurrence.remove_completion(dict(existing), ts, now=dt_util.now())
        self._tasks[task_id] = updated
        await self._save()
        return updated

    async def delete_archived_completion(
        self, asset_id: str, task_id: str, ts: str
    ) -> dict[str, Any]:
        """Remove one completion from an appliance's archived task history.

        Returns the updated asset. Raises ``KeyError`` if the asset is unknown.
        """
        asset = self._assets.get(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        if assets.remove_archived_completion(asset, task_id, ts):
            await self._save()
        return asset

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
                # Completing a wear-part replacement consumes one stocked spare;
                # signal a reorder if that drops it to/below its threshold.
                if assets.consume_part_stock(part):
                    self._emit_low_stock(asset, part)
                break

    def _emit_low_stock(self, asset: dict[str, Any], part: dict[str, Any]) -> None:
        """Fire the low-stock event so users can automate a reorder / shopping-list add."""
        self._hass.bus.async_fire(
            EVENT_PART_LOW_STOCK, events.low_stock_event_data(asset, part)
        )

    async def adjust_part_stock(
        self, asset_id: str, part_id: str, delta: int
    ) -> dict[str, Any]:
        """Change a part's on-hand spare count by ``delta`` (clamped at zero).

        Persists and, when a *decrease* drops the part to/below its reorder
        threshold, fires the low-stock event (a restock never nags). Returns the
        updated asset. Raises ``KeyError`` for an unknown asset or part.
        """
        asset = self._assets.get(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        for part in asset.get("parts", []):
            if part.get("id") == part_id:
                low = assets.adjust_part_stock(part, delta)
                await self._save()
                if low and delta < 0:
                    self._emit_low_stock(asset, part)
                return asset
        raise KeyError(part_id)
