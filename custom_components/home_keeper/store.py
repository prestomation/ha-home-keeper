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
from .const import STORAGE_KEY, STORAGE_VERSION

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

    async def _save(self) -> None:
        await self._store.async_save({"tasks": self._tasks, "assets": self._assets})

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
        merged = assets.merge_update(existing, updates, now=dt_util.now())
        self._assets[asset_id] = merged
        await self._save()
        return merged

    async def set_asset_device_id(self, asset_id: str, device_id: str) -> None:
        """Record the registry device id assigned to a provisioned virtual asset."""
        asset = self._assets.get(asset_id)
        if asset is not None and asset.get("device_id") != device_id:
            asset["device_id"] = device_id
            await self._save()

    async def delete_asset(self, asset_id: str) -> dict[str, Any] | None:
        """Remove an asset; returns the removed asset (for device cleanup) or None."""
        asset = self._assets.pop(asset_id, None)
        if asset is not None:
            await self._save()
        return asset

    async def complete_task(
        self, task_id: str, completed_at: Any | None = None
    ) -> dict[str, Any]:
        """Mark a task completed and advance its recurrence."""
        existing = self._tasks.get(task_id)
        if existing is None:
            raise KeyError(task_id)
        now = dt_util.now()
        when = completed_at or now
        updated = recurrence.apply_completion(dict(existing), when, now=now)
        self._tasks[task_id] = updated
        await self._save()
        _LOGGER.debug(
            "Completed task %s; next due %s", task_id, updated.get("next_due")
        )
        return updated
