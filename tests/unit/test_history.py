"""Unit tests for task ↔ appliance association and completion-history retention.

These exercise the pure ``assets`` helpers that back the panel's history views and
the reference-counting retention of a deleted task's completions (no Home Assistant
runtime; the ``store`` wiring that calls them is covered by the integration tests).
"""

import hk_assets as a


def _asset(**over):
    base = {
        "id": "asset1",
        "kind": "virtual",
        "name": "Water heater",
        "device_id": "dev1",
        "related_device_ids": ["dev2"],
        "parts": [],
    }
    base.update(over)
    return base


def _part_task(asset_id="asset1", part_id="p1", **over):
    task = {
        "id": "t1",
        "name": "Replace anode",
        "completions": [{"ts": "2025-05-01T10:00:00-04:00"}],
        "source": {"part": {"asset_id": asset_id, "part_id": part_id}},
    }
    task.update(over)
    return task


# ── association ──────────────────────────────────────────────────────────────
def test_relates_by_part_source():
    assert a.task_relates_to_asset(_part_task(), _asset()) is True


def test_relates_by_attached_device():
    task = {"id": "t", "name": "x", "device_id": "dev1"}
    assert a.task_relates_to_asset(task, _asset()) is True


def test_relates_by_related_device():
    task = {"id": "t", "name": "x", "device_id": "dev2"}
    assert a.task_relates_to_asset(task, _asset()) is True


def test_unrelated_standalone_task():
    assert a.task_relates_to_asset({"id": "t", "name": "x"}, _asset()) is False
    assert a.task_relates_to_asset({"id": "t", "name": "x", "device_id": "z"}, _asset()) is False


def test_tasks_for_asset_filters():
    tasks = [
        {"id": "a", "name": "a", "device_id": "dev1"},
        {"id": "b", "name": "b", "device_id": "nope"},
        _part_task(),
    ]
    assert [t["id"] for t in a.tasks_for_asset(_asset(), tasks)] == ["a", "t1"]


# ── archiving target precedence ──────────────────────────────────────────────
def test_find_archiving_asset_prefers_part_source():
    assets = {"asset1": _asset(), "asset2": _asset(id="asset2", device_id="dev1")}
    # The part-source asset wins even though asset2 also owns the task's device.
    found = a.find_archiving_asset(assets, _part_task(device_id="dev1"))
    assert found["id"] == "asset1"


def test_find_archiving_asset_by_device():
    assets = {"asset1": _asset()}
    found = a.find_archiving_asset(assets, {"id": "t", "name": "x", "device_id": "dev1"})
    assert found["id"] == "asset1"


def test_find_archiving_asset_none_for_standalone():
    assets = {"asset1": _asset()}
    assert a.find_archiving_asset(assets, {"id": "t", "name": "x"}) is None
    assert a.find_archiving_asset(assets, {"id": "t", "name": "x", "device_id": "z"}) is None


def test_find_archiving_asset_part_source_missing_asset():
    # The part's asset no longer exists -> nothing to archive onto.
    assert a.find_archiving_asset({}, _part_task()) is None


# ── archive entry construction & append ──────────────────────────────────────
def test_build_archived_history_snapshots_name_and_part():
    entry = a.build_archived_history(_part_task(), archived_at="2026-06-15T00:00:00-04:00")
    assert entry["task_id"] == "t1"
    assert entry["task_name"] == "Replace anode"
    assert entry["part_id"] == "p1"
    assert entry["completions"] == [{"ts": "2025-05-01T10:00:00-04:00"}]
    assert entry["archived_at"] == "2026-06-15T00:00:00-04:00"


def test_build_archived_history_standalone_has_no_part():
    entry = a.build_archived_history(
        {"id": "t", "name": "Flush tank", "completions": [{"ts": "2025-01-01T00:00:00-04:00"}]},
        archived_at="2026-06-15T00:00:00-04:00",
    )
    assert entry["part_id"] is None


def test_append_task_history_appends_and_returns_true():
    asset = _asset()
    entry = a.build_archived_history(_part_task(), archived_at="2026-06-15T00:00:00-04:00")
    assert a.append_task_history(asset, entry) is True
    assert asset["task_history"] == [entry]


def test_append_task_history_skips_empty_completions():
    asset = _asset()
    entry = a.build_archived_history(
        {"id": "t", "name": "x", "completions": []}, archived_at="2026-06-15T00:00:00-04:00"
    )
    assert a.append_task_history(asset, entry) is False
    assert "task_history" not in asset


def test_append_task_history_dedupes_by_task_id():
    asset = _asset()
    entry = a.build_archived_history(_part_task(), archived_at="2026-06-15T00:00:00-04:00")
    assert a.append_task_history(asset, entry) is True
    assert a.append_task_history(asset, entry) is False
    assert len(asset["task_history"]) == 1
