"""Pure logic for the ``device_class: problem`` binary-sensor → task sync.

When the *sync problem sensors* option is on, Home Keeper mirrors every eligible
``binary_sensor`` with ``device_class: problem`` as a condition-driven
(``triggered``) task. The task is **armed** (reads as due-now) while the sensor
reports a problem and goes **dormant** when it clears. Unlike an ordinary task it
cannot be completed from inside Home Keeper — the originating integration has to
resolve the underlying problem (the sensor returns to ``off``), at which point the
sync clears the task automatically.

Each task is keyed by ``source = {"problem_sensor": {"entity_id": ...}}`` so the
reconciler exclusively owns it, and carries a ``managed_by`` block marking it as
Home-Keeper-managed, deletion-protected, and **completion-blocked**.

This module imports nothing from Home Assistant: it is a pure transformation over
plain dicts that :class:`store.HomeKeeperStore` wraps with persistence (the HA-aware
enumeration of eligible sensors and the state listener live in ``problem_sync.py``).
Keeping it pure lets the create/arm/clear/orphan branches be unit-tested directly
(see ``tests/unit/test_problem_tasks.py``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from . import models, recurrence
from .const import (
    DOMAIN,
    PANEL_TITLE,
    REC_TRIGGERED,
    TASK_SOURCE_PROBLEM_SENSOR,
)

# Fields the managing sync owns; user edits to these (via the update_task service)
# are stripped by ``models.merge_update``. The panel additionally hides edit/delete
# for source-owned tasks, and ``next_due`` is driven solely by arm/clear.
_LOCKED_FIELDS = ["name", "recurrence_type", "device_id", "area_id"]


def problem_source(task: dict[str, Any]) -> dict[str, Any] | None:
    """Return a task's ``{entity_id}`` problem-sensor provenance, or ``None``."""
    source = task.get("source")
    if isinstance(source, dict) and isinstance(
        source.get(TASK_SOURCE_PROBLEM_SENSOR), dict
    ):
        return source[TASK_SOURCE_PROBLEM_SENSOR]
    return None


def problem_sensor_entity_id(task: dict[str, Any]) -> str | None:
    """The originating ``binary_sensor`` entity id of a synced task, or ``None``."""
    src = problem_source(task)
    return src.get("entity_id") if src else None


def build_managed_by(entity_id: str, config_entry_id: str) -> dict[str, Any]:
    """Ownership block stamped on a synced task.

    ``deletion_protected`` requires ``config_entry_id`` (see
    ``models.validate_managed_by``) so the task stays cleanable if Home Keeper is
    removed. ``completion_blocked`` tells the panel to hide the *Done* action, and
    ``completion_prompt`` explains how the problem actually clears.
    """
    return {
        "integration": DOMAIN,
        "display_name": PANEL_TITLE,
        "config_entry_id": config_entry_id,
        "deletion_protected": True,
        "locked_fields": list(_LOCKED_FIELDS),
        "completion_blocked": True,
        "completion_prompt": (
            f"Synced from {entity_id}. This problem can't be cleared in Home "
            "Keeper — it clears automatically once the originating integration "
            "resolves it (the sensor returns to OK)."
        ),
    }


def _build_task(
    entity_id: str,
    meta: dict[str, Any],
    *,
    config_entry_id: str,
    now: datetime,
    note: str = "",
    consumable: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a fresh synced task dict for *entity_id*, armed per ``is_problem``.

    *note* re-hydrates the free-text note the user last attached to this sensor. It
    is persisted independently of the task (keyed by ``entity_id`` in the store), so
    a note survives the task being deleted and later recreated — turning the sync off
    and on again, or temporarily excluding the sensor — and reappears the next time
    the problem fires.

    *consumable* re-hydrates the spare-part link (``{asset_id, part_id,
    consume_on_clear}``) the same way — attached to a problem mirror it surfaces
    where-to-buy / spares-on-hand and, when ``consume_on_clear`` is ``auto``, draws
    down a spare on clear. Like the note it is persisted by the store keyed on the
    sensor entity_id so it survives the mirror being deleted and recreated.
    """
    consumable = consumable or {}
    task = models.build_task(
        {
            "name": meta["name"],
            "recurrence_type": REC_TRIGGERED,
            "notes": note,
            "device_id": meta.get("device_id"),
            "area_id": meta.get("area_id"),
            "source": {TASK_SOURCE_PROBLEM_SENSOR: {"entity_id": entity_id}},
            "managed_by": build_managed_by(entity_id, config_entry_id),
            "consumable": (
                {
                    "asset_id": consumable["asset_id"],
                    "part_id": consumable["part_id"],
                }
                if consumable.get("asset_id") and consumable.get("part_id")
                else None
            ),
            "consume_on_clear": consumable.get("consume_on_clear"),
        },
        now=now,
    )
    # ``build_task`` arms a triggered task by default (compute_next_due -> now). Arm
    # only when the sensor is *definitely* reporting a problem; a clear (``False``)
    # or indeterminate (``None`` — unavailable/unknown/not-yet-restored) state starts
    # the mirror dormant so we never fabricate a problem we haven't observed.
    if meta.get("is_problem") is not True:
        task["next_due"] = None
    return task


def reconcile_problem_tasks(
    eligible: dict[str, dict[str, Any]],
    tasks: dict[str, dict[str, Any]],
    *,
    config_entry_id: str,
    now: datetime,
    notes_by_entity: dict[str, str] | None = None,
    consumables_by_entity: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, dict[str, Any]]], bool]:
    """Compute the task map mirroring the eligible problem sensors.

    *eligible* maps ``entity_id`` -> ``{"name", "device_id", "area_id",
    "is_problem"}`` for every sensor that should be synced (already filtered for the
    option being on, exclusions, and Home Keeper's own entities by the caller).

    *notes_by_entity* maps ``entity_id`` -> the durable free-text note the user last
    saved for that sensor. A freshly created task seeds its ``notes`` from it, so a
    note the user wrote last time reappears when the same problem is mirrored again
    (see :func:`_build_task`). Existing tasks keep their live ``notes`` untouched.

    *consumables_by_entity* maps ``entity_id`` -> the durable spare-part link
    (``{asset_id, part_id, consume_on_clear}``) the same way, so a freshly created
    mirror re-hydrates the part the user attached. Existing tasks keep their live
    ``consumable``/``consume_on_clear`` untouched.

    Returns ``(new_tasks, ops, changed)``:

    * ``new_tasks`` — a fresh task map (non-synced tasks carried through untouched).
    * ``ops`` — ordered ``(kind, task)`` events the store must fire: ``"created"``,
      ``"deleted"``, ``"armed"`` (sensor went to problem) and ``"cleared"`` (sensor
      resolved). Metadata-only edits (name/device/area drift) produce no op but do
      set ``changed``.
    * ``changed`` — whether ``new_tasks`` differs from ``tasks`` (persist if true).
    """
    result = dict(tasks)
    notes_by_entity = notes_by_entity or {}
    consumables_by_entity = consumables_by_entity or {}
    ops: list[tuple[str, dict[str, Any]]] = []
    changed = False

    existing_by_entity: dict[str, str] = {}
    for tid, task in result.items():
        eid = problem_sensor_entity_id(task)
        if eid is not None:
            existing_by_entity[eid] = tid

    # Remove orphans: the sensor was deleted, excluded, or syncing was turned off.
    for entity_id, tid in list(existing_by_entity.items()):
        if entity_id not in eligible:
            ops.append(("deleted", result.pop(tid)))
            existing_by_entity.pop(entity_id, None)
            changed = True

    # Create or arm/clear/update the rest.
    for entity_id, meta in eligible.items():
        existing_tid = existing_by_entity.get(entity_id)
        if existing_tid is None:
            task = _build_task(
                entity_id,
                meta,
                config_entry_id=config_entry_id,
                now=now,
                note=notes_by_entity.get(entity_id, ""),
                consumable=consumables_by_entity.get(entity_id),
            )
            result[task["id"]] = task
            ops.append(("created", task))
            changed = True
            continue

        task = result[existing_tid]
        # Re-derive owned metadata that follows the sensor (rename, re-home to a new
        # device/area). Silent churn — not announced as a user-facing update.
        managed_by = build_managed_by(entity_id, config_entry_id)
        for field, value in (
            ("name", meta["name"]),
            ("device_id", meta.get("device_id")),
            ("area_id", meta.get("area_id")),
        ):
            if task.get(field) != value:
                task[field] = value
                changed = True
        if task.get("managed_by") != managed_by:
            task["managed_by"] = managed_by
            changed = True

        armed = task.get("next_due") is not None
        problem = meta.get("is_problem")
        # ``problem`` is three-way: True (arm), False (clear), None (indeterminate —
        # sensor unavailable/unknown/not-yet-restored). Only transition on a definite
        # reading; leave the armed state untouched while indeterminate so a
        # device-offline blip or an early-setup reconcile can't fabricate a clear
        # (which would fire a spurious completion) or a false arm.
        if problem is True and not armed:
            task["next_due"] = now.isoformat()
            ops.append(("armed", task))
            changed = True
        elif problem is False and armed:
            recurrence.apply_completion(task, now, now=now)
            ops.append(("cleared", task))
            changed = True

    return result, ops, changed
