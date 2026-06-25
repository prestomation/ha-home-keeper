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
)
from .documents import validate_upload

_LOGGER = logging.getLogger(__name__)

__all__ = ["HomeKeeperDocumentView", "async_register_http", "validate_upload"]


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
        coord = _coordinator(hass)
        if coord is None:
            return self.json_message("Home Keeper is not loaded", HTTPStatus.NOT_FOUND)
        if coord.store.get_asset(asset_id) is None:
            return self.json_message("Unknown asset", HTTPStatus.NOT_FOUND)

        display_name = ""
        filename: str | None = None
        declared_type: str | None = None
        data = b""
        try:
            reader = await request.multipart()
        except (ValueError, AssertionError):
            return self.json_message(
                "Expected a multipart upload", HTTPStatus.BAD_REQUEST
            )
        while True:
            part = await reader.next()
            if part is None:
                break
            # A nested multipart body isn't expected here; only flat parts carry the
            # file/name fields (and narrows the type for the attribute access below).
            if not isinstance(part, BodyPartReader):
                continue
            if part.name == "name":
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
                    return self.json_message(
                        "File is too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE
                    )
            data = bytes(buffer)

        if filename is None:
            return self.json_message("No file part in upload", HTTPStatus.BAD_REQUEST)
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


def async_register_http(hass: HomeAssistant) -> None:
    """Register the document HTTP view (idempotent across entry reloads)."""
    if hass.data.get(f"{DOMAIN}_document_view"):
        return
    hass.http.register_view(HomeKeeperDocumentView())
    hass.data[f"{DOMAIN}_document_view"] = True
