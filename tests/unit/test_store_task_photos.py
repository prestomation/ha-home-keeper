"""The store side of task photos (#399).

The harness is ``test_store_consumable.py``'s: a fake ``Store`` and a fake ``hass``.
``hk.manuals`` there is a double, so these tests record which files the store asks
it to delete rather than touching a disk.
"""

from __future__ import annotations

import sys

import pytest
from asserts import raises_exactly
from test_store_consumable import (  # noqa: F401
    TaskValidationError,
    _run,
    _task,
    store,
)

EVENT_TASK_UPDATED = "home_keeper_task_updated"


@pytest.fixture
def deleted(monkeypatch):
    """Record the photo deletes the store asks ``manuals`` for."""
    calls: list[tuple] = []
    manuals = sys.modules["hk.manuals"]

    async def _photo(hass, task_id, photo_id, filename):
        calls.append(("photo", task_id, photo_id, filename))

    async def _dirs(hass, task_ids):
        calls.append(("dirs", list(task_ids)))

    monkeypatch.setattr(manuals, "async_delete_task_photo", _photo, raising=False)
    monkeypatch.setattr(manuals, "async_delete_task_photo_dirs", _dirs, raising=False)
    return calls


def _photo(n: int) -> dict:
    return {
        "id": f"p{n}",
        "filename": f"p{n}.jpg",
        "content_type": "image/jpeg",
        "size": 10,
    }


def _with_photos(store, n):  # noqa: F811
    task = _task(store)
    for i in range(n):
        _run(store.add_task_photo(task["id"], _photo(i)))
    return task


def test_add_task_photo_saves_stamps_and_fires(store):  # noqa: F811
    task = _task(store)
    saves = store._store.saves

    entry = _run(store.add_task_photo(task["id"], _photo(0)))

    assert entry["id"] == "p0"
    assert entry["created"]
    assert store._tasks[task["id"]]["photos"] == [entry]
    assert store._store.saves == saves + 1
    fired = store._hass.bus.of(EVENT_TASK_UPDATED)
    assert [e["changed_fields"] for e in fired] == [["photos"]]
    assert fired[0]["task_id"] == task["id"]


def test_add_task_photo_to_an_unknown_task(store):  # noqa: F811
    with pytest.raises(KeyError):
        _run(store.add_task_photo("nope", _photo(0)))


def test_add_task_photo_to_a_full_task(store):  # noqa: F811
    task = _with_photos(store, 6)
    saves = store._store.saves
    with raises_exactly(TaskValidationError, "a task can have at most 6 photos"):
        _run(store.add_task_photo(task["id"], _photo(9)))
    assert store._store.saves == saves


def test_remove_task_photo_deletes_its_files(store, deleted):  # noqa: F811
    task = _with_photos(store, 2)
    store._hass.bus.fired.clear()

    updated = _run(store.remove_task_photo(task["id"], "p0"))

    assert [p["id"] for p in updated["photos"]] == ["p1"]
    assert deleted == [("photo", task["id"], "p0", "p0.jpg")]
    fired = store._hass.bus.of(EVENT_TASK_UPDATED)
    assert [e["changed_fields"] for e in fired] == [["photos"]]


def test_remove_task_photo_saves_before_it_deletes(store, monkeypatch):  # noqa: F811
    # A delete that does not finish leaves a file with no record, which the setup
    # sweep removes. A save that does not happen must not leave a record with no file.
    task = _with_photos(store, 1)
    order: list[str] = []
    manuals = sys.modules["hk.manuals"]

    async def _photo(hass, task_id, photo_id, filename):
        order.append(f"delete:{store._store.saves}")

    monkeypatch.setattr(manuals, "async_delete_task_photo", _photo, raising=False)
    saves = store._store.saves
    _run(store.remove_task_photo(task["id"], "p0"))
    assert order == [f"delete:{saves + 1}"]


def test_remove_task_photo_keeps_the_files_when_the_save_fails(
    store,  # noqa: F811
    deleted,
    monkeypatch,
):
    task = _with_photos(store, 1)

    async def _fail() -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(store, "_save", _fail)
    with pytest.raises(RuntimeError):
        _run(store.remove_task_photo(task["id"], "p0"))
    assert deleted == []


def test_remove_an_unknown_task_photo(store, deleted):  # noqa: F811
    task = _with_photos(store, 1)
    with pytest.raises(KeyError):
        _run(store.remove_task_photo(task["id"], "nope"))
    assert deleted == []


def test_set_task_photo_cover(store):  # noqa: F811
    task = _with_photos(store, 3)
    store._hass.bus.fired.clear()

    updated = _run(store.set_task_photo_cover(task["id"], "p2"))

    assert [p["id"] for p in updated["photos"]] == ["p2", "p0", "p1"]
    assert len(store._hass.bus.of(EVENT_TASK_UPDATED)) == 1


def test_set_the_cover_that_is_already_the_cover_saves_nothing(store):  # noqa: F811
    task = _with_photos(store, 2)
    saves = store._store.saves
    store._hass.bus.fired.clear()

    _run(store.set_task_photo_cover(task["id"], "p0"))

    assert store._store.saves == saves
    assert store._hass.bus.of(EVENT_TASK_UPDATED) == []


def test_an_owner_cannot_lock_photos(store, deleted):  # noqa: F811
    # Photos belong to the household, like the stock of a managed part. ``photos`` in
    # ``locked_fields`` has no effect: add, cover and remove all still work.
    task = _task(
        store,
        managed_by={"integration": "x", "locked_fields": ["name", "photos"]},
    )
    for i in range(2):
        _run(store.add_task_photo(task["id"], _photo(i)))
    _run(store.set_task_photo_cover(task["id"], "p1"))
    updated = _run(store.remove_task_photo(task["id"], "p0"))

    assert [p["id"] for p in updated["photos"]] == ["p1"]
    assert deleted == [("photo", task["id"], "p0", "p0.jpg")]


def test_set_the_cover_of_an_unknown_photo(store):  # noqa: F811
    task = _with_photos(store, 1)
    with pytest.raises(KeyError):
        _run(store.set_task_photo_cover(task["id"], "nope"))


def test_deleting_a_task_with_photos_deletes_its_folder(store, deleted):  # noqa: F811
    task = _with_photos(store, 1)
    other = _task(store)

    _run(store.delete_task(task["id"]))
    _run(store.delete_task(other["id"]))

    assert deleted == [("dirs", [task["id"]])]


def test_a_task_removed_by_any_path_loses_its_folder(store, deleted):  # noqa: F811
    task = _with_photos(store, 1)
    # A reconciler replaces the map without calling delete_task.
    store._tasks = {}
    _run(store.async_persist())
    assert deleted == [("dirs", [task["id"]])]
    # The next save does not delete it again.
    _run(store.async_persist())
    assert deleted == [("dirs", [task["id"]])]


def test_update_task_does_not_write_photos(store):  # noqa: F811
    task = _with_photos(store, 1)
    _run(store.update_task(task["id"], {"name": "Renamed", "photos": []}))
    assert [p["id"] for p in store._tasks[task["id"]]["photos"]] == ["p0"]
