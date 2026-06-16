"""Auto-register the Home Keeper dashboard card as a Lovelace resource.

The card's JS bundle is served from the same static path as the sidebar panel
(registered in ``panel.async_register_panel``). Here we add it to the frontend's
extra module URLs so the custom card registers itself in every dashboard's "Add
card" picker — no manual resource entry required, mirroring how the sidebar
panel needs no YAML.
"""

from __future__ import annotations

import logging

from homeassistant.components import frontend
from homeassistant.core import HomeAssistant, callback

from .const import CARD_JS_FILENAME, DOMAIN, PANEL_STATIC_URL, PANEL_VERSION

_LOGGER = logging.getLogger(__name__)

# Guard so the extra-module URL is added once per HA run (not on every reload).
_CARD_REGISTERED = f"{DOMAIN}_card_registered"


@callback
def async_register_card(hass: HomeAssistant) -> None:
    """Add the card bundle to the frontend's module URLs (idempotent).

    Assumes the static path that serves the bundle has already been registered
    by ``panel.async_register_panel`` (called first during entry setup).
    """
    if hass.data.get(_CARD_REGISTERED):
        return
    url = f"{PANEL_STATIC_URL}/{CARD_JS_FILENAME}?v={PANEL_VERSION}"
    frontend.add_extra_js_url(hass, url)
    hass.data[_CARD_REGISTERED] = True
    _LOGGER.info("Registered Home Keeper dashboard card resource at %s", url)
