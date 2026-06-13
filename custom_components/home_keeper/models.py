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
    REC_FIXED,
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


def normalize_fields(data: dict) -> dict:
    """Validate and normalize the user-supplied fields of a task.

    Returns a dict containing only the recurrence-defining fields plus name/notes/
    device/area. Does not assign an id or compute next_due (see :func:`build_task`
    and :func:`merge_update`).
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
        # Validate parseable ISO datetime; store as the original ISO string.
        try:
            datetime.fromisoformat(anchor)
        except (TypeError, ValueError) as err:
            raise TaskValidationError(f"invalid anchor datetime: {anchor!r}") from err
        fields["freq"] = freq
        fields["anchor"] = anchor

    return fields


def build_task(data: dict, *, now: datetime) -> dict:
    """Create a brand-new task dict (with id, history, and computed next_due)."""
    fields = normalize_fields(data)
    task: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "created": now.isoformat(),
        "last_completed": None,
        "completions": [],
        **fields,
    }
    task["next_due"] = recurrence.compute_next_due(task, now=now).isoformat()
    return task


def merge_update(existing: dict, updates: dict, *, now: datetime) -> dict:
    """Return *existing* updated with *updates*, recomputing next_due if needed.

    Only the recurrence-relevant fields trigger a next_due recompute; editing the
    name or notes leaves the schedule untouched.
    """
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
    fields = normalize_fields(candidate)
    merged.update(fields)

    recurrence_keys = {"recurrence_type", "interval", "unit", "freq", "anchor"}
    if recurrence_keys & set(updates):
        merged["next_due"] = recurrence.compute_next_due(merged, now=now).isoformat()
    return merged
