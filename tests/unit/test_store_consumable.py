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
