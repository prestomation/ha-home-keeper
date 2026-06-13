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

from . import models, recurrence
from .const import STORAGE_KEY, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


class HomeKeeperStore:
    """Wrapper around HA's Store helper holding the task dictionary."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._tasks: dict[str, dict[str, Any]] = {}

    async def load(self) -> None:
        """Load tasks from disk (no-op safe on first run)."""
        data = await self._store.async_load()
        if data and isinstance(data.get("tasks"), dict):
            self._tasks = data["tasks"]
        else:
            self._tasks = {}

    async def _save(self) -> None:
        await self._store.async_save({"tasks": self._tasks})

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
