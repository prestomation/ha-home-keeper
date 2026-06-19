"""Config flow for Home Keeper.

A single config entry is supported; tasks are managed from the sidebar panel
rather than the config flow, so setup is a one-click confirmation. An **options**
flow exposes the integration-wide settings — currently the opt-in syncing of
``device_class: problem`` binary sensors as tasks, with entity/area/label
exclusions.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS,
    OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS,
    OPTION_SYNC_PROBLEM_SENSORS,
    PANEL_TITLE,
)


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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return HomeKeeperOptionsFlow()


class HomeKeeperOptionsFlow(OptionsFlow):
    """Integration-wide options (problem-sensor syncing)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single options step. Saving triggers a reload (see __init__)."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    OPTION_SYNC_PROBLEM_SENSORS,
                    default=current.get(OPTION_SYNC_PROBLEM_SENSORS, False),
                ): selector.BooleanSelector(),
                vol.Optional(
                    OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES,
                    default=current.get(OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES, []),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="binary_sensor",
                        device_class=BinarySensorDeviceClass.PROBLEM,
                        multiple=True,
                    )
                ),
                vol.Optional(
                    OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS,
                    default=current.get(OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS, []),
                ): selector.AreaSelector(
                    selector.AreaSelectorConfig(multiple=True)
                ),
                vol.Optional(
                    OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS,
                    default=current.get(OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS, []),
                ): selector.LabelSelector(
                    selector.LabelSelectorConfig(multiple=True)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
