"""Coordinator lookup and edge state across the entry lifecycle.

* X13-2: ``find_coordinator`` returns only the coordinator of a ``LOADED`` entry.
* B18-6: an unload for a disabled entry drops its edge state, so the entry that is
  enabled again sets a silent baseline.
* B15-5: a stock change that starts the count of a part reloads the entry, so the
  part gets its stock entities.
* X08-5: the settle writes only the part entities before the refresh, not every
  entity twice.

``coordinator.py`` loads the way ``test_coordinator_purge.py`` loads it.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_coordinator_purge import coordinator

_COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "home_keeper"


def _coord() -> object:
    return object.__new__(coordinator.HomeKeeperCoordinator)


class _Entries:
    def __init__(self, entries: list) -> None:
        self._entries = entries

    def async_entries(self, domain: str) -> list:
        assert domain == coordinator.DOMAIN
        return self._entries


def _hass(*entries) -> SimpleNamespace:
    return SimpleNamespace(config_entries=_Entries(list(entries)), data={})


# ── X13-2 ────────────────────────────────────────────────────────────────────
def test_x13_2_a_loaded_entry_gives_its_coordinator():
    coord = _coord()
    entry = SimpleNamespace(
        state=coordinator.ConfigEntryState.LOADED, runtime_data=coord
    )
    assert coordinator.find_coordinator(_hass(entry)) is coord


def test_x13_2_a_failed_setup_gives_no_coordinator():
    # Home Assistant keeps runtime_data on an entry whose setup failed.
    entry = SimpleNamespace(state="setup_error", runtime_data=_coord())
    assert coordinator.find_coordinator(_hass(entry)) is None


def test_x13_2_the_loaded_entry_wins_over_a_failed_one():
    coord = _coord()
    failed = SimpleNamespace(state="setup_error", runtime_data=_coord())
    loaded = SimpleNamespace(
        state=coordinator.ConfigEntryState.LOADED, runtime_data=coord
    )
    assert coordinator.find_coordinator(_hass(failed, loaded)) is coord


def test_x13_2_a_loaded_entry_without_a_coordinator_gives_none():
    entry = SimpleNamespace(state=coordinator.ConfigEntryState.LOADED, runtime_data=1)
    assert coordinator.find_coordinator(_hass(entry)) is None


# ── B18-6 ────────────────────────────────────────────────────────────────────
def _hass_with_edges() -> SimpleNamespace:
    hass = _hass()
    store = coordinator._edge_state_store(hass)
    store["entry-1"] = {"t1": "overdue"}
    store["entry-2"] = {"t2": "due_soon"}
    return hass


def test_b18_6_a_disabled_entry_drops_its_edge_state():
    hass = _hass_with_edges()
    entry = SimpleNamespace(entry_id="entry-1", disabled_by="user")
    coordinator.discard_edge_state_if_disabled(hass, entry)
    assert coordinator._edge_state_store(hass) == {"entry-2": {"t2": "due_soon"}}


def test_b18_6_a_reload_keeps_the_edge_state():
    hass = _hass_with_edges()
    entry = SimpleNamespace(entry_id="entry-1", disabled_by=None)
    coordinator.discard_edge_state_if_disabled(hass, entry)
    assert coordinator._edge_state_store(hass) == {
        "entry-1": {"t1": "overdue"},
        "entry-2": {"t2": "due_soon"},
    }


def test_b18_6_the_unload_drops_the_edge_state_of_a_disabled_entry():
    """``async_unload_entry`` calls the helper after the platforms unload.

    ``__init__.py`` imports all of Home Assistant, so this reads its source, as
    ``test_lifecycle_handlers.py`` does. ``tests/integration`` drives the unload.
    """
    tree = ast.parse((_COMPONENT / "__init__.py").read_text())
    unload = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_unload_entry"
    )
    calls = [
        ast.unparse(node)
        for node in ast.walk(unload)
        if isinstance(node, ast.Call)
        and ast.unparse(node.func) == "discard_edge_state_if_disabled"
    ]
    assert calls == ["discard_edge_state_if_disabled(hass, entry)"]


# ── B15-5 and X08-5: the stock settle ────────────────────────────────────────
class _StockStore:
    def __init__(self, part: dict) -> None:
        self.asset = {"id": "a1", "parts": [part]}
        self.buy_changed = False

    def get_asset(self, asset_id):
        return self.asset if asset_id == "a1" else None

    async def adjust_part_stock(self, asset_id, part_id, delta):
        part = self.asset["parts"][0]
        part["stock"] = (part.get("stock") or 0) + delta
        return {"stock": part["stock"], "applied_delta": delta}

    async def settle_use_tasks(self):
        return None

    async def reconcile_buy_tasks(self):
        return self.buy_changed


class _SettleHass:
    def __init__(self) -> None:
        self.created: list = []

    def async_create_task(self, coro):
        self.created.append(coro)
        coro.close()


def _stock_coord(part: dict, monkeypatch):
    coord = _coord()
    coord.store = _StockStore(part)
    coord.hass = _SettleHass()
    coord.shopping_sync = None
    coord._buy_reload_scheduled = False
    log: list = []

    def _update_listeners():
        log.append("update_listeners")

    async def _refresh():
        log.append("refresh")

    coord.async_update_listeners = _update_listeners
    coord.async_request_refresh = _refresh
    monkeypatch.setattr(
        coordinator,
        "async_dispatcher_send",
        lambda hass, signal, *args: log.append(("signal", signal)),
        raising=False,
    )
    return coord, log


@pytest.mark.parametrize(
    ("part", "expected"),
    [
        ({"id": "p1"}, (False, False)),
        ({"id": "p1", "stock": 0}, (True, False)),
        ({"id": "p1", "stock": 2, "reorder_at": 1}, (True, True)),
        ({"id": "p1", "reorder_at": 1}, (False, False)),
    ],
)
def test_b15_5_part_entity_kinds(part, expected):
    assert coordinator.part_entity_kinds({"parts": [part]}, "p1") == expected


def test_b15_5_part_entity_kinds_of_a_missing_part():
    assert coordinator.part_entity_kinds(None, "p1") == (False, False)
    assert coordinator.part_entity_kinds({"parts": []}, "p1") == (False, False)


def test_b15_5_a_part_that_starts_its_count_reloads_the_entry(monkeypatch):
    coord, log = _stock_coord({"id": "p1", "reorder_at": 1}, monkeypatch)
    report = asyncio.run(coord.async_adjust_part_stock("a1", "p1", 2))
    assert report == {"stock": 2, "applied_delta": 2}
    assert len(coord.hass.created) == 1
    assert log == []


def test_b15_5_a_tracked_part_only_refreshes(monkeypatch):
    coord, log = _stock_coord({"id": "p1", "stock": 3, "reorder_at": 1}, monkeypatch)
    asyncio.run(coord.async_adjust_part_stock("a1", "p1", -1))
    assert coord.hass.created == []
    assert log == [("signal", coordinator.SIGNAL_PART_STOCK_CHANGED), "refresh"]


def test_x08_5_the_settle_writes_only_the_part_entities_early(monkeypatch):
    coord, log = _stock_coord({"id": "p1", "stock": 3}, monkeypatch)
    asyncio.run(coord.async_settle_buy_tasks())
    assert "update_listeners" not in log
    assert log == [("signal", coordinator.SIGNAL_PART_STOCK_CHANGED), "refresh"]


def test_x08_5_a_buy_task_change_reloads_without_a_signal(monkeypatch):
    coord, log = _stock_coord({"id": "p1", "stock": 3}, monkeypatch)
    coord.store.buy_changed = True
    asyncio.run(coord.async_settle_buy_tasks())
    assert len(coord.hass.created) == 1
    assert log == []


def test_x08_5_the_part_entities_listen_for_the_signal():
    tree = ast.parse((_COMPONENT / "entity.py").read_text())
    part_entity = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "HomeKeeperPartEntity"
    )
    assert (
        "async_dispatcher_connect(self.hass, SIGNAL_PART_STOCK_CHANGED, "
        "self.async_write_ha_state)" in ast.unparse(part_entity)
    )
