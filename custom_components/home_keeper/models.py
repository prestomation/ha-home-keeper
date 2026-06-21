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
    COMPLETION_DETAIL_MODES,
    COMPLETION_DETAIL_NONE,
    COMPLETION_DETAIL_REQUIRED,
    COMPLETION_METADATA_FIELDS,
    FREQS,
    MAX_INTERVAL,
    REC_FLOATING,
    REC_TRIGGERED,
    RECURRENCE_TYPES,
    UNITS,
)


class TaskValidationError(ValueError):
    """Raised when task input fails validation."""


def normalize_completion_metadata(data: Any) -> dict[str, Any]:
    """Clean optional per-completion metadata into a dict of non-empty keys.

    Accepts a mapping with any of ``note`` / ``cost`` / ``photo`` / ``who`` and
    returns only the keys that carry a value: strings are stripped (blanks dropped),
    ``cost`` is coerced to a non-negative ``float``, and ``photo`` / ``who`` are
    opaque id strings (an image-upload id and a ``person`` entity id respectively).
    The result is what gets merged into a completion's history entry, so an empty
    input yields an empty dict (a plain timestamped completion). Pure — no HA imports.
    """
    if not isinstance(data, dict) or not data:
        return {}
    result: dict[str, Any] = {}
    note = str(data.get("note") or "").strip()
    if note:
        result["note"] = note
    cost = data.get("cost")
    if cost is not None and cost != "":
        try:
            cost_value = float(cost)
        except (TypeError, ValueError) as err:
            raise TaskValidationError("cost must be a number") from err
        if cost_value < 0:
            raise TaskValidationError("cost must be >= 0")
        result["cost"] = cost_value
    photo = str(data.get("photo") or "").strip()
    if photo:
        result["photo"] = photo
    who = str(data.get("who") or "").strip()
    if who:
        result["who"] = who
    return result


def normalize_completion_required_fields(value: Any, mode: str) -> list[str]:
    """Normalize a task's ``completion_required_fields`` for capture *mode*.

    Keeps only recognised metadata field names (order-preserving, de-duplicated).
    The list is only meaningful when *mode* is ``required`` — for ``none`` /
    ``optional`` it is forced empty (nothing is mandatory). When ``required`` with no
    explicit list, it defaults to ``["note"]`` so v1's single capture-mode picker has
    a sensible mandatory field; a future per-field editor simply passes its own list.
    """
    if mode != COMPLETION_DETAIL_REQUIRED:
        return []
    allowed = set(COMPLETION_METADATA_FIELDS)
    result: list[str] = []
    if isinstance(value, (list, tuple)):
        for item in value:
            field = str(item).strip()
            if field in allowed and field not in result:
                result.append(field)
    return result or ["note"]


def _require(data: dict, key: str) -> Any:
    if key not in data or data[key] in (None, ""):
        raise TaskValidationError(f"missing required field: {key!r}")
    return data[key]


def normalize_labels(value: Any) -> list[str]:
    """Normalize a task's ``labels`` into a de-duplicated list of HA label ids.

    Accepts a list/tuple of strings (Home Assistant label ids), a single string,
    or ``None``; blanks and duplicates are dropped while order is preserved.
    Labels reference HA's shared label registry, so the same id (e.g. ``"dog"``)
    can sit on a task here and on a device/area in the registry — that's what
    lets the dashboard card filter across both. Anything that isn't a string or
    list fails loudly at the edge rather than persisting junk.
    """
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise TaskValidationError("labels must be a list of label ids")
    seen: set[str] = set()
    result: list[str] = []
    for item in value:
        label = str(item).strip()
        if label and label not in seen:
            seen.add(label)
            result.append(label)
    return result


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

    detail_mode = data.get("completion_detail") or COMPLETION_DETAIL_NONE
    if detail_mode not in COMPLETION_DETAIL_MODES:
        raise TaskValidationError(f"invalid completion_detail: {detail_mode!r}")

    fields: dict[str, Any] = {
        "name": name,
        "notes": str(data.get("notes", "")),
        "recurrence_type": rec_type,
        "device_id": data.get("device_id") or None,
        "area_id": data.get("area_id") or None,
        "enabled": bool(data.get("enabled", True)),
        # Per-task completion-capture mode + the fields it makes mandatory. Stored on
        # every task kind (the dialog applies regardless of recurrence). See const.py.
        "completion_detail": detail_mode,
        "completion_required_fields": normalize_completion_required_fields(
            data.get("completion_required_fields"), detail_mode
        ),
    }

    # A triggered (condition-driven) task has no schedule at all: no interval, unit,
    # freq, or anchor. Its state is carried entirely by next_due (None = dormant, a
    # timestamp = armed/due), managed by the owning integration via add/complete/
    # trigger. Return early so we don't validate or store schedule fields it lacks.
    if rec_type == REC_TRIGGERED:
        return fields

    try:
        interval = int(data.get("interval", 1))
    except (TypeError, ValueError) as err:
        raise TaskValidationError("interval must be a valid integer") from err
    if interval < 1:
        raise TaskValidationError("interval must be >= 1")
    if interval > MAX_INTERVAL:
        raise TaskValidationError(f"interval must be <= {MAX_INTERVAL}")
    fields["interval"] = interval

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
                parsed_anchor.replace(tzinfo=tz)
                if tz is not None
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


def _coerce_seed(value: Any, *, tz: Any) -> datetime:
    """Parse a ``last_completed`` seed into an aware datetime.

    Accepts a datetime (passed straight through) or an ISO string. A naive value is
    qualified with *tz* (the caller's configured zone) just like a fixed anchor, so
    the recurrence engine can compare it against an aware ``now``.
    """
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError) as err:
            raise TaskValidationError(
                f"invalid last_completed datetime: {value!r}"
            ) from err
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz) if tz is not None else parsed.astimezone()
    return parsed


def build_task(data: dict, *, now: datetime) -> dict:
    """Create a brand-new task dict (with id, history, and computed next_due).

    An optional ``last_completed`` seed records an initial completion so the task
    starts measured from a known "last done" date rather than due-now. Used by
    integrations that already know when the activity last happened (e.g. Pawsistant
    passing a pet's most recent logged event). Without it, a floating task is due now.
    """
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
        # HA label-registry ids attached to this task. Free-form, many-to-many, and
        # used (alongside device/area labels) to scope the dashboard card.
        "labels": normalize_labels(data.get("labels")),
        **fields,
    }
    seed = data.get("last_completed")
    if seed not in (None, ""):
        # Recording the seed as a completion both stamps last_completed and lets the
        # recurrence engine derive next_due (floating -> seed + interval; fixed stays
        # anchor-driven, the seed just becomes its first history entry).
        recurrence.apply_completion(task, _coerce_seed(seed, tz=now.tzinfo), now=now)
    else:
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
        "completion_detail": updates.get(
            "completion_detail", existing.get("completion_detail")
        ),
        "completion_required_fields": updates.get(
            "completion_required_fields", existing.get("completion_required_fields")
        ),
    }
    fields = normalize_fields(candidate, tz=now.tzinfo)
    merged.update(fields)

    # Labels are independent of recurrence/identity, so handle them outside
    # normalize_fields: only rewrite when the caller actually sent ``labels`` (a
    # plain rename must not spuriously stamp ``labels: []`` onto a task that never
    # had the field, which would surface as a phantom "labels changed" event).
    if "labels" in updates:
        merged["labels"] = normalize_labels(updates["labels"])

    # A triggered task has no schedule: its next_due is owned by trigger_task /
    # complete_task (armed timestamp vs dormant None), so editing name/notes/device
    # must never recompute it (that would re-arm a dormant "monitored" task).
    recurrence_keys = {"recurrence_type", "interval", "unit", "freq", "anchor"}
    if merged.get("recurrence_type") != REC_TRIGGERED and (
        recurrence_keys & set(updates)
    ):
        merged["next_due"] = recurrence.compute_next_due(merged, now=now).isoformat()
    return merged
