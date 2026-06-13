"""Asset (appliance) model helpers for Home Keeper.

An *asset* is a physical thing you keep — a fridge, a furnace, an under-sink RO
unit — that maintenance tasks (and, later, batteries / other metadata) hang off
of. Like tasks, an asset is stored as a plain JSON-serializable ``dict`` so it
round-trips through HA's ``Store`` and the websocket/service APIs untouched.

Two **decoupled** concerns live in one record (see ``IDEAS.md`` / ``docs/DESIGN.md``):

1. **Virtual-device provision** — when an appliance has no Home Assistant device
   to attach to, Home Keeper registers a real registry device for it
   (``kind == "virtual"``). Its registry identifier is
   ``(DOMAIN, f"{ASSET_IDENTIFIER_PREFIX}_{asset_id}")`` so it never collides with
   the per-task self-owned devices, which key on the bare task id.
2. **Asset metadata** — descriptive/temporal attributes (purchase/install/warranty
   dates, cost, vendor, manual link, consumable part numbers, notes) that can also
   enrich an *existing* device from another integration (``kind == "existing"``),
   without Home Keeper owning that device.

This module imports nothing from Home Assistant so it stays unit-testable; HA
specifics (the current time) are injected by the caller.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from .const import (
    ASSET_IDENTIFIER_PREFIX,
    ASSET_KIND_VIRTUAL,
    ASSET_KINDS,
    DOMAIN,
)


class AssetValidationError(ValueError):
    """Raised when asset input fails validation."""


# Free-form descriptive metadata stored verbatim (purely informational — these are
# *not* surfaced as entities, only shown in the panel / device page context).
# ``manual_url`` is handled separately (scheme/length validated).
_TEXT_FIELDS = (
    "manufacturer",
    "model",
    "serial_number",
    "warranty_provider",
    "vendor",
    "part_numbers",
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


# Upper bound on stored URLs/text-ish fields to keep the JSON document sane and to
# blunt pathological inputs that might later be surfaced in other contexts.
_MAX_URL_LEN = 2048


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
    else:  # ASSET_KIND_EXISTING — metadata attached to someone else's device.
        # The device supplies its own name; we only need to know which device.
        fields["name"] = str(data.get("name", "")).strip()
        fields["device_id"] = _require(data, "device_id")

    for key in _TEXT_FIELDS:
        value = data.get(key)
        fields[key] = str(value).strip() if value not in (None, "") else ""

    fields["manual_url"] = _normalize_url(data.get("manual_url"))

    for key in DATE_FIELDS:
        fields[key] = _normalize_date(data.get(key), key)

    fields["cost"] = _normalize_cost(data.get("cost"))
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
    }
    for key in (*_TEXT_FIELDS, "manual_url", *DATE_FIELDS):
        candidate[key] = updates.get(key, existing.get(key))

    fields = normalize_fields(candidate)
    merged = dict(existing)
    # For a virtual asset, normalize_fields omits device_id, so the provisioned
    # device_id is preserved. For an existing-device asset it carries through the
    # (re-)chosen target. Either way the kind and virtual identifier are immutable.
    merged.update(fields)
    merged["kind"] = existing.get("kind", ASSET_KIND_VIRTUAL)
    return merged
