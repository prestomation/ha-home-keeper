"""Persistent task storage for Home Keeper.

A single JSON document under ``.storage/home_keeper`` holds all tasks (there are
typically only a handful, so no partitioning is needed). All mutations funnel
through this class; the coordinator reads from it and is refreshed after each
change so entities stay in sync within the current HA tick.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import assets, events, models, recurrence, sensor_tasks, sensor_watcher
from .assets import STOCK_LOW, STOCK_OUT, STOCK_RESTOCKED
from .const import (
    EVENT_ASSET_CREATED,
    EVENT_ASSET_DELETED,
    EVENT_ASSET_UPDATED,
    EVENT_PART_LOW_STOCK,
    EVENT_PART_OUT_OF_STOCK,
    EVENT_PART_RESTOCKED,
    EVENT_TASK_COMPLETED,
    EVENT_TASK_COMPLETION_UPDATED,
    EVENT_TASK_CREATED,
    EVENT_TASK_DELETED,
    EVENT_TASK_SKIPPED,
    EVENT_TASK_SNOOZED,
    EVENT_TASK_TRIGGERED,
    EVENT_TASK_UNCOMPLETED,
    EVENT_TASK_UPDATED,
    ORIGIN_PROBLEM_SENSOR_SYNC,
    REC_SENSOR,
    REC_TRIGGERED,
    SENSOR_MODE_USAGE,
    STORAGE_KEY,
    STORAGE_VERSION,
    TASK_SOURCE_BUY,
    TASK_SOURCE_PART,
    TASK_SOURCE_PROBLEM_SENSOR,
    resolve_buy_task_naming,
    resolve_wear_task_naming,
)
from .problem_tasks import problem_sensor_entity_id as _problem_entity
from .problem_tasks import problem_source as _problem_source
from .problem_tasks import reconcile_problem_tasks as _reconcile_problem_tasks
from .reconcile import buy_source as _buy_source
from .reconcile import is_manual_part_link as _is_manual_part_link
from .reconcile import part_source as _part_source
from .reconcile import reconcile_buy_tasks as _reconcile_buy_tasks
from .reconcile import reconcile_part_tasks as _reconcile_part_tasks

# Stock transition -> the bus event it fires (STOCK_NONE maps to nothing).
_STOCK_EVENT = {
    STOCK_LOW: EVENT_PART_LOW_STOCK,
    STOCK_OUT: EVENT_PART_OUT_OF_STOCK,
    STOCK_RESTOCKED: EVENT_PART_RESTOCKED,
}

_LOGGER = logging.getLogger(__name__)


def _task_owns_entities(task: dict[str, Any]) -> bool:
    """True when a task owns per-task device-page entities (button/sensor/…).

    Mirrors ``coordinator.task_has_entities`` (an enabled, device-attached task),
    inlined here to avoid a store→coordinator import cycle. Used to decide whether
    creating/removing a reconciler-owned task needs a full entry reload.
    """
    return bool(task.get("device_id")) and bool(task.get("enabled", True))


def _reject_synced_problem(task: dict[str, Any], origin: str | None) -> None:
    """Raise unless *origin* authorizes mutating a problem-sensor-synced task.

    A synced task mirrors a ``device_class: problem`` binary sensor and is owned by
    the sync. Every user-facing surface (to-do, button, service, websocket, panel)
    calls without :data:`ORIGIN_PROBLEM_SENSOR_SYNC`, so this rejects them with a
    clear message; only the internal sync (which passes the marker) may arm or clear
    the task. The problem itself has to be resolved in the originating integration.
    """
    if _problem_source(task) is None or origin == ORIGIN_PROBLEM_SENSOR_SYNC:
        return
    entity_id = _problem_entity(task) or "the originating integration"
    raise models.TaskValidationError(
        f"This task mirrors the problem sensor {entity_id} and can't be cleared in "
        "Home Keeper. Resolve the problem in the originating integration — the task "
        "clears automatically when the sensor returns to OK."
    )


def _changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Top-level keys whose value differs between *before* and *after*.

    Drives the ``changed_fields`` payload on the update events (and the decision to
    suppress a no-op update event entirely). Backend-managed bookkeeping keys that
    aren't user-meaningful are ignored so a reschedule doesn't spam ``next_due``/
    ``completions`` churn as "changes".
    """
    ignore = {"completions", "last_completed", "next_due", "created"}
    keys = (set(before) | set(after)) - ignore
    return sorted(k for k in keys if before.get(k) != after.get(k))


class HomeKeeperStore:
    """Wrapper around HA's Store helper holding the task dictionary."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._tasks: dict[str, dict[str, Any]] = {}
        self._assets: dict[str, dict[str, Any]] = {}
        # Durable free-text notes for problem-sensor mirrors, keyed by the sensor
        # ``entity_id`` (not the task id). Kept outside the task so a note survives the
        # task being deleted and later recreated — sync toggled off/on, or the sensor
        # temporarily excluded — and re-hydrates onto the fresh task the next time the
        # same problem fires. See ``reconcile_problem_sensor_tasks`` / ``update_task``.
        self._problem_notes: dict[str, str] = {}

    async def load(self) -> None:
        """Load tasks and assets from disk (no-op safe on first run).

        The ``assets`` and ``problem_notes`` keys are additive — documents written
        before they existed simply lack them, so we default to empty without a
        storage migration.
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
        if data and isinstance(data.get("problem_notes"), dict):
            self._problem_notes = data["problem_notes"]
        else:
            self._problem_notes = {}
        # Additive migrations (no storage-version bump): fold a legacy
        # ``part_numbers`` string into structured ``parts`` and drop links to
        # assets that no longer exist.
        changed = False
        for asset in self._assets.values():
            if assets.migrate_legacy_part_numbers(asset):
                changed = True
            if assets.migrate_documents_from_manual_url(asset):
                changed = True
        if self._clean_relationship_links():
            changed = True
        if changed:
            await self._save()

    async def _save(self) -> None:
        await self._store.async_save(
            {
                "tasks": self._tasks,
                "assets": self._assets,
                "problem_notes": self._problem_notes,
            }
        )

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
        self._problem_notes = {}

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
        """Create and persist a new task; returns the created task dict.

        ``source`` is opaque provenance a caller may attach, but the ``part``,
        ``problem_sensor`` and ``buy`` namespaces are *reserved* — the reconcilers own
        tasks that carry them (and will silently delete a task whose reserved source
        doesn't match a live part/sensor). Reject them here so an external ``add_task``
        can't mint a task that masquerades as reconciler-owned and then vanishes on the
        next reconcile pass. Home Keeper's own reconcilers build such tasks via
        ``models.build_task`` directly, not through this service path.
        """
        source = data.get("source")
        if isinstance(source, dict):
            reserved = {
                TASK_SOURCE_PART,
                TASK_SOURCE_PROBLEM_SENSOR,
                TASK_SOURCE_BUY,
            } & set(source)
            if reserved:
                raise models.TaskValidationError(
                    f"source keys {sorted(reserved)} are reserved for Home Keeper's "
                    "own task reconcilers and cannot be set via add_task"
                )
        task = models.build_task(data, now=dt_util.now())
        self._tasks[task["id"]] = task
        await self._save()
        _LOGGER.debug("Added task %s (%s)", task["id"], task["name"])
        self._hass.bus.async_fire(EVENT_TASK_CREATED, events.task_event_data(task))
        return task

    async def update_task(
        self, task_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        existing = self._tasks.get(task_id)
        if existing is None:
            raise KeyError(task_id)
        merged = models.merge_update(existing, updates, now=dt_util.now())
        self._tasks[task_id] = merged
        # Mirror a problem-sensor task's note into the durable, entity-keyed side-store
        # so it outlives the task (the mirror is deleted/recreated as the sensor is
        # excluded or the sync is toggled). Locked fields keep name/schedule owned by
        # the sync, but ``notes`` is intentionally user-editable on these tasks.
        entity_id = _problem_entity(merged)
        if entity_id is not None:
            note = merged.get("notes") or ""
            if note:
                self._problem_notes[entity_id] = note
            else:
                self._problem_notes.pop(entity_id, None)
        await self._save()
        # Fire only on a real change; carry which fields moved so automations can react
        # selectively (e.g. a rename vs. a schedule change).
        changed = _changed_fields(existing, merged)
        if changed:
            self._hass.bus.async_fire(
                EVENT_TASK_UPDATED,
                events.task_event_data(merged, extra={"changed_fields": changed}),
            )
        return merged

    async def set_task_consumable(
        self, task_id: str, asset_id: str | None, part_id: str | None
    ) -> dict[str, Any]:
        """Link a task to an asset consumable/part, or clear the link.

        A manual link sets the task's ``source`` to a part reference (flagged
        ``manual`` so the part-task reconciler leaves it alone — see
        ``reconcile.is_manual_part_link``) so that *completing* the task consumes one
        spare from the part's ``stock``, firing the edge-triggered low/out-of-stock
        events when the reorder threshold is crossed — exactly like a wear-part
        replacement. This is how a user wires an arbitrary task (e.g. a sensor task
        armed by a fridge's filter-life entity) to the consumable it depletes.

        Pass both ``asset_id`` and ``part_id`` to link; pass both as ``None`` to clear.
        Raises ``KeyError`` for an unknown task; ``TaskValidationError`` for an unknown
        asset/part, a half-specified link, or a task already owned by another source (a
        reconciler-derived wear-part task, or a synced ``problem`` sensor).
        """
        existing = self._tasks.get(task_id)
        if existing is None:
            raise KeyError(task_id)
        _reject_synced_problem(existing, None)
        # A reconciler-derived part task is already bound to its part; re-pointing it by
        # hand would just be undone on the next reconcile. Only a user-owned task (no
        # part source) or an existing manual link may be (re)linked or cleared.
        src = _part_source(existing)
        if src is not None and not src.get("manual"):
            raise models.TaskValidationError(
                "This task is auto-generated from an appliance wear part and is "
                "already linked to it — manage its part in the appliance editor."
            )

        if asset_id is None and part_id is None:
            if existing.get("source") is None:
                return existing  # already unlinked — no-op, no event
            existing["source"] = None
        else:
            if not asset_id or not part_id:
                raise models.TaskValidationError(
                    "linking a consumable needs both asset_id and part_id"
                )
            asset = self._assets.get(asset_id)
            if asset is None:
                raise models.TaskValidationError(f"unknown asset: {asset_id!r}")
            if not any(p.get("id") == part_id for p in asset.get("parts", [])):
                raise models.TaskValidationError(
                    f"asset {asset_id!r} has no part {part_id!r}"
                )
            new_source = {
                TASK_SOURCE_PART: {
                    "asset_id": asset_id,
                    "part_id": part_id,
                    "manual": True,
                }
            }
            if existing.get("source") == new_source:
                return existing  # already linked to this part — no-op, no event
            existing["source"] = new_source
        await self._save()
        _LOGGER.debug(
            "Set consumable link for task %s -> %s", task_id, existing.get("source")
        )
        self._hass.bus.async_fire(
            EVENT_TASK_UPDATED,
            events.task_event_data(existing, extra={"changed_fields": ["source"]}),
        )
        return existing

    async def trigger_task(
        self, task_id: str, *, origin: str | None = None
    ) -> dict[str, Any]:
        """Arm a condition-driven (``triggered``) or sensor-based task so it's due-now.

        Sets ``next_due`` to now, moving the task from dormant to active. This is the
        owner-facing counterpart to ``complete_task`` (which clears it back to
        dormant): an integration calls it when the condition it monitors becomes true
        again (e.g. a battery drops low after a prior replacement), and the sensor-task
        watcher calls it when a bound reading meets the task's condition. Idempotent —
        arming an already-active task just refreshes its trigger time. Only valid for
        ``triggered`` / ``sensor`` tasks; rejects others so callers don't accidentally
        strand a scheduled task on a fixed due date.
        """
        existing = self._tasks.get(task_id)
        if existing is None:
            raise KeyError(task_id)
        if existing.get("recurrence_type") not in (REC_TRIGGERED, REC_SENSOR):
            raise models.TaskValidationError(
                "trigger_task is only valid for triggered or sensor-based tasks"
            )
        _reject_synced_problem(existing, origin)
        existing["next_due"] = dt_util.now().isoformat()
        await self._save()
        _LOGGER.debug("Triggered task %s (armed, due now)", task_id)
        self._hass.bus.async_fire(
            EVENT_TASK_TRIGGERED, events.task_event_data(existing)
        )
        return existing

    async def snooze_task(
        self, task_id: str, until: Any, *, origin: str | None = None
    ) -> dict[str, Any]:
        """Push a task's ``next_due`` to *until* without recording a completion.

        "Remind me later": unlike :meth:`complete_task` this advances *only*
        ``next_due`` — recurrence, ``last_completed`` and the completion history are
        untouched — so the schedule isn't advanced, just deferred. Because
        ``next_due`` changes, the coordinator re-arms the edge-triggered
        overdue/due-soon events for the new date (a fresh reminder fires when the
        snooze lapses). *until* is a timezone-aware datetime (the caller computes it
        from the requested duration). Rejects a synced problem-sensor task like every
        other user mutation, and a **dormant** task (``next_due is None``) — there's no
        due date to defer. Fires ``home_keeper_task_snoozed``.
        """
        existing = self._tasks.get(task_id)
        if existing is None:
            raise KeyError(task_id)
        _reject_synced_problem(existing, origin)
        if existing.get("next_due") is None:
            # A dormant task (a completed one-off, or a condition/sensor task not yet
            # armed) has no due date to defer; snoozing it would silently re-arm
            # something that was intentionally off every time surface.
            raise models.TaskValidationError(
                "This task is dormant (no due date) — snooze only defers a task that "
                "is currently scheduled. Re-arm it instead (undo a completion, or wait "
                "for its condition/sensor)."
            )
        existing["next_due"] = until.isoformat()
        await self._save()
        _LOGGER.debug("Snoozed task %s until %s", task_id, existing["next_due"])
        self._hass.bus.async_fire(
            EVENT_TASK_SNOOZED,
            events.task_event_data(
                existing, extra={"snoozed_until": existing["next_due"]}
            ),
        )
        return existing

    async def skip_task(
        self, task_id: str, *, origin: str | None = None
    ) -> dict[str, Any]:
        """Advance a task to its next occurrence with **no** completion recorded.

        "Skip this one": delegates the (pure) recurrence math to
        :func:`recurrence.skip_occurrence` — floating jumps a fresh interval, fixed
        advances one scheduled occurrence, and one-off/triggered/sensor go dormant —
        without stamping history or ``last_completed``. Rejects a synced
        problem-sensor task. Fires ``home_keeper_task_skipped``.
        """
        existing = self._tasks.get(task_id)
        if existing is None:
            raise KeyError(task_id)
        _reject_synced_problem(existing, origin)
        updated = recurrence.skip_occurrence(dict(existing), now=dt_util.now())
        self._tasks[task_id] = updated
        await self._save()
        _LOGGER.debug("Skipped task %s; next due %s", task_id, updated.get("next_due"))
        self._hass.bus.async_fire(EVENT_TASK_SKIPPED, events.task_event_data(updated))
        return updated

    async def set_sensor_baseline(
        self, task_id: str, baseline: float
    ) -> dict[str, Any]:
        """Stamp a usage sensor task's meter ``baseline`` (silent bookkeeping).

        Called by the sensor watcher to anchor a fresh usage task to its first live
        reading and to re-anchor after a meter reset. This is internal state, not a
        user action, so it persists without firing a lifecycle event (mirroring the
        wear-part reconcile edits). A no-op for a non-sensor task or an unchanged value.
        """
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        cfg = task.get("sensor")
        if not isinstance(cfg, dict):
            return task
        if cfg.get("baseline") != baseline:
            cfg["baseline"] = baseline
            await self._save()
            _LOGGER.debug("Set usage baseline for task %s -> %s", task_id, baseline)
        return task

    async def delete_task(self, task_id: str, *, force: bool = False) -> None:
        task = self._tasks.get(task_id)
        if task is not None and _part_source(task) and not _is_manual_part_link(task):
            # Derived from a wear part; deleting it here would just be recreated by
            # the next reconcile. Direct the user to manage the part instead. A *manual*
            # consumable link is user-owned, so it is freely deletable (the link is just
            # dropped along with the task).
            raise models.TaskValidationError(
                "This task is managed by an appliance wear part; remove or change "
                "the part to delete it."
            )
        if task is not None and _buy_source(task):
            # System-managed auto-buy reminder; the reconciler would recreate it while
            # the part is still low. Direct the user to restock or turn off the option.
            raise models.TaskValidationError(
                "This is an auto-created buy reminder; restock the part or turn off "
                "its auto-buy option to remove it."
            )
        if task is not None:
            managed_by = task.get("managed_by")
            orphaned = self.managed_task_orphaned(task)
            if models.deletion_blocked(task, orphaned=orphaned, force=force):
                display_name = (managed_by or {}).get(
                    "display_name"
                ) or "an integration"
                raise models.TaskValidationError(
                    f"This task is managed by {display_name}. "
                    f"Delete it from {display_name} instead."
                )
        if task_id in self._tasks:
            removed = self._tasks[task_id]
            self._archive_task_history(removed)
            del self._tasks[task_id]
            await self._save()
            self._hass.bus.async_fire(
                EVENT_TASK_DELETED, events.task_event_data(removed)
            )

    def managed_task_orphaned(self, task: dict[str, Any]) -> bool:
        """Whether a managed task's owning integration is no longer present.

        A task is orphaned when its ``managed_by.config_entry_id`` names a config
        entry that is not currently loaded — i.e. the integration was uninstalled,
        disabled, or is failing to set up. Without a recorded ``config_entry_id`` we
        can't prove the owner is gone, so we treat it as present (not orphaned) and
        rely on the ``force`` escape hatch for cleanup. See ``models.deletion_blocked``.
        """
        managed_by = task.get("managed_by")
        if not isinstance(managed_by, dict):
            return False
        entry_id = managed_by.get("config_entry_id")
        if not entry_id:
            return False
        entry = self._hass.config_entries.async_get_entry(entry_id)
        return entry is None or entry.state is not ConfigEntryState.LOADED

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
            for tid in changed:
                self._hass.bus.async_fire(
                    EVENT_TASK_UPDATED,
                    events.task_event_data(
                        self._tasks[tid], extra={"changed_fields": ["device_id"]}
                    ),
                )
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
        self._hass.bus.async_fire(EVENT_ASSET_CREATED, events.asset_event_data(asset))
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
        changed = _changed_fields(existing, merged)
        if changed:
            self._hass.bus.async_fire(
                EVENT_ASSET_UPDATED,
                events.asset_event_data(merged, extra={"changed_fields": changed}),
            )
        return merged

    async def add_asset_document(
        self, asset_id: str, document: dict[str, Any]
    ) -> dict[str, Any]:
        """Attach a document (link or uploaded file) to an asset; return the entry.

        Stamps ``created`` (this is the clock-aware chokepoint; ``assets`` is HA-free)
        and fires ``home_keeper_asset_updated`` with ``changed_fields=["documents"]``.
        Raises ``KeyError`` for an unknown asset and ``AssetValidationError`` for an
        invalid document.
        """
        asset = self._assets.get(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        entry = assets.append_document(
            asset, document, created=dt_util.now().isoformat()
        )
        await self._save()
        self._hass.bus.async_fire(
            EVENT_ASSET_UPDATED,
            events.asset_event_data(asset, extra={"changed_fields": ["documents"]}),
        )
        return entry

    async def remove_asset_document(
        self, asset_id: str, document_id: str
    ) -> dict[str, Any]:
        """Detach a document from an asset; delete its on-disk blob if it was a file.

        Returns the updated asset. Raises ``KeyError`` for an unknown asset or
        document. Fires ``home_keeper_asset_updated`` with documents in changed_fields.
        """
        from . import manuals  # lazy: manuals -> devices imports would cycle at load

        asset = self._assets.get(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        removed = assets.remove_document(asset, document_id)
        if removed is None:
            raise KeyError(document_id)
        if removed.get("kind") == "file" and removed.get("filename"):
            await manuals.async_delete_document(
                self._hass, asset_id, document_id, removed["filename"]
            )
        await self._save()
        self._hass.bus.async_fire(
            EVENT_ASSET_UPDATED,
            events.asset_event_data(asset, extra={"changed_fields": ["documents"]}),
        )
        return asset

    async def update_asset_document(
        self, asset_id: str, document_id: str, changes: dict[str, Any]
    ) -> dict[str, Any]:
        """Edit a document (link name/url, or a file's display name); return the entry.

        Raises ``KeyError`` for an unknown asset or document, and
        ``AssetValidationError`` for invalid changes. Fires
        ``home_keeper_asset_updated`` (changed_fields: ``["documents"]``).
        """
        asset = self._assets.get(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        entry = assets.update_document(asset, document_id, changes)
        if entry is None:
            raise KeyError(document_id)
        await self._save()
        self._hass.bus.async_fire(
            EVENT_ASSET_UPDATED,
            events.asset_event_data(asset, extra={"changed_fields": ["documents"]}),
        )
        return entry

    async def set_part_file(
        self, asset_id: str, part_id: str, file_meta: dict[str, Any]
    ) -> dict[str, Any]:
        """Attach (or replace) a part's single file; return the updated part.

        *file_meta* is ``{filename, content_type, size}`` (already validated/sniffed
        by the caller — see ``manuals.HomeKeeperPartFileView``). Raises ``KeyError``
        for an unknown asset or part. Fires ``home_keeper_asset_updated`` with
        ``changed_fields=["parts"]``.
        """
        asset = self._assets.get(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        updated = assets.set_part_file(asset, part_id, file_meta)
        if updated is None:
            raise KeyError(part_id)
        await self._save()
        self._hass.bus.async_fire(
            EVENT_ASSET_UPDATED,
            events.asset_event_data(asset, extra={"changed_fields": ["parts"]}),
        )
        return updated

    async def remove_part_file(self, asset_id: str, part_id: str) -> dict[str, Any]:
        """Detach a part's file; delete its on-disk blob if it had one.

        Returns the updated asset. Raises ``KeyError`` for an unknown asset or part.
        A part with no attached file is a no-op (idempotent — no save, no event).
        Otherwise fires ``home_keeper_asset_updated`` with
        ``changed_fields=["parts"]``.
        """
        from . import manuals  # lazy: manuals -> devices imports would cycle at load

        asset = self._assets.get(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        if not any(p.get("id") == part_id for p in asset.get("parts", [])):
            raise KeyError(part_id)
        removed = assets.clear_part_file(asset, part_id)
        if removed is None:
            return asset
        if removed.get("filename"):
            await manuals.async_delete_part_file(
                self._hass, asset_id, part_id, removed["filename"]
            )
        await self._save()
        self._hass.bus.async_fire(
            EVENT_ASSET_UPDATED,
            events.asset_event_data(asset, extra={"changed_fields": ["parts"]}),
        )
        return asset

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

        Drops the tasks **derived** from this asset's wear parts, but only **unlinks**
        a user-owned task that was *manually* linked to one of its consumables (clearing
        the dangling part source, keeping the task and its history). Also detaches any
        child asset that named it as a parent (so the child becomes standalone).
        """
        asset = self._assets.pop(asset_id, None)
        if asset is None:
            return None
        dropped_ids = set()
        unlinked = []
        for tid, t in self._tasks.items():
            # An auto-created buy task for this appliance's part goes with it (it
            # carries a ``buy`` source, not ``part``, so the loop below would skip it).
            buy = _buy_source(t)
            if buy is not None and buy.get("asset_id") == asset_id:
                dropped_ids.add(tid)
                continue
            src = _part_source(t)
            if src is None or src.get("asset_id") != asset_id:
                continue
            if _is_manual_part_link(t):
                # A user-owned manual link: keep the task, just clear the now-dangling
                # link (its consumable is gone with the appliance).
                t["source"] = None
                unlinked.append(t)
            else:
                dropped_ids.add(tid)
        dropped = [self._tasks[tid] for tid in dropped_ids]
        self._tasks = {
            tid: t for tid, t in self._tasks.items() if tid not in dropped_ids
        }
        for child in self._assets.values():
            if child.get("parent_asset_id") == asset_id:
                child["parent_asset_id"] = None
        await self._save()
        # Drop any uploaded-document blobs the appliance owned (best-effort cleanup).
        from . import manuals  # lazy import: avoids a load-time import cycle

        await manuals.async_delete_asset_documents(self._hass, asset_id)
        # The appliance and the wear-part tasks it owned are both gone — announce each.
        for task in dropped:
            self._hass.bus.async_fire(EVENT_TASK_DELETED, events.task_event_data(task))
        # A surviving manual-link task lost its consumable — announce the source change.
        for task in unlinked:
            self._hass.bus.async_fire(
                EVENT_TASK_UPDATED,
                events.task_event_data(task, extra={"changed_fields": ["source"]}),
            )
        self._hass.bus.async_fire(EVENT_ASSET_DELETED, events.asset_event_data(asset))
        return asset

    async def reconcile_part_tasks(self) -> bool:
        """Create/update/remove the maintenance tasks derived from wear parts.

        Delegates the (pure) computation to :func:`reconcile.reconcile_part_tasks`
        and persists the result. Returns ``True`` if any task changed.

        The generated task name is localized to Home Assistant's configured language
        (``hass.config.language`` — the household's primary language) here, at the HA
        boundary, so the pure reconciler stays language-agnostic. A language change
        relocalizes every generated name as ordinary name drift on the next reconcile
        (the ``__init__`` EVENT_CORE_CONFIG_UPDATE listener reloads the entry to force
        one immediately).
        """
        old_tasks = self._tasks
        name_template, appliance_fallback = resolve_wear_task_naming(
            self._hass.config.language
        )
        new_tasks, changed = _reconcile_part_tasks(
            self._assets,
            old_tasks,
            name_template=name_template,
            appliance_fallback=appliance_fallback,
            now=dt_util.now(),
        )
        if changed:
            # A part-derived task dropped here means its wear part was removed while
            # the appliance remains; preserve its history on the appliance. (Deleting
            # the whole appliance drops its derived tasks via delete_asset, before any
            # reconcile, so this only archives part removals — not appliance deletes.)
            removed = [task for tid, task in old_tasks.items() if tid not in new_tasks]
            for task in removed:
                if _part_source(task):
                    self._archive_task_history(task)
            self._tasks = new_tasks
            await self._save()
            # Wear-part tasks are created/removed here, bypassing add_task/delete_task,
            # so fire their lifecycle events directly (else this whole class of task is
            # silent to automations). Reconcile-time *edits* are intentionally not fired
            # as updates — they're internal churn (name/interval re-derivation), not a
            # user action.
            for task in removed:
                self._hass.bus.async_fire(
                    EVENT_TASK_DELETED, events.task_event_data(task)
                )
            for tid, task in new_tasks.items():
                if tid not in old_tasks:
                    self._hass.bus.async_fire(
                        EVENT_TASK_CREATED, events.task_event_data(task)
                    )
            # A manual consumable link whose part was removed has its source cleared by
            # the reconcile (the task survives standalone); announce the source change.
            for tid, task in new_tasks.items():
                old = old_tasks.get(tid)
                if old is not None and old.get("source") != task.get("source"):
                    self._hass.bus.async_fire(
                        EVENT_TASK_UPDATED,
                        events.task_event_data(
                            task, extra={"changed_fields": ["source"]}
                        ),
                    )
        return changed

    async def reconcile_buy_tasks(self) -> bool:
        """Create/remove the auto-generated "buy" tasks synced to low spare parts.

        Delegates the (pure) diff to :func:`reconcile.reconcile_buy_tasks` and persists
        the result. A buy task exists exactly while its part opts in
        (``create_buy_task``) and is low; it's created when the part crosses low and
        removed once restocked / opted out / the part or asset is gone. Because these
        tasks bypass ``add_task``/``delete_task``, fire their lifecycle events here.

        Returns ``True`` when the per-task **entity set** changed (a buy task that owns
        device-page entities was created or removed) so the caller can decide between a
        full entry reload and a plain coordinator refresh — mirroring
        :meth:`reconcile_problem_sensor_tasks`.
        """
        old_tasks = self._tasks
        name_template = resolve_buy_task_naming(self._hass.config.language)
        new_tasks, changed = _reconcile_buy_tasks(
            self._assets,
            old_tasks,
            name_template=name_template,
            now=dt_util.now(),
        )
        if not changed:
            return False
        removed = [task for tid, task in old_tasks.items() if tid not in new_tasks]
        # A removed buy task's completions (if any) belong to its appliance record.
        for task in removed:
            if _buy_source(task):
                self._archive_task_history(task)
        self._tasks = new_tasks
        await self._save()
        entity_set_changed = False
        for task in removed:
            self._hass.bus.async_fire(EVENT_TASK_DELETED, events.task_event_data(task))
            if _task_owns_entities(task):
                entity_set_changed = True
        for tid, task in new_tasks.items():
            if tid not in old_tasks:
                self._hass.bus.async_fire(
                    EVENT_TASK_CREATED, events.task_event_data(task)
                )
                if _task_owns_entities(task):
                    entity_set_changed = True
        return entity_set_changed

    async def reconcile_problem_sensor_tasks(
        self, eligible: dict[str, dict[str, Any]], *, config_entry_id: str
    ) -> bool:
        """Sync the triggered tasks mirroring ``device_class: problem`` sensors.

        *eligible* maps ``entity_id`` -> ``{"name", "device_id", "area_id",
        "is_problem"}`` for the sensors that should be synced (the HA-aware filtering
        — option on, exclusions, skipping Home Keeper's own entities — happens in
        ``problem_sync.py``; an empty map removes every synced task, e.g. when the
        option is turned off). Delegates the diff to the pure
        :func:`problem_tasks.reconcile_problem_tasks`, persists, and fires the
        matching lifecycle events. Returns ``True`` when the per-task **entity set**
        changed (a task was created or removed) so the caller can decide between a
        full entry reload and a plain coordinator refresh.
        """
        new_tasks, ops, changed = _reconcile_problem_tasks(
            eligible,
            self._tasks,
            config_entry_id=config_entry_id,
            now=dt_util.now(),
            notes_by_entity=self._problem_notes,
        )
        if not changed:
            return False
        self._tasks = new_tasks
        await self._save()
        entity_set_changed = False
        for kind, task in ops:
            if kind == "created":
                self._hass.bus.async_fire(
                    EVENT_TASK_CREATED, events.task_event_data(task)
                )
                entity_set_changed = True
            elif kind == "deleted":
                self._hass.bus.async_fire(
                    EVENT_TASK_DELETED, events.task_event_data(task)
                )
                entity_set_changed = True
            elif kind == "armed":
                self._hass.bus.async_fire(
                    EVENT_TASK_TRIGGERED, events.task_event_data(task)
                )
            elif kind == "cleared":
                self._hass.bus.async_fire(
                    EVENT_TASK_COMPLETED,
                    events.completion_event_data(
                        task, dt_util.now(), ORIGIN_PROBLEM_SENSOR_SYNC
                    ),
                )
        return entity_set_changed

    async def complete_task(
        self,
        task_id: str,
        completed_at: Any | None = None,
        *,
        origin: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Mark a task completed and advance its recurrence.

        *metadata* is the optional per-completion context (``note``/``cost``/
        ``photo``/``who``); it is cleaned here via
        ``models.normalize_completion_metadata`` and recorded on the new history
        entry. The cleaned mapping is also echoed in the completion event so
        listeners see the same data that was stored.

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
        _reject_synced_problem(existing, origin)
        now = dt_util.now()
        when = completed_at or now
        if when.tzinfo is None:
            # ``cv.datetime`` accepts offset-less strings as naive datetimes;
            # qualify with HA's configured zone (mirrors ``models._coerce_seed``)
            # so the event payload / part stamp / recurrence math all stay aware.
            when = when.replace(tzinfo=now.tzinfo)
        clean_metadata = models.normalize_completion_metadata(metadata)
        updated = recurrence.apply_completion(
            dict(existing), when, now=now, metadata=clean_metadata
        )
        self._reset_usage_baseline(updated)
        self._tasks[task_id] = updated
        # A task carries at most one reserved source, so exactly one stock side-effect
        # applies: a part-linked completion *consumes* a spare, a buy reminder
        # *restocks*. Branch (rather than call both self-guarding helpers) so a
        # malformed both-sources task can never both consume and restock on one
        # completion — a `part` source wins, mirroring add_task's reserved-key guard.
        if _part_source(updated):
            self._stamp_part_replacement(updated, when)
        elif _buy_source(updated):
            self._stamp_buy_restock(updated)
        await self._save()
        _LOGGER.debug(
            "Completed task %s; next due %s", task_id, updated.get("next_due")
        )
        self._hass.bus.async_fire(
            EVENT_TASK_COMPLETED,
            events.completion_event_data(
                updated, when, origin, metadata=clean_metadata
            ),
        )
        return updated

    async def update_completion(
        self, task_id: str, ts: str, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        """Amend a recorded completion's metadata (note/cost/photo/who).

        Edits the entry identified by ISO timestamp *ts* without touching the
        schedule — amending the maintenance log must never rewind or re-arm a task.
        Cleans the metadata the same way as :meth:`complete_task`, persists, and
        fires ``home_keeper_task_completion_updated``. Raises ``KeyError`` for an
        unknown task and ``TaskValidationError`` when no completion matches *ts* (or
        the metadata is invalid). Returns the updated task.
        """
        existing = self._tasks.get(task_id)
        if existing is None:
            raise KeyError(task_id)
        # A synced problem task's history is owned by the sync, not the user.
        _reject_synced_problem(existing, None)
        clean_metadata = models.normalize_completion_metadata(metadata)
        try:
            updated, _replaced_photo = recurrence.update_completion(
                dict(existing),
                ts,
                clean_metadata,
                fields=tuple(models.COMPLETION_METADATA_FIELDS),
            )
        except ValueError as err:
            raise models.TaskValidationError(str(err)) from err
        self._tasks[task_id] = updated
        await self._save()
        # NOTE: a replaced/cleared photo's image-upload blob is cleaned up at the
        # HA boundary once the panel actually uploads images (frontend phase).
        self._hass.bus.async_fire(
            EVENT_TASK_COMPLETION_UPDATED,
            events.task_event_data(updated, extra={"ts": ts}),
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
        # A synced problem task's history is owned by the sync (arm/clear), not the
        # user; don't let the panel/websocket rewrite it.
        _reject_synced_problem(existing, None)
        updated = recurrence.remove_completion(dict(existing), ts, now=dt_util.now())
        self._tasks[task_id] = updated
        await self._save()
        self._hass.bus.async_fire(
            EVENT_TASK_UNCOMPLETED, events.task_event_data(updated)
        )
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
            # The asset's archived history changed — fire asset_updated so listeners
            # (and the events contract) see it, mirroring every other asset mutation.
            self._hass.bus.async_fire(
                EVENT_ASSET_UPDATED,
                events.asset_event_data(
                    asset, extra={"changed_fields": ["archived_history"]}
                ),
            )
        return asset

    def _reset_usage_baseline(self, task: dict[str, Any]) -> None:
        """Reset a usage sensor task's meter baseline to the live reading on completion.

        Completing a usage task ("I changed the oil") resets its counter just as
        completing a floating task resets its clock: the next arming is measured from
        the reading at completion. Done here (the store is HA-aware) rather than in the
        pure recurrence layer. If the bound entity is currently unavailable the baseline
        is cleared (``None``) so the watcher re-anchors on the first valid reading after
        completion rather than measuring from the stale pre-completion baseline.
        """
        cfg = sensor_tasks.sensor_config(task)
        if cfg is None or cfg.get("mode") != SENSOR_MODE_USAGE:
            return
        # Reset the meter to the reading at completion. If the entity is currently
        # unavailable, clear the baseline (``None``) so the watcher re-anchors to the
        # first valid reading *after* completion rather than measuring from the now
        # stale pre-completion baseline — which could otherwise immediately re-arm the
        # task if the meter advanced past target while the entity was unavailable.
        cfg["baseline"] = sensor_watcher.read_sensor_value(self._hass, cfg)

    def _stamp_part_replacement(self, task: dict[str, Any], when: Any) -> None:
        src = _part_source(task)
        if not src:
            return
        asset = self._assets.get(src["asset_id"])
        if not asset:
            return
        when_date = when.date().isoformat() if hasattr(when, "date") else str(when)[:10]
        for part in asset.get("parts", []):
            if part.get("id") == src.get("part_id"):
                part["last_replaced"] = when_date
                # Completing a wear-part replacement consumes one stocked spare;
                # signal a low/out-of-stock crossing so users can automate a reorder.
                self._emit_stock_event(assets.consume_part_stock(part), asset, part)
                break

    def _stamp_buy_restock(self, task: dict[str, Any]) -> None:
        """On completing an auto-created buy task, restock its part.

        Adds the part's ``restock_quantity`` (default 1) to ``stock`` and emits the
        resulting stock transition — normally a ``restocked`` crossing, which the next
        buy-task reconcile turns into removal of this now-satisfied reminder. Buy tasks
        never carry a ``part`` source, so ``_stamp_part_replacement`` leaves them
        untouched (no double-mutation).
        """
        src = _buy_source(task)
        if not src:
            return
        asset = self._assets.get(src["asset_id"])
        if not asset:
            return
        for part in asset.get("parts", []):
            if part.get("id") == src.get("part_id"):
                qty = max(1, int(part.get("restock_quantity") or 1))
                self._emit_stock_event(assets.adjust_part_stock(part, qty), asset, part)
                break

    def _emit_stock_event(
        self, transition: str, asset: dict[str, Any], part: dict[str, Any]
    ) -> None:
        """Fire the bus event for a stock *transition* (low / out / restocked), if any.

        Edge-triggered: ``assets.stock_transition`` returns the crossing this change
        caused (or ``none``), so users can automate a reorder / shopping-list add /
        "back in stock" notification without Home Keeper owning a shopping integration.
        """
        event = _STOCK_EVENT.get(transition)
        if event is not None:
            self._hass.bus.async_fire(event, events.stock_event_data(asset, part))

    async def adjust_part_stock(
        self, asset_id: str, part_id: str, delta: int
    ) -> dict[str, Any]:
        """Change a part's on-hand spare count by ``delta`` (clamped at zero).

        Persists and fires the matching edge-triggered stock event once when the
        adjustment crosses a threshold — low-stock, out-of-stock, or restocked (a
        decrease while already low never nags). Returns the updated asset. Raises
        ``KeyError`` for an unknown asset or part.
        """
        asset = self._assets.get(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        for part in asset.get("parts", []):
            if part.get("id") == part_id:
                transition = assets.adjust_part_stock(part, delta)
                await self._save()
                self._emit_stock_event(transition, asset, part)
                return asset
        raise KeyError(part_id)
