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


# Structured text fields kept verbatim. These are special: they sync into the Home
# Assistant device registry (they title/brand/identify the device card —
# ``manufacturer``/``model`` and ``serial_number`` map onto the matching ``DeviceInfo``
# fields), so they stay first-class rather than folding into the free-form ``metadata``
# list below. ``icon`` and ``cost`` (-> the inventory value rollup) are likewise
# structured but validated separately, as is the ``documents`` list below.
_TEXT_FIELDS = (
    "manufacturer",
    "model",
    "serial_number",
)

# Free-form metadata: an ordered list of typed entries the user can shape however
# they like (serial numbers, warranty/purchase/install dates, provider, links…),
# replacing the old prescriptive per-field set. Each entry is
# ``{id, type, label, value[, track]}``. A ``date`` entry with ``track`` set becomes
# a real ``date`` sensor on the asset's device page (so e.g. "warranty expiring in
# 30 days -> notify" still works natively, but only for dates you opt in to track).
METADATA_TYPES = ("text", "link", "date")

# Per-asset documents: an ordered list of manuals / warranties / receipts. Each entry
# is EITHER an external ``link`` (an http(s) ``url``) OR an uploaded ``file`` stored on
# disk and served back through the document HTTP view. For a ``file`` entry the binary
# lives under the config dir (see ``manuals.py``); the record only carries the metadata
# (``filename``/``content_type``/``size``) needed to locate and serve it. Each entry is
# ``{id, kind, name, created[, url | filename, content_type, size]}``.
DOCUMENT_KINDS = ("link", "file")
_ALLOWED_DOC_CONTENT_TYPES = frozenset(
    {"application/pdf", "image/png", "image/jpeg", "image/webp", "image/gif"}
)
_MAX_DOC_NAME_LEN = 200
# Bound the per-asset documents list (the whole asset map is one JSON document that's
# rewritten on every save, and each file can be up to MAX_DOCUMENT_BYTES on disk).
_MAX_DOCUMENTS = 50

_MAX_URL_LEN = 2048
_ICON_RE = re.compile(r"^[a-z0-9-]+:[a-z0-9-]+$")


def _is_safe_basename(name: str) -> bool:
    """True when *name* is a plain filename (no path separators or traversal)."""
    return bool(name) and name not in (".", "..") and not re.search(r"[/\\]", name)


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


def _normalize_http_url(value: Any, field: str) -> str:
    """Validate an http(s) URL: empty allowed, else http(s) within a size bound."""
    if value in (None, ""):
        return ""
    text = str(value).strip()
    if len(text) > _MAX_URL_LEN:
        raise AssetValidationError(f"{field} is too long")
    scheme = text.split("://", 1)[0].lower() if "://" in text else ""
    if scheme not in ("http", "https"):
        raise AssetValidationError(f"{field} must be an http(s) URL")
    return text


def _normalize_metadata(value: Any) -> list[dict]:
    """Validate and normalize the free-form ``metadata`` list.

    Each entry is ``{id, type, label, value[, track]}``. ``label`` is required;
    ``value`` is validated per type (date -> ISO ``YYYY-MM-DD``, link -> http(s)
    URL, text -> verbatim). ``track`` is only meaningful for a ``date`` entry (it
    opts that date into a tracked sensor). Entry ids are unique — collisions from
    a misbehaving caller are regenerated.
    """
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise AssetValidationError("metadata must be a list")
    entries = [_normalize_metadata_entry(entry) for entry in value]
    seen: set[str] = set()
    for entry in entries:
        if entry["id"] in seen:
            entry["id"] = str(uuid.uuid4())
        seen.add(entry["id"])
    return entries


def _normalize_metadata_entry(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise AssetValidationError("each metadata entry must be an object")
    mtype = raw.get("type", "text")
    if mtype not in METADATA_TYPES:
        raise AssetValidationError(f"invalid metadata type: {mtype!r}")
    label = str(raw.get("label", "")).strip()
    if not label:
        raise AssetValidationError("metadata label must not be empty")
    entry: dict[str, Any] = {
        "id": str(raw.get("id") or uuid.uuid4()),
        "type": mtype,
        "label": label,
    }
    if mtype == "date":
        entry["value"] = _normalize_date(raw.get("value"), label) or ""
        entry["track"] = bool(raw.get("track"))
    elif mtype == "link":
        entry["value"] = _normalize_http_url(raw.get("value"), label)
    else:
        entry["value"] = str(raw.get("value", "")).strip()
    return entry


def _normalize_documents(value: Any) -> list[dict]:
    """Validate and normalize the per-asset ``documents`` list.

    Each entry is ``{id, kind, name, created[, url | filename, content_type, size]}``.
    A ``link`` carries an http(s) ``url``; a ``file`` carries backend-managed
    ``filename``/``content_type``/``size`` for the on-disk blob. Entry ids are unique
    — collisions from a misbehaving caller are regenerated.
    """
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise AssetValidationError("documents must be a list")
    if len(value) > _MAX_DOCUMENTS:
        raise AssetValidationError(
            f"an appliance can have at most {_MAX_DOCUMENTS} documents"
        )
    entries = [_normalize_document_entry(entry) for entry in value]
    seen: set[str] = set()
    for entry in entries:
        if entry["id"] in seen:
            entry["id"] = str(uuid.uuid4())
        seen.add(entry["id"])
    return entries


def _normalize_document_entry(raw: Any) -> dict:
    """Validate a single document entry (a link or an uploaded file).

    ``created`` is backend-managed (stamped by the store on add) and preserved
    verbatim when present. ``filename``/``content_type``/``size`` are likewise
    backend-managed — the binary itself is validated by ``manuals.validate_upload``
    at upload time; here we only enforce a safe basename and the type allowlist so a
    crafted ``file`` entry can't escape the storage root.
    """
    if not isinstance(raw, dict):
        raise AssetValidationError("each document must be an object")
    kind = raw.get("kind", "link")
    if kind not in DOCUMENT_KINDS:
        raise AssetValidationError(f"invalid document kind: {kind!r}")
    name = str(raw.get("name", "")).strip()
    if len(name) > _MAX_DOC_NAME_LEN:
        raise AssetValidationError("document name is too long")
    entry: dict[str, Any] = {
        "id": str(raw.get("id") or uuid.uuid4()),
        "kind": kind,
        "created": str(raw.get("created") or ""),
    }
    if kind == "link":
        entry["url"] = _normalize_http_url(raw.get("url"), "document url")
        # A link with no name falls back to its host so the panel never renders blank.
        entry["name"] = name or _url_host(entry["url"])
    else:  # file
        filename = str(raw.get("filename", "")).strip()
        if not _is_safe_basename(filename):
            raise AssetValidationError("document filename is invalid")
        content_type = str(raw.get("content_type", "")).strip().lower()
        if content_type not in _ALLOWED_DOC_CONTENT_TYPES:
            raise AssetValidationError(f"unsupported document type: {content_type!r}")
        size = raw.get("size")
        if size is None or size == "":
            entry["size"] = 0
        else:
            try:
                entry["size"] = max(0, int(size))
            except (TypeError, ValueError) as err:
                raise AssetValidationError("document size must be an integer") from err
        entry["filename"] = filename
        entry["content_type"] = content_type
        entry["name"] = name or filename
    return entry


def _url_host(url: str) -> str:
    """Best-effort host of an http(s) URL for a fallback document name."""
    rest = url.split("://", 1)[-1]
    return rest.split("/", 1)[0] or url


def _merge_documents(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Reconcile a generic asset write's ``documents`` against the stored list.

    ``file`` documents own an on-disk blob, so they are **upload-only**: managed solely
    by the upload view and the ``*_asset_document`` services, never by the generic
    ``add_asset`` / ``update_asset`` write. This keeps the two in sync — a generic
    write can't inject a phantom ``file`` entry (no blob behind it) and, by always
    carrying the stored ``file`` entries through, can't orphan a blob by omitting one.
    The generic write therefore controls only the ``link`` documents.
    """
    files = [d for d in existing if d.get("kind") == "file"]
    links = [d for d in incoming if d.get("kind") == "link"]
    return [*files, *links]


def append_document(asset: dict, raw: Any, *, created: str) -> dict:
    """Validate *raw* as a new document and append it to *asset* (in place).

    *created* is the ISO timestamp the store stamps on add (this module is HA-free
    and has no clock). Returns the appended entry. A colliding id is regenerated so
    the documents list stays uniquely keyed.
    """
    documents = asset.get("documents")
    if not isinstance(documents, list):
        documents = []
    if len(documents) >= _MAX_DOCUMENTS:
        raise AssetValidationError(
            f"an appliance can have at most {_MAX_DOCUMENTS} documents"
        )
    entry = _normalize_document_entry({**raw, "created": created})
    if entry["id"] in {d.get("id") for d in documents}:
        entry["id"] = str(uuid.uuid4())
    documents.append(entry)
    asset["documents"] = documents
    return entry


def remove_document(asset: dict, document_id: str) -> dict | None:
    """Remove the document with *document_id* from *asset* (in place).

    Returns the removed entry (so the caller can delete its on-disk blob), or
    ``None`` when no such document exists.
    """
    documents = asset.get("documents") or []
    for index, document in enumerate(documents):
        if document.get("id") == document_id:
            removed = documents.pop(index)
            asset["documents"] = documents
            return removed
    return None


def update_document(asset: dict, document_id: str, changes: Any) -> dict | None:
    """Edit an existing document in place; return the updated entry or ``None``.

    A ``link`` can change its ``name`` and ``url``; a ``file`` is upload-only so only
    its display ``name`` is editable (its blob/filename/type are immutable here — to
    replace the file, remove it and upload again). The entry is re-validated, its
    ``id``/``kind``/``created`` preserved. ``None`` when no such document exists.
    """
    if not isinstance(changes, dict):
        raise AssetValidationError("document changes must be an object")
    documents = asset.get("documents") or []
    for index, document in enumerate(documents):
        if document.get("id") != document_id:
            continue
        merged = dict(document)
        if "name" in changes:
            merged["name"] = changes["name"]
        if document.get("kind") == "link" and "url" in changes:
            merged["url"] = changes["url"]
        updated = _normalize_document_entry(merged)
        documents[index] = updated
        asset["documents"] = documents
        return updated
    return None


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


def _normalize_part(raw: Any, *, today: date | None = None) -> dict:
    """Validate and normalize a single part dict.

    Backend-managed fields (``id``, ``last_replaced``) are preserved when present so
    a round-trip through the panel doesn't drop them; :func:`_merge_parts` reconciles
    them against the stored record. *today* is the injected clock the public entry
    points thread down (so ``last_replaced`` is validated against Home Assistant's
    timezone, not the process wall clock); it falls back to ``date.today()`` only when
    an internal caller omits it. ``file_name``/``file_content_type``/``file_size``
    (a part's single attached file) are deliberately **not** read from *raw* here —
    like an asset's ``file`` documents, they are upload-only and settable solely via
    :func:`set_part_file`/:func:`clear_part_file`; :func:`_merge_parts` always restores
    them from the stored part so a generic edit can neither inject nor drop them.
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
        "url": _normalize_http_url(raw.get("url"), "part url"),
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
        # Upload-only; see the docstring. Always absent here — _merge_parts restores
        # the stored values (or set_part_file/clear_part_file set them directly).
        "file_name": None,
        "file_content_type": None,
        "file_size": None,
    }
    if part["replace_interval"] is not None:
        unit = raw.get("replace_unit") or "months"
        if unit not in UNITS:
            raise AssetValidationError(f"invalid replace_unit: {unit!r}")
        part["replace_unit"] = unit
    # A future "last replaced" would push the derived maintenance task far out and
    # silently hide it; it can only be a past (or today's) date.
    if part["last_replaced"] and date.fromisoformat(part["last_replaced"]) > (
        today or date.today()
    ):
        raise AssetValidationError("last_replaced must not be in the future")
    return part


def _normalize_parts(value: Any, *, today: date | None = None) -> list[dict]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise AssetValidationError("parts must be a list")
    parts = [_normalize_part(p, today=today) for p in value]
    # Part ids must be unique: duplicates (from a misbehaving caller) would collapse
    # derived tasks onto one key and mis-stamp replacements. Regenerate collisions.
    seen: set[str] = set()
    for part in parts:
        if part["id"] in seen:
            part["id"] = str(uuid.uuid4())
        seen.add(part["id"])
    return parts


def _merge_parts(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Carry the stored ``last_replaced`` and attached-file fields across an edit.

    The panel can seed ``last_replaced`` when adding a wear item (so the derived
    maintenance task starts from the real date), but it is also stamped automatically
    on completion. To avoid a parts round-trip that doesn't re-send it clobbering that
    completion history, for parts that already exist (matched by ``id``) we keep the
    stored value unless the caller explicitly set one. ``stock``/``reorder_at`` are
    ordinary user-editable fields — incoming wins, including a ``None`` that clears
    them — so they are intentionally *not* preserved here (otherwise stock tracking
    could never be switched back off).

    ``file_name``/``file_content_type``/``file_size`` are **always** restored from the
    stored part, unconditionally — like an asset's ``file`` documents, a part's
    attached file is upload-only (see :func:`set_part_file`) and must never be
    settable through a generic write, so incoming values for these three keys (which
    ``_normalize_part`` never actually produces) are ignored outright.
    """
    by_id = {p["id"]: p for p in existing}
    merged: list[dict] = []
    for part in incoming:
        prior = by_id.get(part["id"])
        if prior and part.get("last_replaced") is None:
            part = {**part, "last_replaced": prior.get("last_replaced")}
        if prior:
            part = {
                **part,
                "file_name": prior.get("file_name"),
                "file_content_type": prior.get("file_content_type"),
                "file_size": prior.get("file_size"),
            }
        merged.append(part)
    return merged


def set_part_file(asset: dict, part_id: str, file_meta: dict) -> dict | None:
    """Attach (or replace) *part_id*'s single file, in place; return the updated part.

    *file_meta* is ``{filename, content_type, size}`` (already validated/sniffed by
    the caller — see ``manuals.HomeKeeperPartFileView``). Returns ``None`` when no
    such part exists.
    """
    parts = asset.get("parts") or []
    for index, part in enumerate(parts):
        if part.get("id") != part_id:
            continue
        updated = {
            **part,
            "file_name": file_meta["filename"],
            "file_content_type": file_meta["content_type"],
            "file_size": file_meta["size"],
        }
        parts[index] = updated
        asset["parts"] = parts
        return updated
    return None


def clear_part_file(asset: dict, part_id: str) -> dict | None:
    """Detach *part_id*'s file, in place; return its *prior* file fields.

    The caller uses the returned ``filename`` to delete the on-disk blob. Returns
    ``None`` when no such part exists or it had no attached file.
    """
    parts = asset.get("parts") or []
    for index, part in enumerate(parts):
        if part.get("id") != part_id:
            continue
        if not part.get("file_name"):
            return None
        prior = {
            "filename": part.get("file_name"),
            "content_type": part.get("file_content_type"),
            "size": part.get("file_size"),
        }
        parts[index] = {
            **part,
            "file_name": None,
            "file_content_type": None,
            "file_size": None,
        }
        asset["parts"] = parts
        return prior
    return None


def part_tracks_stock(part: dict) -> bool:
    """True when a part carries an on-hand spare count (gets a stock ``number``).

    ``stock`` is the single signal that the user opted this part into inventory
    tracking; a part without it simply isn't counted (and gets no stock entity).
    """
    return part.get("stock") is not None


def part_has_reorder(part: dict) -> bool:
    """True when a stock-tracked part also has a reorder threshold.

    Such a part gets a low-stock ``binary_sensor`` (its on/off state is
    :func:`part_is_low`); both ``stock`` and ``reorder_at`` must be set for the
    comparison to mean anything.
    """
    return part.get("stock") is not None and part.get("reorder_at") is not None


def part_is_low(part: dict) -> bool:
    """True when a stock-tracked part is at or below its reorder threshold."""
    stock = part.get("stock")
    reorder = part.get("reorder_at")
    return stock is not None and reorder is not None and stock <= reorder


# Stock-change outcomes, returned by ``stock_transition`` / ``consume_part_stock`` /
# ``adjust_part_stock``. Each maps to one bus event (or none); see store.py.
STOCK_NONE = "none"
STOCK_LOW = "low"
STOCK_OUT = "out"
STOCK_RESTOCKED = "restocked"


def stock_transition(old: int, new: int, reorder_at: int | None) -> str:
    """Classify a stock change from *old* to *new* as a single edge transition.

    Returns one of ``"none" | "low" | "out" | "restocked"``. This is the pure core
    behind the edge-triggered stock events: it fires once *per crossing* rather than on
    every step. Precedence matters — ``"out"`` (reaching zero) wins over ``"low"`` so a
    single decrement that drops an already-low part to zero is reported as out-of-stock,
    not a (repeat) low-stock. A part with no ``reorder_at`` threshold is untracked and
    never transitions.
    """
    if reorder_at is None:
        return STOCK_NONE
    if new == 0 and old > 0:
        return STOCK_OUT
    if new <= reorder_at and old > reorder_at:
        return STOCK_LOW
    if new > reorder_at and old <= reorder_at:
        return STOCK_RESTOCKED
    return STOCK_NONE


def consume_part_stock(part: dict) -> str:
    """Decrement a part's on-hand ``stock`` by one (never below zero).

    A no-op (``STOCK_NONE``) for parts that don't track stock. Otherwise returns the
    edge transition (``stock_transition``) this consumption caused, so the caller emits
    at most one stock event per crossing rather than on every step while already low.
    """
    stock = part.get("stock")
    if stock is None:
        return STOCK_NONE
    old = int(stock)
    new = max(0, old - 1)
    part["stock"] = new
    return stock_transition(old, new, part.get("reorder_at"))


def adjust_part_stock(part: dict, delta: int) -> str:
    """Adjust a part's on-hand ``stock`` by ``delta`` (clamped at zero).

    Begins tracking from zero for a previously untracked part. Returns the edge
    transition (``stock_transition``) the adjustment caused — ``"low"`` / ``"out"`` on a
    decrease that crosses a threshold, ``"restocked"`` when a restock lifts it above
    the reorder point, else ``"none"``.
    """
    old = int(part.get("stock") or 0)
    new = max(0, old + int(delta))
    part["stock"] = new
    return stock_transition(old, new, part.get("reorder_at"))


def normalize_fields(data: dict, *, today: date | None = None) -> dict:
    """Validate and normalize the user-supplied fields of an asset.

    Returns only the descriptive/provisioning fields (no id / created / device_id /
    identifiers — those are assigned by :func:`build_asset` and the provisioning
    layer). ``kind`` defaults to ``virtual``. *today* is threaded through to the parts
    normalizer so ``last_replaced`` is validated against the injected clock (the public
    :func:`build_asset` / :func:`merge_update` entry points pass ``now.date()``).
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

    fields["documents"] = _normalize_documents(data.get("documents"))
    fields["icon"] = _normalize_icon(data.get("icon"))
    fields["metadata"] = _normalize_metadata(data.get("metadata"))
    fields["cost"] = _normalize_cost(data.get("cost"))
    fields["parts"] = _normalize_parts(data.get("parts"), today=today)

    related = data.get("related_device_ids") or []
    if not isinstance(related, list):
        raise AssetValidationError("related_device_ids must be a list")
    fields["related_device_ids"] = [str(d) for d in related if d]
    return fields


def build_asset(data: dict, *, now: datetime) -> dict:
    """Create a brand-new asset dict (with id, created, and provisioning anchors)."""
    fields = normalize_fields(data, today=now.date())
    # Files are upload-only (they own an on-disk blob, which a brand-new asset can't
    # have yet), so a create payload can only seed link documents.
    fields["documents"] = [d for d in fields["documents"] if d.get("kind") == "link"]
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
        "metadata": updates.get("metadata", existing.get("metadata", [])),
        "documents": updates.get("documents", existing.get("documents", [])),
        "related_device_ids": updates.get(
            "related_device_ids", existing.get("related_device_ids", [])
        ),
    }
    for key in _TEXT_FIELDS:
        candidate[key] = updates.get(key, existing.get(key))

    fields = normalize_fields(candidate, today=now.date())
    # Preserve backend-managed part fields across the edit.
    if "parts" in updates:
        fields["parts"] = _merge_parts(existing.get("parts", []), fields["parts"])
    # File documents are upload-only: a generic write controls only links, and always
    # carries the stored file documents through (see _merge_documents).
    if "documents" in updates:
        fields["documents"] = _merge_documents(
            existing.get("documents", []), fields["documents"]
        )
        # _normalize_documents caps only the *incoming* payload; _merge_documents then
        # prepends the stored file documents, so the merged total can exceed the cap.
        # Enforce it on the assembled result (mirrors append_document's merged cap).
        if len(fields["documents"]) > _MAX_DOCUMENTS:
            raise AssetValidationError(
                f"an appliance can have at most {_MAX_DOCUMENTS} documents"
            )

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


def migrate_documents_from_manual_url(asset: dict) -> bool:
    """Fold a legacy ``manual_url`` into the ``documents`` list.

    Returns ``True`` if the asset was changed (so the caller persists it). The old
    single manual link becomes one ``link`` document; ``manual_url`` is dropped. Keeps
    the storage document backward-compatible without a version bump, and guarantees
    every asset carries a ``documents`` list afterwards.
    """
    legacy = asset.pop("manual_url", None)
    changed = legacy is not None
    documents = asset.get("documents")
    if not isinstance(documents, list):
        documents = []
        changed = True
    if legacy:
        try:
            url = _normalize_http_url(legacy, "manual_url")
        except AssetValidationError:
            url = ""
        # Idempotent: only add when no existing document already points at this url.
        if url and not any(
            d.get("kind") == "link" and d.get("url") == url for d in documents
        ):
            documents = [
                *documents,
                {
                    "id": str(uuid.uuid4()),
                    "kind": "link",
                    "name": _url_host(url),
                    "url": url,
                    "created": "",
                },
            ]
    asset["documents"] = documents
    return changed


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


def find_archiving_asset(assets_by_id: dict[str, dict], task: dict) -> dict | None:
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
