"""Minimal config flow so HA will set up the seeded config entry.

The entry is seeded directly in ``.storage/core.config_entries``; this flow only
needs to be importable for HA to load and set up that entry. No UI steps are
exercised — Home Keeper detects this glue from its catalog once it's installed.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigFlow

from . import DOMAIN


class BatteryNotesBridgeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Stub flow — never invoked interactively in the e2e harness."""

    VERSION = 1
