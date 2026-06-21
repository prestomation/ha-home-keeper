"""Companion registry — discover integrations that work with Home Keeper.

This is the Home-Assistant-facing half of companion discovery; the pure model
(catalog + merge logic) lives in ``companions_catalog.py`` so it's unit-testable
without HA.

The registry is a small in-memory object on ``hass.data`` (one per HA instance). It
holds the companions that have *self-registered* (the push path) and remembers which
companion domains it has already announced, so the
``home_keeper_companion_connected`` / ``_suggested`` events are **edge-triggered**.

Event firing follows the same baseline-on-startup contract as the coordinator's
time-based transitions (see ``coordinator.py`` / ``transitions.py``):

* Reads (``async_list_companions`` → ``build``) are pure and **never** fire events.
* ``reconcile`` recomputes the connected/suggested sets and fires an event only for a
  domain that newly entered a state — and only once the registry is **live**.
* The registry stays *not live* (silently baselining) until ``set_live`` is called
  from ``async_at_started`` (HA fully started), so an HA restart never replays a
  ``companion_connected`` storm for companions that were already there.

Detection of the *pull* path (a popular upstream installed, its glue absent) is
recomputed cheaply on each coordinator refresh (5-minute cadence) and whenever a
companion (re-)registers — no dedicated config-entry listener needed.
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
    DOMAIN,
    EVENT_COMPANION_CONNECTED,
    EVENT_COMPANION_SUGGESTED,
    EVENT_REGISTER_COMPANIONS,
    OPTION_DISMISSED_COMPANIONS,
)

_LOGGER = logging.getLogger(__name__)


def _http_url(value: Any) -> str:
    """Validate a string is an http(s) URL, else reject.

    The companion descriptor is stored verbatim and a ``docs_url`` flows into the
    panel's ``window.open``; restricting the scheme here keeps a malicious/compromised
    companion from smuggling a ``javascript:`` (or other) URL through.
    """
    text = cv.string(value)
    if text.startswith("http://") or text.startswith("https://"):
        return text
    raise vol.Invalid("expected an http(s) URL")


# A companion's self-registration descriptor. ``domain`` and ``name`` are required;
# everything else is optional metadata the panel uses to render and deep-link the row.
# ``config_entry_id`` lets the panel's "Configure" button open the companion's own
# integration page. Extra keys are ignored (forward-compatible).
REGISTER_COMPANION_SCHEMA = vol.Schema(
    {
        vol.Required("domain"): cv.string,
        vol.Required("name"): cv.string,
        vol.Optional("icon"): cv.string,
        vol.Optional("description"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
        vol.Optional("docs_url"): _http_url,
        vol.Optional("capabilities"): vol.All(cv.ensure_list, [cv.string]),
    },
    extra=vol.REMOVE_EXTRA,
)


class CompanionRegistry:
    """Holds self-registered companions and edge-triggers discovery events."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._registered: dict[str, dict[str, Any]] = {}
        # The connected / suggested domains as of the last reconcile. After each
        # reconcile these mirror the current state; an event fires (when live) for a
        # domain that wasn't in the prior set.
        self._connected: set[str] = set()
        self._suggested: set[str] = set()
        # Gated like the coordinator's transition events: reconciles before this is
        # set baseline silently; only genuine changes observed while running fire.
        self._live = False

    @callback
    def set_live(self) -> None:
        """Start firing discovery events (called once from ``async_at_started``)."""
        self._live = True

    def register(self, descriptor: dict[str, Any]) -> dict[str, Any]:
        """Record a self-registered companion (idempotent); returns the stored row.

        Does not fire events itself — the caller runs ``reconcile`` so a new
        registration is announced through the single edge-trigger path.
        """
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
        if self._registered.get(domain) != stored:
            _LOGGER.debug("Companion registered: %s", domain)
        self._registered[domain] = stored
        return stored

    def _installed_domains(self) -> set[str]:
        """Domains that currently have at least one config entry."""
        return {entry.domain for entry in self._hass.config_entries.async_entries()}

    def _dismissed(self) -> set[str]:
        """Catalog glue domains the user dismissed (read from Home Keeper options)."""
        dismissed: set[str] = set()
        for entry in self._hass.config_entries.async_entries(DOMAIN):
            for domain in entry.options.get(OPTION_DISMISSED_COMPANIONS, []) or []:
                dismissed.add(str(domain))
        return dismissed

    def build(self) -> list[dict[str, Any]]:
        """Return the merged companion rows — a pure read, never fires events."""
        return catalog.build_companion_list(
            self._registered,
            self._installed_domains(),
            dismissed=self._dismissed(),
        )

    @callback
    def reconcile(self) -> list[dict[str, Any]]:
        """Rebuild the rows, firing an event for any domain that newly changed state.

        Always updates the connected/suggested baselines; fires events only when the
        registry is live, so startup reconciles baseline silently. A domain that
        leaves a state (e.g. a companion uninstalled) is dropped from the set, so a
        later re-appearance re-announces.
        """
        rows = self.build()
        by_domain = {
            row["domain"]: row for row in rows if isinstance(row.get("domain"), str)
        }
        connected_now = {
            d for d, row in by_domain.items() if row.get("status") == STATUS_CONNECTED
        }
        suggested_now = {
            d for d, row in by_domain.items() if row.get("status") == STATUS_SUGGESTED
        }
        if self._live:
            for domain in sorted(connected_now - self._connected):
                self._hass.bus.async_fire(
                    EVENT_COMPANION_CONNECTED,
                    events.companion_event_data(by_domain[domain]),
                )
            for domain in sorted(suggested_now - self._suggested):
                self._hass.bus.async_fire(
                    EVENT_COMPANION_SUGGESTED,
                    events.companion_event_data(by_domain[domain]),
                )
        self._connected = connected_now
        self._suggested = suggested_now
        return rows


def async_get_registry(hass: HomeAssistant) -> CompanionRegistry:
    """Return (creating if needed) the per-instance companion registry."""
    registry = hass.data.get(DATA_COMPANIONS)
    if not isinstance(registry, CompanionRegistry):
        registry = CompanionRegistry(hass)
        hass.data[DATA_COMPANIONS] = registry
    return registry


@callback
def async_register_companion(hass: HomeAssistant, descriptor: dict[str, Any]) -> None:
    """Register a companion and reconcile so a newly-connected one announces."""
    registry = async_get_registry(hass)
    registry.register(descriptor)
    registry.reconcile()


@callback
def async_list_companions(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return the merged companion rows (self-registered + catalog detection).

    A pure read — used by the ``get_companions`` websocket command and the
    ``list_companions`` service. Never fires events.
    """
    return async_get_registry(hass).build()


@callback
def async_reconcile(hass: HomeAssistant) -> None:
    """Recompute companion state and fire edge-triggered events (coordinator tick)."""
    async_get_registry(hass).reconcile()


@callback
def async_set_live(hass: HomeAssistant) -> None:
    """Flip the registry live so subsequent reconciles fire events."""
    async_get_registry(hass).set_live()


@callback
def async_request_registration(hass: HomeAssistant) -> None:
    """Ask companions to (re-)announce themselves, then run a detection pass.

    Fired once Home Keeper's services exist so companions that set up first (and
    thus saw no ``register_companion`` service) get a chance to register. The
    reconcile afterwards baselines catalog *suggestions* (silently, since the
    registry isn't live until ``async_at_started``).
    """
    hass.bus.async_fire(EVENT_REGISTER_COMPANIONS)
    async_reconcile(hass)


__all__ = [
    "REGISTER_COMPANION_SCHEMA",
    "STATUS_CONNECTED",
    "STATUS_SUGGESTED",
    "CompanionRegistry",
    "async_get_registry",
    "async_list_companions",
    "async_reconcile",
    "async_register_companion",
    "async_request_registration",
    "async_set_live",
]
