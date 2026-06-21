"""Companion registry — discover integrations that work with Home Keeper.

This is the Home-Assistant-facing half of companion discovery; the pure model
(catalog + merge logic) lives in ``companions_catalog.py`` so it's unit-testable
without HA.

The registry is a small in-memory object on ``hass.data`` (one per HA instance). It
holds the companions that have *self-registered* (the push path) and remembers which
companion domains it has already announced an event for, so the
``home_keeper_companion_connected`` / ``_suggested`` events are edge-triggered and
deduped. Self-registration survives Home Keeper config-entry reloads (``hass.data``
isn't cleared on reload); a full HA restart rebuilds it as companions re-announce in
response to ``EVENT_REGISTER_COMPANIONS``.

Detection of the *pull* path (a popular upstream installed, its glue absent) is
computed on demand by scanning ``hass.config_entries`` — no background poller.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv

from . import companions_catalog as catalog
from . import events
from .companions_catalog import STATUS_CONNECTED, STATUS_SUGGESTED
from .const import (
    DATA_COMPANIONS,
    EVENT_COMPANION_CONNECTED,
    EVENT_COMPANION_SUGGESTED,
    EVENT_REGISTER_COMPANIONS,
    OPTION_DISMISSED_COMPANIONS,
)

_LOGGER = logging.getLogger(__name__)

# A companion's self-registration descriptor. ``domain`` and ``name`` are required;
# everything else is optional metadata the panel uses to render and deep-link the row.
# ``config_entry_id`` lets the panel's "Configure" button open the companion's own
# options page. Extra keys are ignored (forward-compatible).
REGISTER_COMPANION_SCHEMA = vol.Schema(
    {
        vol.Required("domain"): cv.string,
        vol.Required("name"): cv.string,
        vol.Optional("icon"): cv.string,
        vol.Optional("description"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
        vol.Optional("docs_url"): cv.string,
        vol.Optional("capabilities"): vol.All(cv.ensure_list, [cv.string]),
    },
    extra=vol.REMOVE_EXTRA,
)


class CompanionRegistry:
    """Holds self-registered companions and dedupes discovery events."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._registered: dict[str, dict[str, Any]] = {}
        # Domains we've already fired a connected/suggested event for, so the events
        # are edge-triggered (announced at most once per state while HA is running).
        self._announced_connected: set[str] = set()
        self._announced_suggested: set[str] = set()

    def register(self, descriptor: dict[str, Any]) -> dict[str, Any]:
        """Record a self-registered companion (idempotent); returns the stored row."""
        domain = descriptor["domain"]
        stored = {
            "domain": domain,
            "name": descriptor["name"],
            "icon": descriptor.get("icon"),
            "description": descriptor.get("description"),
            "config_entry_id": descriptor.get("config_entry_id"),
            "docs_url": descriptor.get("docs_url"),
            "capabilities": list(descriptor.get("capabilities") or []),
        }
        changed = self._registered.get(domain) != stored
        self._registered[domain] = stored
        if changed:
            _LOGGER.debug("Companion registered: %s", domain)
        # A (re-)registration means it's connected; re-announce if this is new and
        # drop any prior "suggested" announcement so a later suggestion of the same
        # domain (shouldn't happen) would re-fire.
        self._announced_suggested.discard(domain)
        return stored

    def _installed_domains(self) -> set[str]:
        """Domains that currently have at least one config entry."""
        return {entry.domain for entry in self._hass.config_entries.async_entries()}

    def _dismissed(self) -> set[str]:
        """Catalog glue domains the user dismissed (read from Home Keeper options)."""
        from .const import DOMAIN

        dismissed: set[str] = set()
        for entry in self._hass.config_entries.async_entries(DOMAIN):
            for domain in entry.options.get(OPTION_DISMISSED_COMPANIONS, []) or []:
                dismissed.add(str(domain))
        return dismissed

    def list_public(self) -> list[dict[str, Any]]:
        """Build the public companion rows and fire any new discovery events."""
        rows = catalog.build_companion_list(
            self._registered,
            self._installed_domains(),
            dismissed=self._dismissed(),
        )
        self._announce(rows)
        return rows

    @callback
    def _announce(self, rows: list[dict[str, Any]]) -> None:
        """Edge-trigger connected/suggested events for newly-seen companion rows."""
        for row in rows:
            domain = row.get("domain")
            status = row.get("status")
            if not isinstance(domain, str):
                continue
            if status == STATUS_CONNECTED and domain not in self._announced_connected:
                self._announced_connected.add(domain)
                self._hass.bus.async_fire(
                    EVENT_COMPANION_CONNECTED, events.companion_event_data(row)
                )
            elif status == STATUS_SUGGESTED and domain not in self._announced_suggested:
                self._announced_suggested.add(domain)
                self._hass.bus.async_fire(
                    EVENT_COMPANION_SUGGESTED, events.companion_event_data(row)
                )


def async_get_registry(hass: HomeAssistant) -> CompanionRegistry:
    """Return (creating if needed) the per-instance companion registry."""
    registry = hass.data.get(DATA_COMPANIONS)
    if not isinstance(registry, CompanionRegistry):
        registry = CompanionRegistry(hass)
        hass.data[DATA_COMPANIONS] = registry
    return registry


@callback
def async_register_companion(hass: HomeAssistant, descriptor: dict[str, Any]) -> None:
    """Register a companion and immediately reconcile so its event fires."""
    async_get_registry(hass).register(descriptor)
    # Rebuild the list so a newly-connected companion announces right away (and any
    # suggestion it satisfies is re-evaluated).
    async_get_registry(hass).list_public()


@callback
def async_list_companions(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return the merged companion rows (self-registered + catalog detection)."""
    return async_get_registry(hass).list_public()


@callback
def async_request_registration(hass: HomeAssistant) -> None:
    """Ask companions to (re-)announce themselves, then run a detection pass.

    Fired once Home Keeper's services exist so companions that set up first (and
    thus saw no ``register_companion`` service) get a chance to register. The
    detection pass afterwards surfaces catalog *suggestions* even when no companion
    self-registers.
    """
    hass.bus.async_fire(EVENT_REGISTER_COMPANIONS)
    # Catalog suggestions don't depend on anyone responding to the ping.
    async_list_companions(hass)


__all__ = [
    "REGISTER_COMPANION_SCHEMA",
    "STATUS_CONNECTED",
    "STATUS_SUGGESTED",
    "CompanionRegistry",
    "async_get_registry",
    "async_list_companions",
    "async_register_companion",
    "async_request_registration",
]
