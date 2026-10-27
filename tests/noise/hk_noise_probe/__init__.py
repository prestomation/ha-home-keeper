"""Count what Home Keeper writes, for the noise-budget tier (tests/noise).

This is a test-only integration. ``ci/test-noise.sh`` copies it into a temporary copy
of the integration fixture, so it is never part of the shipped component and never in
the fixture that the other tiers use.

It counts with no timing in it:

* each write of a Home Keeper store file (``Store._async_write_data``),
* each entry setup, unload and reload of the ``home_keeper`` config entry,
* each ``state_changed`` of a Home Keeper entity, by kind,
* each write with an identical state and attributes (``state_reported``),
* each ``home_keeper_*`` bus event, and each call to a to-do, notify or shopping list.

``snapshot`` returns the counts and the seconds since the last count moved, so the
harness can wait until Home Keeper is quiet. ``reset`` sets the counts to 0. A restart
of Home Assistant also sets them to 0, so a snapshot after a restart counts the boot.
The patches are made at import time, before Home Keeper sets up, so the cold start is
counted too.
"""

from __future__ import annotations

import collections
import logging
import time
from typing import Any

from homeassistant import config_entries
from homeassistant.core import (
    Event,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import storage
from homeassistant.helpers.typing import ConfigType

DOMAIN = "hk_noise_probe"
WATCHED = "home_keeper"
OUTBOUND_DOMAINS = ("notify", "persistent_notification", "shopping_list", "todo")
_LOGGER = logging.getLogger(__name__)

_COUNTS: collections.Counter[str] = collections.Counter()
_DETAIL: dict[str, collections.Counter[str]] = collections.defaultdict(
    collections.Counter
)
_LAST_CHANGE = [time.monotonic()]


def _bump(key: str, sub: str | None = None) -> None:
    _COUNTS[key] += 1
    if sub is not None:
        _DETAIL[key][sub] += 1
    _LAST_CHANGE[0] = time.monotonic()


# --- Store writes ---------------------------------------------------------------
_orig_write = storage.Store._async_write_data


async def _write(self: storage.Store[Any], *args: Any) -> None:
    if self.key.startswith(WATCHED):
        _bump("storage_writes", self.key)
    await _orig_write(self, *args)


storage.Store._async_write_data = _write  # type: ignore[method-assign]

# --- Config entry lifecycle -----------------------------------------------------
_entries = config_entries.ConfigEntries
_orig_setup = _entries.async_setup
_orig_unload = _entries.async_unload
_orig_reload = _entries.async_reload


def _watched(manager: config_entries.ConfigEntries, entry_id: str) -> bool:
    entry = manager.async_get_entry(entry_id)
    return entry is not None and entry.domain == WATCHED


async def _setup(
    self: config_entries.ConfigEntries, entry_id: str, *a: Any, **k: Any
) -> bool:
    if _watched(self, entry_id):
        _bump("entry_setups")
    return await _orig_setup(self, entry_id, *a, **k)


async def _unload(
    self: config_entries.ConfigEntries, entry_id: str, *a: Any, **k: Any
) -> bool:
    if _watched(self, entry_id):
        _bump("entry_unloads")
    return await _orig_unload(self, entry_id, *a, **k)


async def _reload(self: config_entries.ConfigEntries, entry_id: str) -> bool:
    if _watched(self, entry_id):
        _bump("entry_reloads")
    return await _orig_reload(self, entry_id)


_entries.async_setup = _setup  # type: ignore[method-assign]
_entries.async_unload = _unload  # type: ignore[method-assign]
_entries.async_reload = _reload  # type: ignore[method-assign]

if hasattr(_entries, "async_schedule_reload"):
    _orig_schedule = _entries.async_schedule_reload

    def _schedule(self: config_entries.ConfigEntries, entry_id: str) -> None:
        if _watched(self, entry_id):
            _bump("entry_reloads", "scheduled")
        _orig_schedule(self, entry_id)

    _entries.async_schedule_reload = _schedule  # type: ignore[method-assign]


def _snapshot(hass: HomeAssistant) -> dict[str, Any]:
    registry = er.async_get(hass)
    return {
        "counts": dict(_COUNTS),
        "detail": {key: dict(c.most_common(30)) for key, c in _DETAIL.items()},
        "quiet_seconds": round(time.monotonic() - _LAST_CHANGE[0], 2),
        "entities": sorted(
            e.entity_id for e in registry.entities.values() if e.platform == WATCHED
        ),
    }


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Listen to the bus and register the probe services."""
    registry = er.async_get(hass)

    @callback
    def _is_watched(entity_id: Any) -> bool:
        if not isinstance(entity_id, str):
            return False
        entry = registry.async_get(entity_id)
        return entry is not None and entry.platform == WATCHED

    @callback
    def _on_state_changed(event: Event[Any]) -> None:
        entity_id = event.data.get("entity_id")
        if not _is_watched(entity_id):
            return
        old, new = event.data.get("old_state"), event.data.get("new_state")
        if old is None:
            _bump("state_added", entity_id)
        elif new is None:
            _bump("state_removed", entity_id)
        elif "unavailable" in (old.state, new.state):
            _bump("unavailable_flips", entity_id)
        elif old.state != new.state:
            _bump("state_value_changes", entity_id)
        else:
            _bump("state_attribute_changes", entity_id)

    @callback
    def _reported_filter(data: Any) -> bool:
        return _is_watched(data.get("entity_id"))

    @callback
    def _on_state_reported(event: Event[Any]) -> None:
        _bump("same_state_writes", event.data.get("entity_id"))

    @callback
    def _on_any(event: Event[Any]) -> None:
        if event.event_type.startswith(WATCHED):
            _bump("events", event.event_type)
        elif event.event_type == "call_service":
            domain = event.data.get("domain")
            if domain in OUTBOUND_DOMAINS:
                _bump("outbound_calls", f"{domain}.{event.data.get('service')}")

    hass.bus.async_listen("state_changed", _on_state_changed)
    hass.bus.async_listen(
        "state_reported", _on_state_reported, event_filter=_reported_filter
    )
    hass.bus.async_listen("*", _on_any)

    async def _reset(call: ServiceCall) -> None:
        _COUNTS.clear()
        _DETAIL.clear()
        _LAST_CHANGE[0] = time.monotonic()

    async def _snap(call: ServiceCall) -> ServiceResponse:
        return _snapshot(hass)

    async def _set_language(call: ServiceCall) -> None:
        # The websocket command config/core/update does the same. A service keeps the
        # harness on plain REST.
        await hass.config.async_update(language=call.data["language"])

    hass.services.async_register(DOMAIN, "reset", _reset)
    hass.services.async_register(
        DOMAIN, "snapshot", _snap, supports_response=SupportsResponse.ONLY
    )

    async def _remove_device(call: ServiceCall) -> None:
        # Home Keeper offers no removal of its devices. A removed appliance device is
        # how Home Assistant gives an appliance a new device id (#467 audit, S5). The
        # registry keeps a removed device, and gives its id back to a new device with
        # the same identifiers, so the record of the removed device goes too.
        registry = dr.async_get(hass)
        registry.async_remove_device(call.data["device_id"])
        registry.deleted_devices.pop(call.data["device_id"], None)

    hass.services.async_register(DOMAIN, "set_language", _set_language)
    hass.services.async_register(DOMAIN, "remove_device", _remove_device)
    _LOGGER.info("Noise probe is counting Home Keeper writes")
    return True
