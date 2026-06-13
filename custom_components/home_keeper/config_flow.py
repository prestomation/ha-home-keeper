"""Config flow for Home Keeper.

A single config entry is supported; tasks are managed from the sidebar panel
rather than the config flow, so setup is a one-click confirmation.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN, PANEL_TITLE


class HomeKeeperConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Home Keeper config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single-instance setup."""
        await self.async_set_unique_id("home_keeper_local")
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title=PANEL_TITLE, data={})

        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))
