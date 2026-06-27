"""Pure logic for the wear-part → maintenance-task reconciliation.

A wear part with a ``replace_interval`` yields a floating maintenance task attached
to the asset's device (so it reuses the existing to-do/calendar/per-task entities).
The task is keyed by ``source = {"part": {asset_id, part_id}}`` so the reconciler
exclusively owns it.

This module imports nothing from Home Assistant: it is a pure transformation over
plain dicts (assets, tasks) that :class:`store.HomeKeeperStore` wraps with
persistence. Keeping it pure lets the create/anchor/heal/orphan branches be
unit-tested directly (see ``tests/unit/test_reconcile.py``).
"""

from __future__ import annotations

from datetime import datetime, tzinfo
from typing import Any

from . import models, recurrence
from .const import PART_WEAR, TASK_SOURCE_PART


def part_source(task: dict[str, Any]) -> dict[str, Any] | None:
    """Return a task's ``{asset_id, part_id}`` part provenance, or None.

    Covers both reconciler-derived tasks (auto-generated from a wear part's
    ``replace_interval``) and tasks a user *manually linked* to a consumable — both
    carry ``source = {"part": {"asset_id", "part_id", ...}}`` so completion consumes
    one spare from the part's stock. A manual link additionally carries
    ``"manual": True`` inside the part dict; use :func:`is_manual_part_link` to tell
    them apart where ownership matters (the reconciler must not own manual links).
    """
    source = task.get("source")
    if isinstance(source, dict) and isinstance(source.get(TASK_SOURCE_PART), dict):
        return source[TASK_SOURCE_PART]
    return None


def is_manual_part_link(task: dict[str, Any]) -> bool:
    """True when a task's part link was set by the user, not the reconciler.

    The reconciler exclusively owns the wear-part tasks it generates (it creates,
    updates, and *deletes* them as parts change). A manual link reuses the same
    ``source.part`` shape so it consumes stock on completion, but must be invisible
    to the reconciler — otherwise the next reconcile pass would delete it as an
    "orphan" (its part has no ``replace_interval``). The ``manual`` flag is the
    discriminator that keeps the two apart with no storage migration: existing
    derived tasks lack it and stay reconciler-owned.
    """
    src = part_source(task)
    return bool(src and src.get("manual"))


def qualify_iso(value: str | None, tz: tzinfo | None) -> str | None:
    """Parse an ISO date/datetime and return an aware ISO string (or None).

    A part's ``last_replaced`` is a date-only string; the recurrence engine
    compares the derived ``next_due`` against an aware ``now``, so a naive value
    must be qualified to Home Assistant's timezone first.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz) if tz is not None else parsed.astimezone()
    return parsed.isoformat()


def reconcile_part_tasks(
    assets: dict[str, dict[str, Any]],
    tasks: dict[str, dict[str, Any]],
    *,
    now: datetime,
) -> tuple[dict[str, dict[str, Any]], bool]:
    """Compute the task map derived from wear parts.

    Returns ``(new_tasks, changed)``. ``new_tasks`` is a fresh dict (the input is
    not mutated); ``changed`` is ``True`` when it differs from ``tasks``. Tasks
    without a part source are carried through untouched.
    """
    result = dict(tasks)

    desired: dict[tuple[str, str], tuple[dict, dict]] = {}
    for asset in assets.values():
        for part in asset.get("parts", []):
            if part.get("type") == PART_WEAR and part.get("replace_interval"):
                desired[(asset["id"], part["id"])] = (asset, part)

    existing_by_key: dict[tuple[str, str], str] = {}
    for tid, task in result.items():
        src = part_source(task)
        # Skip manually-linked tasks: they reuse the part-source shape (to consume
        # stock on completion) but are user-owned, so the reconciler must never
        # update or orphan-delete them.
        if src and not src.get("manual"):
            existing_by_key[(src["asset_id"], src["part_id"])] = tid

    changed = False

    # Remove orphaned part-tasks (the part or its wear cadence went away).
    for key, tid in list(existing_by_key.items()):
        if key not in desired:
            del result[tid]
            existing_by_key.pop(key, None)
            changed = True

    # Create or update the rest.
    for key, (asset, part) in desired.items():
        name = f"Replace {part['name']} ({asset.get('name') or 'appliance'})"
        # A part's last_replaced is a date-only string; qualify it to HA's tz so the
        # derived next_due is timezone-aware. A naive next_due otherwise crashes the
        # next-due sensor, overdue binary_sensor, and the calendar (which compare it
        # against an aware "now").
        anchored = qualify_iso(part.get("last_replaced"), now.tzinfo)
        existing_tid = existing_by_key.get(key)
        if existing_tid is None:
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
            # Anchor the floating clock to the recorded replacement. With no
            # recorded replacement we leave last_completed unset (build_task's
            # default), so the part reads as due now rather than "assumed fresh" a
            # full interval out: an unknown replacement history is better surfaced
            # now — the user can backdate the replacement or mark it done — than
            # silently hidden for a cycle.
            if anchored:
                task["last_completed"] = anchored
                task["next_due"] = recurrence.compute_next_due(
                    task, now=now
                ).isoformat()
            result[task["id"]] = task
            changed = True
        else:
            # Only pass fields that actually changed. Passing interval/unit
            # unconditionally would re-trigger a next_due recompute on every
            # reconcile (setup, any asset edit), needlessly churning the schedule.
            before = result[existing_tid]
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
            merged = (
                models.merge_update(before, updates, now=now) if updates else before
            )
            # Heal a legacy timezone-naive last_completed (older builds stored a
            # date-only last_replaced verbatim, yielding a naive next_due that crashed
            # the sensors/calendar). Only re-qualify a naive value — never overwrite a
            # real (already-aware) completion timestamp.
            lc = merged.get("last_completed")
            healed = qualify_iso(lc, now.tzinfo) if lc else None
            if healed and healed != lc:
                merged = dict(merged)
                merged["last_completed"] = healed
                merged["next_due"] = recurrence.compute_next_due(
                    merged, now=now
                ).isoformat()
            if merged is not before:
                result[existing_tid] = merged
                changed = True

    # Clear a manual consumable link whose target part no longer exists (the part was
    # removed while the appliance remains). Left dangling, the link silently no-ops on
    # completion — the user would think they're drawing down stock but aren't. The task
    # itself survives as a plain standalone task; only its source is cleared.
    existing_parts = {
        (asset.get("id"), part.get("id"))
        for asset in assets.values()
        for part in asset.get("parts", [])
        if part.get("id")
    }
    for tid, task in list(result.items()):
        if not is_manual_part_link(task):
            continue
        src = part_source(task)
        if (src["asset_id"], src["part_id"]) not in existing_parts:
            result[tid] = {**task, "source": None}
            changed = True

    return result, changed
