"""On-disk storage and HTTP serving for uploaded asset documents.

Asset *documents* (manuals, warranties, receipts) can be either an external link or
an **uploaded file** kept locally so the manual works offline. The file bytes are too
large for the JSON store, so each upload is written to disk under the HA config dir and
streamed back through an authenticated :class:`HomeAssistantView` — the integration's
only HTTP view and its only non-websocket/​non-service mutation surface. The document
*metadata* (``filename``/``content_type``/``size``) still funnels through the store
(``store.add_asset_document``), which fires the ``home_keeper_asset_updated`` event.

Layout: ``<config>/home_keeper/documents/<asset_id>/<document_id>__<safe_filename>``.
One directory per asset, so deleting an asset is a single ``rmtree``.

Security posture: the binary is validated by magic-byte sniff against a small
allowlist (PDF + common images) and a hard size ceiling; every client-supplied id and
filename is sanitized and the resolved path is asserted to live under the storage root
(``documents.resolve_under_root``) so a crafted ``../`` can't escape it. Those pure
checks live in ``documents.py`` so they stay unit-testable without an HA runtime.
"""

from __future__ import annotations

import logging
import shutil
from http import HTTPStatus
from pathlib import Path
from typing import Any

from aiohttp import BodyPartReader, hdrs, web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import KEY_HASS

from . import documents
from .assets import AssetValidationError
from .const import (
    DOCUMENT_URL_PREFIX,
    DOMAIN,
    MANUALS_SUBDIR,
    MAX_DOCUMENT_BYTES,
    PART_FILE_URL_PREFIX,
)
from .documents import validate_upload

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "HomeKeeperDocumentView",
    "HomeKeeperPartFileView",
    "async_delete_part_file",
    "async_register_http",
    "validate_upload",
]


def _root(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(MANUALS_SUBDIR))


def _document_path(
    hass: HomeAssistant, asset_id: str, document_id: str, filename: str
) -> Path:
    return documents.document_path(_root(hass), asset_id, document_id, filename)


# ── blocking IO (run via the executor) ───────────────────────────────────────
def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _read(path: Path) -> bytes:
    return path.read_bytes()


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)


def _rmtree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


async def async_save_document(
    hass: HomeAssistant, asset_id: str, document_id: str, filename: str, data: bytes
) -> None:
    """Persist an uploaded document's bytes to disk."""
    path = _document_path(hass, asset_id, document_id, filename)
    await hass.async_add_executor_job(_write, path, data)


async def async_read_document(
    hass: HomeAssistant, asset_id: str, document_id: str, filename: str
) -> bytes:
    """Read an uploaded document's bytes from disk (raises ``FileNotFoundError``)."""
    path = _document_path(hass, asset_id, document_id, filename)
    return await hass.async_add_executor_job(_read, path)


async def async_delete_document(
    hass: HomeAssistant, asset_id: str, document_id: str, filename: str
) -> None:
    """Delete a single uploaded document's bytes (no-op if already gone)."""
    path = _document_path(hass, asset_id, document_id, filename)
    await hass.async_add_executor_job(_unlink, path)


async def async_delete_asset_documents(hass: HomeAssistant, asset_id: str) -> None:
    """Remove an asset's entire on-disk document directory."""
    path = documents.resolve_under_root(_root(hass), asset_id)
    await hass.async_add_executor_job(_rmtree, path)


def document_path(asset_id: str, document_id: str) -> str:
    """The view path for a file document (signed by the websocket command)."""
    return f"{DOCUMENT_URL_PREFIX}/{asset_id}/{document_id}"


def part_file_path(asset_id: str, part_id: str) -> str:
    """The view path for a part's attached file (signed by the websocket command)."""
    return f"{PART_FILE_URL_PREFIX}/{asset_id}/{part_id}"


def _part_document_id(part_id: str) -> str:
    """The on-disk storage key for a part's file.

    Deliberately distinct from a bare document id: asset documents and part files
    are two different lists but share one on-disk directory per asset
    (``<asset_id>/<key>__<filename>``), so this discriminator guarantees a part id
    can never collide with an unrelated document id in that shared namespace — even
    though both are random ids and a real collision is not practically reachable.
    Storage-internal only; the HTTP route and signed view path use the bare
    ``part_id`` (a separate namespace with no such collision risk).
    """
    return f"part_{part_id}"


async def async_save_part_file(
    hass: HomeAssistant, asset_id: str, part_id: str, filename: str, data: bytes
) -> None:
    """Persist a part's uploaded file bytes to disk."""
    await async_save_document(
        hass, asset_id, _part_document_id(part_id), filename, data
    )


async def async_read_part_file(
    hass: HomeAssistant, asset_id: str, part_id: str, filename: str
) -> bytes:
    """Read a part's uploaded file bytes from disk (raises ``FileNotFoundError``)."""
    return await async_read_document(
        hass, asset_id, _part_document_id(part_id), filename
    )


async def async_delete_part_file(
    hass: HomeAssistant, asset_id: str, part_id: str, filename: str
) -> None:
    """Delete a part's uploaded file bytes (no-op if already gone)."""
    await async_delete_document(hass, asset_id, _part_document_id(part_id), filename)


def _coordinator(hass: HomeAssistant) -> Any:
    """Locate the loaded Home Keeper coordinator (lazy import avoids a cycle)."""
    from .coordinator import HomeKeeperCoordinator

    for entry in hass.config_entries.async_entries(DOMAIN):
        coord = getattr(entry, "runtime_data", None)
        if isinstance(coord, HomeKeeperCoordinator):
            return coord
    return None


def _file_document(asset: dict[str, Any] | None, document_id: str) -> dict | None:
    for document in (asset or {}).get("documents", []):
        if document.get("id") == document_id and document.get("kind") == "file":
            return document
    return None


def _part_with_file(asset: dict[str, Any] | None, part_id: str) -> dict | None:
    for part in (asset or {}).get("parts", []):
        if part.get("id") == part_id and part.get("file_name"):
            return part
    return None


async def _parse_upload(
    view: HomeAssistantView, request: web.Request, *, want_name: bool = False
) -> tuple[bytes, str, str | None, str] | web.Response:
    """Parse a multipart upload's single file part, streamed with a size cap.

    Shared by :class:`HomeKeeperDocumentView` and :class:`HomeKeeperPartFileView` —
    both accept one file per request, over the same size ceiling. When *want_name*
    is set, a ``name`` text part is also captured (asset documents have a
    user-editable display name; a part's file doesn't). Returns ``(data, filename,
    declared_type, display_name)`` on success, or an early ``web.Response`` (bad
    request / too large) that the caller should return as-is.
    """
    too_large = view.json_message(
        f"File exceeds the {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB limit",
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    )
    try:
        reader = await request.multipart()
    except (ValueError, AssertionError):
        return view.json_message("Expected a multipart upload", HTTPStatus.BAD_REQUEST)

    display_name = ""
    filename: str | None = None
    declared_type: str | None = None
    data = b""
    try:
        while True:
            part = await reader.next()
            if part is None:
                break
            # A nested multipart body isn't expected here; only flat parts carry
            # the file/name fields (and narrows the type for the access below).
            if not isinstance(part, BodyPartReader):
                continue
            if want_name and part.name == "name":
                display_name = (await part.text()).strip()
                continue
            if not part.filename:
                continue
            filename = part.filename
            declared_type = part.headers.get(hdrs.CONTENT_TYPE)
            buffer = bytearray()
            while chunk := await part.read_chunk():
                buffer += chunk
                if len(buffer) > MAX_DOCUMENT_BYTES:
                    return too_large
            data = bytes(buffer)
    except web.HTTPRequestEntityTooLarge:
        # Backstop: aiohttp enforces the (raised) per-request cap too.
        return too_large

    if filename is None:
        return view.json_message("No file part in upload", HTTPStatus.BAD_REQUEST)
    return data, filename, declared_type, display_name


class HomeKeeperDocumentView(HomeAssistantView):
    """Upload (POST) and serve (GET) uploaded asset documents.

    GET is reachable via an ``async_sign_path`` signed URL so the panel can open a
    document in a new browser tab without setting an auth header.
    """

    url = DOCUMENT_URL_PREFIX + "/{asset_id}/{document_id}"
    name = "api:home_keeper:document"
    requires_auth = True

    async def get(
        self, request: web.Request, asset_id: str, document_id: str
    ) -> web.StreamResponse:
        hass = request.app[KEY_HASS]
        coord = _coordinator(hass)
        document = _file_document(
            coord.store.get_asset(asset_id) if coord else None, document_id
        )
        if document is None:
            return web.Response(status=HTTPStatus.NOT_FOUND)
        try:
            data = await async_read_document(
                hass, asset_id, document_id, document["filename"]
            )
        except (FileNotFoundError, AssetValidationError):
            return web.Response(status=HTTPStatus.NOT_FOUND)
        disposition = f'inline; filename="{document["filename"]}"'
        return web.Response(
            body=data,
            content_type=document.get("content_type") or "application/octet-stream",
            headers={hdrs.CONTENT_DISPOSITION: disposition},
        )

    async def post(
        self, request: web.Request, asset_id: str, document_id: str
    ) -> web.Response:
        hass = request.app[KEY_HASS]
        # Raise this request's body cap to our document ceiling. HA's global app limit
        # (`MAX_CLIENT_SIZE`, 16 MB) is *smaller* than MAX_DOCUMENT_BYTES, so without
        # this aiohttp rejects a larger upload with a bare 413 before our handler runs.
        # Mirrors homeassistant.components.image_upload. We still enforce the real
        # ceiling (with a clear message) while streaming below.
        request._client_max_size = MAX_DOCUMENT_BYTES
        coord = _coordinator(hass)
        if coord is None:
            return self.json_message("Home Keeper is not loaded", HTTPStatus.NOT_FOUND)
        if coord.store.get_asset(asset_id) is None:
            return self.json_message("Unknown asset", HTTPStatus.NOT_FOUND)

        parsed = await _parse_upload(self, request, want_name=True)
        if isinstance(parsed, web.Response):
            return parsed
        data, filename, declared_type, display_name = parsed
        try:
            content_type, safe_name = validate_upload(filename, declared_type, data)
        except AssetValidationError as err:
            return self.json_message(str(err), HTTPStatus.BAD_REQUEST)

        try:
            entry = await coord.store.add_asset_document(
                asset_id,
                {
                    "id": document_id,
                    "kind": "file",
                    "name": display_name,
                    "filename": safe_name,
                    "content_type": content_type,
                    "size": len(data),
                },
            )
        except (KeyError, AssetValidationError) as err:
            return self.json_message(str(err), HTTPStatus.BAD_REQUEST)
        try:
            await async_save_document(hass, asset_id, entry["id"], safe_name, data)
        except OSError as err:  # roll the metadata back if the disk write fails
            _LOGGER.error("Failed to write document for asset %s: %s", asset_id, err)
            await coord.store.remove_asset_document(asset_id, entry["id"])
            return self.json_message(
                "Failed to store the file", HTTPStatus.INTERNAL_SERVER_ERROR
            )
        # Documents touch neither the device registry nor any entity/task, so there's
        # no device reconcile or entry reload to do — the store already persisted and
        # fired ``home_keeper_asset_updated``.
        return self.json({"asset": coord.store.get_asset(asset_id), "document": entry})


class HomeKeeperPartFileView(HomeAssistantView):
    """Upload (POST) and serve (GET) a part's single attached file.

    A smaller sibling of :class:`HomeKeeperDocumentView`: a part has exactly one
    optional file slot (no link kind — that's the part's ``url`` field, and no list to
    manage), keyed by the part's own id instead of a document id. Reuses the same
    on-disk blob helpers, storage root, and validation.
    """

    url = PART_FILE_URL_PREFIX + "/{asset_id}/{part_id}"
    name = "api:home_keeper:part_document"
    requires_auth = True

    async def get(
        self, request: web.Request, asset_id: str, part_id: str
    ) -> web.StreamResponse:
        hass = request.app[KEY_HASS]
        coord = _coordinator(hass)
        part = _part_with_file(
            coord.store.get_asset(asset_id) if coord else None, part_id
        )
        if part is None:
            return web.Response(status=HTTPStatus.NOT_FOUND)
        try:
            data = await async_read_part_file(
                hass, asset_id, part_id, part["file_name"]
            )
        except (FileNotFoundError, AssetValidationError):
            return web.Response(status=HTTPStatus.NOT_FOUND)
        disposition = f'inline; filename="{part["file_name"]}"'
        return web.Response(
            body=data,
            content_type=part.get("file_content_type") or "application/octet-stream",
            headers={hdrs.CONTENT_DISPOSITION: disposition},
        )

    async def post(
        self, request: web.Request, asset_id: str, part_id: str
    ) -> web.Response:
        hass = request.app[KEY_HASS]
        request._client_max_size = MAX_DOCUMENT_BYTES  # see HomeKeeperDocumentView.post
        coord = _coordinator(hass)
        if coord is None:
            return self.json_message("Home Keeper is not loaded", HTTPStatus.NOT_FOUND)
        asset = coord.store.get_asset(asset_id)
        if asset is None:
            return self.json_message("Unknown asset", HTTPStatus.NOT_FOUND)
        if not any(p.get("id") == part_id for p in asset.get("parts", [])):
            return self.json_message("Unknown part", HTTPStatus.NOT_FOUND)

        parsed = await _parse_upload(self, request)
        if isinstance(parsed, web.Response):
            return parsed
        data, filename, declared_type, _display_name = parsed
        try:
            content_type, safe_name = validate_upload(filename, declared_type, data)
        except AssetValidationError as err:
            return self.json_message(str(err), HTTPStatus.BAD_REQUEST)

        # A re-upload replaces the existing file (only one slot per part) — remember
        # the old filename so its blob can be deleted once the new one is written.
        old_part = _part_with_file(asset, part_id)
        old_filename = old_part["file_name"] if old_part else None

        try:
            updated_part = await coord.store.set_part_file(
                asset_id,
                part_id,
                {
                    "filename": safe_name,
                    "content_type": content_type,
                    "size": len(data),
                },
            )
        except (KeyError, AssetValidationError) as err:
            return self.json_message(str(err), HTTPStatus.BAD_REQUEST)
        try:
            await async_save_part_file(hass, asset_id, part_id, safe_name, data)
        except OSError as err:  # roll the metadata back if the disk write fails
            _LOGGER.error("Failed to write file for part %s: %s", part_id, err)
            await coord.store.remove_part_file(asset_id, part_id)
            return self.json_message(
                "Failed to store the file", HTTPStatus.INTERNAL_SERVER_ERROR
            )
        if old_filename and old_filename != safe_name:
            await async_delete_part_file(hass, asset_id, part_id, old_filename)
        return self.json(
            {"asset": coord.store.get_asset(asset_id), "part": updated_part}
        )


def async_register_http(hass: HomeAssistant) -> None:
    """Register the document HTTP views (idempotent across entry reloads)."""
    if hass.data.get(f"{DOMAIN}_document_view"):
        return
    hass.http.register_view(HomeKeeperDocumentView())
    hass.http.register_view(HomeKeeperPartFileView())
    hass.data[f"{DOMAIN}_document_view"] = True
