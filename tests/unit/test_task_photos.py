"""Unit tests for the pure task photo rules (``task_photos.py``, #399).

The HA-bound upload view, the thumbnail and the store wiring are covered by
``test_manuals_uploads.py``, ``test_photo_thumbs.py`` and the Docker tiers.
"""

import uuid
from pathlib import Path

import hk_task_photos as tp
import pytest
from asserts import raises_exactly
from hk_models import TaskValidationError

PNG = b"\x89PNG\r\n\x1a\n\x00\x00"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF"
PDF = b"%PDF-1.7\n..."


def _entry(**over):
    return {
        "id": str(uuid.uuid4()),
        "filename": "attic.jpg",
        "content_type": "image/jpeg",
        "size": 1234,
        **over,
    }


def _task(n=0):
    task = {"id": "t1", "photos": []}
    for i in range(n):
        tp.append_photo(task, _entry(id=f"p{i}"), created=f"2026-10-0{i + 1}")
    return task


# ── reads ───────────────────────────────────────────────────────────────────


def test_photos_of_a_task_stored_before_photos_is_empty():
    assert tp.photos_of({"id": "t"}) == []
    assert tp.photos_of({"id": "t", "photos": None}) == []
    assert tp.photos_of({"id": "t", "photos": "nonsense"}) == []


def test_cover_is_the_first_photo():
    task = _task(3)
    assert tp.cover_of(task)["id"] == "p0"
    assert tp.cover_of({"id": "t"}) is None


def test_find_photo():
    task = _task(2)
    assert tp.find_photo(task, "p1")["id"] == "p1"
    assert tp.find_photo(task, "nope") is None
    assert tp.find_photo(None, "p1") is None


# ── upload validation ───────────────────────────────────────────────────────


def test_validate_photo_upload_accepts_an_image():
    assert tp.validate_photo_upload("My Attic.JPG", JPEG, 10) == (
        "image/jpeg",
        "My_Attic.jpg",
    )
    assert tp.validate_photo_upload("a.png", PNG, 10)[0] == "image/png"


def test_validate_photo_upload_refuses_a_pdf():
    with raises_exactly(
        TaskValidationError, "unsupported photo type (allowed: PNG, JPEG, WebP, GIF)"
    ):
        tp.validate_photo_upload("manual.pdf", PDF, 10)


def test_validate_photo_upload_refuses_an_unknown_type():
    with raises_exactly(
        TaskValidationError,
        "unsupported file type (allowed: PDF, PNG, JPEG, WebP, GIF)",
    ):
        tp.validate_photo_upload("x.bin", b"\x00" * 16, 10)


def test_validate_photo_upload_refuses_an_empty_file():
    with raises_exactly(TaskValidationError, "uploaded file is empty"):
        tp.validate_photo_upload("a.jpg", JPEG, 0)


def test_validate_photo_upload_size_limit_is_inclusive():
    limit = tp.MAX_TASK_PHOTO_BYTES
    assert tp.validate_photo_upload("a.jpg", JPEG, limit)[0] == "image/jpeg"
    with raises_exactly(TaskValidationError, "a photo can be at most 25 MB"):
        tp.validate_photo_upload("a.jpg", JPEG, limit + 1)


# ── entries ─────────────────────────────────────────────────────────────────


def test_normalize_photo_entry_shape():
    entry = tp.normalize_photo_entry(
        {
            "id": "p1",
            "name": "  Attic gap  ",
            "filename": "attic.jpg",
            "content_type": "IMAGE/JPEG ",
            "size": "2048",
            "created": "2026-10-02T10:00:00+00:00",
            "extra": "dropped",
        }
    )
    assert entry == {
        "id": "p1",
        "name": "Attic gap",
        "filename": "attic.jpg",
        "content_type": "image/jpeg",
        "size": 2048,
        "created": "2026-10-02T10:00:00+00:00",
    }


def test_normalize_photo_entry_defaults():
    entry = tp.normalize_photo_entry({"filename": "a.png", "content_type": "image/png"})
    uuid.UUID(entry["id"])
    assert entry["name"] == "a.png"
    assert entry["size"] == 0
    assert entry["created"] == ""


def test_normalize_photo_entry_clamps_a_negative_size():
    assert tp.normalize_photo_entry(_entry(size=-5))["size"] == 0


def test_normalize_photo_entry_caps_the_name():
    assert len(tp.normalize_photo_entry(_entry(name="x" * 500))["name"]) == 200


@pytest.mark.parametrize(
    "filename", ["", "../evil.jpg", "a/b.jpg", ".hidden.jpg", "sp ace.jpg"]
)
def test_normalize_photo_entry_refuses_an_unsafe_filename(filename):
    with raises_exactly(TaskValidationError, "photo filename is invalid"):
        tp.normalize_photo_entry(_entry(filename=filename))


def test_normalize_photo_entry_refuses_a_pdf_type():
    with raises_exactly(
        TaskValidationError, "unsupported photo type: 'application/pdf'"
    ):
        tp.normalize_photo_entry(_entry(content_type="application/pdf"))


@pytest.mark.parametrize("size", ["big", float("inf"), [1]])
def test_normalize_photo_entry_refuses_a_bad_size(size):
    with raises_exactly(TaskValidationError, "photo size must be an integer"):
        tp.normalize_photo_entry(_entry(size=size))


def test_normalize_photo_entry_refuses_a_missing_type():
    entry = _entry()
    del entry["content_type"]
    with raises_exactly(TaskValidationError, "unsupported photo type: ''"):
        tp.normalize_photo_entry(entry)


def test_normalize_photo_entry_refuses_a_non_object():
    with raises_exactly(TaskValidationError, "each photo must be an object"):
        tp.normalize_photo_entry("attic.jpg")


# ── list operations ─────────────────────────────────────────────────────────


def test_append_photo_stamps_created_and_appends_in_order():
    task = {"id": "t"}
    first = tp.append_photo(task, _entry(id="a"), created="2026-10-01")
    tp.append_photo(task, _entry(id="b"), created="2026-10-02")
    assert first["created"] == "2026-10-01"
    assert [p["id"] for p in task["photos"]] == ["a", "b"]


def test_append_photo_ignores_a_created_from_the_caller():
    task = {"id": "t"}
    entry = tp.append_photo(task, _entry(created="1999-01-01"), created="2026-10-01")
    assert entry["created"] == "2026-10-01"


def test_append_photo_refuses_a_taken_id():
    # The files are on disk under the id before the record is saved, so a record
    # under a new id would name no file.
    task = _task(1)
    with raises_exactly(TaskValidationError, "the photo id is already in use"):
        tp.append_photo(task, _entry(id="p0"), created="x")
    assert [p["id"] for p in task["photos"]] == ["p0"]


def test_append_photo_does_not_change_the_list_in_place():
    task = _task(1)
    before = task["photos"]
    tp.append_photo(task, _entry(), created="x")
    assert len(before) == 1
    assert len(task["photos"]) == 2


def test_append_photo_cap():
    task = _task(tp.MAX_TASK_PHOTOS)
    with raises_exactly(TaskValidationError, "a task can have at most 6 photos"):
        tp.append_photo(task, _entry(), created="x")
    assert len(task["photos"]) == 6


def test_append_photo_up_to_the_cap():
    task = _task(tp.MAX_TASK_PHOTOS - 1)
    tp.append_photo(task, _entry(), created="x")
    assert len(task["photos"]) == tp.MAX_TASK_PHOTOS


def test_append_photo_bad_entry_leaves_the_task_alone():
    task = _task(1)
    with pytest.raises(TaskValidationError):
        tp.append_photo(task, _entry(filename=""), created="x")
    assert [p["id"] for p in task["photos"]] == ["p0"]


def test_remove_photo():
    task = _task(3)
    removed = tp.remove_photo(task, "p1")
    assert removed["id"] == "p1"
    assert [p["id"] for p in task["photos"]] == ["p0", "p2"]


def test_remove_the_last_photo():
    task = _task(2)
    tp.remove_photo(task, "p1")
    assert [p["id"] for p in task["photos"]] == ["p0"]
    tp.remove_photo(task, "p0")
    assert task["photos"] == []


def test_remove_an_unknown_photo():
    task = _task(2)
    assert tp.remove_photo(task, "nope") is None
    assert len(task["photos"]) == 2


def test_make_cover_moves_the_photo_to_the_front():
    task = _task(4)
    assert tp.make_cover(task, "p2") is True
    assert [p["id"] for p in task["photos"]] == ["p2", "p0", "p1", "p3"]


def test_make_cover_of_the_last_photo():
    task = _task(3)
    assert tp.make_cover(task, "p2") is True
    assert [p["id"] for p in task["photos"]] == ["p2", "p0", "p1"]


def test_make_cover_of_the_cover_changes_nothing():
    task = _task(3)
    assert tp.make_cover(task, "p0") is False
    assert [p["id"] for p in task["photos"]] == ["p0", "p1", "p2"]


def test_make_cover_of_an_unknown_photo_names_the_photo():
    # The websocket tells a gone task from a gone photo by this argument.
    with pytest.raises(KeyError) as info:
        tp.make_cover(_task(2), "nope")
    assert info.value.args == ("nope",)


# ── paths ───────────────────────────────────────────────────────────────────


def test_photo_and_thumb_paths(tmp_path: Path):
    root = tmp_path / "task_photos"
    assert tp.photo_path(root, "t1", "p1", "attic.jpg") == (
        root.resolve() / "t1" / "p1__attic.jpg"
    )
    assert tp.thumb_path(root, "t1", "p1") == (
        root.resolve() / "t1" / "thumb_p1__thumb.jpg"
    )


def test_a_photo_named_thumb_jpg_does_not_take_the_thumbnail_path(tmp_path: Path):
    root = tmp_path
    assert tp.photo_path(root, "t", "p", "thumb.jpg") != tp.thumb_path(root, "t", "p")


def test_photo_path_refuses_traversal(tmp_path: Path):
    path = tp.photo_path(tmp_path, "../../etc", "p", "passwd")
    assert path.is_relative_to(tmp_path.resolve())


def test_stray_photo_files():
    photos = [{"id": "a", "filename": "gap.jpg"}, {"id": "b", "filename": "x.png"}]
    present = [
        "a__gap.jpg",
        "thumb_a__thumb.jpg",
        "b__x.png",
        "thumb_b__thumb.jpg",
        "c__old.jpg",
        "thumb_c__thumb.jpg",
        "a__other.jpg",
        ".keep",
    ]
    assert tp.stray_photo_files(present, photos) == [
        "a__other.jpg",
        "c__old.jpg",
        "thumb_c__thumb.jpg",
    ]
    assert tp.stray_photo_files(["z", "y"], []) == ["y", "z"]
    assert tp.stray_photo_files([], photos) == []


def test_stale_task_dirs():
    present = ["t1", "t2", ".incoming", "t3"]
    assert tp.stale_task_dirs(present, {"t1", "t3"}) == ["t2"]
    assert tp.stale_task_dirs(["b", "a"], set()) == ["a", "b"]
    assert tp.stale_task_dirs([], {"t1"}) == []
