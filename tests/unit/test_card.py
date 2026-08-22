"""Unit tests for the Lovelace card resource registration in ``card.py``.

``card.py`` imports Home Assistant (``homeassistant.core`` and the internal
``lovelace`` resource-collection API) and its sibling ``panel.cache_token``, so —
like ``test_notifier_blocking``/``test_coordinator_purge`` — we load it under a
synthetic ``hk`` package with additive HA stubs (when real HA is absent) and a
fake ``hk.panel`` so the pure registration logic can be exercised against fake
resource collections without a running Home Assistant.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
import types
from pathlib import Path

import pytest

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)

_TOKEN = "toktoktoktok"


def _real_ha_present() -> bool:
    mod = sys.modules.get("homeassistant")
    if mod is None:
        try:  # pragma: no cover - depends on environment
            import homeassistant as mod  # type: ignore[no-redef]
        except ImportError:
            return False
    return getattr(mod, "__file__", None) is not None


def _install_ha_stubs() -> None:
    """Additively register only the HA symbols ``card.py`` imports."""
    if _real_ha_present():  # pragma: no cover - real HA env (CI)
        return

    def _mod(name: str) -> types.ModuleType:
        existing = sys.modules.get(name)
        if existing is not None:
            return existing
        m = types.ModuleType(name)
        sys.modules[name] = m
        return m

    _mod("homeassistant")
    core = _mod("homeassistant.core")
    if not hasattr(core, "HomeAssistant"):

        class HomeAssistant:
            pass

        core.HomeAssistant = HomeAssistant

    _mod("homeassistant.components")
    lovelace = _mod("homeassistant.components.lovelace")
    const = _mod("homeassistant.components.lovelace.const")
    if not hasattr(const, "LOVELACE_DATA"):
        const.LOVELACE_DATA = "lovelace"
    lovelace.const = const


def _load_card() -> types.ModuleType:
    """Load ``card.py`` under ``hk.card`` with a faked ``hk.panel`` sibling."""
    existing = sys.modules.get("hk.card")
    if existing is not None and hasattr(existing, "async_register_card"):
        return existing
    sys.modules.pop("hk.card", None)
    _install_ha_stubs()

    # panel.py imports HA (frontend/http); we only need its cache_token, so fake it.
    panel = types.ModuleType("hk.panel")
    panel.cache_token = lambda path: _TOKEN
    sys.modules["hk.panel"] = panel

    spec = importlib.util.spec_from_file_location(
        "hk.card", str(_COMPONENT_DIR / "card.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hk.card"] = module
    spec.loader.exec_module(module)
    return module


card = _load_card()
BASE_URL = "/home_keeper_panel/home-keeper-card.js"
DESIRED_URL = f"{BASE_URL}?v={_TOKEN}"


# ── fakes ────────────────────────────────────────────────────────────────────
class FakeStorageResources:
    """Mimics HA's mutable ``ResourceStorageCollection`` closely enough."""

    def __init__(self, items: list[dict] | None = None) -> None:
        self._items = list(items or [])
        self.loaded = False
        self.load_calls = 0
        self.create_calls = 0
        self.update_calls = 0
        self.delete_calls = 0
        self._next = 1

    async def async_load(self) -> None:
        self.load_calls += 1

    def async_items(self) -> list[dict]:
        return list(self._items)

    async def async_create_item(self, data: dict) -> dict:
        self.create_calls += 1
        item = {"id": f"id{self._next}", **data}
        self._next += 1
        self._items.append(item)
        return item

    async def async_update_item(self, item_id: str, updates: dict) -> dict:
        self.update_calls += 1
        for it in self._items:
            if it["id"] == item_id:
                it.update(updates)
                return it
        raise KeyError(item_id)

    async def async_delete_item(self, item_id: str) -> None:
        self.delete_calls += 1
        self._items = [it for it in self._items if it["id"] != item_id]


class FakeYamlResources:
    """Read-only collection (global YAML mode): no create/update/delete."""

    def __init__(self, items: list[dict] | None = None) -> None:
        self._items = list(items or [])

    def async_items(self) -> list[dict]:
        return list(self._items)


class FakeHass:
    def __init__(self, resources: object | None) -> None:
        lovelace = types.SimpleNamespace(resources=resources) if resources else None
        self.data = {card.LOVELACE_DATA: lovelace} if lovelace is not None else {}

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _run(coro):
    return asyncio.run(coro)


# ── register ─────────────────────────────────────────────────────────────────
def test_register_creates_single_resource():
    res = FakeStorageResources()
    _run(card.async_register_card(FakeHass(res)))
    assert len(res.async_items()) == 1
    item = res.async_items()[0]
    assert item["url"] == DESIRED_URL
    assert item["res_type"] == "module"
    assert res.create_calls == 1
    # We explicitly load once before enumerating async_items().
    assert res.load_calls == 1


def test_register_is_idempotent_no_duplicate():
    res = FakeStorageResources([{"id": "id0", "url": DESIRED_URL, "res_type": "module"}])
    _run(card.async_register_card(FakeHass(res)))
    assert len(res.async_items()) == 1
    assert res.create_calls == 0
    assert res.update_calls == 0


def test_register_updates_url_in_place_on_token_change():
    stale = {"id": "id0", "url": f"{BASE_URL}?v=oldtoken", "res_type": "module"}
    res = FakeStorageResources([stale])
    _run(card.async_register_card(FakeHass(res)))
    items = res.async_items()
    assert len(items) == 1
    assert items[0]["id"] == "id0"  # updated in place, not recreated
    assert items[0]["url"] == DESIRED_URL
    assert res.update_calls == 1
    assert res.create_calls == 0


def test_register_matches_by_base_url_ignoring_query():
    # A user-added duplicate with a different token still matches by base URL, so we
    # update (never add a second) — PAT-002.
    res = FakeStorageResources(
        [{"id": "id0", "url": f"{BASE_URL}?v=whatever&foo=bar", "res_type": "module"}]
    )
    _run(card.async_register_card(FakeHass(res)))
    assert len(res.async_items()) == 1
    assert res.create_calls == 0
    assert res.update_calls == 1


def test_register_yaml_mode_warns_and_does_not_raise(caplog):
    res = FakeYamlResources()
    with caplog.at_level(logging.WARNING):
        _run(card.async_register_card(FakeHass(res)))
    assert res.async_items() == []
    assert any("YAML mode" in r.message for r in caplog.records)


def test_register_no_lovelace_data_warns_and_does_not_raise(caplog):
    with caplog.at_level(logging.WARNING):
        _run(card.async_register_card(FakeHass(None)))
    assert any("Lovelace resources unavailable" in r.message for r in caplog.records)


# ── unregister ───────────────────────────────────────────────────────────────
def test_unregister_removes_resource():
    res = FakeStorageResources([{"id": "id0", "url": DESIRED_URL, "res_type": "module"}])
    _run(card.async_unregister_card(FakeHass(res)))
    assert res.async_items() == []
    assert res.delete_calls == 1


def test_unregister_ignores_query_token_when_matching():
    res = FakeStorageResources(
        [{"id": "id0", "url": f"{BASE_URL}?v=oldtoken", "res_type": "module"}]
    )
    _run(card.async_unregister_card(FakeHass(res)))
    assert res.async_items() == []


def test_unregister_no_op_when_absent():
    res = FakeStorageResources()
    _run(card.async_unregister_card(FakeHass(res)))
    assert res.delete_calls == 0


def test_unregister_yaml_mode_no_op_no_raise():
    res = FakeYamlResources([{"id": "x", "url": DESIRED_URL}])
    _run(card.async_unregister_card(FakeHass(res)))
    assert len(res.async_items()) == 1  # untouched, no error


def test_unregister_no_lovelace_data_no_raise():
    _run(card.async_unregister_card(FakeHass(None)))
