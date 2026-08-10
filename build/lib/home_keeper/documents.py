"""Pure (HA-free) helpers for uploaded asset documents.

The on-disk storage and HTTP view live in ``manuals.py`` (which needs Home
Assistant); the security-critical, side-effect-free pieces — magic-byte sniffing,
filename sanitization, the upload allowlist/size guard, and the path-traversal guard —
live here so they stay unit-testable without an HA runtime (see
``tests/unit/test_documents.py``). This module imports nothing from Home Assistant.
"""

from __future__ import annotations

import re
import time
from pathlib import Path, PurePath

from .assets import AssetValidationError
from .const import MAX_DOCUMENT_BYTES

# content-type -> canonical extension. The key set is the upload allowlist.
TYPE_EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

_MAX_FILENAME_LEN = 120

# How many leading bytes ``sniff_content_type`` needs. The longest signature check
# reads ``data[8:12]`` (WebP), so 16 is comfortably enough — uploads are streamed to
# disk, and this is all that's kept in memory to identify the type.
SNIFF_BYTES = 16


def sniff_content_type(data: bytes) -> str | None:
    """Return the allowlisted content type *data* matches by magic bytes, or None."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def safe_filename(name: str, content_type: str) -> str:
    """Sanitize an uploaded filename to a plain, extension-correct basename.

    Strips any path component, collapses unusual characters, guarantees a non-empty
    stem, and forces the canonical extension for *content_type* so the served file is
    typed consistently regardless of what the client claimed.
    """
    base = PurePath(str(name)).name
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")
    stem = PurePath(base).stem or "document"
    stem = stem[:_MAX_FILENAME_LEN]
    return f"{stem}{TYPE_EXTENSIONS[content_type]}"


def validate_upload_stream(filename: str, header: bytes, size: int) -> tuple[str, str]:
    """Validate a streamed upload from its first bytes and total size.

    The counterpart to :func:`validate_upload` for uploads that are written straight
    to disk and never held in memory (see ``manuals._parse_upload``): everything the
    checks need is the leading ``header`` (at least :data:`SNIFF_BYTES`) and the byte
    count. Returns ``(content_type, safe_filename)``.

    Raises :class:`AssetValidationError` when the file is empty, over the size ceiling,
    or not a recognized allowlisted type (sniffed by magic bytes — any client-declared
    MIME is ignored entirely). The returned content type is the sniffed one, so the
    stored metadata can't be spoofed by a misleading client header.
    """
    if size <= 0:
        raise AssetValidationError("uploaded file is empty")
    if size > MAX_DOCUMENT_BYTES:
        raise AssetValidationError(
            f"file exceeds the {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB limit"
        )
    content_type = sniff_content_type(header)
    if content_type is None:
        raise AssetValidationError(
            "unsupported file type (allowed: PDF, PNG, JPEG, WebP, GIF)"
        )
    return content_type, safe_filename(filename, content_type)


def validate_upload(filename: str, data: bytes) -> tuple[str, str]:
    """Validate an in-memory uploaded blob; return ``(content_type, safe_filename)``.

    Thin wrapper over :func:`validate_upload_stream` for callers that already hold the
    whole file. The HTTP upload path does *not* — it streams to disk — so prefer the
    stream variant for anything that could be large.
    """
    return validate_upload_stream(filename, data[:SNIFF_BYTES], len(data))


def purge_stale_temps(tmp_root: Path, max_age_s: float) -> None:
    """Delete temp uploads old enough that no request can still be writing them.

    Deliberately age-based rather than a blanket wipe of *tmp_root*: the caller runs
    this at setup, which re-runs on every config entry *reload* while the upload view
    stays registered — clearing the directory outright could delete the temp file an
    in-flight upload is still writing, turning it into a 500 mid-transfer.
    """
    if not tmp_root.is_dir():
        return
    cutoff = time.time() - max_age_s
    for path in tmp_root.glob("upload-*"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            # Raced with the upload that owns it, or it vanished — try again next time.
            continue


def safe_segment(value: str) -> str:
    """Reduce an id/filename to a single safe path segment (defense in depth)."""
    seg = re.sub(r"[^A-Za-z0-9._-]", "_", PurePath(str(value)).name).lstrip(".")
    if not seg or seg in (".", ".."):
        raise AssetValidationError("invalid document path")
    return seg


def resolve_under_root(root: Path, *parts: str) -> Path:
    """Join *parts* under *root* and assert the result stays inside it.

    Each part is first reduced to a safe single segment, then the fully-resolved path
    is checked to be relative to the resolved root — a belt-and-braces guard against a
    crafted asset/document id or filename escaping the storage tree (``..``, absolute
    paths, separators).
    """
    root = root.resolve()
    candidate = root.joinpath(*(safe_segment(p) for p in parts)).resolve()
    if not candidate.is_relative_to(root):
        raise AssetValidationError("document path escapes the storage root")
    return candidate


def document_path(root: Path, asset_id: str, document_id: str, filename: str) -> Path:
    """The on-disk path for an uploaded document, guarded against traversal."""
    return resolve_under_root(
        root, asset_id, f"{document_id}__{safe_segment(filename)}"
    )
