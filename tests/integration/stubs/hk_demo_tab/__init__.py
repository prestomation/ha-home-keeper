"""Test-only companion that adds a tab to the Home Keeper panel.

It lives under ``tests/integration/stubs/`` and is bind-mounted into the Docker Home
Assistant. It is not part of the shipped integration. It uses the public panel tab
contract the same way a real companion does (docs/INTEGRATING.md, "Add a panel
tab"): it serves its ES module from a static path, registers the tab with
``async_register_panel_tab`` and gives the unregister callable to
``entry.async_on_unload``. It also registers as a companion, so Settings, Companions
has a row for the tab.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from custom_components.home_keeper.panel_tabs import PanelTab, async_register_panel_tab

DOMAIN = "hk_demo_tab"
STATIC_URL = "/hk_demo_tab_static"
_STATIC_DONE = f"{DOMAIN}_static"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Serve the module, register the tab, and register as a companion."""
    # A static path stays for the Home Assistant run, so register it 1 time only.
    if not hass.data.get(_STATIC_DONE):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(Path(__file__).parent / "www"), False)]
        )
        hass.data[_STATIC_DONE] = True
    unregister = async_register_panel_tab(
        hass,
        PanelTab(
            companion=DOMAIN,
            id="demo-tab",
            titles={"en": "Library", "de": "Bibliothek"},
            icon="mdi:bookshelf",
            module_url=f"{STATIC_URL}/demo-tab.js?v=1",
            element="home-keeper-demo-tab",
        ),
    )
    entry.async_on_unload(unregister)
    await hass.services.async_call(
        "home_keeper",
        "register_companion",
        {
            "domain": DOMAIN,
            "name": "Demo library",
            "icon": "mdi:bookshelf",
            "description": "A test companion that adds a Library tab to the panel.",
            "config_entry_id": entry.entry_id,
        },
        blocking=True,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """The unload callbacks remove the tab."""
    return True
