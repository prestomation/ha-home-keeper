"""Register the Home Keeper dashboard card as a Lovelace module resource.

Registering the card bundle as a Lovelace *module resource* (rather than
``frontend.add_extra_js_url``) makes the frontend import it after boot, like
HACS-installed community cards. Storage-mode Lovelace is mutable so we manage a
single entry programmatically; YAML-mode dashboards are read-only and must
declare the resource in their own config.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .const import CARD_JS_FILENAME, PANEL_STATIC_URL
from .panel import cache_token

_LOGGER = logging.getLogger(__name__)

try:  # The Lovelace resource collection is an internal (non-public) API.
    from homeassistant.components.lovelace.const import LOVELACE_DATA
except ImportError:  # pragma: no cover - defensive against HA API churn
    LOVELACE_DATA = None  # type: ignore[assignment]
    _LOGGER.error(
        "Lovelace resource collection API unavailable; Home Keeper card not registered. "
        "Add '%s' as a 'module' resource to use the dashboard card.",
        f"{PANEL_STATIC_URL}/{CARD_JS_FILENAME}",
    )

# Token-less URL, matched regardless of an entry's ?v= cache token.
_CARD_BASE_URL = f"{PANEL_STATIC_URL}/{CARD_JS_FILENAME}"


def _get_resources(hass: HomeAssistant) -> Any | None:
    """Return the Lovelace resource collection, or ``None`` if unavailable."""
    if LOVELACE_DATA is None:
        return None
    lovelace = hass.data.get(LOVELACE_DATA)
    return getattr(lovelace, "resources", None)


def _find_existing(resources: Any) -> dict[str, Any] | None:
    """Find our resource by base URL, ignoring any ``?v=`` cache token."""
    return next(
        (
            item
            for item in resources.async_items()
            if str(item.get("url", "")).split("?", 1)[0] == _CARD_BASE_URL
        ),
        None,
    )


async def _ensure_loaded(resources: Any) -> None:
    """``async_items`` doesn't lazy-load, so load once before enumerating."""
    if not resources.loaded:
        await resources.async_load()


async def async_register_card(hass: HomeAssistant) -> None:
    """Ensure exactly one current Home Keeper card module resource exists."""
    resources = _get_resources(hass)
    if resources is None:
        _LOGGER.warning(
            "Lovelace resources unavailable; Home Keeper card not registered. "
            "Add '%s' as a 'module' resource to use the dashboard card.",
            _CARD_BASE_URL,
        )
        return

    card_path = Path(__file__).parent / "frontend" / "dist" / CARD_JS_FILENAME
    token = await hass.async_add_executor_job(cache_token, card_path)
    desired_url = f"{_CARD_BASE_URL}?v={token}"

    # Global YAML-mode Lovelace exposes a read-only resource collection: we cannot
    # register programmatically, so tell the user how to add it themselves.
    if not hasattr(resources, "async_create_item"):
        _LOGGER.warning(
            "Lovelace is in YAML mode; add '%s' as a 'module' resource to your "
            "dashboard configuration to use the Home Keeper card.",
            desired_url,
        )
        return

    await _ensure_loaded(resources)

    existing = _find_existing(resources)
    if existing is None:
        await resources.async_create_item({"res_type": "module", "url": desired_url})
        _LOGGER.info("Registered Home Keeper card resource at %s", desired_url)
    elif existing.get("url") != desired_url:
        await resources.async_update_item(existing["id"], {"url": desired_url})
        _LOGGER.info("Updated Home Keeper card resource to %s", desired_url)
    else:
        _LOGGER.debug("Home Keeper card resource already current")


async def async_unregister_card(hass: HomeAssistant) -> None:
    """Remove the Home Keeper card module resource, if present and mutable."""
    resources = _get_resources(hass)
    if resources is None or not hasattr(resources, "async_delete_item"):
        return

    await _ensure_loaded(resources)

    existing = _find_existing(resources)
    if existing is not None:
        await resources.async_delete_item(existing["id"])
        _LOGGER.info("Removed Home Keeper card resource %s", existing.get("url"))
