"""The store's consumable link, and what a managed appliance may do to a task.

``store.py`` is Home Assistant-coupled, but the paths here touch nothing beyond the
storage document and the bus, so a fake ``Store`` and a fake ``hass`` are the whole
harness — the same technique ``test_todo_list_sync.py`` uses. The integration tier
drives these same services against a real container; what this file holds is the
rule that no other tier can state cheaply: **a source dict is merged, never
replaced**. Every writer pops its own key and leaves the rest, because another
integration's namespace on the same task is the only record of what made the task.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import hk_assets as assets_model
import pytest
from asserts import raises_exactly
from ha_stubs import install_ha_stubs

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)

GLUE = "battery_notes"


@contextmanager
def _borrowed(modules: dict[str, types.ModuleType]) -> Iterator[None]:
    """Register *modules* while the store's body executes, then put back what was."""
    saved = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        yield
    finally:
        for name, prior in saved.items():
            if prior is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior


def _load_store() -> types.ModuleType:
    """Load the real ``store.py`` under ``hk`` with doubles for its HA-aware kin."""
    install_ha_stubs()
    watcher = types.ModuleType("hk.sensor_watcher")
    watcher.read_sensor_value = lambda *args, **kwargs: None
    manuals = types.ModuleType("hk.manuals")

    async def _delete_documents(hass: object, asset_id: str) -> None:
        return None

    manuals.async_delete_asset_documents = _delete_documents
    spec = importlib.util.spec_from_file_location(
        "hk.store", str(_COMPONENT_DIR / "store.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    with _borrowed(
        {
            "hk.sensor_watcher": watcher,
            "hk.manuals": manuals,
            "hk.store": module,
        }
    ):
        spec.loader.exec_module(module)
    sys.modules.setdefault("hk.manuals", manuals)
    # Pin the clock: the recurrence dates these tests read are facts about the
    # fixtures, not about today. The shared stub tree keeps no clock of its own.
    module.dt_util = types.SimpleNamespace(
        now=lambda: NOW,
        utcnow=lambda: NOW,
        as_local=lambda when: when,
        parse_datetime=lambda text: datetime.fromisoformat(text),
    )
    return module


store_mod = _load_store()
TaskValidationError = sys.modules["hk.models"].TaskValidationError
AssetValidationError = assets_model.AssetValidationError


class _FakeStore:
    """Home Assistant's ``Store`` helper: one in-memory document."""

    def __init__(self, hass: object, version: int, key: str) -> None:
        self.data: dict | None = None
        self.saves = 0

    async def async_load(self) -> dict | None:
        return self.data

    async def async_save(self, data: dict) -> None:
        self.saves += 1
        self.data = data

    async def async_remove(self) -> None:
        self.data = None


class _FakeBus:
    def __init__(self) -> None:
        self.fired: list[tuple[str, dict]] = []

    def async_fire(self, event: str, data: dict) -> None:
        self.fired.append((event, data))

    def of(self, event: str) -> list[dict]:
        return [data for name, data in self.fired if name == event]


class _FakeEntries:
    """``hass.config_entries``: which owner entries are loaded right now."""

    def __init__(self, loaded: set[str] | None = None) -> None:
        self.loaded = loaded if loaded is not None else {"entry1"}

    def async_get_entry(self, entry_id: str):
        state = sys.modules["homeassistant.config_entries"].ConfigEntryState
        if entry_id not in self.loaded:
            return None
        return types.SimpleNamespace(state=state.LOADED)


class _FakeHass:
    def __init__(self) -> None:
        self.bus = _FakeBus()
        self.config_entries = _FakeEntries()
        self.config = types.SimpleNamespace(language="en")


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def store():
    """A loaded store with no records, its ``Store`` replaced by the fake."""
    prior = store_mod.Store
    store_mod.Store = _FakeStore
    try:
        instance = store_mod.HomeKeeperStore(_FakeHass())
        yield instance
    finally:
        store_mod.Store = prior


def _asset(store, **overrides):
    """One appliance with a stocked consumable, written straight into the store."""
    data = {
        "name": "Batteries",
        "parts": [{"name": "AAA", "stock": 4, "reorder_at": 1}],
        **overrides,
    }
    asset = assets_model.build_asset(data, now=NOW)
    store._assets[asset["id"]] = asset
    return asset


def _task(store, **overrides):
    """One ordinary floating task, written straight into the store."""
    models = sys.modules["hk.models"]
    task = models.build_task(
        {"name": "Replace battery", "interval": 6, "unit": "months", **overrides},
        now=NOW,
    )
    store._tasks[task["id"]] = task
    return task


# ── set_task_consumable merges ───────────────────────────────────────────────


def test_linking_a_consumable_keeps_a_foreign_namespace(store):
    asset = _asset(store)
    part = asset["parts"][0]
    task = _task(store, source={GLUE: {"device_id": "dev1"}})

    linked = _run(
        store.set_task_consumable(task["id"], asset["id"], part["id"], quantity=2)
    )

    assert linked["source"][GLUE] == {"device_id": "dev1"}
    assert linked["source"]["part"] == {
        "asset_id": asset["id"],
        "part_id": part["id"],
        "manual": True,
        "quantity": 2,
    }


def test_a_link_without_a_quantity_states_none(store):
    asset = _asset(store)
    part = asset["parts"][0]
    task = _task(store)
    linked = _run(store.set_task_consumable(task["id"], asset["id"], part["id"]))
    assert "quantity" not in linked["source"]["part"]


def test_relinking_the_same_part_and_quantity_is_a_no_op(store):
    asset = _asset(store)
    part = asset["parts"][0]
    task = _task(store)
    _run(store.set_task_consumable(task["id"], asset["id"], part["id"], quantity=2))
    fired = len(store._hass.bus.fired)

    _run(store.set_task_consumable(task["id"], asset["id"], part["id"], quantity=2))
    assert len(store._hass.bus.fired) == fired, "an unchanged link announces nothing"

    # A changed quantity is a real change, and is applied in place.
    changed = _run(
        store.set_task_consumable(task["id"], asset["id"], part["id"], quantity=3)
    )
    assert changed["source"]["part"]["quantity"] == 3
    assert len(store._hass.bus.fired) == fired + 1


def test_unlinking_pops_only_the_part_key(store):
    asset = _asset(store)
    part = asset["parts"][0]
    task = _task(store, source={GLUE: {"device_id": "dev1"}})
    _run(store.set_task_consumable(task["id"], asset["id"], part["id"]))

    cleared = _run(store.set_task_consumable(task["id"], None, None))
    assert cleared["source"] == {GLUE: {"device_id": "dev1"}}

    # And a task whose only namespace was the link ends with no source at all.
    plain = _task(store, name="Plain")
    _run(store.set_task_consumable(plain["id"], asset["id"], part["id"]))
    assert _run(store.set_task_consumable(plain["id"], None, None))["source"] is None


def test_unlinking_a_task_that_only_carries_a_foreign_namespace_is_a_no_op(store):
    task = _task(store, source={GLUE: {"device_id": "dev1"}})
    fired = len(store._hass.bus.fired)
    cleared = _run(store.set_task_consumable(task["id"], None, None))
    assert cleared["source"] == {GLUE: {"device_id": "dev1"}}
    assert len(store._hass.bus.fired) == fired


def test_a_link_quantity_must_be_usable(store):
    asset = _asset(store)
    part = asset["parts"][0]
    task = _task(store)
    with raises_exactly(TaskValidationError, "quantity must be greater than zero"):
        _run(store.set_task_consumable(task["id"], asset["id"], part["id"], quantity=0))


def test_a_buy_reminder_takes_no_consumable_link(store):
    # A buy reminder restocks its part. A ``part`` source wins on completion, so a
    # link would turn the restock into a draw-down.
    asset = _asset(store)
    part = asset["parts"][0]
    task = _task(store, name="Buy AAA")
    task["source"] = {"buy": {"asset_id": asset["id"], "part_id": part["id"]}}
    fired = len(store._hass.bus.fired)

    with raises_exactly(
        TaskValidationError,
        "A buy reminder restocks its part, so it cannot be linked to a consumable.",
    ):
        _run(store.set_task_consumable(task["id"], asset["id"], part["id"]))

    assert task["source"] == {"buy": {"asset_id": asset["id"], "part_id": part["id"]}}
    assert len(store._hass.bus.fired) == fired
    # Clearing stays a no-op on a buy reminder, not an error.
    assert _run(store.set_task_consumable(task["id"], None, None)) is task


def test_completing_a_linked_task_takes_the_links_quantity(store):
    asset = _asset(store)
    part = asset["parts"][0]
    task = _task(store)
    _run(store.set_task_consumable(task["id"], asset["id"], part["id"], quantity=2))

    _run(store.complete_task(task["id"]))
    assert part["stock"] == 2, "the link's quantity, not the part's single spare"

    # The second completion crosses the reorder threshold and says so once.
    _run(store.complete_task(task["id"]))
    assert part["stock"] == 0
    assert store._hass.bus.of("home_keeper_part_out_of_stock")


def test_completing_a_link_without_a_quantity_takes_the_parts_own_amount(store):
    asset = _asset(
        store, parts=[{"name": "Bottle", "stock": 1, "consume_quantity": 0.5}]
    )
    part = asset["parts"][0]
    task = _task(store)
    _run(store.set_task_consumable(task["id"], asset["id"], part["id"]))
    _run(store.complete_task(task["id"]))
    assert part["stock"] == 0.5


# ── undoing a completion gives its stock back ────────────────────────────────


def _completed_ts(store, task_id):
    return store._tasks[task_id]["completions"][-1]["ts"]


def test_a_completion_records_what_it_took(store):
    asset = _asset(store)
    part = asset["parts"][0]
    task = _task(store)
    _run(store.set_task_consumable(task["id"], asset["id"], part["id"], quantity=2))
    _run(store.complete_task(task["id"]))
    entry = store._tasks[task["id"]]["completions"][-1]
    assert entry["stock_drawn"] == {
        "asset_id": asset["id"],
        "part_id": part["id"],
        "quantity": 2,
    }


def test_deleting_a_completion_gives_its_stock_back(store):
    asset = _asset(store)
    part = asset["parts"][0]
    task = _task(store)
    _run(store.set_task_consumable(task["id"], asset["id"], part["id"], quantity=2))
    _run(store.complete_task(task["id"]))
    assert part["stock"] == 2
    _run(store.delete_completion(task["id"], _completed_ts(store, task["id"])))
    assert part["stock"] == 4, "a mistaken tick must not leave the count short"


def test_undo_gives_back_only_what_the_empty_part_really_gave(store):
    # The count stops at zero. A completion that asked for 2 but found 1 took 1, so
    # its undo adds 1, not 2, and does not make a spare up.
    asset = _asset(store, parts=[{"name": "AAA", "stock": 1, "reorder_at": 1}])
    part = asset["parts"][0]
    task = _task(store)
    _run(store.set_task_consumable(task["id"], asset["id"], part["id"], quantity=2))
    _run(store.complete_task(task["id"]))
    assert part["stock"] == 0
    assert store._tasks[task["id"]]["completions"][-1]["stock_drawn"]["quantity"] == 1
    _run(store.delete_completion(task["id"], _completed_ts(store, task["id"])))
    assert part["stock"] == 1


def test_a_completion_of_an_empty_part_records_nothing(store):
    asset = _asset(store, parts=[{"name": "AAA", "stock": 0}])
    part = asset["parts"][0]
    task = _task(store)
    _run(store.set_task_consumable(task["id"], asset["id"], part["id"]))
    _run(store.complete_task(task["id"]))
    assert "stock_drawn" not in store._tasks[task["id"]]["completions"][-1]
    _run(store.delete_completion(task["id"], _completed_ts(store, task["id"])))
    assert part["stock"] == 0


def test_the_undo_fires_the_restocked_event(store):
    asset = _asset(store, parts=[{"name": "AAA", "stock": 2, "reorder_at": 1}])
    part = asset["parts"][0]
    task = _task(store)
    _run(store.set_task_consumable(task["id"], asset["id"], part["id"]))
    _run(store.complete_task(task["id"]))
    assert store._hass.bus.of("home_keeper_part_low_stock")
    _run(store.delete_completion(task["id"], _completed_ts(store, task["id"])))
    [restocked] = store._hass.bus.of("home_keeper_part_restocked")
    assert restocked["stock"] == 2


def test_the_undo_leaves_a_part_that_stopped_counting(store):
    # The user cleared the count after the completion. There is no count left to
    # correct, so the undo must not start one.
    asset = _asset(store)
    part = asset["parts"][0]
    task = _task(store)
    _run(store.set_task_consumable(task["id"], asset["id"], part["id"]))
    _run(store.complete_task(task["id"]))
    part["stock"] = None
    _run(store.delete_completion(task["id"], _completed_ts(store, task["id"])))
    assert part["stock"] is None


def test_the_undo_survives_a_deleted_appliance(store):
    asset = _asset(store)
    part = asset["parts"][0]
    task = _task(store)
    _run(store.set_task_consumable(task["id"], asset["id"], part["id"]))
    _run(store.complete_task(task["id"]))
    ts = _completed_ts(store, task["id"])
    del store._assets[asset["id"]]
    _run(store.delete_completion(task["id"], ts))
    assert not store._tasks[task["id"]]["completions"]


# ── adjust_part_stock reports the count ──────────────────────────────────────


def test_adjust_part_stock_reports_the_new_count(store):
    asset = _asset(store, parts=[{"name": "Rolls", "stock": 3, "reorder_at": 1}])
    part = asset["parts"][0]
    report = _run(store.adjust_part_stock(asset["id"], part["id"], -2))
    assert report == {
        "stock": 1,
        "applied_delta": -2,
        "reorder_at": 1,
        "unit": "",
        "status": "low",
    }


def test_adjust_part_stock_reports_the_delta_it_really_applied(store):
    asset = _asset(store, parts=[{"name": "Rolls", "stock": 1}])
    part = asset["parts"][0]
    report = _run(store.adjust_part_stock(asset["id"], part["id"], -3))
    assert (report["stock"], report["applied_delta"], report["status"]) == (
        0,
        -1,
        "out",
    )


# ── deleting an appliance ────────────────────────────────────────────────────


def test_deleting_an_appliance_keeps_a_linked_tasks_other_namespaces(store):
    asset = _asset(store)
    part = asset["parts"][0]
    task = _task(store, source={GLUE: {"device_id": "dev1"}})
    _run(store.set_task_consumable(task["id"], asset["id"], part["id"]))

    _run(store.delete_asset(asset["id"]))

    assert task["source"] == {GLUE: {"device_id": "dev1"}}, (
        "deleting the appliance must not orphan the integration that made the task"
    )
    assert store._tasks[task["id"]] is task


def test_deleting_an_appliance_clears_a_link_that_was_the_only_source(store):
    asset = _asset(store)
    part = asset["parts"][0]
    task = _task(store)
    _run(store.set_task_consumable(task["id"], asset["id"], part["id"]))
    _run(store.delete_asset(asset["id"]))
    assert task["source"] is None


def _protected(store):
    return _asset(
        store,
        source={GLUE: {"role": "battery_stock"}},
        managed_by={
            "integration": GLUE,
            "display_name": "Battery Notes",
            "config_entry_id": "entry1",
            "deletion_protected": True,
            "locked_fields": ["name", "parts"],
        },
    )


def test_a_protected_appliance_is_not_deletable_while_its_owner_is_loaded(store):
    asset = _protected(store)
    with raises_exactly(
        AssetValidationError,
        "This appliance is managed by Battery Notes. "
        "Delete it from Battery Notes instead.",
    ):
        _run(store.delete_asset(asset["id"]))
    assert asset["id"] in store._assets


def test_a_protected_appliance_is_deletable_once_its_owner_is_gone(store):
    asset = _protected(store)
    store._hass.config_entries.loaded = set()
    assert _run(store.delete_asset(asset["id"])) is not None
    assert asset["id"] not in store._assets


def test_force_deletes_a_protected_appliance(store):
    asset = _protected(store)
    assert _run(store.delete_asset(asset["id"], force=True)) is not None
    assert asset["id"] not in store._assets


def test_an_appliance_with_no_entry_id_counts_as_owned(store):
    # Nothing proves the owner is gone, so protection holds and force is the way out.
    asset = _asset(
        store,
        managed_by={"integration": GLUE, "display_name": "Battery Notes"},
    )
    assert store.managed_asset_orphaned(asset) is False
    assert store.managed_asset_orphaned(_asset(store, name="Plain")) is False


# ── the owner's door ─────────────────────────────────────────────────────────


def test_update_managed_asset_writes_the_locked_name_and_parts(store):
    asset = _protected(store)
    stored_part = asset["parts"][0]

    updated = _run(
        store.update_managed_asset(
            asset["id"],
            name="Battery stock",
            parts=[
                {"id": stored_part["id"], "name": "AAA", "notes": "Used by 3 devices"},
                {"name": "CR2032"},
            ],
        )
    )

    assert updated["name"] == "Battery stock"
    aaa, cr = updated["parts"]
    assert aaa["notes"] == "Used by 3 devices"
    assert aaa["stock"] == 4, "the household's count is not the owner's to write"
    assert cr["stock"] is None, "a part nobody has counted starts untracked"
    (event,) = store._hass.bus.of("home_keeper_asset_updated")
    assert set(event["changed_fields"]) == {"name", "parts"}
    assert event["managed_by"]["integration"] == GLUE


def test_update_managed_asset_refuses_an_appliance_nobody_owns(store):
    asset = _asset(store)
    with raises_exactly(
        AssetValidationError,
        "update_managed_asset only writes an appliance an integration owns; "
        "use update_asset.",
    ):
        _run(store.update_managed_asset(asset["id"], name="Mine"))
    with pytest.raises(KeyError):
        _run(store.update_managed_asset("nope", name="Mine"))


def test_update_managed_asset_announces_nothing_when_it_changes_nothing(store):
    asset = _protected(store)
    fired = len(store._hass.bus.fired)
    _run(store.update_managed_asset(asset["id"], name=asset["name"]))
    assert len(store._hass.bus.fired) == fired
    # A second identical apply of the same parts is a no-op too.
    _run(
        store.update_managed_asset(
            asset["id"],
            parts=[{"id": asset["parts"][0]["id"], "name": "AAA"}],
        )
    )
    assert len(store._hass.bus.fired) == fired


def test_update_managed_asset_refuses_an_empty_name(store):
    asset = _protected(store)
    with raises_exactly(AssetValidationError, "name must not be empty"):
        _run(store.update_managed_asset(asset["id"], name="   "))
    assert asset["name"] == "Batteries"


# ── the split-duplicate merge (B17-1) ────────────────────────────────────────
# These run the REAL ``async_merge_split_duplicates``. ``test_device_heal.py``
# replaces it with a fake, so nothing else covers what it deletes.


def _dated_task(store, created, **overrides):
    task = _task(store, **overrides)
    task["created"] = created
    return task


def _battery_tasks(store, devices, *, canonical_payload=False):
    """One 'Replace battery' task per device, each linked to one AAA part."""
    asset = _asset(store)
    part = asset["parts"][0]
    tasks = []
    for index, device in enumerate(devices):
        task = _dated_task(
            store,
            f"2026-01-0{index + 1}T00:00:00+00:00",
            name=f"Replace battery {index}",
            device_id=device,
            source={GLUE: {"device_id": device}},
        )
        _run(store.set_task_consumable(task["id"], asset["id"], part["id"], quantity=2))
        tasks.append(task)
    return tasks


def _snapshot(store):
    return {
        tid: (task["device_id"], dict(task["source"][GLUE]))
        for tid, task in store._tasks.items()
    }


def test_b17_1_merge_with_no_split_keeps_tasks_linked_to_one_part(store):
    """B17-1: an empty map (no split anywhere) deletes and moves nothing."""
    _battery_tasks(store, ["dev_hall", "dev_kitchen", "dev_bedroom"])
    before = _snapshot(store)
    assert len(before) == 3

    assert _run(store.async_merge_split_duplicates({})) == 0

    assert _snapshot(store) == before
    assert store._hass.bus.of("home_keeper_task_deleted") == []


def test_b17_1_two_manual_links_to_one_part_are_not_merged_by_a_split_elsewhere(
    store,
):
    """B17-1: a real split of another device does not turn the merge on for parts."""
    asset = _asset(store)
    part = asset["parts"][0]
    first = _dated_task(store, "2026-01-01T00:00:00+00:00", device_id="dev_kitchen")
    second = _dated_task(store, "2026-02-01T00:00:00+00:00", device_id="dev_garage")
    for task in (first, second):
        _run(store.set_task_consumable(task["id"], asset["id"], part["id"], quantity=2))
    assert first["source"]["part"] == second["source"]["part"]

    split = {"zw_half": "composite", "sb_half": "composite"}
    assert _run(store.async_merge_split_duplicates(split)) == 0

    assert set(store._tasks) == {first["id"], second["id"]}
    assert (first["device_id"], second["device_id"]) == ("dev_kitchen", "dev_garage")


def test_b17_1_tasks_on_the_same_half_of_a_split_are_not_merged(store):
    split = {"zw_half": "composite", "sb_half": "composite"}
    older = _dated_task(
        store,
        "2026-01-01T00:00:00+00:00",
        device_id="zw_half",
        source={GLUE: {"device_id": "zw_half", "item": "filter"}},
    )
    newer = _dated_task(
        store,
        "2026-02-01T00:00:00+00:00",
        device_id="zw_half",
        source={GLUE: {"device_id": "zw_half", "item": "filter"}},
    )
    assert _run(store.async_merge_split_duplicates(split)) == 0
    assert set(store._tasks) == {older["id"], newer["id"]}


def test_b17_1_a_real_split_duplicate_is_still_merged(store):
    """The repair the merge exists for: 2 copies on 2 halves of one device."""
    split = {"zw_half": "composite", "sb_half": "composite"}
    older = _dated_task(
        store,
        "2026-01-01T00:00:00+00:00",
        device_id="zw_half",
        source={GLUE: {"device_id": "zw_half", "item": "filter"}},
    )
    newer = _dated_task(
        store,
        "2026-02-01T00:00:00+00:00",
        device_id="sb_half",
        source={GLUE: {"device_id": "sb_half", "item": "filter"}},
    )
    # Another item on the same device is a different task, not a duplicate.
    other = _dated_task(
        store,
        "2026-01-15T00:00:00+00:00",
        device_id="zw_half",
        source={GLUE: {"device_id": "zw_half", "item": "firmware"}},
    )

    assert _run(store.async_merge_split_duplicates(split)) == 1

    assert set(store._tasks) == {older["id"], other["id"]}
    # The survivor (oldest on a tie) takes the newest copy's device.
    assert older["device_id"] == "sb_half"
    assert older["source"][GLUE]["device_id"] == "sb_half"
    assert other["device_id"] == "zw_half"
    deleted = store._hass.bus.of("home_keeper_task_deleted")
    assert [event["task_id"] for event in deleted] == [newer["id"]]


def test_b17_1_a_duplicate_on_the_undivided_composite_id_is_merged(store):
    """A task still on the dead composite id and one on a live half are one."""
    split = {"sb_half": "composite"}
    older = _dated_task(
        store,
        "2026-01-01T00:00:00+00:00",
        device_id="composite",
        source={GLUE: {"device_id": "composite", "item": "filter"}},
    )
    _dated_task(
        store,
        "2026-02-01T00:00:00+00:00",
        device_id="sb_half",
        source={GLUE: {"device_id": "sb_half", "item": "filter"}},
    )
    assert _run(store.async_merge_split_duplicates(split)) == 1
    assert list(store._tasks) == [older["id"]]
    assert older["device_id"] == "sb_half"


def test_b17_1_the_survivor_keeps_a_device_the_user_chose(store):
    """Only a device id that came from the split is rewritten on the survivor."""
    split = {"zw_half": "composite", "sb_half": "composite"}
    older = _dated_task(
        store,
        "2026-01-01T00:00:00+00:00",
        device_id="dev_user_choice",
        source={GLUE: {"device_id": "zw_half", "item": "filter"}},
    )
    _dated_task(
        store,
        "2026-02-01T00:00:00+00:00",
        device_id="sb_half",
        source={GLUE: {"device_id": "sb_half", "item": "filter"}},
    )
    assert _run(store.async_merge_split_duplicates(split)) == 1
    assert older["device_id"] == "dev_user_choice"
    # The contributor's own payload still follows its device.
    assert older["source"][GLUE]["device_id"] == "sb_half"


def test_b17_1_a_copy_with_completions_is_never_deleted(store):
    split = {"zw_half": "composite", "sb_half": "composite"}
    older = _dated_task(
        store,
        "2026-01-01T00:00:00+00:00",
        device_id="zw_half",
        source={GLUE: {"device_id": "zw_half", "item": "filter"}},
    )
    newer = _dated_task(
        store,
        "2026-02-01T00:00:00+00:00",
        device_id="sb_half",
        source={GLUE: {"device_id": "sb_half", "item": "filter"}},
    )
    newer["completions"] = [{"ts": NOW.isoformat()}]
    older["completions"] = [{"ts": NOW.isoformat()}]
    assert _run(store.async_merge_split_duplicates(split)) == 0
    assert set(store._tasks) == {older["id"], newer["id"]}


def test_b17_1_a_wear_part_task_in_a_group_is_skipped_not_raised_on(store):
    """``delete_task`` refuses a derived part task; the merge must not abort."""
    split = {"zw_half": "composite", "sb_half": "composite"}
    older = _dated_task(
        store,
        "2026-01-01T00:00:00+00:00",
        device_id="zw_half",
        source={GLUE: {"device_id": "zw_half", "item": "filter"}},
    )
    derived = _dated_task(
        store,
        "2026-02-01T00:00:00+00:00",
        device_id="sb_half",
        source={
            GLUE: {"device_id": "sb_half", "item": "filter"},
            "part": {"asset_id": "a1", "part_id": "p1"},
        },
    )
    buy = _dated_task(
        store,
        "2026-03-01T00:00:00+00:00",
        device_id="sb_half",
        source={
            GLUE: {"device_id": "sb_half", "item": "filter"},
            "buy": {"asset_id": "a1", "part_id": "p1"},
        },
    )
    assert _run(store.async_merge_split_duplicates(split)) == 0
    assert set(store._tasks) == {older["id"], derived["id"], buy["id"]}


# ── bulk deletes keep the completion history (B01-4) ─────────────────────────


def _purifier_with_task(store, source):
    """An appliance on a device, and a task with one completion on that device."""
    asset = _asset(store, name="Air purifier")
    asset["device_id"] = "dev_purifier"
    task = _task(store, name="Replace HEPA filter", device_id="dev_purifier")
    task["source"] = source
    task["completions"] = [{"ts": NOW.isoformat()}]
    return asset, task


def _archived_ids(asset):
    return [entry["task_id"] for entry in asset.get("task_history") or []]


def test_b01_4_deleting_a_declarative_companion_archives_its_tasks_history(
    store, monkeypatch
):
    """B01-4: the companion's tasks keep their completions on the appliance."""
    monkeypatch.setattr(store_mod, "async_dispatcher_send", lambda *args: None)
    link = {"spec_id": "spec1", "entity_registry_id": "reg1"}
    asset, task = _purifier_with_task(store, {"declarative_companion": link})
    store._declarative_companions["spec1"] = {"id": "spec1", "name": "HEPA"}

    _run(store.async_delete_declarative_companion("spec1"))

    assert task["id"] not in store._tasks
    assert _archived_ids(asset) == [task["id"]]
    assert asset["task_history"][0]["completions"] == [{"ts": NOW.isoformat()}]


def test_b01_4_a_companion_reconcile_that_deletes_a_task_archives_it(store):
    link = {"spec_id": "spec1", "entity_registry_id": "reg1"}
    asset, task = _purifier_with_task(store, {"declarative_companion": link})
    spec = {"id": "spec1", "name": "HEPA", "task_template": {}}

    # No entity matches the companion any more, so its task is an orphan.
    _run(
        store.reconcile_declarative_companion_tasks(
            spec, {}, {}, config_entry_id="entry1"
        )
    )

    assert task["id"] not in store._tasks
    assert _archived_ids(asset) == [task["id"]]


def test_b01_4_a_problem_sensor_sync_that_deletes_a_task_archives_it(store):
    source = {"problem_sensor": {"entity_id": "binary_sensor.purifier_filter"}}
    asset, task = _purifier_with_task(store, source)

    _run(store.reconcile_problem_sensor_tasks({}, config_entry_id="entry1"))

    assert task["id"] not in store._tasks
    assert _archived_ids(asset) == [task["id"]]


# ── an appliance edit (B05-1, B06-3, B09-3, B15-3) ───────────────────────────


@pytest.fixture
def deleted_part_files(monkeypatch):
    """Record the part files the store asks ``manuals`` to delete."""
    calls: list[tuple[str, str, str]] = []

    async def _delete(hass: object, asset_id: str, part_id: str, name: str) -> None:
        calls.append((asset_id, part_id, name))

    holders = [sys.modules["hk.manuals"]]
    package = sys.modules.get("hk")
    if package is not None and hasattr(package, "manuals"):
        holders.append(package.manuals)
    for holder in holders:
        monkeypatch.setattr(holder, "async_delete_part_file", _delete, raising=False)
    return calls


_FILE = {"filename": "receipt.pdf", "content_type": "application/pdf", "size": 64}


def test_b06_3_removing_a_part_deletes_its_file(store, deleted_part_files):
    """B06-3: a part the update leaves out has its file deleted from disk."""
    asset = _asset(store, parts=[{"name": "Filter"}, {"name": "Belt"}])
    filter_part, belt = asset["parts"]
    assets_model.set_part_file(asset, filter_part["id"], _FILE)
    assets_model.set_part_file(asset, belt["id"], _FILE)

    _run(
        store.update_asset(asset["id"], {"parts": [{"id": belt["id"], "name": "Belt"}]})
    )

    assert deleted_part_files == [(asset["id"], filter_part["id"], "receipt.pdf")]
    assert store._assets[asset["id"]]["parts"][0]["file_name"] == "receipt.pdf"


def test_b05_1_a_notes_edit_keeps_and_deletes_no_part_file(store, deleted_part_files):
    """B05-1: the inline Notes edit sends only ``notes``."""
    asset = _asset(store)
    assets_model.set_part_file(asset, asset["parts"][0]["id"], _FILE)

    updated = _run(store.update_asset(asset["id"], {"notes": "Spares in the drawer"}))

    assert updated["parts"][0]["file_name"] == "receipt.pdf"
    assert deleted_part_files == []


def test_b06_3_a_managed_owner_dropping_a_part_deletes_its_file(
    store, deleted_part_files
):
    asset = _protected(store)
    # The owner can remove only a part that tracks no stock.
    asset["parts"][0]["stock"] = None
    part = asset["parts"][0]
    assets_model.set_part_file(asset, part["id"], _FILE)

    _run(store.update_managed_asset(asset["id"], parts=[{"name": "AA"}]))

    assert deleted_part_files == [(asset["id"], part["id"], "receipt.pdf")]


def test_b09_3_editing_last_replaced_moves_the_wear_task(store):
    """B09-3: the store applies the edit and announces the moved task."""
    wear = {"name": "Filter", "type": "wear", "replace_interval": 6}
    asset = _asset(store, parts=[wear])
    _run(store.reconcile_part_tasks())
    task = next(iter(store._tasks.values()))
    assert task["last_completed"] is None
    part = asset["parts"][0]

    _run(
        store.update_asset(
            asset["id"],
            {"parts": [{**wear, "id": part["id"], "last_replaced": "2026-05-01"}]},
        )
    )

    moved = store._tasks[task["id"]]
    anchor = datetime(2026, 5, 1, tzinfo=TZ)
    assert moved["last_completed"] == anchor.isoformat()
    assert moved["next_due"] == datetime(2026, 11, 1, tzinfo=TZ).isoformat()
    updated = store._hass.bus.of("home_keeper_task_updated")
    assert [(e["task_id"], e["changed_fields"]) for e in updated] == [
        (task["id"], ["last_completed", "next_due"])
    ]
    # The reconcile that runs after an appliance edit leaves the new date in place.
    _run(store.reconcile_part_tasks())
    assert store._tasks[task["id"]]["last_completed"] == anchor.isoformat()


def test_b15_3_a_restock_past_the_maximum_keeps_the_appliance_editable(store):
    """B15-3: stock stops at the spares maximum, so a later rename still saves."""
    asset = _asset(store, parts=[{"name": "Descaler", "stock": 9500}])
    part = asset["parts"][0]

    report = _run(store.adjust_part_stock(asset["id"], part["id"], 1000))

    assert (report["stock"], report["applied_delta"]) == (10000, 500)
    renamed = _run(store.update_asset(asset["id"], {"name": "Kettle"}))
    assert renamed["name"] == "Kettle"
    parts = [{"id": part["id"], "name": "Descaler", "stock": part["stock"]}]
    assert _run(store.update_asset(asset["id"], {"parts": parts}))["parts"][0][
        "stock"
    ] == (10000)
