"""Shared read/write helpers for the config-entry ``options``.

Three surfaces edit the same options object — the **options flow**
(``config_flow.HomeKeeperOptionsFlow``), the **``set_options`` service**, and the
**panel's Settings tab** (over the ``home_keeper/get_options`` /
``home_keeper/set_options`` websocket commands). The key list, defaults, and
normalization live here so they can't drift. Writing options goes through
``hass.config_entries.async_update_entry``, which fires the entry's update listener
(wired in ``__init__``) and reloads — re-running the problem-sensor reconcile.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS,
    OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS,
    OPTION_SYNC_PROBLEM_SENSORS,
)

# The exclusion options are id lists; the sync toggle is the only boolean.
_LIST_OPTIONS = (
    OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS,
    OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS,
)


def current_options(entry: ConfigEntry) -> dict[str, Any]:
    """Return the entry's options with every key defaulted (toggle off, lists empty).

    A fully-populated dict keeps the panel form and the options flow simple — they
    never have to special-case a missing key.
    """
    opts = entry.options or {}
    result: dict[str, Any] = {
        OPTION_SYNC_PROBLEM_SENSORS: bool(opts.get(OPTION_SYNC_PROBLEM_SENSORS, False)),
    }
    for key in _LIST_OPTIONS:
        result[key] = list(opts.get(key, []) or [])
    return result


def _normalize(updates: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """Merge *updates* onto *base*, coercing to the stored shape (bool / id list)."""
    merged = dict(base)
    if OPTION_SYNC_PROBLEM_SENSORS in updates:
        merged[OPTION_SYNC_PROBLEM_SENSORS] = bool(updates[OPTION_SYNC_PROBLEM_SENSORS])
    for key in _LIST_OPTIONS:
        if key in updates:
            merged[key] = [str(x) for x in (updates[key] or [])]
    return merged


async def async_set_options(
    hass: HomeAssistant, entry: ConfigEntry, updates: dict[str, Any]
) -> dict[str, Any]:
    """Apply a partial options *updates* to *entry* and persist; returns the merged set.

    Only the keys present in *updates* change (the panel saves the whole form, but
    the service / an automation may set just one). ``async_update_entry`` reloads the
    entry when the options actually change, which re-runs the problem-sensor sync.
    """
    merged = _normalize(updates, current_options(entry))
    hass.config_entries.async_update_entry(entry, options=merged)
    return merged
