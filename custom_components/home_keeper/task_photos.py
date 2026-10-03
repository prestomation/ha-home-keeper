"""Pure (HA-free) rules for the photos on a task (#399).

A task carries ``photos``: an ordered list of up to :data:`MAX_TASK_PHOTOS` uploaded
images. The first one is the cover. Each entry is
``{id, name, filename, content_type, size, created}``, the same file metadata that an
appliance's uploaded document carries. The bytes live on disk (see ``manuals.py``),
in one folder per task: ``<task_id>/<photo_id>__<filename>`` plus a JPEG thumbnail
``<task_id>/thumb_<photo_id>__thumb.jpg``. The ``thumb_`` key keeps a photo
uploaded as ``thumb.jpg`` off the thumbnail's path.

Photos are **upload-only**. The upload view and the photo services are the only
writers. ``models.build_task`` and ``models.merge_update`` never take ``photos`` from
a caller, so ``add_task``, ``update_task`` and an import cannot name a file that is
not on disk. This module imports nothing from Home Assistant.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from . import documents
from .const import MAX_TASK_PHOTO_BYTES, MAX_TASK_PHOTOS
from .models import TaskValidationError

# The image half of the document allowlist. A PDF is a fine manual but not a photo.
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
THUMB_FILENAME = "thumb.jpg"
_MAX_NAME_LEN = 200


def photos_of(task: dict[str, Any]) -> list[dict[str, Any]]:
    """The task's photo list. A task stored before #399 has none."""
    photos = task.get("photos")
    return photos if isinstance(photos, list) else []


def cover_of(task: dict[str, Any]) -> dict[str, Any] | None:
    """The cover photo (the first one), or None."""
    photos = photos_of(task)
    return photos[0] if photos else None


def validate_photo_upload(filename: str, header: bytes, size: int) -> tuple[str, str]:
    """Check a streamed upload is a photo. Returns ``(content_type, safe_filename)``.

    The document checks run first (empty, magic bytes), then the two that are
    stricter for a photo: an image type only, and the smaller size limit.
    """
    if size > MAX_TASK_PHOTO_BYTES:
        raise TaskValidationError(
            f"a photo can be at most {MAX_TASK_PHOTO_BYTES // (1024 * 1024)} MB"
        )
    try:
        content_type, safe_name = documents.validate_upload_stream(
            filename, header, size
        )
    except documents.AssetValidationError as err:
        raise TaskValidationError(str(err)) from err
    if content_type not in IMAGE_TYPES:
        raise TaskValidationError(
            "unsupported photo type (allowed: PNG, JPEG, WebP, GIF)"
        )
    return content_type, safe_name


def normalize_photo_entry(raw: Any) -> dict[str, Any]:
    """Validate one photo entry and return it in its stored shape."""
    if not isinstance(raw, dict):
        raise TaskValidationError("each photo must be an object")
    filename = str(raw.get("filename") or "").strip()
    try:
        safe = documents.safe_segment(filename)
    except documents.AssetValidationError as err:
        raise TaskValidationError("photo filename is invalid") from err
    if safe != filename:
        raise TaskValidationError("photo filename is invalid")
    content_type = str(raw.get("content_type") or "").strip().lower()
    if content_type not in IMAGE_TYPES:
        raise TaskValidationError(f"unsupported photo type: {content_type!r}")
    try:
        size = max(0, int(raw.get("size") or 0))
    # int() of an infinite float raises OverflowError (B05-6).
    except (TypeError, ValueError, OverflowError) as err:
        raise TaskValidationError("photo size must be an integer") from err
    name = documents.display_filename(str(raw.get("name") or ""))[:_MAX_NAME_LEN]
    return {
        "id": str(raw.get("id") or uuid.uuid4()),
        "name": name or filename,
        "filename": filename,
        "content_type": content_type,
        "size": size,
        "created": str(raw.get("created") or ""),
    }


def append_photo(task: dict[str, Any], raw: Any, *, created: str) -> dict[str, Any]:
    """Validate *raw* as a new photo and append it to *task* (in place).

    *created* is the ISO timestamp the store stamps (this module has no clock). A
    taken id gets a new one. Returns the stored entry.
    """
    photos = list(photos_of(task))
    if len(photos) >= MAX_TASK_PHOTOS:
        raise TaskValidationError(f"a task can have at most {MAX_TASK_PHOTOS} photos")
    entry = normalize_photo_entry({**raw, "created": created})
    if entry["id"] in {p.get("id") for p in photos}:
        entry["id"] = str(uuid.uuid4())
    photos.append(entry)
    task["photos"] = photos
    return entry


def remove_photo(task: dict[str, Any], photo_id: str) -> dict[str, Any] | None:
    """Remove the photo *photo_id* from *task* (in place); return it, or None."""
    photos = photos_of(task)
    for index, photo in enumerate(photos):
        if photo.get("id") == photo_id:
            task["photos"] = photos[:index] + photos[index + 1 :]
            return photo
    return None


def make_cover(task: dict[str, Any], photo_id: str) -> bool:
    """Move *photo_id* to the front of the list (in place).

    Returns whether the order changed. Raises ``KeyError`` for an unknown photo.
    """
    photos = photos_of(task)
    for index, photo in enumerate(photos):
        if photo.get("id") == photo_id:
            if index == 0:
                return False
            task["photos"] = [photo, *photos[:index], *photos[index + 1 :]]
            return True
    raise KeyError(photo_id)


def find_photo(task: dict[str, Any] | None, photo_id: str) -> dict[str, Any] | None:
    """The photo *photo_id* of *task*, or None."""
    for photo in photos_of(task or {}):
        if photo.get("id") == photo_id:
            return photo
    return None


def photo_path(root: Path, task_id: str, photo_id: str, filename: str) -> Path:
    """The on-disk path of a photo, guarded against traversal. Blocking."""
    return documents.document_path(root, task_id, photo_id, filename)


def thumb_path(root: Path, task_id: str, photo_id: str) -> Path:
    """The on-disk path of a photo's thumbnail. Blocking."""
    return documents.document_path(root, task_id, f"thumb_{photo_id}", THUMB_FILENAME)


def stale_task_dirs(present: list[str], live_ids: set[str]) -> list[str]:
    """The folder names under the photo root that belong to no live task.

    *present* is the listing of the root. Names with a leading dot are the upload
    area and similar, never a task, so they stay.
    """
    return sorted(
        name for name in present if not name.startswith(".") and name not in live_ids
    )
