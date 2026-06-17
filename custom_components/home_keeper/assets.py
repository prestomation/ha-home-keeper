"""Asset (appliance) model helpers for Home Keeper.

An *asset* is a physical thing you keep — a fridge, a furnace, an under-sink RO
unit — that maintenance tasks (and, later, batteries / other metadata) hang off
of. Like tasks, an asset is stored as a plain JSON-serializable ``dict`` so it
round-trips through HA's ``Store`` and the websocket/service APIs untouched.

Concerns living in one record (see ``IDEAS.md`` / ``docs/DESIGN.md``):

1. **Virtual-device provision** — when an appliance has no Home Assistant device
   to attach to, Home Keeper registers a real registry device for it
   (``kind == "virtual"``). Its registry identifier is
   ``(DOMAIN, f"{ASSET_IDENTIFIER_PREFIX}_{asset_id}")`` so it never collides with
   the per-task self-owned devices, which key on the bare task id.
2. **Asset metadata** — descriptive/temporal attributes (purchase/install/warranty
   dates, cost, vendor, manual link, notes) that can also enrich an *existing*
   device from another integration (``kind == "existing"``), without owning it.
3. **Parts / wear items** — a structured list of components (filters, bulbs, anode
   rods, shade material). A ``wear`` part with a replacement interval drives a
   maintenance task elsewhere (see ``store.reconcile_part_tasks``).
4. **Relationships** — ``parent_asset_id`` makes a virtual asset a *subdevice* of
   another virtual asset (native ``via_device`` hierarchy); ``related_device_ids``
   loosely associates arbitrary registry devices (including foreign ones HA won't
   let us reparent), surfaced only in the panel.

This module imports nothing from Home Assistant so it stays unit-testable; HA
specifics (the current time, the area/device registries) are injected or validated
by the caller.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Any

from .const import (
    ASSET_IDENTIFIER_PREFIX,
    ASSET_KIND_VIRTUAL,
    ASSET_KINDS,
    DOMAIN,
    MAX_INTERVAL,
    PART_CONSUMABLE,
    PART_TYPES,
    UNITS,
)


class AssetValidationError(ValueError):
    """Raised when asset input fails validation."""


# Free-form descriptive metadata stored verbatim (purely informational — these are
# *not* surfaced as entities, only shown in the panel / device page context).
# ``manual_url`` and ``icon`` are handled separately (validated).
_TEXT_FIELDS = (
    "manufacturer",
    "model",
    "serial_number",
    "warranty_provider",
    "vendor",
    "notes",
)

# Date metadata. Each that is set becomes a real ``date`` sensor on the asset's
# device page (so e.g. "warranty expiring in 30 days -> notify" works natively).
DATE_FIELDS = (
    "manufacture_date",
    "purchase_date",
    "install_date",
    "warranty_expiry",
)

_MAX_URL_LEN = 2048
_ICON_RE = re.compile(r"^[a-z0-9-]+:[a-z0-9-]+$")


def _require(data: dict, key: str) -> Any:
    if key not in data or data[key] in (None, ""):
        raise AssetValidationError(f"missing required field: {key!r}")
    return data[key]


def asset_device_identifier(asset_id: str) -> tuple[str, str]:
    """Registry identifier for a virtual asset device.

    Prefixed so it never collides with a per-task self-owned device, which keys on
    the bare task id ``(DOMAIN, task_id)``.
    """
    return (DOMAIN, f"{ASSET_IDENTIFIER_PREFIX}_{asset_id}")


def _normalize_date(value: Any, field: str) -> str | None:
    """Validate and normalize a metadata date to an ISO ``YYYY-MM-DD`` string."""
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    text = str(value)
    # Accept a full datetime too (panel may send one) but store just the date.
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except (TypeError, ValueError) as err:
        raise AssetValidationError(
            f"invalid date for {field!r}: {value!r} (expected YYYY-MM-DD)"
        ) from err


def _normalize_cost(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        cost = float(value)
    except (TypeError, ValueError) as err:
        raise AssetValidationError("cost must be a number") from err
    if cost < 0:
        raise AssetValidationError("cost must not be negative")
    return cost


def _normalize_url(value: Any) -> str:
    """Validate a manual/docs URL: empty, or an http(s) URL within a size bound."""
    if value in (None, ""):
        return ""
    text = str(value).strip()
    if len(text) > _MAX_URL_LEN:
        raise AssetValidationError("manual_url is too long")
    scheme = text.split("://", 1)[0].lower() if "://" in text else ""
    if scheme not in ("http", "https"):
        raise AssetValidationError("manual_url must be an http(s) URL")
    return text


def _normalize_icon(value: Any) -> str:
    """Validate an optional MDI-style icon (e.g. ``mdi:piano``); empty allowed."""
    if value in (None, ""):
        return ""
    text = str(value).strip().lower()
    if not _ICON_RE.match(text):
        raise AssetValidationError("icon must look like 'mdi:name'")
    return text


def _normalize_interval(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        interval = int(value)
    except (TypeError, ValueError) as err:
        raise AssetValidationError("replace_interval must be an integer") from err
    if interval < 1:
        raise AssetValidationError("replace_interval must be >= 1")
    if interval > MAX_INTERVAL:
        raise AssetValidationError(f"replace_interval must be <= {MAX_INTERVAL}")
    return interval


def _normalize_stock(value: Any, field: str) -> int | None:
    """Validate an optional non-negative spare-count (``stock`` / ``reorder_at``)."""
    if value in (None, ""):
        return None
    try:
        count = int(value)
    except (TypeError, ValueError) as err:
        raise AssetValidationError(f"{field} must be an integer") from err
    if count < 0:
        raise AssetValidationError(f"{field} must not be negative")
    if count > MAX_INTERVAL:
        raise AssetValidationError(f"{field} must be <= {MAX_INTERVAL}")
    return count


def _normalize_part(raw: Any) -> dict:
    """Validate and normalize a single part dict.

    Backend-managed fields (``id``, ``last_replaced``) are preserved when present so
    a round-trip through the panel doesn't drop them; :func:`_merge_parts` reconciles
    them against the stored record.
    """
    if not isinstance(raw, dict):
        raise AssetValidationError("each part must be an object")
    name = str(raw.get("name", "")).strip()
    if not name:
        raise AssetValidationError("part name must not be empty")
    ptype = raw.get("type", PART_CONSUMABLE)
    if ptype not in PART_TYPES:
        raise AssetValidationError(f"invalid part type: {ptype!r}")

    part: dict[str, Any] = {
        "id": str(raw.get("id") or uuid.uuid4()),
        "name": name,
        "part_number": str(raw.get("part_number", "")).strip(),
        "type": ptype,
        "vendor": str(raw.get("vendor", "")).strip(),
        "cost": _normalize_cost(raw.get("cost")),
        "notes": str(raw.get("notes", "")).strip(),
        # Replacement cadence (only meaningful for wear items — drives a task).
        "replace_interval": _normalize_interval(raw.get("replace_interval")),
        "replace_unit": None,
        "last_replaced": _normalize_date(raw.get("last_replaced"), "last_replaced"),
        # Spare-inventory tracking. ``stock`` is how many spares are on hand
        # (decremented when a wear-part replacement is completed); ``reorder_at``
        # is the low-stock threshold that, when reached, fires a low-stock event.
        # Both are optional — a part without ``stock`` simply isn't tracked.
        "stock": _normalize_stock(raw.get("stock"), "stock"),
        "reorder_at": _normalize_stock(raw.get("reorder_at"), "reorder_at"),
    }
    if part["replace_interval"] is not None:
        unit = raw.get("replace_unit") or "months"
        if unit not in UNITS:
            raise AssetValidationError(f"invalid replace_unit: {unit!r}")
        part["replace_unit"] = unit
    # A future "last replaced" would push the derived maintenance task far out and
    # silently hide it; it can only be a past (or today's) date.
    if part["last_replaced"] and date.fromisoformat(part["last_replaced"]) > date.today():
        raise AssetValidationError("last_replaced must not be in the future")
    return part


def _normalize_parts(value: Any) -> list[dict]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise AssetValidationError("parts must be a list")
    parts = [_normalize_part(p) for p in value]
    # Part ids must be unique: duplicates (from a misbehaving caller) would collapse
    # derived tasks onto one key and mis-stamp replacements. Regenerate collisions.
    seen: set[str] = set()
    for part in parts:
        if part["id"] in seen:
            part["id"] = str(uuid.uuid4())
        seen.add(part["id"])
    return parts


def _merge_parts(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Carry the stored ``last_replaced`` across an edit when the caller omits it.

    The panel can seed ``last_replaced`` when adding a wear item (so the derived
    maintenance task starts from the real date), but it is also stamped automatically
    on completion. To avoid a parts round-trip that doesn't re-send it clobbering that
    completion history, for parts that already exist (matched by ``id``) we keep the
    stored value unless the caller explicitly set one. ``stock``/``reorder_at`` are
    ordinary user-editable fields — incoming wins, including a ``None`` that clears
    them — so they are intentionally *not* preserved here (otherwise stock tracking
    could never be switched back off).
    """
    by_id = {p["id"]: p for p in existing}
    merged: list[dict] = []
    for part in incoming:
        prior = by_id.get(part["id"])
        if prior and part.get("last_replaced") is None:
            part = {**part, "last_replaced": prior.get("last_replaced")}
        merged.append(part)
    return merged


def part_is_low(part: dict) -> bool:
    """True when a stock-tracked part is at or below its reorder threshold."""
    stock = part.get("stock")
    reorder = part.get("reorder_at")
    return stock is not None and reorder is not None and stock <= reorder


def consume_part_stock(part: dict) -> bool:
    """Decrement a part's on-hand ``stock`` by one (never below zero).

    A no-op for parts that don't track stock. Returns ``True`` only when this
    consumption *crosses* the part from not-low into low (edge-triggered), so the
    caller emits one low-stock signal per crossing rather than on every step while
    already low.
    """
    stock = part.get("stock")
    if stock is None:
        return False
    was_low = part_is_low(part)
    part["stock"] = max(0, int(stock) - 1)
    return part_is_low(part) and not was_low


def adjust_part_stock(part: dict, delta: int) -> bool:
    """Adjust a part's on-hand ``stock`` by ``delta`` (clamped at zero).

    Begins tracking from zero for a previously untracked part. Returns ``True`` only
    when the adjustment *crosses* the part from not-low into low (edge-triggered); a
    restock, or a decrease while already low, returns ``False``.
    """
    was_low = part_is_low(part)
    current = part.get("stock") or 0
    part["stock"] = max(0, int(current) + int(delta))
    return part_is_low(part) and not was_low


def normalize_fields(data: dict) -> dict:
    """Validate and normalize the user-supplied fields of an asset.

    Returns only the descriptive/provisioning fields (no id / created / device_id /
    identifiers — those are assigned by :func:`build_asset` and the provisioning
    layer). ``kind`` defaults to ``virtual``.
    """
    kind = data.get("kind", ASSET_KIND_VIRTUAL)
    if kind not in ASSET_KINDS:
        raise AssetValidationError(f"invalid kind: {kind!r}")

    fields: dict[str, Any] = {"kind": kind, "area_id": data.get("area_id") or None}

    if kind == ASSET_KIND_VIRTUAL:
        # We own this device, so a name is required (it titles the device page).
        name = str(_require(data, "name")).strip()
        if not name:
            raise AssetValidationError("name must not be empty")
        fields["name"] = name
        # Only a device we own can be a native subdevice of another via via_device.
        fields["parent_asset_id"] = data.get("parent_asset_id") or None
    else:  # ASSET_KIND_EXISTING — metadata attached to someone else's device.
        # The device supplies its own name; we only need to know which device.
        fields["name"] = str(data.get("name", "")).strip()
        fields["device_id"] = _require(data, "device_id")
        fields["parent_asset_id"] = None

    for key in _TEXT_FIELDS:
        value = data.get(key)
        fields[key] = str(value).strip() if value not in (None, "") else ""

    fields["manual_url"] = _normalize_url(data.get("manual_url"))
    fields["icon"] = _normalize_icon(data.get("icon"))

    for key in DATE_FIELDS:
        fields[key] = _normalize_date(data.get(key), key)

    fields["cost"] = _normalize_cost(data.get("cost"))
    fields["parts"] = _normalize_parts(data.get("parts"))

    related = data.get("related_device_ids") or []
    if not isinstance(related, list):
        raise AssetValidationError("related_device_ids must be a list")
    fields["related_device_ids"] = [str(d) for d in related if d]
    return fields


def build_asset(data: dict, *, now: datetime) -> dict:
    """Create a brand-new asset dict (with id, created, and provisioning anchors)."""
    fields = normalize_fields(data)
    asset_id = str(uuid.uuid4())
    asset: dict[str, Any] = {
        "id": asset_id,
        "created": now.isoformat(),
        # device_id is the registry anchor: for an existing-device asset it is the
        # user-chosen target; for a virtual asset it is filled in once the device
        # is provisioned. identifiers/connections snapshot the device for
        # reconciliation when another integration recreates it under a new id.
        "device_id": fields.pop("device_id", None),
        "identifiers": [],
        "connections": [],
        **fields,
    }
    if asset["kind"] == ASSET_KIND_VIRTUAL:
        asset["identifiers"] = [list(asset_device_identifier(asset_id))]
    return asset


def merge_update(existing: dict, updates: dict, *, now: datetime) -> dict:
    """Return *existing* updated with *updates*, re-validating the whole record.

    ``kind`` and the virtual-device identifier are immutable after creation — an
    asset cannot switch between owning a device and decorating someone else's.
    """
    candidate: dict[str, Any] = {
        "kind": existing.get("kind", ASSET_KIND_VIRTUAL),
        "name": updates.get("name", existing.get("name")),
        "area_id": updates.get("area_id", existing.get("area_id")),
        "device_id": updates.get("device_id", existing.get("device_id")),
        "cost": updates.get("cost", existing.get("cost")),
        "icon": updates.get("icon", existing.get("icon")),
        "parent_asset_id": updates.get(
            "parent_asset_id", existing.get("parent_asset_id")
        ),
        "parts": updates.get("parts", existing.get("parts", [])),
        "related_device_ids": updates.get(
            "related_device_ids", existing.get("related_device_ids", [])
        ),
    }
    for key in (*_TEXT_FIELDS, "manual_url", *DATE_FIELDS):
        candidate[key] = updates.get(key, existing.get(key))

    fields = normalize_fields(candidate)
    # Preserve backend-managed part fields across the edit.
    if "parts" in updates:
        fields["parts"] = _merge_parts(existing.get("parts", []), fields["parts"])

    merged = dict(existing)
    # For a virtual asset, normalize_fields omits device_id, so the provisioned
    # device_id is preserved. For an existing-device asset it carries through the
    # (re-)chosen target. Either way the kind and virtual identifier are immutable.
    merged.update(fields)
    merged["kind"] = existing.get("kind", ASSET_KIND_VIRTUAL)
    return merged


def migrate_legacy_part_numbers(asset: dict) -> bool:
    """Convert a pre-parts ``part_numbers`` string into a single consumable part.

    Returns ``True`` if the asset was changed (so the caller persists it). Keeps the
    storage document backward-compatible without a version bump.
    """
    if "parts" in asset and asset["parts"] is not None:
        legacy = asset.pop("part_numbers", None)
        if legacy:  # both present: fold legacy in, then drop it
            asset["parts"] = [*asset["parts"], _legacy_part(legacy)]
            return True
        return False
    legacy = asset.pop("part_numbers", None)
    asset["parts"] = [_legacy_part(legacy)] if legacy else []
    return True


def _legacy_part(text: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": str(text).strip(),
        "part_number": "",
        "type": PART_CONSUMABLE,
        "vendor": "",
        "cost": None,
        "notes": "",
        "replace_interval": None,
        "replace_unit": None,
        "last_replaced": None,
    }


# ── task ↔ appliance association & completion-history retention ───────────────
# These pure helpers answer "which tasks belong to this appliance" and preserve a
# deleted task's completion history on its appliance. The retention rule is
# reference-counting: a task's history outlives the task only while an appliance
# still references it (a part-derived, device-attached, or related-device task). A
# standalone task's history is dropped with it, and deleting an appliance drops the
# archive with it (it is a field on the asset record).


def _part_asset_id(task: dict) -> str | None:
    """Return the asset id a part-derived task is sourced from, or None."""
    source = task.get("source")
    if isinstance(source, dict):
        part = source.get("part")
        if isinstance(part, dict):
            return part.get("asset_id")
    return None


def task_relates_to_asset(task: dict, asset: dict) -> bool:
    """True when *task* is associated with *asset*.

    A task belongs to an appliance when it is derived from one of the appliance's
    wear parts, attached to the appliance's device, or attached to a device the
    appliance lists as related.
    """
    if _part_asset_id(task) == asset.get("id"):
        return True
    device_id = task.get("device_id")
    if not device_id:
        return False
    if asset.get("device_id") and device_id == asset["device_id"]:
        return True
    return device_id in (asset.get("related_device_ids") or [])


def tasks_for_asset(asset: dict, tasks: list[dict]) -> list[dict]:
    """Every task associated with *asset* (see :func:`task_relates_to_asset`)."""
    return [task for task in tasks if task_relates_to_asset(task, asset)]


def find_archiving_asset(
    assets_by_id: dict[str, dict], task: dict
) -> dict | None:
    """The asset a deleted *task*'s history should be preserved on, or None.

    Precedence: the part-source appliance (the strong, explicit link) first, then
    the first appliance that owns or relates to the task's device. Returns None for
    a standalone task — its history is dropped on delete.
    """
    part_asset = assets_by_id.get(_part_asset_id(task) or "")
    if part_asset is not None:
        return part_asset
    device_id = task.get("device_id")
    if device_id:
        for asset in assets_by_id.values():
            if asset.get("device_id") == device_id or device_id in (
                asset.get("related_device_ids") or []
            ):
                return asset
    return None


def build_archived_history(task: dict, *, archived_at: str) -> dict:
    """A ``task_history`` entry snapshotting a deleted task's completions.

    The task name and part id are snapshotted so the appliance view still reads
    correctly after the task (and possibly its wear part) is gone.
    """
    source = task.get("source")
    part_id = None
    if isinstance(source, dict) and isinstance(source.get("part"), dict):
        part_id = source["part"].get("part_id")
    return {
        "task_id": task.get("id"),
        "task_name": task.get("name"),
        "part_id": part_id,
        "completions": list(task.get("completions", [])),
        "archived_at": archived_at,
    }


def append_task_history(asset: dict, entry: dict) -> bool:
    """Append history *entry* to *asset*'s ``task_history`` (in place).

    Skips an entry with no completions (nothing worth preserving) and a duplicate
    of an already-archived task id. Returns ``True`` when the asset was changed.
    """
    if not entry.get("completions"):
        return False
    history = asset.setdefault("task_history", [])
    if any(e.get("task_id") == entry.get("task_id") for e in history):
        return False
    history.append(entry)
    return True


def remove_archived_completion(asset: dict, task_id: str, ts: str) -> bool:
    """Remove a single archived completion (ISO *ts*) from *asset*'s history.

    Targets the ``task_history`` entry for *task_id* and drops the first completion
    matching *ts*; if that empties the entry, the entry is removed entirely. Mutates
    *asset* in place and returns ``True`` when something changed.
    """
    history = asset.get("task_history") or []
    for index, entry in enumerate(history):
        if entry.get("task_id") != task_id:
            continue
        completions = list(entry.get("completions", []))
        for i, completion in enumerate(completions):
            if completion.get("ts") == ts:
                del completions[i]
                if completions:
                    history[index] = {**entry, "completions": completions}
                else:
                    del history[index]
                asset["task_history"] = history
                return True
        return False
    return False


def would_create_cycle(
    assets_by_id: dict[str, dict], asset_id: str, parent_asset_id: str | None
) -> bool:
    """True if setting *parent_asset_id* on *asset_id* would form a parent cycle."""
    seen = {asset_id}
    cursor = parent_asset_id
    while cursor:
        if cursor in seen:
            return True
        seen.add(cursor)
        parent = assets_by_id.get(cursor)
        cursor = parent.get("parent_asset_id") if parent else None
    return False
