"""Minimal config flow so Home Assistant sets up the seeded config entry.

The entry is seeded in ``.storage/core.config_entries``. The flow only has to be
importable. No UI step runs.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigFlow

from . import DOMAIN


class DemoTabConfigFlow(ConfigFlow, domain=DOMAIN):
    """Stub flow. The e2e harness never starts it."""

    VERSION = 1
