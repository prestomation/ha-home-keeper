"""Unit tests for the sidebar panel registration in ``panel.py``.

``panel.py`` imports Home Assistant's ``frontend`` and ``http`` components. Like
``test_card_delivery.py``, it loads here with fakes for those imports, put in
``sys.modules`` only while it loads.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

from ha_stubs import install_ha_stubs

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)


def _fake(name: str, **attrs: object) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    return module


class _StaticPathConfig:
    def __init__(self, url: str, path: str, cache: bool) -> None:
        self.url = url


def _load_panel() -> types.ModuleType:
    install_ha_stubs()
    registered: list[str] = []

    def _register_panel(hass, **kwargs):
        hass.data.setdefault("frontend_panels", {})[kwargs["frontend_url_path"]] = (
            kwargs
        )
        registered.append(kwargs["frontend_url_path"])

    fakes = {
        "homeassistant.components.frontend": _fake(
            "homeassistant.components.frontend",
            async_register_built_in_panel=_register_panel,
            async_remove_panel=lambda hass, path: None,
        ),
        "homeassistant.components.http": _fake(
            "homeassistant.components.http", StaticPathConfig=_StaticPathConfig
        ),
    }
    saved = {name: sys.modules.get(name) for name in fakes}
    sys.modules.update(fakes)
    try:
        spec = importlib.util.spec_from_file_location(
            "hk.panel_under_test", str(_COMPONENT_DIR / "panel.py")
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # ``from homeassistant.components import frontend`` reads the attribute of
        # the parent package, which is the real one when Home Assistant is
        # installed. Bind the fakes on the loaded module.
        module.frontend = fakes["homeassistant.components.frontend"]
        module.StaticPathConfig = _StaticPathConfig
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module


panel = _load_panel()


class _Http:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def async_register_static_paths(self, configs) -> None:
        # Like Home Assistant for a directory: no error for a second registration,
        # only one more router resource.
        self.calls.append([config.url for config in configs])


class _Hass:
    def __init__(self) -> None:
        self.data: dict = {}
        self.http = _Http()

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def test_b20_5_static_path_is_registered_once_per_run():
    hass = _Hass()

    async def _reloads() -> None:
        for _ in range(3):
            await panel.async_register_panel(hass)

    asyncio.run(_reloads())
    assert hass.http.calls == [[panel.PANEL_STATIC_URL]]
    assert panel.PANEL_URL_PATH in hass.data["frontend_panels"]


def test_b20_5_a_new_run_registers_the_static_path_again():
    first, second = _Hass(), _Hass()
    asyncio.run(panel.async_register_panel(first))
    asyncio.run(panel.async_register_panel(second))
    assert first.http.calls == [[panel.PANEL_STATIC_URL]]
    assert second.http.calls == [[panel.PANEL_STATIC_URL]]
