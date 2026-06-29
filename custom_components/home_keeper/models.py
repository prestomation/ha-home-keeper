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
    REC_ONE_OFF,
    REC_SENSOR,
    REC_TRIGGERED,
    RECURRENCE_TYPES,
    SENSOR_COMPARISONS,
    SENSOR_MODE_USAGE,
    SENSOR_MODES,
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


def normalize_sensor(data: Any) -> dict[str, Any]:
    """Validate and normalize a sensor-based task's ``sensor`` binding.

    A sensor task derives its armed/dormant state from a bound numeric entity. The
    binding always carries ``entity_id`` and ``mode``; the rest is mode-specific:

    * ``usage`` (a meter) — ``target`` (> 0): arm when the reading advances ``target``
      units past ``baseline``. ``baseline`` (the reading captured at creation / last
      completion) is carried through if present; a fresh task leaves it unset for the
      watcher to stamp from the live reading.
    * ``threshold`` — ``comparison`` (one of :data:`SENSOR_COMPARISONS`) against a
      numeric ``value``, with an optional non-negative ``for_seconds`` hold.

    An optional ``attribute`` reads that entity attribute instead of the state. Raises
    :class:`TaskValidationError` on any malformed field so bad input fails at the edge
    rather than persisting. Pure — no HA imports.
    """
    if not isinstance(data, dict):
        raise TaskValidationError("a sensor task requires a sensor configuration")
    entity_id = str(data.get("entity_id") or "").strip()
    if not entity_id:
        raise TaskValidationError("sensor.entity_id is required")
    mode = data.get("mode") or SENSOR_MODE_USAGE
    if mode not in SENSOR_MODES:
        raise TaskValidationError(f"invalid sensor mode: {mode!r}")
    result: dict[str, Any] = {"entity_id": entity_id, "mode": mode}
    attribute = str(data.get("attribute") or "").strip()
    if attribute:
        result["attribute"] = attribute

    if mode == SENSOR_MODE_USAGE:
        target_raw = data.get("target")
        if target_raw is None or target_raw == "":
            raise TaskValidationError("sensor.target must be a number")
        try:
            target = float(target_raw)
        except (TypeError, ValueError) as err:
            raise TaskValidationError("sensor.target must be a number") from err
        if target <= 0:
            raise TaskValidationError("sensor.target must be > 0")
        result["target"] = target
        baseline_raw = data.get("baseline")
        if baseline_raw is not None and baseline_raw != "":
            try:
                result["baseline"] = float(baseline_raw)
            except (TypeError, ValueError) as err:
                raise TaskValidationError("sensor.baseline must be a number") from err
    else:  # SENSOR_MODE_THRESHOLD
        comparison = data.get("comparison")
        if comparison not in SENSOR_COMPARISONS:
            raise TaskValidationError(f"invalid sensor comparison: {comparison!r}")
        value_raw = data.get("value")
        if value_raw is None or value_raw == "":
            raise TaskValidationError("sensor.value must be a number")
        try:
            value = float(value_raw)
        except (TypeError, ValueError) as err:
            raise TaskValidationError("sensor.value must be a number") from err
        result["comparison"] = comparison
        result["value"] = value
        raw_for = data.get("for_seconds") or 0
        try:
            for_seconds = int(raw_for)
        except (TypeError, ValueError) as err:
            raise TaskValidationError("sensor.for_seconds must be an integer") from err
        if for_seconds < 0:
            raise TaskValidationError("sensor.for_seconds must be >= 0")
        if for_seconds:
            result["for_seconds"] = for_seconds
    return result


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


def normalize_card_links(value: Any) -> list[dict[str, str]]:
    """Normalize a task's ``card_links`` — references to appliance links to surface
    on the dashboard task card.

    Each entry is an ``{"asset_id", "entry_id"}`` pair pointing at an appliance
    document of kind ``link`` or a metadata entry of type ``link``. The card resolves
    the reference to a live name/URL at render time and silently drops any that no
    longer exist, so this stays a pure shape check — it never reaches into the asset
    store (keeping ``models.py`` free of HA/store imports). Accepts a list of such
    dicts (or ``None``/empty); blanks and duplicates are dropped, order preserved.
    Anything that isn't a list of objects fails loudly at the edge rather than
    persisting junk.
    """
    if value in (None, "", []):
        return []
    if not isinstance(value, (list, tuple)):
        raise TaskValidationError("card_links must be a list")
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise TaskValidationError("each card_links entry must be an object")
        asset_id = str(item.get("asset_id", "")).strip()
        entry_id = str(item.get("entry_id", "")).strip()
        if not asset_id or not entry_id:
            continue
        key = (asset_id, entry_id)
        if key in seen:
            continue
        seen.add(key)
        result.append({"asset_id": asset_id, "entry_id": entry_id})
    return result


def normalize_task_chips(value: Any) -> list[dict[str, str]]:
    """Normalize a task's ``task_chips`` — integration-provided metadata chips shown
    in both the sidebar panel task list and the dashboard card.

    Each chip is a ``{"label": str, "icon"?: "mdi:*", "url"?: "https?://..."}`` dict.
    ``label`` is required and non-empty. ``icon`` must start with ``mdi:`` if present.
    ``url`` must be an http(s) URL if present. Chips without a label are silently
    dropped; anything that isn't a list fails loudly at the service edge.
    """
    if value in (None, "", []):
        return []
    if not isinstance(value, (list, tuple)):
        raise TaskValidationError("task_chips must be a list")
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise TaskValidationError("each task_chips entry must be an object")
        label = str(item.get("label", "")).strip()
        if not label:
            continue
        chip: dict[str, str] = {"label": label}
        if icon := str(item.get("icon", "")).strip():
            if not (icon.startswith("mdi:") and len(icon) > 4):
                raise TaskValidationError(
                    f"task_chips icon must be 'mdi:<name>' with a non-empty"
                    f" name: {icon!r}"
                )
            chip["icon"] = icon
        if url := str(item.get("url", "")).strip():
            lower = url.lower()
            if not (lower.startswith("http://") or lower.startswith("https://")):
                raise TaskValidationError(
                    f"task_chips url must be an http(s) URL: {url!r}"
                )
            chip["url"] = url
        result.append(chip)
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

    # A sensor-based task has no clock-driven cadence either: its schedule fields are
    # replaced by a ``sensor`` binding that the watcher evaluates to arm/clear it. Its
    # state is carried by next_due (None = dormant, a timestamp = armed). Validate the
    # binding and return early so we don't validate or store interval/unit/freq.
    if rec_type == REC_SENSOR:
        fields["sensor"] = normalize_sensor(data.get("sensor"))
        return fields

    # A do-once task has no cadence (no interval/unit/freq) — only a single ``due``
    # datetime. Its state is carried by next_due (the due date, or None once
    # completed). Qualify a naive value with the caller tz exactly like a fixed
    # anchor (the panel's <input type="datetime-local"> yields a naive value), then
    # return early so we don't validate or store schedule fields it lacks.
    if rec_type == REC_ONE_OFF:
        due = _require(data, "due")
        try:
            parsed_due = datetime.fromisoformat(due)
        except (TypeError, ValueError) as err:
            raise TaskValidationError(f"invalid due datetime: {due!r}") from err
        if parsed_due.tzinfo is None:
            parsed_due = (
                parsed_due.replace(tzinfo=tz)
                if tz is not None
                else parsed_due.astimezone()
            )
        fields["due"] = parsed_due.isoformat()
        return fields

    # Default to 1 when interval is absent *or* explicitly unset. ``merge_update``
    # always carries an ``interval`` key forward, so for a task that never had one
    # (e.g. converting a triggered task to floating/fixed) the value is ``None``;
    # ``dict.get("interval", 1)`` would return that ``None`` rather than the default,
    # so coalesce here to keep the conversion working like a fresh creation.
    raw_interval = data.get("interval", 1)
    if raw_interval in (None, ""):
        raw_interval = 1
    try:
        interval = int(raw_interval)
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

    A one-off task without an explicit ``due`` defaults to *now* (due today), so the
    service / a caller can create a do-once task with just a name.
    """
    if data.get("recurrence_type") == REC_ONE_OFF and not data.get("due"):
        data = {**data, "due": now.isoformat()}
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
        # References to appliance links (documents/metadata) the dashboard card shows
        # on this task's row. Independent of recurrence/identity, like labels.
        "card_links": normalize_card_links(data.get("card_links")),
        # Integration-provided metadata chips shown in both the panel task list and the
        # dashboard card. Each chip is {label, icon?, url?}. Integration-owned; the
        # panel does not expose an editor for this field.
        "task_chips": normalize_task_chips(data.get("task_chips")),
        **fields,
    }
    seed = data.get("last_completed")
    if task["recurrence_type"] == REC_SENSOR:
        # A sensor task is born dormant: the watcher arms it (via ``trigger_task``)
        # only once the live reading actually meets its condition. ``compute_next_due``
        # would read as due-now (the re-arm contract), so set ``None`` directly.
        task["next_due"] = None
    elif seed not in (None, ""):
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
        "due": updates.get("due", existing.get("due")),
        "sensor": updates.get("sensor", existing.get("sensor")),
        "completion_detail": updates.get(
            "completion_detail", existing.get("completion_detail")
        ),
        "completion_required_fields": updates.get(
            "completion_required_fields", existing.get("completion_required_fields")
        ),
    }
    # Converting a task to one-off without supplying a due date defaults to now (due
    # today), mirroring build_task — so the conversion can't fail for a missing due
    # (the panel always sends one, but a service caller may not).
    if candidate["recurrence_type"] == REC_ONE_OFF and not candidate.get("due"):
        candidate["due"] = now.isoformat()
    fields = normalize_fields(candidate, tz=now.tzinfo)
    merged.update(fields)

    # Preserve a usage meter's accumulated baseline across edits. The panel's edit
    # payload rebuilds the ``sensor`` binding from form fields and never carries the
    # watcher-stamped ``baseline``, so without this a plain rename or target tweak
    # would drop it and the watcher would re-anchor to the current reading — silently
    # resetting "12,000 of 15,000" to zero. Carry the old baseline forward only when
    # the binding still points at the same entity in usage mode and the update didn't
    # set one explicitly; changing the entity (a genuinely new meter) re-baselines.
    new_sensor = merged.get("sensor")
    old_sensor = existing.get("sensor")
    if (
        isinstance(new_sensor, dict)
        and new_sensor.get("mode") == SENSOR_MODE_USAGE
        and "baseline" not in new_sensor
        and isinstance(old_sensor, dict)
        and old_sensor.get("entity_id") == new_sensor.get("entity_id")
        and old_sensor.get("baseline") is not None
    ):
        new_sensor["baseline"] = old_sensor["baseline"]

    # Labels are independent of recurrence/identity, so handle them outside
    # normalize_fields: only rewrite when the caller actually sent ``labels`` (a
    # plain rename must not spuriously stamp ``labels: []`` onto a task that never
    # had the field, which would surface as a phantom "labels changed" event).
    if "labels" in updates:
        merged["labels"] = normalize_labels(updates["labels"])

    # Card-link references are likewise independent of recurrence/identity; only
    # rewrite them when the caller actually sent ``card_links`` so a plain rename
    # doesn't wipe a task's chosen links (normalize_fields never touches them).
    if "card_links" in updates:
        merged["card_links"] = normalize_card_links(updates["card_links"])

    # Integration chips follow the same pattern: only rewrite when explicitly sent so
    # a routine update_task call can't accidentally clear chips set at creation time.
    if "task_chips" in updates:
        merged["task_chips"] = normalize_task_chips(updates["task_chips"])

    # A triggered or sensor task has no schedule: its next_due is owned by the arm /
    # complete chokepoints (armed timestamp vs dormant None), so editing
    # name/notes/device/threshold must never recompute it (that would re-arm a dormant
    # "monitored" task). Re-targeting the sensor binding does not arm the task either;
    # the watcher re-evaluates it on the next tick / state change.
    recurrence_keys = {
        "recurrence_type",
        "interval",
        "unit",
        "freq",
        "anchor",
        "due",
        "sensor",
    }
    new_type = merged.get("recurrence_type")
    old_type = existing.get("recurrence_type")
    if new_type not in (REC_TRIGGERED, REC_SENSOR) and (recurrence_keys & set(updates)):
        merged["next_due"] = recurrence.compute_next_due(merged, now=now).isoformat()
    elif new_type == REC_SENSOR and old_type != REC_SENSOR:
        # Converting an existing (e.g. floating, due-now) task into a sensor task: it
        # starts dormant like a freshly-built one, so the watcher arms it only when the
        # bound reading meets the condition (rather than inheriting a stale due date).
        merged["next_due"] = None
    elif new_type == REC_TRIGGERED and old_type != REC_TRIGGERED:
        # Converting a scheduled (floating/fixed/one-off) or sensor task into a
        # condition-driven one: the old next_due is a stale schedule date that has no
        # meaning for a triggered task — carried verbatim it would render as "armed" at
        # an arbitrary past/future instant. Reset to the fresh-build state — armed now,
        # exactly like ``build_task`` creates a triggered task — so the owner can
        # complete it to dormancy or let it re-arm on the next condition.
        merged["next_due"] = recurrence.compute_next_due(merged, now=now).isoformat()
    return merged
