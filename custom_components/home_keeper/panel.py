"""Custom sidebar panel registration for Home Keeper.

This serves the built TypeScript bundle as a static path and registers a
full-page custom panel in the HA sidebar. We use the built-in ``custom`` panel
component with a ``_panel_custom`` config block — exactly the mechanism HA's own
``panel_custom`` integration uses — so the sidebar entry appears with no user
YAML required.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import (
    PANEL_ICON,
    PANEL_JS_FILENAME,
    PANEL_STATIC_URL,
    PANEL_TITLE,
    PANEL_URL_PATH,
    PANEL_VERSION,
    WEBCOMPONENT_NAME,
)

_LOGGER = logging.getLogger(__name__)


def cache_token(path: Path) -> str:
    """A short content hash of a built asset for cache-busting its module URL.

    Tying the panel/card ``?v=`` token to the file's *content* (rather than the
    integration version) means any rebuild serves a fresh URL — including
    same-version preview builds (``X.Y.Z.dev<pr>`` is reused across pushes to a PR)
    and the dev→stable transition that reuses a version string. Without this,
    browsers and the mobile-app webview cling to a stale bundle and render the old
    card. This blocking file read must be dispatched off the event loop by callers
    (via ``async_add_executor_job``); it falls back to the version string if the
    file is somehow unreadable (it always exists in a real install).
    """
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    except OSError:
        return PANEL_VERSION


async def async_register_panel(hass: HomeAssistant) -> None:
    """Register the static path and the sidebar panel (idempotent)."""
    frontend_dir = Path(__file__).parent / "frontend"
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(PANEL_STATIC_URL, str(frontend_dir), False)]
        )
    except RuntimeError:
        # Already registered (e.g. on reload) — fine.
        _LOGGER.debug("Static path %s already registered", PANEL_STATIC_URL)

    # Don't double-register the sidebar panel across reloads.
    if PANEL_URL_PATH in hass.data.get("frontend_panels", {}):
        return

    token = await hass.async_add_executor_job(
        cache_token, frontend_dir / PANEL_JS_FILENAME
    )
    js_url = f"{PANEL_STATIC_URL}/{PANEL_JS_FILENAME}?v={token}"
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=PANEL_URL_PATH,
        require_admin=False,
        config={
            "_panel_custom": {
                "name": WEBCOMPONENT_NAME,
                "module_url": js_url,
                "embed_iframe": False,
                "trust_external": False,
            }
        },
    )
    _LOGGER.info("Registered Home Keeper sidebar panel at /%s", PANEL_URL_PATH)


def async_unregister_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel (static path persists for the HA lifetime)."""
    if PANEL_URL_PATH in hass.data.get("frontend_panels", {}):
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
