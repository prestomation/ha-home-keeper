"""Pure (HA-free) helpers for uploaded asset documents.

The on-disk storage and HTTP view live in ``manuals.py`` (which needs Home
Assistant); the security-critical, side-effect-free pieces — magic-byte sniffing,
filename sanitization, the upload allowlist/size guard, and the path-traversal guard —
live here so they stay unit-testable without an HA runtime (see
``tests/unit/test_documents.py``). This module imports nothing from Home Assistant.
"""

from __future__ import annotations

import re
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


def validate_upload(
    filename: str, declared_type: str | None, data: bytes
) -> tuple[str, str]:
    """Validate an uploaded blob; return ``(content_type, safe_filename)``.

    Raises :class:`AssetValidationError` when the file is empty, over the size ceiling,
    or not a recognized allowlisted type (sniffed by magic bytes — the declared MIME is
    advisory only). The returned content type is the sniffed one, so the stored metadata
    can't be spoofed by a misleading client header.
    """
    if not data:
        raise AssetValidationError("uploaded file is empty")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise AssetValidationError(
            f"file exceeds the {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB limit"
        )
    content_type = sniff_content_type(data)
    if content_type is None:
        raise AssetValidationError(
            "unsupported file type (allowed: PDF, PNG, JPEG, WebP, GIF)"
        )
    return content_type, safe_filename(filename, content_type)


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
