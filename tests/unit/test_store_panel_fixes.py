"""Store paths behind two panel fixes.

X08-1 / F07-5: "Remove orphaned tasks" deletes every orphaned managed task in one
store save, instead of one ``delete_task`` (and one entry reload) per task.

F10-1: after a task stops recording readings (its type or sensor mode changed), its
old completions and skips can still be edited. The edit form sends the stored
reading back, and that is not a change.

The harness is ``test_store_consumable.py``'s: a fake ``Store`` and a fake ``hass``.
"""

from __future__ import annotations

import sys

import pytest
from asserts import raises_exactly
from test_store_consumable import NOW, _run, _task, store  # noqa: F401

EVENT_TASK_DELETED = "home_keeper_task_deleted"
READING_ERROR = "reading is only valid for a sensor task with a numeric binding"


def _managed(store, entry_id: str, **extra):  # noqa: F811
    managed_by = {
        "integration": "glue",
        "display_name": "Glue",
        "config_entry_id": entry_id,
        **extra,
    }
    task = _task(store)
    task["managed_by"] = managed_by
    return task


# ── X08-1: delete_orphaned_tasks ─────────────────────────────────────────────


def test_x08_1_deletes_every_orphan_in_one_save(store):  # noqa: F811
    gone_a = _managed(store, "gone")
    gone_b = _managed(store, "gone", deletion_protected=True)
    live = _managed(store, "entry1", deletion_protected=True)
    plain = _task(store)
    saves_before = store._store.saves

    removed = _run(store.delete_orphaned_tasks())

    assert sorted(t["id"] for t in removed) == sorted([gone_a["id"], gone_b["id"]])
    assert set(store._tasks) == {live["id"], plain["id"]}
    assert store._store.saves == saves_before + 1
    fired = store._hass.bus.of(EVENT_TASK_DELETED)
    assert sorted(e["task_id"] for e in fired) == sorted([gone_a["id"], gone_b["id"]])


def test_x08_1_leaves_a_task_a_single_delete_would_refuse(store):  # noqa: F811
    wear = _managed(store, "gone")
    wear["source"] = {"part": {"asset_id": "a1", "part_id": "p1"}}
    buy = _managed(store, "gone")
    buy["source"] = {"buy": {"asset_id": "a1", "part_id": "p1"}}
    orphan = _managed(store, "gone")

    removed = _run(store.delete_orphaned_tasks())

    assert [t["id"] for t in removed] == [orphan["id"]]
    assert wear["id"] in store._tasks
    assert buy["id"] in store._tasks


def test_x08_1_saves_nothing_when_there_is_no_orphan(store):  # noqa: F811
    _managed(store, "entry1")
    _task(store)
    saves_before = store._store.saves

    assert _run(store.delete_orphaned_tasks()) == []
    assert store._store.saves == saves_before
    assert store._hass.bus.of(EVENT_TASK_DELETED) == []


def test_x08_1_single_delete_still_refuses_a_protected_live_task(store):  # noqa: F811
    live = _managed(store, "entry1", deletion_protected=True)
    with raises_exactly(
        sys.modules["hk.models"].TaskValidationError,
        "This task is managed by Glue. Delete it from Glue instead.",
    ):
        _run(store.delete_task(live["id"]))
    _run(store.delete_task(live["id"], force=True))
    assert live["id"] not in store._tasks


# ── F10-1: edit a logged entry after the task stopped recording readings ────

TS = "2026-06-01T10:00:00-04:00"


def _floating_with_history(store):  # noqa: F811
    """A floating task whose history came from its sensor days."""
    task = _task(store)
    task["completions"] = [{"ts": TS, "reading": 55.0, "note": "old"}]
    task["skips"] = [{"ts": TS, "reading": 55.0, "note": "old skip"}]
    return task


def test_f10_1_a_note_edit_on_a_completion_keeps_its_reading(store):  # noqa: F811
    task = _floating_with_history(store)
    updated = _run(
        store.update_completion(task["id"], TS, {"reading": 55.0, "note": "new"})
    )
    assert updated["completions"][0] == {"ts": TS, "reading": 55.0, "note": "new"}


def test_f10_1_a_note_edit_on_a_skip_keeps_its_reading(store):  # noqa: F811
    task = _floating_with_history(store)
    updated = _run(store.update_skip(task["id"], TS, {"note": "new skip"}))
    assert updated["skips"][0] == {"ts": TS, "reading": 55.0, "note": "new skip"}


@pytest.mark.parametrize("method", ["update_completion", "update_skip"])
def test_f10_1_a_changed_reading_is_still_refused(store, method):  # noqa: F811
    task = _floating_with_history(store)
    with raises_exactly(sys.modules["hk.models"].TaskValidationError, READING_ERROR):
        _run(getattr(store, method)(task["id"], TS, {"reading": 60.0}))


# ── B09-5: a rename of a part-owned task is refused, not reverted later ──────


def test_b09_5_update_task_refuses_a_rename_of_a_wear_item_task(store):  # noqa: F811
    task = _task(store)
    task["source"] = {"part": {"asset_id": "a1", "part_id": "p1"}}
    with pytest.raises(sys.modules["hk.models"].TaskValidationError, match="part"):
        _run(store.update_task(task["id"], {"name": "Swap the filter"}))
    assert store._tasks[task["id"]]["name"] == "Replace battery"


def test_b09_5_update_task_keeps_a_rename_of_a_manual_link(store):  # noqa: F811
    task = _task(store)
    task["source"] = {"part": {"asset_id": "a1", "part_id": "p1", "manual": True}}
    updated = _run(store.update_task(task["id"], {"name": "Swap the filter"}))
    assert updated["name"] == "Swap the filter"
