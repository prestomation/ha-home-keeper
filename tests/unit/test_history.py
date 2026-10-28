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
    assert (
        a.task_relates_to_asset({"id": "t", "name": "x", "device_id": "z"}, _asset())
        is False
    )


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


def test_find_archiving_asset_part_source_wins_over_an_earlier_device_owner():
    # The device owner comes first in the dict, so only the part link finds "part".
    assets = {
        "owner": _asset(id="owner"),
        "part": _asset(id="part", device_id="other", related_device_ids=[]),
    }
    found = a.find_archiving_asset(
        assets, _part_task(asset_id="part", device_id="dev1")
    )
    assert found["id"] == "part"


def test_find_archiving_asset_by_related_device():
    # dev2 is not the asset's own device, only 1 of its related devices.
    assets = {"asset1": _asset()}
    found = a.find_archiving_asset(
        assets, {"id": "t", "name": "x", "device_id": "dev2"}
    )
    assert found["id"] == "asset1"


def test_find_archiving_asset_by_device():
    assets = {"asset1": _asset()}
    found = a.find_archiving_asset(
        assets, {"id": "t", "name": "x", "device_id": "dev1"}
    )
    assert found["id"] == "asset1"


def test_find_archiving_asset_none_for_standalone():
    assets = {"asset1": _asset()}
    assert a.find_archiving_asset(assets, {"id": "t", "name": "x"}) is None
    assert (
        a.find_archiving_asset(assets, {"id": "t", "name": "x", "device_id": "z"})
        is None
    )


def test_find_archiving_asset_part_source_missing_asset():
    # The part's asset no longer exists -> nothing to archive onto.
    assert a.find_archiving_asset({}, _part_task()) is None


# ── archive entry construction & append ──────────────────────────────────────
def test_build_archived_history_snapshots_name_and_part():
    entry = a.build_archived_history(
        _part_task(), archived_at="2026-06-15T00:00:00-04:00"
    )
    assert entry["task_id"] == "t1"
    assert entry["task_name"] == "Replace anode"
    assert entry["part_id"] == "p1"
    assert entry["completions"] == [{"ts": "2025-05-01T10:00:00-04:00"}]
    assert entry["archived_at"] == "2026-06-15T00:00:00-04:00"


def test_build_archived_history_standalone_has_no_part():
    entry = a.build_archived_history(
        {
            "id": "t",
            "name": "Flush tank",
            "completions": [{"ts": "2025-01-01T00:00:00-04:00"}],
        },
        archived_at="2026-06-15T00:00:00-04:00",
    )
    assert entry["part_id"] is None


def test_append_task_history_appends_and_returns_true():
    asset = _asset()
    entry = a.build_archived_history(
        _part_task(), archived_at="2026-06-15T00:00:00-04:00"
    )
    assert a.append_task_history(asset, entry) is True
    assert asset["task_history"] == [entry]


def test_append_task_history_skips_empty_completions():
    asset = _asset()
    entry = a.build_archived_history(
        {"id": "t", "name": "x", "completions": []},
        archived_at="2026-06-15T00:00:00-04:00",
    )
    assert a.append_task_history(asset, entry) is False
    assert "task_history" not in asset


def test_append_task_history_dedupes_by_task_id():
    asset = _asset()
    entry = a.build_archived_history(
        _part_task(), archived_at="2026-06-15T00:00:00-04:00"
    )
    assert a.append_task_history(asset, entry) is True
    assert a.append_task_history(asset, entry) is False
    assert len(asset["task_history"]) == 1


# ── archived-completion deletion ─────────────────────────────────────────────
def _asset_with_history():
    asset = _asset()
    asset["task_history"] = [
        {
            "task_id": "old_flush",
            "task_name": "Flush tank",
            "part_id": None,
            "completions": [
                {"ts": "2023-06-01T10:00:00-04:00"},
                {"ts": "2024-06-01T10:00:00-04:00"},
            ],
            "archived_at": "2025-06-15T10:00:00-04:00",
        }
    ]
    return asset


def test_remove_archived_completion_drops_one():
    asset = _asset_with_history()
    assert (
        a.remove_archived_completion(asset, "old_flush", "2024-06-01T10:00:00-04:00")
        is True
    )
    assert asset["task_history"][0]["completions"] == [
        {"ts": "2023-06-01T10:00:00-04:00"}
    ]


def test_remove_archived_completion_drops_entry_when_emptied():
    asset = _asset_with_history()
    asset["task_history"][0]["completions"] = [{"ts": "2023-06-01T10:00:00-04:00"}]
    assert (
        a.remove_archived_completion(asset, "old_flush", "2023-06-01T10:00:00-04:00")
        is True
    )
    assert asset["task_history"] == []


def test_remove_archived_completion_missing_is_noop():
    asset = _asset_with_history()
    assert (
        a.remove_archived_completion(asset, "old_flush", "2099-01-01T00:00:00-04:00")
        is False
    )
    assert (
        a.remove_archived_completion(asset, "no_such_task", "2024-06-01T10:00:00-04:00")
        is False
    )
    assert a.remove_archived_completion(_asset(), "x", "y") is False


def _listed_task(*asset_ids, **over):
    """A task linked to a consumable on each of *asset_ids* (#493)."""
    parts = [{"asset_id": aid, "part_id": f"p{n}"} for n, aid in enumerate(asset_ids)]
    return {"id": "t1", "name": "Replace filters", "source": {"parts": parts}, **over}


def test_493_a_task_relates_to_each_appliance_whose_part_it_takes():
    task = _listed_task("other", "asset1")
    assert a.task_relates_to_asset(task, _asset()) is True
    assert a.task_relates_to_asset(task, _asset(id="other")) is True
    assert a.task_relates_to_asset(task, _asset(id="third")) is False
    assert a.task_relates_to_asset(_listed_task(), _asset()) is False


def test_493_the_first_linked_appliance_keeps_the_history():
    assets = {
        "asset1": _asset(),
        "other": _asset(id="other", device_id="dev1"),
    }
    found = a.find_archiving_asset(assets, _listed_task("gone", "asset1", "other"))
    assert found["id"] == "asset1"
    # The link wins over the device, as a wear part does.
    found = a.find_archiving_asset(assets, _listed_task("asset1", device_id="dev1"))
    assert found["id"] == "asset1"


def test_493_a_malformed_list_relates_to_nothing():
    task = {"id": "t", "name": "x", "source": {"parts": ["asset1", {"part_id": "p"}]}}
    assert a.task_relates_to_asset(task, _asset()) is False
    assert (
        a.task_relates_to_asset({"id": "t", "source": {"parts": None}}, _asset())
        is False
    )
