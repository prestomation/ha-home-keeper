"""Task model helpers for Home Keeper.

A task is stored as a plain ``dict`` (JSON-serializable) so it round-trips through
the HA ``Store`` helper and the websocket/service APIs without any conversion. This
module centralizes construction, validation, and normalization of those dicts. It
imports the recurrence engine but nothing from Home Assistant, keeping it
unit-testable.
"""

from __future__ import annotations

import math
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
    MAX_SENSOR_STATE_LEN,
    MAX_SENSOR_UNIT_LEN,
    REC_FLOATING,
    REC_ONE_OFF,
    REC_SENSOR,
    REC_TRIGGERED,
    RECURRENCE_TYPES,
    SENSOR_COMBINATOR_ANY,
    SENSOR_COMBINATORS,
    SENSOR_COMPARISONS,
    SENSOR_MODE_THRESHOLD,
    SENSOR_MODE_USAGE,
    SENSOR_MODES,
    UNITS,
)

# Binding fields that only mean anything for a ``usage`` meter. The edge-driven modes
# (``threshold``, ``state``) reject them rather than storing a setting that never
# applies.
USAGE_ONLY_SENSOR_FIELDS = ("also_every", "combinator", "unit", "target", "baseline")


class TaskValidationError(ValueError):
    """Raised when task input fails validation."""


def _finite_float(value: Any, field: str) -> float:
    """Parse *value* to a float, rejecting NaN/Infinity.

    ``float("nan")`` passes every ``<``/``<=`` comparison (all False), so a bare
    ``float()`` would let NaN/inf slip past the range gates and persist — and NaN
    serializes to ``null`` on the JSON round-trip, producing exactly the junk state
    validation exists to prevent. Callers use this instead of ``float()`` for any
    numeric field that is stored.
    """
    try:
        result = float(value)
    except (TypeError, ValueError) as err:
        raise TaskValidationError(f"{field} must be a number") from err
    if not math.isfinite(result):
        raise TaskValidationError(f"{field} must be a finite number")
    return result


def normalize_completion_metadata(
    data: Any, *, allow_reading: bool = False
) -> dict[str, Any]:
    """Clean optional per-completion metadata into a dict of non-empty keys.

    Accepts a mapping with any of ``note`` / ``cost`` / ``photo`` / ``who`` and
    returns only the keys that carry a value: strings are stripped (blanks dropped),
    ``cost`` is coerced to a non-negative ``float``, and ``photo`` / ``who`` are
    opaque id strings (an image-upload id and a ``person`` entity id respectively).
    The result is what gets merged into a completion's history entry, so an empty
    input yields an empty dict (a plain timestamped completion). Pure — no HA imports.

    ``allow_reading`` opts in to the captured ``reading`` key — the bound sensor's
    value at completion time. It is off by default and a disallowed ``reading``
    **raises** rather than being dropped, mirroring :func:`_reject_fields`: silently
    discarding it would let a caller believe a floating task's history recorded a
    meter it has no sensor to read. Unlike ``cost`` there is no ``>= 0`` floor — a
    net-energy or temperature sensor legitimately reads below zero, and
    ``sensor.baseline`` (the number this has to stay comparable with) has none either.
    """
    if not isinstance(data, dict) or not data:
        return {}
    result: dict[str, Any] = {}
    reading = data.get("reading")
    if reading is not None and reading != "":
        if not allow_reading:
            raise TaskValidationError(
                "reading is only valid for a sensor task with a numeric binding"
            )
        result["reading"] = _finite_float(reading, "reading")
    note = str(data.get("note") or "").strip()
    if note:
        result["note"] = note
    cost = data.get("cost")
    if cost is not None and cost != "":
        cost_value = _finite_float(cost, "cost")
        if cost_value < 0:
            raise TaskValidationError("cost must be >= 0")
        result["cost"] = cost_value
    photo = str(data.get("photo") or "").strip()
    if photo:
        # ``photo`` is rendered into an ``href``/``img src`` in the panel, so reject
        # anything that isn't http(s) or a site-relative path (the shape
        # ``ha-picture-upload`` produces) — otherwise a ``javascript:``/``data:`` URI
        # becomes stored XSS the moment someone views the history. Defence-in-depth
        # matches the frontend ``isSafeImageUrl`` guard.
        lowered = photo.lower()
        is_http = lowered.startswith(("http://", "https://"))
        is_site_relative = photo.startswith("/") and not photo.startswith("//")
        if not (is_http or is_site_relative):
            raise TaskValidationError(
                "photo must be an http(s) URL or a site-relative path"
            )
        result["photo"] = photo
    who = str(data.get("who") or "").strip()
    if who:
        result["who"] = who
    return result


def task_records_reading(task: Any) -> bool:
    """Whether completing *task* should record the bound sensor's reading.

    True for a sensor task in a **numeric** mode (``usage`` or ``threshold``). A
    ``state`` binding compares a string (``on`` / ``docked``), so there is no number
    to log. This is the single gate for the whole feature — the store consults it
    before capturing, the metadata normalizer before accepting, and the panel before
    offering the field — so widening it later (a future numeric mode) is one line.
    Pure — takes a plain task dict, no HA imports.
    """
    if not isinstance(task, dict) or task.get("recurrence_type") != REC_SENSOR:
        return False
    cfg = task.get("sensor")
    if not isinstance(cfg, dict):
        return False
    return cfg.get("mode", SENSOR_MODE_USAGE) in (
        SENSOR_MODE_USAGE,
        SENSOR_MODE_THRESHOLD,
    )


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
    # Deliberately the *metadata* list, not COMPLETION_ENTRY_FIELDS: a captured field
    # like ``reading`` is filled in by Home Keeper, so demanding it would gate the
    # completion on something the user was never asked for — and on a task with no
    # sensor bound, on something that can never arrive at all.
    allowed = set(COMPLETION_METADATA_FIELDS)
    result: list[str] = []
    if isinstance(value, (list, tuple)):
        for item in value:
            field = str(item).strip()
            if field in allowed and field not in result:
                result.append(field)
    return result or ["note"]


def _normalize_also_every(data: Any) -> dict[str, Any]:
    """Validate a usage binding's optional time backstop (``{interval, unit}``).

    Same interval/unit rules as a floating task's cadence, so "or every 6 months"
    means exactly what it does everywhere else in Home Keeper.
    """
    if not isinstance(data, dict):
        raise TaskValidationError("sensor.also_every must be a mapping")
    raw_interval = data.get("interval", 1)
    if raw_interval in (None, ""):
        raw_interval = 1
    try:
        interval = int(raw_interval)
    except (TypeError, ValueError) as err:
        raise TaskValidationError(
            "sensor.also_every.interval must be a valid integer"
        ) from err
    if interval < 1:
        raise TaskValidationError("sensor.also_every.interval must be >= 1")
    if interval > MAX_INTERVAL:
        raise TaskValidationError(
            f"sensor.also_every.interval must be <= {MAX_INTERVAL}"
        )
    unit = data.get("unit")
    if unit not in UNITS:
        raise TaskValidationError(f"invalid sensor.also_every.unit: {unit!r}")
    return {"interval": interval, "unit": unit}


def _normalize_for_seconds(data: dict[str, Any]) -> int:
    """Validate the optional ``for_seconds`` hold shared by edge-driven modes.

    ``threshold`` and ``state`` both let a condition be required to *persist* before
    the task arms ("the door has been open for 10 minutes"), so the rule lives here
    rather than in each branch.
    """
    raw_for = data.get("for_seconds") or 0
    try:
        for_seconds = int(raw_for)
    except (TypeError, ValueError) as err:
        raise TaskValidationError("sensor.for_seconds must be an integer") from err
    if for_seconds < 0:
        raise TaskValidationError("sensor.for_seconds must be >= 0")
    return for_seconds


def _reject_fields(data: dict[str, Any], fields: tuple[str, ...], mode: str) -> None:
    """Fail when a binding carries fields that belong to a different mode.

    Silently dropping them would let the panel save an "every 300 h" target onto a
    state task and leave the user believing it applies.
    """
    for name in fields:
        if data.get(name) not in (None, "", {}):
            raise TaskValidationError(
                f"sensor.{name} is not valid for a {mode}-mode sensor task"
            )


def normalize_sensor(data: Any) -> dict[str, Any]:
    """Validate and normalize a sensor-based task's ``sensor`` binding.

    A sensor task derives its armed/dormant state from a bound entity. The
    binding always carries ``entity_id`` and ``mode``; the rest is mode-specific:

    * ``usage`` (a meter) — ``target`` (> 0): arm when the reading advances ``target``
      units past ``baseline``. ``baseline`` (the reading captured at creation / last
      completion) is carried through if present; a fresh task leaves it unset for the
      watcher to stamp from the live reading. An optional ``also_every``
      (``{interval, unit}``) adds a **time backstop** — the "or every 6 months" half of
      a real service interval, measured from the last completion (or the task's
      creation if it has never been completed) — combined with the meter target by
      ``combinator`` (``any``, the default, = whichever comes first; ``all`` = both).
      An optional ``unit`` labels the meter in the UI.
    * ``threshold`` — ``comparison`` (one of :data:`SENSOR_COMPARISONS`) against a
      numeric ``value``, with an optional non-negative ``for_seconds`` hold.
    * ``state`` — a ``state`` string the entity must enter, with the same optional
      ``for_seconds`` hold. This is the binary-sensor mode (``on``/``off``), though any
      state-y entity works.

    ``threshold`` and ``state`` also accept ``clear_on_recover``: when set, an armed
    task clears itself once the condition goes away again, instead of waiting to be
    completed by hand.

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
        target = _finite_float(target_raw, "sensor.target")
        if target <= 0:
            raise TaskValidationError("sensor.target must be > 0")
        result["target"] = target
        baseline_raw = data.get("baseline")
        if baseline_raw is not None and baseline_raw != "":
            result["baseline"] = _finite_float(baseline_raw, "sensor.baseline")
        unit_label = str(data.get("unit") or "").strip()
        if unit_label:
            if len(unit_label) > MAX_SENSOR_UNIT_LEN:
                raise TaskValidationError(
                    f"sensor.unit must be <= {MAX_SENSOR_UNIT_LEN} characters"
                )
            result["unit"] = unit_label
        also_every = data.get("also_every")
        if also_every not in (None, "", {}):
            result["also_every"] = _normalize_also_every(also_every)
            combinator = data.get("combinator") or SENSOR_COMBINATOR_ANY
            if combinator not in SENSOR_COMBINATORS:
                raise TaskValidationError(f"invalid sensor.combinator: {combinator!r}")
            result["combinator"] = combinator
    elif mode == SENSOR_MODE_THRESHOLD:
        _reject_fields(data, USAGE_ONLY_SENSOR_FIELDS, "threshold")
        comparison = data.get("comparison")
        if comparison not in SENSOR_COMPARISONS:
            raise TaskValidationError(f"invalid sensor comparison: {comparison!r}")
        value_raw = data.get("value")
        if value_raw is None or value_raw == "":
            raise TaskValidationError("sensor.value must be a number")
        value = _finite_float(value_raw, "sensor.value")
        result["comparison"] = comparison
        result["value"] = value
        if for_seconds := _normalize_for_seconds(data):
            result["for_seconds"] = for_seconds
        if data.get("clear_on_recover"):
            result["clear_on_recover"] = True
    else:  # SENSOR_MODE_STATE
        _reject_fields(
            data, (*USAGE_ONLY_SENSOR_FIELDS, "comparison", "value"), "state"
        )
        state = str(data.get("state") or "").strip()
        if not state:
            raise TaskValidationError("sensor.state is required")
        if len(state) > MAX_SENSOR_STATE_LEN:
            raise TaskValidationError(
                f"sensor.state must be <= {MAX_SENSOR_STATE_LEN} characters"
            )
        result["state"] = state
        if for_seconds := _normalize_for_seconds(data):
            result["for_seconds"] = for_seconds
        if data.get("clear_on_recover"):
            result["clear_on_recover"] = True
    return result


def _require(data: dict, key: str) -> Any:
    if key not in data or data[key] in (None, ""):
        raise TaskValidationError(f"missing required field: {key!r}")
    return data[key]


def normalize_tag_id(value: Any) -> str | None:
    """Normalize a task's ``tag_id`` — the NFC/RFID tag that completes it.

    The value is a Home Assistant tag id (from the ``tag`` integration), stored so a
    ``tag_scanned`` event can be routed back to every task bound to it. ``None``, an
    empty string, or whitespace means "no tag" and normalizes to ``None`` so
    unlinking a tag is expressible; anything that isn't a string fails loudly at the
    edge rather than persisting junk that could never match a scan.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise TaskValidationError("tag_id must be a string")
    return value.strip() or None


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
        # ``str(None)`` would store the literal "None"; coalesce to "" so an explicit
        # ``notes: null`` (reachable via the websocket updates dict) clears the field.
        "notes": str(data.get("notes") or ""),
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
    tag_id = normalize_tag_id(data.get("tag_id"))
    require_tag_scan = bool(data.get("require_tag_scan"))
    if require_tag_scan and tag_id is None:
        raise TaskValidationError("require_tag_scan needs a linked tag")
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
        # The NFC/RFID tag that completes this task, and whether a scan is the *only*
        # way to complete it (a physical presence check: you have to be at the thing).
        "tag_id": tag_id,
        "require_tag_scan": require_tag_scan,
        **fields,
    }
    seed = data.get("last_completed")
    if task["recurrence_type"] == REC_SENSOR:
        # A sensor task is born dormant: the watcher arms it (via ``trigger_task``)
        # only once the live reading actually meets its condition. ``compute_next_due``
        # would read as due-now (the re-arm contract), so set ``None`` directly.
        task["next_due"] = None
        if seed not in (None, ""):
            # A seeded "last serviced" date is meaningful for a sensor task too: it
            # anchors the time backstop (``sensor.also_every``), so a task created for
            # a machine serviced three months ago is three months into its calendar
            # interval rather than starting the clock today. ``apply_completion``
            # leaves a sensor task dormant, so this records history without arming.
            #
            # When the binding also carries an explicit ``baseline``, the two together
            # describe one event — "serviced on that date, at that reading" — so the
            # seeded history entry records the reading as well. That keeps the whole
            # feature's invariant true from the very first row: a usage task's
            # baseline *is* the reading on its latest completion.
            meta: dict[str, Any] = {}
            baseline = fields["sensor"].get("baseline")
            if baseline is not None and task_records_reading(task):
                meta["reading"] = baseline
            recurrence.apply_completion(
                task, _coerce_seed(seed, tz=now.tzinfo), now=now, metadata=meta
            )
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
        and isinstance(old_sensor, dict)
        and old_sensor.get("entity_id") == new_sensor.get("entity_id")
        and "baseline" not in new_sensor
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

    # The tag binding follows the same only-when-sent rule, so a plain rename can't
    # unlink a task's tag or drop its scan requirement.
    if "tag_id" in updates:
        merged["tag_id"] = normalize_tag_id(updates["tag_id"])
    if "require_tag_scan" in updates:
        merged["require_tag_scan"] = bool(updates["require_tag_scan"])
    # Checked against the *merged* task rather than the payload: requiring a scan with
    # no tag to scan would lock the task out of every completion surface, and that
    # state is reachable by clearing the tag alone (leaving the flag standing) just as
    # easily as by setting the flag alone.
    if merged.get("require_tag_scan") and not merged.get("tag_id"):
        raise TaskValidationError("require_tag_scan needs a linked tag")

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
    # Recompute only when a recurrence field's *value* actually changed — not merely
    # because the key is present in the payload. The panel's edit form always sends
    # recurrence_type/due (and interval/unit for scheduled tasks), so keying off
    # presence recomputed next_due on every rename: it resurrected a completed one-off
    # (next_due derived from its past ``due``) and silently cancelled a snooze
    # (next_due snapped back to the schedule). Comparing merged-vs-existing keeps a
    # no-op field edit a no-op while still rescheduling on a genuine change.
    recurrence_changed = any(
        key in updates and merged.get(key) != existing.get(key)
        for key in recurrence_keys
    )
    if new_type not in (REC_TRIGGERED, REC_SENSOR) and recurrence_changed:
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
