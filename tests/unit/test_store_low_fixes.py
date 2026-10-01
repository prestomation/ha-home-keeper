"""Store rules behind 3 low findings.

* B03-5: a skip entry keeps only the skip fields. ``cost`` and ``photo`` belong to
  a completion, and ``update_skip`` cannot clear them from a skip.
* B02-8: ``set_sensor_baseline`` rejects NaN and infinity, as ``models`` does for
  every other stored number.
* B17-8: only a virtual appliance can be a parent, because only it has a Home
  Keeper device to nest under.

The harness is ``test_store_consumable.py``'s: a fake ``Store`` and a fake ``hass``.
"""

from __future__ import annotations

import math

import pytest
from asserts import raises_exactly
from test_store_consumable import (  # noqa: F401
    AssetValidationError,
    TaskValidationError,
    _run,
    _task,
    store,
)

EVENT_TASK_UPDATED = "home_keeper_task_updated"


# ── B03-5 ────────────────────────────────────────────────────────────────────
def test_b03_5_a_skip_keeps_only_the_skip_fields(store):  # noqa: F811
    task = _task(store)
    updated = _run(
        store.skip_task(
            task["id"],
            metadata={
                "note": "away",
                "who": "Sam",
                "cost": 50,
                "photo": "https://example.com/y.jpg",
            },
        )
    )
    entry = updated["skips"][-1]
    assert entry["note"] == "away"
    assert entry["who"] == "Sam"
    assert "cost" not in entry
    assert "photo" not in entry


def test_b03_5_a_skip_with_only_completion_fields_records_no_metadata(store):  # noqa: F811
    task = _task(store)
    updated = _run(store.skip_task(task["id"], metadata={"cost": 12.5}))
    assert set(updated["skips"][-1]) == {"ts"}


# ── B02-8 ────────────────────────────────────────────────────────────────────
def _usage_task(store):  # noqa: F811
    return _task(
        store,
        recurrence_type="sensor",
        sensor={
            "mode": "usage",
            "entity_id": "sensor.odometer",
            "target": 5000,
            "baseline": 25000,
        },
    )


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_b02_8_a_non_finite_baseline_is_rejected(store, value):  # noqa: F811
    task = _usage_task(store)
    saves = store._store.saves
    with raises_exactly(TaskValidationError, "sensor.baseline must be a finite number"):
        _run(store.set_sensor_baseline(task["id"], value, silent=False))
    assert store._tasks[task["id"]]["sensor"]["baseline"] == 25000
    assert store._store.saves == saves
    assert store._hass.bus.of(EVENT_TASK_UPDATED) == []


def test_b02_8_a_finite_baseline_is_stored(store):  # noqa: F811
    task = _usage_task(store)
    _run(store.set_sensor_baseline(task["id"], 30000.0, silent=False))
    assert store._tasks[task["id"]]["sensor"]["baseline"] == 30000.0
    assert len(store._hass.bus.of(EVENT_TASK_UPDATED)) == 1


def test_b02_8_an_unknown_task_is_still_a_key_error(store):  # noqa: F811
    with pytest.raises(KeyError):
        _run(store.set_sensor_baseline("missing", math.nan))


# ── B17-8 ────────────────────────────────────────────────────────────────────
def _parent(store, kind):  # noqa: F811
    return _run(
        store.add_asset(
            {"name": f"{kind} parent", "kind": kind, "device_id": "dev1"}
            if kind == "existing"
            else {"name": f"{kind} parent"}
        )
    )


def test_b17_8_an_existing_kind_parent_is_rejected_on_add(store):  # noqa: F811
    parent = _parent(store, "existing")
    with raises_exactly(
        AssetValidationError, "parent_asset_id must name a virtual appliance"
    ):
        _run(store.add_asset({"name": "Child", "parent_asset_id": parent["id"]}))


def test_b17_8_a_virtual_parent_is_accepted(store):  # noqa: F811
    parent = _parent(store, "virtual")
    child = _run(store.add_asset({"name": "Child", "parent_asset_id": parent["id"]}))
    assert child["parent_asset_id"] == parent["id"]


def test_b17_8_an_existing_kind_parent_is_rejected_on_update(store):  # noqa: F811
    parent = _parent(store, "existing")
    child = _run(store.add_asset({"name": "Child"}))
    with raises_exactly(
        AssetValidationError, "parent_asset_id must name a virtual appliance"
    ):
        _run(store.update_asset(child["id"], {"parent_asset_id": parent["id"]}))
    assert store.get_asset(child["id"])["parent_asset_id"] is None


def test_b17_8_an_older_stored_link_does_not_block_an_edit(store):  # noqa: F811
    parent = _parent(store, "existing")
    child = _run(store.add_asset({"name": "Child"}))
    store._assets[child["id"]]["parent_asset_id"] = parent["id"]
    updated = _run(store.update_asset(child["id"], {"name": "Renamed"}))
    assert updated["name"] == "Renamed"


# ── B02-4 ────────────────────────────────────────────────────────────────────
def test_b02_4_update_task_merges_the_source(store):  # noqa: F811
    task = _task(store, source={"acme": {"v": 1}, "other": {"x": 1}})
    updated = _run(store.update_task(task["id"], {"source": {"acme": {"v": 2}}}))
    assert updated["source"] == {"acme": {"v": 2}, "other": {"x": 1}}
    assert store._tasks[task["id"]]["source"] == updated["source"]
    [event] = store._hass.bus.of(EVENT_TASK_UPDATED)
    assert event["changed_fields"] == ["source"]


def test_b02_4_update_task_rejects_a_reserved_namespace(store):  # noqa: F811
    task = _task(store, source={"acme": {"v": 1}})
    with pytest.raises(TaskValidationError):
        _run(store.update_task(task["id"], {"source": {"part": {"asset_id": "a"}}}))
    assert store._tasks[task["id"]]["source"] == {"acme": {"v": 1}}


def test_b02_4_update_task_without_source_keeps_it(store):  # noqa: F811
    task = _task(store, source={"acme": {"v": 1}})
    updated = _run(store.update_task(task["id"], {"name": "Renamed"}))
    assert updated["source"] == {"acme": {"v": 1}}


def test_b02_4_a_locked_source_stays(store):  # noqa: F811
    task = _task(store, source={"acme": {"v": 1}})
    task["managed_by"] = {
        "integration": "acme",
        "display_name": "Acme",
        "locked_fields": ["source"],
    }
    updated = _run(store.update_task(task["id"], {"source": {"acme": {"v": 2}}}))
    assert updated["source"] == {"acme": {"v": 1}}
