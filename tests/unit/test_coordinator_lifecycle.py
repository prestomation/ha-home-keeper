"""Coordinator lookup and edge state across the entry lifecycle.

* X13-2: ``find_coordinator`` returns only the coordinator of a ``LOADED`` entry.
* B18-6: an unload for a disabled entry drops its edge state, so the entry that is
  enabled again sets a silent baseline.

``coordinator.py`` loads the way ``test_coordinator_purge.py`` loads it.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

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
