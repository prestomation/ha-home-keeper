"""Minimal config flow so HA will set up the seeded config entry.

The entry is seeded directly in ``.storage/core.config_entries``; this flow only
needs to be importable for HA to load and set that entry up. No UI step is ever
exercised by the upgrade suite.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigFlow

from . import DOMAIN


class BambuLabStubConfigFlow(ConfigFlow, domain=DOMAIN):
    """Stub flow — never invoked interactively."""

    VERSION = 1
