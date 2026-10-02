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

import asyncio
import logging
import os
import shutil
import tempfile
from collections.abc import Collection
from dataclasses import dataclass
from datetime import timedelta
from http import HTTPStatus
from pathlib import Path
from typing import Any

from aiohttp import BodyPartReader, hdrs, web
from homeassistant.components.http import HomeAssistantView, require_admin
from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.http.const import KEY_HASS_USER
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import KEY_HASS

from . import documents, task_photos
from .assets import AssetValidationError, find_part
from .backend_i18n import resolve_exception
from .const import (
    DOCUMENT_URL_PREFIX,
    DOMAIN,
    MANUALS_SUBDIR,
    MAX_DOCUMENT_BYTES,
    MAX_TASK_PHOTO_BYTES,
    PART_FILE_URL_PREFIX,
    TASK_PHOTO_URL_PREFIX,
    TASK_PHOTOS_SUBDIR,
)
from .documents import SNIFF_BYTES, validate_upload, validate_upload_stream
from .models import TaskValidationError

# Uploads are streamed to a temp file rather than buffered: a 100 MB manual held in
# memory (twice, counting the bytes() copy) is enough to OOM a small Home Assistant
# box. These bound how much is in RAM at once, independent of the file's size.
_CHUNK_BYTES = 256 * 1024
_FLUSH_BYTES = 1024 * 1024
# Temp uploads live in a sibling of the per-asset directories so the finished file can
# be moved into place with an atomic same-filesystem rename. The leading dot keeps it
# out of reach of ``documents.safe_segment`` (which strips leading dots), so no asset
# id can ever resolve into it.
_TMP_SUBDIR = ".incoming"
# How old a temp upload must be before setup treats it as stray (see
# ``async_cleanup_temp_uploads``). Generous: a big upload over a slow link can run for
# a long time, and deleting a live one is far worse than keeping a stray for a day.
_TEMP_MAX_AGE_S = 24 * 60 * 60
# How long a signed document/part-file URL stays valid for the dashboard card,
# which pre-signs file documents and embeds the URL as a plain <a href> (so a tap
# opens natively; the iOS app's WKWebView blocks an async window.open). The URL
# must outlive a reasonably idle dashboard, not just a click; the card re-signs
# well before this on refresh.
DOCUMENT_URL_TTL = timedelta(hours=1)
# TTL for URLs minted by the sign_document_url/sign_part_file_url *services*
# (issue #161), for a non-browser caller (e.g. an MCP-connected agent) to fetch
# the file shortly after receiving the service response. Much shorter than
# DOCUMENT_URL_TTL: this URL needs no auth header to use, so it can end up
# sitting in a model provider's request logs, and unlike the dashboard card it
# has no "idle page" to outlive.
SERVICE_DOCUMENT_URL_TTL = timedelta(minutes=15)


_LOGGER = logging.getLogger(__name__)

__all__ = [
    "DOCUMENT_URL_TTL",
    "SERVICE_DOCUMENT_URL_TTL",
    "HomeKeeperDocumentView",
    "HomeKeeperPartFileView",
    "HomeKeeperTaskPhotoView",
    "async_cleanup_temp_uploads",
    "async_delete_part_file",
    "async_register_http",
    "async_sign_document_url",
    "async_sign_part_file_url",
    "async_sign_task_photo_url",
    "validate_upload",
    "validate_upload_stream",
]


def _root(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(MANUALS_SUBDIR))


def _document_path(
    hass: HomeAssistant, asset_id: str, document_id: str, filename: str
) -> Path:
    """Return the guarded path of a stored blob. Blocking: it resolves the path.

    ``documents.resolve_under_root`` calls ``Path.resolve``, which reads the file
    system, so call this only from an executor job, never on the event loop (B06-9).
    """
    return documents.document_path(_root(hass), asset_id, document_id, filename)


@dataclass(frozen=True)
class UploadedFile:
    """A received upload, already on disk in the temp area.

    The caller owns ``path`` until it is moved into place (``async_store_document`` /
    ``async_store_part_file``) and must always finish with ``async_discard_upload`` so
    a rejected upload can't leak a temp file.
    """

    path: Path
    size: int
    #: The first :data:`SNIFF_BYTES` bytes — all that's needed to identify the type.
    header: bytes


# ── blocking IO (run via the executor) ───────────────────────────────────────
def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _make_temp(tmp_root: Path) -> Path:
    tmp_root.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=tmp_root, prefix="upload-")
    os.close(fd)
    return Path(name)


def _append(path: Path, data: bytes) -> None:
    with path.open("ab") as fh:
        fh.write(data)


def _move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Same filesystem by construction (the temp dir is a sibling of the asset dirs),
    # so this is an atomic rename — a reader never sees a half-written blob.
    os.replace(src, dst)


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)


async def _async_unlink(hass: HomeAssistant, path: Path) -> None:
    """Delete *path* in the executor, also if the caller is cancelled again.

    A client abort cancels the upload handler (B06-4). The cleanup then runs in an
    ``except`` or ``finally`` block, and a second cancel must not skip the unlink,
    so the executor job is shielded.
    """
    await asyncio.shield(hass.async_add_executor_job(_unlink, path))


def _rmtree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _tmp_root(hass: HomeAssistant) -> Path:
    return _root(hass) / _TMP_SUBDIR


async def async_save_document(
    hass: HomeAssistant, asset_id: str, document_id: str, filename: str, data: bytes
) -> None:
    """Persist an uploaded document's bytes to disk (in-memory callers only)."""

    def _job() -> None:
        _write(_document_path(hass, asset_id, document_id, filename), data)

    await hass.async_add_executor_job(_job)


async def async_store_document(
    hass: HomeAssistant,
    asset_id: str,
    document_id: str,
    filename: str,
    uploaded: UploadedFile,
) -> None:
    """Move a streamed upload into place as this document's blob."""

    def _job() -> None:
        _move(uploaded.path, _document_path(hass, asset_id, document_id, filename))

    await hass.async_add_executor_job(_job)


async def async_rename_document(
    hass: HomeAssistant, asset_id: str, from_id: str, to_id: str, filename: str
) -> None:
    """Re-key a stored blob (the store regenerated a colliding document id)."""

    def _job() -> None:
        _move(
            _document_path(hass, asset_id, from_id, filename),
            _document_path(hass, asset_id, to_id, filename),
        )

    await hass.async_add_executor_job(_job)


async def async_discard_upload(hass: HomeAssistant, uploaded: UploadedFile) -> None:
    """Drop a temp upload. A no-op once it has been moved into place."""
    await _async_unlink(hass, uploaded.path)


async def async_cleanup_temp_uploads(hass: HomeAssistant) -> None:
    """Drop stray temp uploads (called at setup).

    An upload interrupted by a restart leaves its temp file behind; at up to 100 MB
    apiece those would quietly accumulate in the config directory forever.

    Deliberately age-based rather than a blanket wipe: setup re-runs on every config
    entry *reload* (an options change, say) while the HTTP view stays registered, so
    clearing the whole directory could delete a temp file an in-flight upload is
    still writing — turning someone's upload into a 500 mid-transfer.
    """
    await hass.async_add_executor_job(
        documents.purge_stale_temps, _tmp_root(hass), _TEMP_MAX_AGE_S
    )


async def async_delete_document(
    hass: HomeAssistant, asset_id: str, document_id: str, filename: str
) -> None:
    """Delete a single uploaded document's bytes (no-op if already gone)."""

    def _job() -> None:
        _unlink(_document_path(hass, asset_id, document_id, filename))

    await hass.async_add_executor_job(_job)


async def async_delete_asset_documents(hass: HomeAssistant, asset_id: str) -> None:
    """Remove an asset's entire on-disk document directory."""

    def _job() -> None:
        _rmtree(documents.resolve_under_root(_root(hass), asset_id))

    await hass.async_add_executor_job(_job)


async def async_delete_all_documents(hass: HomeAssistant) -> None:
    """Remove the entire uploaded-documents tree (called on integration removal).

    Per-asset deletes cover the running lifecycle, but uninstalling the integration
    must also drop the blob tree — otherwise gigabytes of manuals/receipts linger in
    the config directory forever (and a reinstall can resurrect stale blobs).
    """
    await hass.async_add_executor_job(_rmtree, _root(hass))
    await hass.async_add_executor_job(_rmtree, _photo_root(hass))


# ── task photos (#399) ───────────────────────────────────────────────────────
def _photo_root(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(TASK_PHOTOS_SUBDIR))


def task_photo_path(task_id: str, photo_id: str) -> str:
    """The view path for a task photo (signed by async_sign_task_photo_url)."""
    return f"{TASK_PHOTO_URL_PREFIX}/{task_id}/{photo_id}"


def _store_task_photo(
    hass: HomeAssistant, task_id: str, photo_id: str, filename: str, src: Path
) -> None:
    """Make the thumbnail of *src*, then move *src* into place. Blocking.

    The thumbnail comes first: a file that does not decode raises
    ``photo_thumbs.ThumbnailError`` before anything is in the task's folder.
    """
    from .photo_thumbs import make_thumbnail  # lazy: Pillow only when needed

    root = _photo_root(hass)
    thumb = task_photos.thumb_path(root, task_id, photo_id)
    make_thumbnail(src, thumb)
    try:
        _move(src, task_photos.photo_path(root, task_id, photo_id, filename))
    except OSError:
        _unlink(thumb)
        raise


async def async_delete_task_photo(
    hass: HomeAssistant, task_id: str, photo_id: str, filename: str
) -> None:
    """Delete one task photo and its thumbnail (no-op if already gone)."""

    def _job() -> None:
        root = _photo_root(hass)
        _unlink(task_photos.photo_path(root, task_id, photo_id, filename))
        _unlink(task_photos.thumb_path(root, task_id, photo_id))

    await asyncio.shield(hass.async_add_executor_job(_job))


async def async_delete_task_photo_dirs(
    hass: HomeAssistant, task_ids: Collection[str]
) -> None:
    """Remove the photo folders of tasks that are gone."""

    def _job() -> None:
        root = _photo_root(hass)
        for task_id in task_ids:
            _rmtree(documents.resolve_under_root(root, task_id))

    if task_ids:
        await hass.async_add_executor_job(_job)


async def async_sweep_task_photos(hass: HomeAssistant, live_ids: set[str]) -> None:
    """Remove every photo folder whose task no longer exists (called at setup).

    The store removes a gone task's folder after the save that drops it. This
    catches what that cannot: a delete that a restart cut short, or an upload that
    finished just after its task was deleted.
    """

    def _job() -> None:
        root = _photo_root(hass)
        if not root.is_dir():
            return
        present = [p.name for p in root.iterdir() if p.is_dir()]
        for name in task_photos.stale_task_dirs(present, live_ids):
            _rmtree(root / name)

    await hass.async_add_executor_job(_job)


async def async_sign_task_photo_url(
    hass: HomeAssistant,
    task_id: str,
    photo_id: str,
    *,
    thumb: bool = False,
    ttl: timedelta = DOCUMENT_URL_TTL,
) -> str | None:
    """Mint a short-lived signed URL for a task photo, or None if not found.

    See :func:`async_sign_document_url` for the signing identity and ``ttl``. With
    *thumb* the URL serves the small copy. The query is part of the signed path,
    so a signed thumbnail URL cannot be changed into a URL for the original.
    """
    coord = _coordinator(hass)
    photo = task_photos.find_photo(
        coord.store.get_task(task_id) if coord else None, photo_id
    )
    if photo is None:
        return None
    path = task_photo_path(task_id, photo_id)
    if thumb:
        path = f"{path}?size=thumb"
    return async_sign_path(hass, path, ttl, use_content_user=True)


def document_path(asset_id: str, document_id: str) -> str:
    """The view path for a file document (signed by async_sign_document_url)."""
    return f"{DOCUMENT_URL_PREFIX}/{asset_id}/{document_id}"


def part_file_path(asset_id: str, part_id: str) -> str:
    """The view path for a part's attached file (signed by async_sign_part_file_url)."""
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
    """Persist a part's uploaded file bytes to disk (in-memory callers only)."""
    await async_save_document(
        hass, asset_id, _part_document_id(part_id), filename, data
    )


async def async_store_part_file(
    hass: HomeAssistant,
    asset_id: str,
    part_id: str,
    filename: str,
    uploaded: UploadedFile,
) -> None:
    """Move a streamed upload into place as this part's attached file."""
    await async_store_document(
        hass, asset_id, _part_document_id(part_id), filename, uploaded
    )


async def async_delete_part_file(
    hass: HomeAssistant, asset_id: str, part_id: str, filename: str
) -> None:
    """Delete a part's uploaded file bytes (no-op if already gone)."""
    await async_delete_document(hass, asset_id, _part_document_id(part_id), filename)


def _coordinator(hass: HomeAssistant) -> Any:
    """Locate the loaded Home Keeper coordinator (lazy import avoids a cycle)."""
    from .coordinator import find_coordinator

    return find_coordinator(hass)


def _uploader_is_a_real_user(request: web.Request) -> bool:
    """True when *request* is authenticated as a person, not as a signed URL.

    GET on these views is reachable through an ``async_sign_path`` URL, which
    authenticates as the "Home Assistant Content" **system** user
    (``use_content_user=True``) and needs no auth header — that is the whole point,
    so a browser tab can open a document. POST shares the same route, so this asks
    the question the route's shape invites: could that read credential ever be used
    to *write*?

    Today it cannot — HA's auth middleware only considers a signed request when
    ``request.method == "GET"`` (``homeassistant/components/http/auth.py``). This is
    a belt for the day that changes: an upload must come from a real user's token,
    never from a system user, and never from a request with no user at all.
    """
    user = request.get(KEY_HASS_USER)
    return user is not None and not user.system_generated


def _file_document(asset: dict[str, Any] | None, document_id: str) -> dict | None:
    for document in (asset or {}).get("documents", []):
        if document.get("id") == document_id and document.get("kind") == "file":
            return document
    return None


def _part_with_file(asset: dict[str, Any] | None, part_id: str) -> dict | None:
    part = find_part(asset or {}, part_id)
    return part if part and part.get("file_name") else None


async def async_sign_document_url(
    hass: HomeAssistant,
    asset_id: str,
    document_id: str,
    *,
    ttl: timedelta = DOCUMENT_URL_TTL,
) -> str | None:
    """Mint a short-lived signed URL for a file document, or None if not found.

    Shared by the ``sign_document_url`` websocket command (a real user's browser
    session, ``ttl`` defaults to ``DOCUMENT_URL_TTL``) and service (issue #161:
    any caller that can invoke a Home Assistant service, including an
    MCP-connected agent with no websocket connection or interactive session of
    its own; passes the shorter ``SERVICE_DOCUMENT_URL_TTL``), one
    implementation, matching the service-first rule in the architecture doc.

    Explicitly signs as Home Assistant's built-in read-only "Home Assistant
    Content" system user (``use_content_user=True``) rather than the calling
    connection's own token. That's the mechanism HA core itself uses for
    externally-fetchable signed URLs (e.g. camera/media proxies): unlike a
    per-connection token, it doesn't depend on the caller having a "normal"
    browser auth session, so it resolves the same way for a browser tab, a
    service call from an automation, or a service call relayed by an MCP
    server. ``use_content_user=True`` must be explicit, not just an omitted
    ``refresh_token_id`` — ``async_sign_path`` only falls back to the content
    user as a last resort, after checking the current websocket connection and
    then the current HTTP request, so an omitted ``refresh_token_id`` would
    still pick up the calling connection's identity when one is live (e.g. a
    service invoked over the REST API within the same request).
    """
    coord = _coordinator(hass)
    document = _file_document(
        coord.store.get_asset(asset_id) if coord else None, document_id
    )
    if document is None:
        return None
    path = document_path(asset_id, document_id)
    return async_sign_path(hass, path, ttl, use_content_user=True)


async def async_sign_part_file_url(
    hass: HomeAssistant,
    asset_id: str,
    part_id: str,
    *,
    ttl: timedelta = DOCUMENT_URL_TTL,
) -> str | None:
    """Mint a short-lived signed URL for a part's attached file, or None if not found.

    See :func:`async_sign_document_url` for the signing-identity and ``ttl`` rationale.
    """
    coord = _coordinator(hass)
    part = _part_with_file(coord.store.get_asset(asset_id) if coord else None, part_id)
    if part is None:
        return None
    path = part_file_path(asset_id, part_id)
    return async_sign_path(hass, path, ttl, use_content_user=True)


async def _parse_upload(
    hass: HomeAssistant,
    view: HomeAssistantView,
    request: web.Request,
    *,
    want_name: bool = False,
    max_bytes: int = MAX_DOCUMENT_BYTES,
) -> tuple[UploadedFile, str, str] | web.Response:
    """Parse a multipart upload's single file part, streaming it to disk under a cap.

    Shared by :class:`HomeKeeperDocumentView` and :class:`HomeKeeperPartFileView` —
    both accept one file per request, over the same size ceiling. When *want_name*
    is set, a ``name`` text part is also captured (asset documents have a
    user-editable display name; a part's file doesn't). The client-declared MIME
    type is deliberately never read — ``validate_upload_stream`` sniffs it from the
    leading bytes instead, so a misleading header can't spoof the stored content type.

    The body is written to a temp file as it arrives, so peak memory is a fixed
    ``_FLUSH_BYTES`` regardless of the upload's size. Returns
    ``(uploaded, filename, display_name)`` — and the caller then **owns the temp
    file**, so it must always end with ``async_discard_upload`` — or an early
    ``web.Response`` (bad request / too large), in which case nothing is left on disk.
    """
    lang = hass.config.language
    too_large = view.json_message(
        resolve_exception(lang, "file_too_large", mb=max_bytes // (1024 * 1024)),
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    )
    try:
        reader = await request.multipart()
    except (ValueError, AssertionError):
        return view.json_message(
            resolve_exception(lang, "expected_multipart_upload"), HTTPStatus.BAD_REQUEST
        )

    display_name = ""
    filename: str | None = None
    uploaded: UploadedFile | None = None
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
            # One file per request. A malformed body with several file parts keeps the
            # last, but the previous temp has to go first — otherwise it is orphaned on
            # disk, and reassigning would lose the only reference to it (including when
            # the next part is rejected as too large and this becomes None).
            if uploaded is not None:
                await async_discard_upload(hass, uploaded)
                uploaded = None
            uploaded = await _stream_to_temp(hass, part, max_bytes)
            if uploaded is None:
                return too_large
    except web.HTTPRequestEntityTooLarge:
        # Backstop: aiohttp enforces the (raised) per-request cap too.
        if uploaded is not None:
            await async_discard_upload(hass, uploaded)
        return too_large
    except BaseException:
        # Also for ``CancelledError``, which is not an ``Exception``: a client that
        # aborts the upload cancels this handler (B06-4).
        if uploaded is not None:
            await async_discard_upload(hass, uploaded)
        raise

    if filename is None or uploaded is None:
        if uploaded is not None:
            await async_discard_upload(hass, uploaded)
        return view.json_message(
            resolve_exception(lang, "no_file_in_upload"), HTTPStatus.BAD_REQUEST
        )
    return uploaded, filename, display_name


async def _stream_to_temp(
    hass: HomeAssistant, part: BodyPartReader, max_bytes: int = MAX_DOCUMENT_BYTES
) -> UploadedFile | None:
    """Write one body part to a temp file. Returns None if it exceeds the ceiling.

    Chunks are buffered only up to ``_FLUSH_BYTES`` before being handed to the
    executor, which keeps both memory bounded and the number of executor round-trips
    proportional to megabytes rather than to chunks.
    """
    tmp = await hass.async_add_executor_job(_make_temp, _tmp_root(hass))
    size = 0
    header = b""
    buffer = bytearray()
    try:
        while chunk := await part.read_chunk(_CHUNK_BYTES):
            size += len(chunk)
            if size > max_bytes:
                # Stop reading immediately — there's no reason to spool gigabytes to
                # disk just to reject them.
                await hass.async_add_executor_job(_unlink, tmp)
                return None
            buffer += chunk
            if len(header) < SNIFF_BYTES:
                header = bytes(buffer[:SNIFF_BYTES])
            if len(buffer) >= _FLUSH_BYTES:
                await hass.async_add_executor_job(_append, tmp, bytes(buffer))
                buffer.clear()
        if buffer:
            await hass.async_add_executor_job(_append, tmp, bytes(buffer))
    except BaseException:
        # Also for ``CancelledError`` (B06-4), see ``_parse_upload``.
        await _async_unlink(hass, tmp)
        raise
    return UploadedFile(path=tmp, size=size, header=header)


async def _serve_signed_file(
    hass: HomeAssistant,
    asset_id: str,
    document_id: str,
    filename: str | None,
    display_name: str = "",
) -> web.StreamResponse:
    """Stream one stored blob back to the browser, or 404.

    Shared by both views' ``get``. The caller looks the record up first and passes
    its stored filename (``None`` when there is no such record) — that lookup is the
    permission check: the document/file must belong to the addressed asset, and it
    must stay ahead of any file response, alongside the view's ``requires_auth``.
    (An asset document spells that field ``filename`` and a part's file spells it
    ``file_name``; the two stored spellings are historical, and renaming either
    would need a storage migration.)

    *document_id* is the on-disk storage key — the document's own id for an asset
    document, ``_part_document_id(part_id)`` for a part's single file.
    """
    if filename is None:
        return web.Response(status=HTTPStatus.NOT_FOUND)

    def _existing_path() -> Path | None:
        # The path checks read the file system, so they run here and not on the
        # event loop (B06-9).
        try:
            path = _document_path(hass, asset_id, document_id, filename)
        except AssetValidationError:
            return None
        return path if path.is_file() else None

    path = await hass.async_add_executor_job(_existing_path)
    if path is None:
        return web.Response(status=HTTPStatus.NOT_FOUND)
    # Stream straight from disk (aiohttp handles range requests, content-type from
    # the file extension, etc.) rather than buffering up to MAX_DOCUMENT_BYTES.
    disposition = documents.content_disposition(filename, display_name)
    return web.FileResponse(path, headers={hdrs.CONTENT_DISPOSITION: disposition})


async def _begin_upload(
    hass: HomeAssistant, view: HomeAssistantView, request: web.Request, asset_id: str
) -> tuple[Any, dict[str, Any], str] | web.Response:
    """Admit an upload request, or hand back the error response to return.

    Shared by both views' ``post``: raise this request's body cap, then check the
    three things an upload needs before a byte is read — a real user behind it, a
    loaded integration, and an asset to hang the file off. Returns
    ``(coordinator, asset, language)`` on success.
    """
    # Raise this request's body cap to our document ceiling. HA's global app limit
    # (`MAX_CLIENT_SIZE`, 16 MB) is *smaller* than MAX_DOCUMENT_BYTES, so without
    # this aiohttp rejects a larger upload with a bare 413 before our handler runs.
    # Mirrors homeassistant.components.image_upload. We still enforce the real
    # ceiling (with a clear message) while streaming below.
    request._client_max_size = MAX_DOCUMENT_BYTES
    lang = hass.config.language
    if not _uploader_is_a_real_user(request):
        message = resolve_exception(lang, "upload_requires_user")
        return view.json_message(message, HTTPStatus.UNAUTHORIZED)
    coord = _coordinator(hass)
    if coord is None:
        message = resolve_exception(lang, "integration_not_loaded")
        return view.json_message(message, HTTPStatus.NOT_FOUND)
    asset = coord.store.get_asset(asset_id)
    if asset is None:
        message = resolve_exception(lang, "asset_not_found", asset_id=asset_id)
        return view.json_message(message, HTTPStatus.NOT_FOUND)
    return coord, asset, lang


def _replaced_response(
    hass: HomeAssistant, view: HomeAssistantView, coord: Any, lang: str
) -> web.Response | None:
    """The error to return if the entry reloaded while the body streamed (X02-1).

    A reload makes a new coordinator and a new store. A write to the old store
    goes to a copy that no part of Home Keeper reads, and the next save of the new
    store removes it. So an upload that spans a reload stops here, before the blob
    moves into place, with the same error as an upload to an unloaded entry.
    """
    if _coordinator(hass) is coord:
        return None
    message = resolve_exception(lang, "integration_not_loaded")
    return view.json_message(message, HTTPStatus.NOT_FOUND)


async def _async_drop_gone_asset_dir(
    hass: HomeAssistant, coord: Any, asset_id: str
) -> None:
    """Remove the directory of an appliance that was deleted during an upload.

    The move into place makes the directory again (``_move``), and no later delete
    of that appliance runs (B06-10).
    """
    if coord.store.get_asset(asset_id) is None:
        await async_delete_asset_documents(hass, asset_id)


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
        return await _serve_signed_file(
            hass,
            asset_id,
            document_id,
            document["filename"] if document else None,
            str(document.get("name") or "") if document else "",
        )

    # Uploads are admin-only, like the ``add_asset_document`` service: a write
    # changes an appliance, and the reply carries the full, unprojected asset.
    @require_admin
    async def post(
        self, request: web.Request, asset_id: str, document_id: str
    ) -> web.Response:
        hass = request.app[KEY_HASS]
        admitted = await _begin_upload(hass, self, request, asset_id)
        if isinstance(admitted, web.Response):
            return admitted
        coord, _asset, lang = admitted

        parsed = await _parse_upload(hass, self, request, want_name=True)
        if isinstance(parsed, web.Response):
            return parsed
        uploaded, filename, display_name = parsed
        # The temp file is ours from here; drop it on every exit path (a no-op once
        # it has been moved into place).
        try:
            try:
                content_type, safe_name = validate_upload_stream(
                    filename, uploaded.header, uploaded.size
                )
            except AssetValidationError as err:
                message = resolve_exception(lang, "invalid_asset", error=str(err))
                return self.json_message(message, HTTPStatus.BAD_REQUEST)
            if replaced := _replaced_response(hass, self, coord, lang):
                return replaced

            # Put the blob in place BEFORE persisting metadata (which fires
            # ``home_keeper_asset_updated``). Otherwise a reader — or an automation
            # reacting to the event — sees a document whose backing file isn't there
            # yet, so a GET 404s in that gap. We store under the caller-supplied
            # ``document_id``, which the store honours (see ``add_asset_document``),
            # so the metadata + blob agree. An id that is taken or not a uuid gets a
            # new one first, so the move never writes over another document's file.
            current = coord.store.get_asset(asset_id) or {}
            document_id = documents.upload_document_id(
                document_id,
                (d.get("id") for d in current.get("documents") or []),
            )
            try:
                await async_store_document(
                    hass, asset_id, document_id, safe_name, uploaded
                )
            except OSError as err:
                _LOGGER.error(
                    "Failed to write document for asset %s: %s", asset_id, err
                )
                message = resolve_exception(lang, "failed_to_store_file")
                return self.json_message(message, HTTPStatus.INTERNAL_SERVER_ERROR)

            try:
                entry = await coord.store.add_asset_document(
                    asset_id,
                    {
                        "id": document_id,
                        "kind": "file",
                        # The safe name is ASCII only. Without a name from the
                        # client, show the real name of the file (B06-6).
                        "name": display_name or documents.display_filename(filename),
                        "filename": safe_name,
                        "content_type": content_type,
                        "size": uploaded.size,
                    },
                )
            except (KeyError, AssetValidationError) as err:
                # Metadata was rejected — don't leave an orphaned blob behind.
                await async_delete_document(hass, asset_id, document_id, safe_name)
                await _async_drop_gone_asset_dir(hass, coord, asset_id)
                message = resolve_exception(lang, "invalid_asset", error=str(err))
                return self.json_message(message, HTTPStatus.BAD_REQUEST)

            # The store regenerates a colliding id (a re-used ``document_id``); in that
            # (rare) case move the blob so the served path matches the stored id.
            if entry["id"] != document_id:
                try:
                    await async_rename_document(
                        hass, asset_id, document_id, entry["id"], safe_name
                    )
                except OSError as err:
                    _LOGGER.error(
                        "Failed to write document for asset %s: %s", asset_id, err
                    )
                    await coord.store.remove_asset_document(asset_id, entry["id"])
                    await async_delete_document(hass, asset_id, document_id, safe_name)
                    message = resolve_exception(lang, "failed_to_store_file")
                    return self.json_message(message, HTTPStatus.INTERNAL_SERVER_ERROR)

            # Documents touch neither the device registry nor any entity/task, so
            # there's no device reconcile or entry reload to do — the store already
            # persisted and fired ``home_keeper_asset_updated``.
            return self.json(
                {"asset": coord.store.get_asset(asset_id), "document": entry}
            )
        finally:
            await async_discard_upload(hass, uploaded)


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
        return await _serve_signed_file(
            hass,
            asset_id,
            _part_document_id(part_id),
            part["file_name"] if part else None,
        )

    # Admin-only for the same reasons as a document upload.
    @require_admin
    async def post(
        self, request: web.Request, asset_id: str, part_id: str
    ) -> web.Response:
        hass = request.app[KEY_HASS]
        admitted = await _begin_upload(hass, self, request, asset_id)
        if isinstance(admitted, web.Response):
            return admitted
        coord, asset, lang = admitted
        if find_part(asset, part_id) is None:
            message = resolve_exception(
                lang, "unknown_part", asset_id=asset_id, part_id=part_id
            )
            return self.json_message(message, HTTPStatus.NOT_FOUND)

        parsed = await _parse_upload(hass, self, request)
        if isinstance(parsed, web.Response):
            return parsed
        uploaded, filename, _display_name = parsed
        try:
            try:
                content_type, safe_name = validate_upload_stream(
                    filename, uploaded.header, uploaded.size
                )
            except AssetValidationError as err:
                message = resolve_exception(lang, "invalid_asset", error=str(err))
                return self.json_message(message, HTTPStatus.BAD_REQUEST)
            if replaced := _replaced_response(hass, self, coord, lang):
                return replaced

            # A re-upload replaces the existing file (only one slot per part) —
            # remember the old filename so its blob can be cleaned up once the new
            # one lands.
            old_part = _part_with_file(asset, part_id)
            old_filename = old_part["file_name"] if old_part else None

            # Put the blob in place BEFORE persisting metadata (which fires
            # ``home_keeper_asset_updated``), same as HomeKeeperDocumentView.post —
            # otherwise a reader reacting to the event sees a part whose backing file
            # isn't there yet.
            try:
                await async_store_part_file(
                    hass, asset_id, part_id, safe_name, uploaded
                )
            except OSError as err:
                _LOGGER.error("Failed to write file for part %s: %s", part_id, err)
                message = resolve_exception(lang, "failed_to_store_file")
                return self.json_message(message, HTTPStatus.INTERNAL_SERVER_ERROR)

            try:
                updated_part = await coord.store.set_part_file(
                    asset_id,
                    part_id,
                    {
                        "filename": safe_name,
                        "content_type": content_type,
                        "size": uploaded.size,
                    },
                )
            except KeyError as err:
                # The appliance or the part was deleted during the upload, so no
                # record names the new blob. Delete it, also for a same-name
                # re-upload: the move already replaced the old file (B06-10).
                await async_delete_part_file(hass, asset_id, part_id, safe_name)
                await _async_drop_gone_asset_dir(hass, coord, asset_id)
                message = resolve_exception(lang, "invalid_asset", error=str(err))
                return self.json_message(message, HTTPStatus.BAD_REQUEST)
            except AssetValidationError as err:
                # Metadata was rejected — don't leave an orphaned blob behind, unless
                # it shares the old file's exact path (a same-name re-upload), in
                # which case deleting it would destroy the still-valid previous file.
                if safe_name != old_filename:
                    await async_delete_part_file(hass, asset_id, part_id, safe_name)
                message = resolve_exception(lang, "invalid_asset", error=str(err))
                return self.json_message(message, HTTPStatus.BAD_REQUEST)

            if old_filename and old_filename != safe_name:
                await async_delete_part_file(hass, asset_id, part_id, old_filename)
            return self.json(
                {"asset": coord.store.get_asset(asset_id), "part": updated_part}
            )
        finally:
            await async_discard_upload(hass, uploaded)


class HomeKeeperTaskPhotoView(HomeAssistantView):
    """Upload (POST) and serve (GET) the photos of a task (#399).

    A sibling of :class:`HomeKeeperDocumentView` keyed by task. GET serves the
    original, or with ``?size=thumb`` the small JPEG made at upload.
    """

    url = TASK_PHOTO_URL_PREFIX + "/{task_id}/{photo_id}"
    name = "api:home_keeper:task_photo"
    requires_auth = True

    async def get(
        self, request: web.Request, task_id: str, photo_id: str
    ) -> web.StreamResponse:
        hass = request.app[KEY_HASS]
        coord = _coordinator(hass)
        # The lookup is the permission check, as for a document.
        photo = task_photos.find_photo(
            coord.store.get_task(task_id) if coord else None, photo_id
        )
        if photo is None:
            return web.Response(status=HTTPStatus.NOT_FOUND)
        thumb = request.query.get("size") == "thumb"

        def _existing_path() -> Path | None:
            root = _photo_root(hass)
            try:
                path = (
                    task_photos.thumb_path(root, task_id, photo_id)
                    if thumb
                    else task_photos.photo_path(
                        root, task_id, photo_id, photo["filename"]
                    )
                )
            except AssetValidationError:
                return None
            return path if path.is_file() else None

        path = await hass.async_add_executor_job(_existing_path)
        if path is None:
            return web.Response(status=HTTPStatus.NOT_FOUND)
        name = task_photos.THUMB_FILENAME if thumb else photo["filename"]
        disposition = documents.content_disposition(
            name, "" if thumb else str(photo.get("name") or "")
        )
        return web.FileResponse(path, headers={hdrs.CONTENT_DISPOSITION: disposition})

    # Admin-only, like the photo services: a write changes the task, and the reply
    # carries the full task.
    @require_admin
    async def post(
        self, request: web.Request, task_id: str, photo_id: str
    ) -> web.Response:
        hass = request.app[KEY_HASS]
        request._client_max_size = MAX_TASK_PHOTO_BYTES
        lang = hass.config.language
        if not _uploader_is_a_real_user(request):
            message = resolve_exception(lang, "upload_requires_user")
            return self.json_message(message, HTTPStatus.UNAUTHORIZED)
        coord = _coordinator(hass)
        if coord is None:
            message = resolve_exception(lang, "integration_not_loaded")
            return self.json_message(message, HTTPStatus.NOT_FOUND)
        if coord.store.get_task(task_id) is None:
            message = resolve_exception(lang, "task_not_found", task_id=task_id)
            return self.json_message(message, HTTPStatus.NOT_FOUND)

        parsed = await _parse_upload(
            hass, self, request, want_name=True, max_bytes=MAX_TASK_PHOTO_BYTES
        )
        if isinstance(parsed, web.Response):
            return parsed
        uploaded, filename, display_name = parsed
        try:
            try:
                content_type, safe_name = task_photos.validate_photo_upload(
                    filename, uploaded.header, uploaded.size
                )
            except TaskValidationError as err:
                message = resolve_exception(lang, "invalid_task", error=str(err))
                return self.json_message(message, HTTPStatus.BAD_REQUEST)
            if replaced := _replaced_response(hass, self, coord, lang):
                return replaced
            current = coord.store.get_task(task_id) or {}
            photo_id = documents.upload_document_id(
                photo_id, (str(p.get("id")) for p in task_photos.photos_of(current))
            )
            # File and thumbnail go in place BEFORE the metadata is saved (which
            # fires ``home_keeper_task_updated``), as for a document.
            from .photo_thumbs import ThumbnailError  # lazy: Pillow

            try:
                await hass.async_add_executor_job(
                    _store_task_photo,
                    hass,
                    task_id,
                    photo_id,
                    safe_name,
                    uploaded.path,
                )
            except ThumbnailError as err:
                message = resolve_exception(lang, "invalid_task", error=str(err))
                return self.json_message(message, HTTPStatus.BAD_REQUEST)
            except OSError as err:
                _LOGGER.error("Failed to write photo for task %s: %s", task_id, err)
                message = resolve_exception(lang, "failed_to_store_file")
                return self.json_message(message, HTTPStatus.INTERNAL_SERVER_ERROR)

            try:
                entry = await coord.store.add_task_photo(
                    task_id,
                    {
                        "id": photo_id,
                        "name": display_name or documents.display_filename(filename),
                        "filename": safe_name,
                        "content_type": content_type,
                        "size": uploaded.size,
                    },
                )
            except (KeyError, TaskValidationError) as err:
                # The task is gone or full: no record names the new files.
                await async_delete_task_photo(hass, task_id, photo_id, safe_name)
                if isinstance(err, KeyError):
                    await async_delete_task_photo_dirs(hass, [task_id])
                    message = resolve_exception(lang, "task_not_found", task_id=task_id)
                    return self.json_message(message, HTTPStatus.NOT_FOUND)
                message = resolve_exception(lang, "invalid_task", error=str(err))
                return self.json_message(message, HTTPStatus.BAD_REQUEST)
            return self.json({"task": coord.store.get_task(task_id), "photo": entry})
        finally:
            await async_discard_upload(hass, uploaded)


def async_register_http(hass: HomeAssistant) -> None:
    """Register the document HTTP views (idempotent across entry reloads)."""
    if hass.data.get(f"{DOMAIN}_document_view"):
        return
    hass.http.register_view(HomeKeeperDocumentView())
    hass.http.register_view(HomeKeeperPartFileView())
    hass.http.register_view(HomeKeeperTaskPhotoView())
    hass.data[f"{DOMAIN}_document_view"] = True
