"""Unit tests for how ``card.py`` delivers the dashboard card (#368).

The card has two delivery paths. ``frontend.add_extra_js_url`` puts an inline
``import()`` into the app shell. A Lovelace resource makes the frontend import the
same URL after it has started. Home Assistant 2026.9 replaces
``window.customElements`` with a scoped-registry polyfill. The shell import can run
before the polyfill is installed, and then the card is defined in the *native*
registry, which the card factory never reads. The resource import of the same URL
then does nothing, because the browser runs a module once.

So in storage mode the resource must be the *only* path. The shell import stays for
YAML resource mode, where it is the only path, and as the fallback when the
resource sync fails. These tests pin which path each case gets, and that removal
undoes only the path that was added.

``card.py`` imports Home Assistant. It loads the same way in every lane: its Home
Assistant imports come from fakes, put in ``sys.modules`` only while it loads. The
unit lane can resolve an old Home Assistant that has no ``LOVELACE_DATA``, and these
tests are about Home Keeper's choice of path, not about Home Assistant's version.
``tests/integration/test_card_resource.py`` checks the real Home Assistant, and the
e2e spec ``card-registration.spec.ts`` checks what the browser sees.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from ha_stubs import install_ha_stubs

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)

URL = "/home_keeper_panel/home-keeper-card.js?v=abc123"


def _fake(name: str, **attrs: object) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    return module


def _load_card() -> types.ModuleType:
    # Gives `homeassistant.core` its `HomeAssistant` when the real package is absent.
    install_ha_stubs()
    fakes = {
        "homeassistant.components.frontend": _fake("homeassistant.components.frontend"),
        "homeassistant.components.lovelace": _fake("homeassistant.components.lovelace"),
        "homeassistant.components.lovelace.const": _fake(
            "homeassistant.components.lovelace.const",
            DOMAIN="lovelace",
            LOVELACE_DATA="lovelace",
            MODE_STORAGE="storage",
        ),
        "homeassistant.setup": _fake(
            "homeassistant.setup", async_when_setup=lambda hass, component, cb: None
        ),
        # card.py takes only `cache_token` from panel.py, and the tests replace
        # `_async_card_url`. The real panel.py imports Home Assistant's http.
        "hk.panel": _fake("hk.panel", cache_token=lambda path: "abc123"),
    }
    saved = {name: sys.modules.get(name) for name in fakes}
    sys.modules.update(fakes)
    try:
        spec = importlib.util.spec_from_file_location(
            "hk.card", str(_COMPONENT_DIR / "card.py")
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules["hk.card"] = module
        spec.loader.exec_module(module)
    finally:
        # Give other suites back what they had, real or stub.
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module


card = _load_card()


# ── fakes ────────────────────────────────────────────────────────────────────
class FakeFrontend:
    """Records the calls on the two ``frontend`` functions card.py uses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def add_extra_js_url(self, hass, url: str) -> None:
        self.calls.append(("add", url))

    def remove_extra_js_url(self, hass, url: str) -> None:
        self.calls.append(("remove", url))


class FakeResources:
    """The part of ``ResourceStorageCollection`` that card.py calls."""

    def __init__(self, *, fail: bool = False) -> None:
        self.items: list[dict] = []
        self.fail = fail
        self._next = 0

    async def async_get_info(self) -> dict:
        if self.fail:
            raise RuntimeError("storage is broken")
        return {"resources": len(self.items)}

    def async_items(self) -> list[dict]:
        return list(self.items)

    async def async_create_item(self, data: dict) -> dict:
        self._next += 1
        item = {"id": f"r{self._next}", **data}
        self.items.append(item)
        return item

    async def async_update_item(self, item_id: str, data: dict) -> dict:
        for item in self.items:
            if item["id"] == item_id:
                item.update(data)
                return item
        raise KeyError(item_id)

    async def async_delete_item(self, item_id: str) -> None:
        self.items = [i for i in self.items if i["id"] != item_id]


@dataclass
class FakeLovelaceData:
    resource_mode: str
    resources: object


@dataclass
class FakeHass:
    data: dict = field(default_factory=dict)


@dataclass
class Harness:
    hass: FakeHass
    frontend: FakeFrontend
    resources: FakeResources | None
    pending: list = field(default_factory=list)

    async def register(self) -> None:
        """Register, then run the `async_when_setup` callback as HA would."""
        await card.async_register_card(self.hass)
        while self.pending:
            await self.pending.pop(0)(self.hass, "lovelace")

    async def unregister(self) -> None:
        await card.async_unregister_card_resource(self.hass)

    def js_calls(self) -> list[tuple[str, str]]:
        return self.frontend.calls


@pytest.fixture
def make(monkeypatch):
    def _make(mode: str | None, *, fail: bool = False) -> Harness:
        hass = FakeHass()
        resources = None
        if mode is not None:
            resources = FakeResources(fail=fail)
            hass.data[card.LOVELACE_DATA] = FakeLovelaceData(mode, resources)
        harness = Harness(hass, FakeFrontend(), resources)

        async def fake_url(_hass) -> str:
            return URL

        monkeypatch.setattr(card, "frontend", harness.frontend)
        monkeypatch.setattr(card, "_async_card_url", fake_url)
        monkeypatch.setattr(
            card,
            "async_when_setup",
            lambda _hass, _component, cb: harness.pending.append(cb),
        )
        return harness

    return _make


def run(coro) -> None:
    asyncio.run(coro)


# ── storage mode: the resource is the only path ──────────────────────────────


def test_storage_mode_delivers_the_card_by_the_resource_only(make):
    # The #368 race: a shell import can define the card in the native registry
    # before the frontend installs its scoped registry. No shell import, no race.
    h = make(card.MODE_STORAGE)
    run(h.register())
    assert h.js_calls() == []
    assert [i["url"] for i in h.resources.items] == [URL]


def test_storage_mode_adds_no_shell_import_before_the_resource_sync_runs(make):
    # `async_when_setup` can run the sync later. Nothing may reach the shell in
    # the time between, or a page loaded then carries the import.
    h = make(card.MODE_STORAGE)
    run(card.async_register_card(h.hass))
    assert h.js_calls() == []


def test_a_failed_resource_sync_falls_back_to_the_shell_import(make):
    # Without the resource, the shell import is the only way to get the card.
    h = make(card.MODE_STORAGE, fail=True)
    run(h.register())
    assert h.js_calls() == [("add", URL)]


def test_storage_mode_removal_leaves_the_shell_import_alone(make):
    # Nothing was added to the shell, so there is nothing to remove there.
    h = make(card.MODE_STORAGE)
    run(h.register())
    run(h.unregister())
    assert h.js_calls() == []
    assert h.resources.items == []


def test_removal_after_the_fallback_removes_the_shell_import(make):
    h = make(card.MODE_STORAGE, fail=True)
    run(h.register())
    run(h.unregister())
    assert h.js_calls() == [("add", URL), ("remove", URL)]


# ── YAML mode and no lovelace: the shell import is the only path ─────────────


@pytest.mark.parametrize("mode", ["yaml", None], ids=["yaml-mode", "no-lovelace"])
def test_without_storage_resources_the_card_uses_the_shell_import(make, mode):
    h = make(mode)
    run(h.register())
    assert h.js_calls() == [("add", URL)]
    if h.resources is not None:
        assert h.resources.items == []


def test_yaml_mode_removal_removes_the_shell_import(make):
    h = make("yaml")
    run(h.register())
    run(h.unregister())
    assert h.js_calls() == [("add", URL), ("remove", URL)]


# ── once per HA run ──────────────────────────────────────────────────────────


def test_a_second_registration_adds_nothing(make):
    # An entry reload calls register again. It must not add a second import.
    h = make("yaml")
    run(h.register())
    run(h.register())
    assert h.js_calls() == [("add", URL)]


def test_registration_after_removal_starts_again(make):
    # Remove, then add the integration again, in one HA run.
    h = make("yaml")
    run(h.register())
    run(h.unregister())
    run(h.register())
    assert h.js_calls() == [("add", URL), ("remove", URL), ("add", URL)]
