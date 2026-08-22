"""Deliver the Home Keeper dashboard card to every browser, by two paths.

Two independent delivery mechanisms, because one of them is not enough (#228):

1. ``frontend.add_extra_js_url`` — the bundle goes into the app-shell HTML that
   ``IndexView`` renders, as one inline ``import("...")`` per extra module. It is
   the only path available when Lovelace runs with ``resource_mode: yaml``.
2. A real Lovelace **resource** — which the frontend fetches over the websocket on
   every dashboard load, before it renders the config.

Path 1 on its own is a cache hazard. Home Assistant's own service worker serves
navigations ``StaleWhileRevalidate`` out of a 24h ``file-cache``, and ``IndexView``
sends the shell with no ``Cache-Control`` and no ETag. So a shell snapshot taken
*before* Home Keeper first registered the card carries no import for it, and that
snapshot is replayed on every ordinary reload: "Configuration error: Custom element
doesn't exist: home-keeper-card", cleared by a cache-bypassing reload and back on
the next normal one. Every HACS card on the reporter's identical shell kept working,
because HACS cards are resources. Path 2 puts the bundled card on the same footing,
and is the only method Home Assistant's own docs describe for loading a custom card.

Registering both is safe: they name the same URL, so the browser's module map runs
the module body once, and ``card-index.ts`` guards both its ``customElements.define``
calls and its ``window.customCards`` push for the case where the two can diverge.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.lovelace.const import DOMAIN as LOVELACE_DOMAIN
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_when_setup

from .card_resource import matching_ids, plan_card_resource, resource_payload
from .const import CARD_JS_FILENAME, DOMAIN, PANEL_STATIC_URL
from .panel import cache_token

_LOGGER = logging.getLogger(__name__)

# Holds the registered URL, so removal can undo both paths. Doubles as the guard
# that keeps registration to once per HA run rather than once per entry reload.
_CARD_REGISTERED = f"{DOMAIN}_card_registered"

# The query-less path the bundle is served from. Stored resources are matched on
# *this*, so a rebuilt bundle's new `?v=` token updates the existing row rather
# than adding one beside it.
CARD_URL_PATH = f"{PANEL_STATIC_URL}/{CARD_JS_FILENAME}"


async def _async_card_url(hass: HomeAssistant) -> str:
    """The cache-busted module URL for the built card bundle."""
    card_path = Path(__file__).parent / "frontend" / "dist" / CARD_JS_FILENAME
    token = await hass.async_add_executor_job(cache_token, card_path)
    return f"{CARD_URL_PATH}?v={token}"


def _storage_resources(hass: HomeAssistant) -> ResourceStorageCollection | None:
    """The writable resource collection, or None when we must not touch it.

    ``ResourceYAMLCollection`` (``lovelace:`` with a ``resources:`` block) has no
    create, update or delete at all — those installs declare every resource in YAML
    and Home Keeper has no business rewriting their file. They keep path 1 only,
    which is exactly what they had before this fix.
    """
    if (data := hass.data.get(LOVELACE_DATA)) is None:
        return None
    if not isinstance(data.resources, ResourceStorageCollection):
        return None
    return data.resources


async def _async_sync_resource(hass: HomeAssistant, url: str) -> None:
    """Leave the Lovelace resources holding exactly one row for *url*."""
    if (resources := _storage_resources(hass)) is None:
        _LOGGER.debug(
            "Lovelace resources are not storage-backed; the card is delivered by "
            "the frontend module URL alone"
        )
        return

    # The storage collection loads lazily: async_items() is empty until the store
    # has been read, and async_get_info() is the public call that reads it. Skip
    # this and every start looks like a fresh install and adds a duplicate.
    await resources.async_get_info()
    plan = plan_card_resource(resources.async_items(), url)

    if plan.create:
        await resources.async_create_item(resource_payload(url))
        _LOGGER.info("Registered the Home Keeper card as a Lovelace resource (%s)", url)
    elif plan.update_id is not None:
        await resources.async_update_item(plan.update_id, resource_payload(url))
        _LOGGER.info("Updated the Home Keeper card Lovelace resource to %s", url)

    for duplicate in plan.delete_ids:
        await resources.async_delete_item(duplicate)
        _LOGGER.info("Removed a duplicate Home Keeper card Lovelace resource")


async def async_register_card(hass: HomeAssistant) -> None:
    """Publish the card bundle by both delivery paths (idempotent).

    Assumes the static path that serves the bundle has already been registered by
    ``panel.async_register_panel`` (called first during entry setup). The ``?v=``
    token is a content hash, so a rebuilt bundle always busts the cache (see
    ``panel.cache_token``).
    """
    if hass.data.get(_CARD_REGISTERED):
        return
    url = await _async_card_url(hass)
    frontend.add_extra_js_url(hass, url)
    hass.data[_CARD_REGISTERED] = url
    _LOGGER.info("Registered Home Keeper dashboard card module at %s", url)

    async def _sync(hass: HomeAssistant, _component: str) -> None:
        try:
            await _async_sync_resource(hass, url)
        except Exception:
            _LOGGER.exception(
                "Could not register the Home Keeper card as a Lovelace resource. "
                "The card is still delivered through the frontend module URL, so a "
                "dashboard loaded from a stale cached page may not render it (#228)"
            )

    # Off the config-entry setup path on purpose: a storage write must never be able
    # to delay or fail setup. `frontend` hard-depends on `lovelace`, so in practice
    # this fires immediately; the callback form keeps us correct if that ever stops
    # being true, and does nothing at all if lovelace is never set up.
    async_when_setup(hass, LOVELACE_DOMAIN, _sync)


async def async_unregister_card_resource(hass: HomeAssistant) -> None:
    """Undo both delivery paths. Integration *removal* only, never unload/reload.

    A reload must leave the resource alone: it is shared state that outlives the
    entry, and rewriting it on every reload would churn ``.storage`` and briefly
    break open dashboards. Removal is the one point where dropping it is right —
    otherwise an uninstalled Home Keeper leaves a resource pointing at a 404 that
    Home Assistant complains about on every dashboard load.
    """
    url = hass.data.pop(_CARD_REGISTERED, None)
    try:
        if isinstance(url, str):
            frontend.remove_extra_js_url(hass, url)
        if (resources := _storage_resources(hass)) is None:
            return
        await resources.async_get_info()
        for item_id in matching_ids(resources.async_items(), CARD_URL_PATH):
            await resources.async_delete_item(item_id)
            _LOGGER.info("Removed the Home Keeper card Lovelace resource")
    except Exception:
        _LOGGER.exception("Could not remove the Home Keeper card Lovelace resource")
