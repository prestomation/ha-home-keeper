"""Task model helpers for Home Keeper.

A task is stored as a plain ``dict`` (JSON-serializable) so it round-trips through
the HA ``Store`` helper and the websocket/service APIs without any conversion. This
module centralizes construction, validation, and normalization of those dicts. It
imports the recurrence engine but nothing from Home Assistant, keeping it
unit-testable.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from . import recurrence
from .const import (
    FREQS,
    MAX_INTERVAL,
    REC_FLOATING,
    RECURRENCE_TYPES,
    UNITS,
)


class TaskValidationError(ValueError):
    """Raised when task input fails validation."""


def _require(data: dict, key: str) -> Any:
    if key not in data or data[key] in (None, ""):
        raise TaskValidationError(f"missing required field: {key!r}")
    return data[key]


def normalize_fields(data: dict, *, tz: Any = None) -> dict:
    """Validate and normalize the user-supplied fields of a task.

    Returns a dict containing only the recurrence-defining fields plus name/notes/
    device/area. Does not assign an id or compute next_due (see :func:`build_task`
    and :func:`merge_update`).

    ``tz`` is the timezone used to qualify a naive fixed-schedule anchor (the
    caller passes Home Assistant's configured tz, e.g. ``dt_util.now().tzinfo``);
    if omitted, the system local tz is used as a fallback.
    """
    name = str(_require(data, "name")).strip()
    if not name:
        raise TaskValidationError("name must not be empty")

    rec_type = data.get("recurrence_type", REC_FLOATING)
    if rec_type not in RECURRENCE_TYPES:
        raise TaskValidationError(f"invalid recurrence_type: {rec_type!r}")

    try:
        interval = int(data.get("interval", 1))
    except (TypeError, ValueError) as err:
        raise TaskValidationError("interval must be a valid integer") from err
    if interval < 1:
        raise TaskValidationError("interval must be >= 1")
    if interval > MAX_INTERVAL:
        raise TaskValidationError(f"interval must be <= {MAX_INTERVAL}")

    fields: dict[str, Any] = {
        "name": name,
        "notes": str(data.get("notes", "")),
        "recurrence_type": rec_type,
        "interval": interval,
        "device_id": data.get("device_id") or None,
        "area_id": data.get("area_id") or None,
        "enabled": bool(data.get("enabled", True)),
    }

    if rec_type == REC_FLOATING:
        unit = data.get("unit")
        if unit not in UNITS:
            raise TaskValidationError(f"invalid unit: {unit!r}")
        fields["unit"] = unit
    else:  # REC_FIXED
        freq = data.get("freq")
        if freq not in FREQS:
            raise TaskValidationError(f"invalid freq: {freq!r}")
        anchor = _require(data, "anchor")
        try:
            parsed_anchor = datetime.fromisoformat(anchor)
        except (TypeError, ValueError) as err:
            raise TaskValidationError(f"invalid anchor datetime: {anchor!r}") from err
        # The panel's <input type="datetime-local"> yields a naive value (no
        # offset). The recurrence engine compares the anchor against an aware
        # ``now``, so a naive anchor would raise a TypeError. Interpret the naive
        # wall-clock time in the caller-provided tz (Home Assistant's configured
        # zone) — falling back to the system tz only if none was passed — and
        # store the offset-qualified ISO string. ``replace`` keeps the wall-clock
        # reading (correct for zoneinfo/DST) rather than shifting it.
        if parsed_anchor.tzinfo is None:
            parsed_anchor = (
                parsed_anchor.replace(tzinfo=tz) if tz is not None
                else parsed_anchor.astimezone()
            )
        fields["freq"] = freq
        fields["anchor"] = parsed_anchor.isoformat()

    return fields


def validate_managed_by(managed_by: Any) -> None:
    """Validate a task's optional ``managed_by`` ownership block.

    A ``deletion_protected`` task must record ``config_entry_id`` — that's how Home
    Keeper detects the managing integration going away and lifts protection so the
    task can be cleaned up. Without it, protection would be a permanent trap (only the
    ``force`` service could remove the task). Rejecting it at creation keeps every
    protected task cleanable. See docs/INTEGRATING.md §6.
    """
    if managed_by is None:
        return
    if not isinstance(managed_by, dict):
        raise TaskValidationError("managed_by must be a mapping")
    if managed_by.get("deletion_protected") and not managed_by.get("config_entry_id"):
        raise TaskValidationError(
            "managed_by.deletion_protected requires config_entry_id so the task can "
            "still be cleaned up if the managing integration is removed"
        )


def deletion_blocked(task: dict, *, orphaned: bool, force: bool = False) -> bool:
    """Whether a task's deletion should be refused.

    Deletion is only blocked for a ``deletion_protected`` managed task while its
    managing integration is still present (``orphaned`` is ``False``). The moment the
    owner is gone — uninstalled, disabled, or failing to load — the task is orphaned
    and must remain deletable so the user can clean it up; otherwise the protection
    becomes a trap (the "delete it from X instead" instruction points nowhere). A
    ``force`` delete bypasses protection entirely (the power-user escape hatch).
    """
    if force:
        return False
    managed_by = task.get("managed_by")
    if not (isinstance(managed_by, dict) and managed_by.get("deletion_protected")):
        return False
    return not orphaned


def build_task(data: dict, *, now: datetime) -> dict:
    """Create a brand-new task dict (with id, history, and computed next_due)."""
    fields = normalize_fields(data, tz=now.tzinfo)
    validate_managed_by(data.get("managed_by"))
    task: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "created": now.isoformat(),
        "last_completed": None,
        "completions": [],
        # Optional provenance, e.g. {"part": {"asset_id", "part_id"}} for a task
        # derived from an asset wear part. Owned by its reconciler when present.
        "source": data.get("source"),
        # Optional well-known ownership block that Home Keeper inspects (unlike the
        # opaque ``source``). Declares which fields are locked, deletion protection,
        # and display metadata. See docs/INTEGRATING.md §6.
        "managed_by": data.get("managed_by"),
        **fields,
    }
    task["next_due"] = recurrence.compute_next_due(task, now=now).isoformat()
    return task


def merge_update(existing: dict, updates: dict, *, now: datetime) -> dict:
    """Return *existing* updated with *updates*, recomputing next_due if needed.

    Only the recurrence-relevant fields trigger a next_due recompute; editing the
    name or notes leaves the schedule untouched.

    When the task has a ``managed_by`` block with ``locked_fields``, those fields
    are stripped from *updates* before merging so the managing integration's values
    are never overwritten by user edits or automation.
    """
    # Enforce locked fields declared by the managing integration.
    managed_by = existing.get("managed_by")
    if managed_by and isinstance(managed_by, dict):
        locked = set(managed_by.get("locked_fields") or [])
        if locked:
            updates = {k: v for k, v in updates.items() if k not in locked}

    merged = dict(existing)
    # Build a candidate field set from existing + updates, then normalize so the
    # same validation applies to edits as to creation.
    candidate = {
        "name": updates.get("name", existing.get("name")),
        "notes": updates.get("notes", existing.get("notes", "")),
        "recurrence_type": updates.get(
            "recurrence_type", existing.get("recurrence_type")
        ),
        "interval": updates.get("interval", existing.get("interval")),
        "device_id": updates.get("device_id", existing.get("device_id")),
        "area_id": updates.get("area_id", existing.get("area_id")),
        "enabled": updates.get("enabled", existing.get("enabled", True)),
        "unit": updates.get("unit", existing.get("unit")),
        "freq": updates.get("freq", existing.get("freq")),
        "anchor": updates.get("anchor", existing.get("anchor")),
    }
    fields = normalize_fields(candidate, tz=now.tzinfo)
    merged.update(fields)

    recurrence_keys = {"recurrence_type", "interval", "unit", "freq", "anchor"}
    if recurrence_keys & set(updates):
        merged["next_due"] = recurrence.compute_next_due(merged, now=now).isoformat()
    return merged
