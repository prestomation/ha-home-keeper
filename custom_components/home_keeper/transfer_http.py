"""The HTTP views of the import and export: download a bundle, upload a file.

A bundle is binary and can be larger than a websocket message, so it goes through
HTTP, like an uploaded document (``manuals.py``). The import and export code is the
same code that the services run (``transfer_runner.py``), and the upload view returns
the same report.

Both views are admin-only on every method, like the ``export_data`` and
``import_data`` services. Each view checks it 2 times: ``@require_admin``, and
:func:`_admin_error`, which also refuses a system user and a signed URL.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from pathlib import Path
from typing import Any

from aiohttp import BodyPartReader, hdrs, web
from homeassistant.components.http import HomeAssistantView, require_admin
from homeassistant.components.http.const import KEY_HASS_USER
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.http import KEY_HASS
from homeassistant.util import dt as dt_util

from . import documents, transfer_bundle, transfer_runner
from .backend_i18n import resolve_exception
from .const import (
    BUNDLE_EXPORT_URL,
    DOMAIN,
    IMPORT_UPLOAD_URL,
    MAX_BUNDLE_BYTES,
    MAX_IMPORT_BYTES,
    MAX_UPLOAD_FIELD_BYTES,
)

_LOGGER = logging.getLogger(__name__)

_CHUNK_BYTES = 256 * 1024
_FLUSH_BYTES = 1024 * 1024
_TRUE = ("1", "true", "yes", "on")

__all__ = [
    "HomeKeeperBundleExportView",
    "HomeKeeperImportUploadView",
    "async_register_http",
]


def _coordinator(hass: HomeAssistant) -> Any:
    """Locate the loaded Home Keeper coordinator (lazy import avoids a cycle)."""
    from .coordinator import find_coordinator

    return find_coordinator(hass)


def _admin_error(view: HomeAssistantView, request: web.Request) -> web.Response | None:
    """The 401 reply for a caller that is not a real admin user, else ``None``.

    A signed URL authenticates as a system user, and a request can have no user.
    Neither can export or import the whole store.
    """
    user = request.get(KEY_HASS_USER)
    if user is None or user.system_generated or not user.is_admin:
        hass = request.app[KEY_HASS]
        message = resolve_exception(hass.config.language, "unauthorized_transfer")
        return view.json_message(message, HTTPStatus.UNAUTHORIZED)
    return None


def _context(request: web.Request) -> Context:
    """The context of the caller, so a companion sees the admin user."""
    user = request.get(KEY_HASS_USER)
    return Context(user_id=user.id if user is not None else None)


def _not_loaded(view: HomeAssistantView, hass: HomeAssistant) -> web.Response:
    message = resolve_exception(hass.config.language, "integration_not_loaded")
    return view.json_message(message, HTTPStatus.NOT_FOUND)


def _flag(value: str | None) -> bool:
    return str(value or "").strip().lower() in _TRUE


class _TooLarge(Exception):
    """A body part passed *limit* bytes. The view stops to read it."""

    def __init__(self, limit: int, key: str = "file_too_large") -> None:
        super().__init__(limit)
        self.limit = limit
        self.key = key


async def _read_field(part: BodyPartReader) -> str:
    """The text of 1 form field, read in chunks up to ``MAX_UPLOAD_FIELD_BYTES``.

    Raises :class:`_TooLarge` as soon as the field passes the limit, so a large field
    never gets into memory whole.
    """
    data = bytearray()
    while chunk := await part.read_chunk(_CHUNK_BYTES):
        data += chunk
        if len(data) > MAX_UPLOAD_FIELD_BYTES:
            raise _TooLarge(MAX_UPLOAD_FIELD_BYTES, "upload_field_too_large")
    return data.decode("utf-8", errors="replace").strip()


def _read_chunk(path: Path, offset: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(offset)
        return handle.read(_FLUSH_BYTES)


def _append(path: Path, data: bytes) -> None:
    with path.open("ab") as handle:
        handle.write(data)


class HomeKeeperBundleExportView(HomeAssistantView):
    """Download a bundle (GET). The query ``include`` is a list with commas."""

    url = BUNDLE_EXPORT_URL
    name = "api:home_keeper:export_bundle"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request) -> web.StreamResponse:
        hass = request.app[KEY_HASS]
        if refused := _admin_error(self, request):
            return refused
        coord = _coordinator(hass)
        if coord is None:
            return _not_loaded(self, hass)
        raw = request.query.get("include", "")
        include = [name.strip() for name in raw.split(",") if name.strip()]
        run_dir = await transfer_runner.async_new_run(hass)
        try:
            name = f"home-keeper-{dt_util.now().date().isoformat()}.zip"
            zip_path = run_dir / name
            try:
                await transfer_runner.async_export_bundle(
                    hass,
                    coord,
                    {"include": include},
                    context=_context(request),
                    zip_path=zip_path,
                )
            except HomeAssistantError as err:
                # Resolve the text here: ``json_message`` shows it as is.
                message = resolve_exception(
                    hass.config.language,
                    err.translation_key or "unknown_export_section",
                    **(err.translation_placeholders or {}),
                )
                return self.json_message(message, HTTPStatus.BAD_REQUEST)
            # Stream the file from the run folder, then delete the folder. A
            # FileResponse would send the file after this handler returns, when the
            # folder is already gone.
            size = await hass.async_add_executor_job(lambda: zip_path.stat().st_size)
            response = web.StreamResponse(
                headers={
                    hdrs.CONTENT_TYPE: "application/zip",
                    hdrs.CONTENT_LENGTH: str(size),
                    hdrs.CONTENT_DISPOSITION: documents.content_disposition(name),
                }
            )
            await response.prepare(request)
            offset = 0
            while chunk := await hass.async_add_executor_job(
                _read_chunk, zip_path, offset
            ):
                await response.write(chunk)
                offset += len(chunk)
            await response.write_eof()
            return response
        finally:
            await transfer_runner.async_remove_run(hass, run_dir)


class HomeKeeperImportUploadView(HomeAssistantView):
    """Import an uploaded bundle or YAML document (POST multipart).

    The form has 1 file part, and the text parts ``dry_run``, ``match`` and
    ``include_settings``. A file that starts like a zip file is a bundle. Any other
    file is YAML text, with the same limit as the service. The reply is the import
    report.
    """

    url = IMPORT_UPLOAD_URL
    name = "api:home_keeper:import_upload"
    requires_auth = True

    @require_admin
    async def post(self, request: web.Request) -> web.Response:
        hass = request.app[KEY_HASS]
        if refused := _admin_error(self, request):
            return refused
        lang = hass.config.language
        coord = _coordinator(hass)
        if coord is None:
            return _not_loaded(self, hass)
        try:
            reader = await request.multipart()
        except (ValueError, AssertionError):
            return self.json_message(
                resolve_exception(lang, "expected_multipart_upload"),
                HTTPStatus.BAD_REQUEST,
            )
        run_dir = await transfer_runner.async_new_run(hass)
        try:
            upload = run_dir / "upload"
            fields: dict[str, str] = {}
            received = False
            header = b""
            try:
                while True:
                    part = await reader.next()
                    if part is None:
                        break
                    if not isinstance(part, BodyPartReader):
                        continue
                    if not part.filename:
                        if part.name:
                            fields[part.name] = await _read_field(part)
                        continue
                    if received:
                        continue
                    received = True
                    header = await self._stream(hass, part, upload)
            except _TooLarge as err:
                return self._too_large(lang, err.limit, err.key)
            except web.HTTPRequestEntityTooLarge:
                return self._too_large(lang, MAX_BUNDLE_BYTES)
            if not received:
                return self.json_message(
                    resolve_exception(lang, "no_file_in_upload"),
                    HTTPStatus.BAD_REQUEST,
                )
            data: dict[str, Any] = {
                "dry_run": _flag(fields.get("dry_run")),
                "include_settings": _flag(fields.get("include_settings")),
                "match": fields.get("match") or "auto",
            }
            if data["match"] not in ("auto", "none"):
                data["match"] = "auto"
            context = _context(request)
            if transfer_bundle.is_zip_header(header):
                report = await transfer_runner.async_import_bundle(
                    hass, coord, upload, data, context=context
                )
                return self.json(report)
            try:
                text = await hass.async_add_executor_job(
                    lambda: upload.read_text(encoding="utf-8")
                )
            except UnicodeDecodeError:
                return self.json_message(
                    resolve_exception(lang, "import_not_text"),
                    HTTPStatus.BAD_REQUEST,
                )
            data["document"] = text
            report = await transfer_runner.async_import_document(
                hass, coord, data, context=context
            )
            return self.json(report)
        finally:
            await transfer_runner.async_remove_run(hass, run_dir)

    def _too_large(
        self, lang: str, limit: int, key: str = "file_too_large"
    ) -> web.Response:
        if key == "file_too_large":
            message = resolve_exception(lang, key, mb=limit // (1024 * 1024))
        else:
            message = resolve_exception(lang, key, kb=limit // 1024)
        return self.json_message(message, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)

    async def _stream(
        self, hass: HomeAssistant, part: BodyPartReader, target: Path
    ) -> bytes:
        """Write 1 body part to *target* in chunks, and return its first 8 bytes.

        A zip file can grow to ``MAX_BUNDLE_BYTES``, and any other file only to
        ``MAX_IMPORT_BYTES``. The first bytes decide which, and :class:`_TooLarge`
        stops the read as soon as the part passes its limit. Memory holds at most
        ``_FLUSH_BYTES``.
        """
        size = 0
        header = b""
        buffer = bytearray()
        while chunk := await part.read_chunk(_CHUNK_BYTES):
            size += len(chunk)
            if len(header) < 8:
                header = bytes((buffer + chunk)[:8])
            limit = (
                MAX_BUNDLE_BYTES
                if transfer_bundle.is_zip_header(header)
                else MAX_IMPORT_BYTES
            )
            if size > limit:
                raise _TooLarge(limit)
            buffer += chunk
            if len(buffer) >= _FLUSH_BYTES:
                await hass.async_add_executor_job(_append, target, bytes(buffer))
                buffer.clear()
        await hass.async_add_executor_job(_append, target, bytes(buffer))
        return header


def async_register_http(hass: HomeAssistant) -> None:
    """Register the import and export views (idempotent across entry reloads)."""
    key = f"{DOMAIN}_transfer_views"
    if hass.data.get(key):
        return
    hass.http.register_view(HomeKeeperBundleExportView())
    hass.http.register_view(HomeKeeperImportUploadView())
    hass.data[key] = True
