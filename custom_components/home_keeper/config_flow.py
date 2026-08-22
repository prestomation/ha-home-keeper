"""Config flow for Home Keeper.

A single config entry is supported; tasks are managed from the sidebar panel
rather than the config flow, so setup is a one-click confirmation. An **options**
flow exposes the integration-wide settings — the opt-in syncing of
``device_class: problem`` binary sensors as tasks (with entity/area/label
exclusions), completed one-off retention, and the to-do list auto-buy reminders
are mirrored onto.

That form covers only ``options.FLOW_OPTIONS``; profiles, notifications and
dismissed companions are edited from the panel and never appear here. Since Home
Assistant stores an options flow's result as the *entire* ``entry.options``, saving
goes through ``options.merge_flow_input`` so those keep their values.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from . import options
from .const import (
    DOMAIN,
    OPTION_ONE_OFF_RETENTION_DAYS,
    OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS,
    OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS,
    OPTION_SHOPPING_LIST_ENTITY,
    OPTION_SYNC_PROBLEM_SENSORS,
    PANEL_TITLE,
)
from .shopping import TODO_DOMAIN
from .shopping_sync import own_todo_entity_ids


def _options_schema(hass: HomeAssistant, current: dict[str, Any]) -> vol.Schema:
    """Build the options form, defaulted from *current* (an ``options`` dict).

    Its keys must be exactly ``options.FLOW_OPTIONS``, in this order —
    ``tests/unit/test_config_flow.py`` fails the build if they drift, because both
    directions lose data. A field here that the tuple omits is discarded on save; a
    key in the tuple that this form omits is *cleared* on every save.

    A field's ``default`` decides what an empty submission means, so choose it
    deliberately when adding one. With a ``default``, voluptuous fills the value back
    in and the key always reaches ``merge_flow_input``. Without one — which only
    ``shopping_list_entity`` wants — the key drops out when the user clears it, and
    that absence is read as "cleared" and reset.
    """
    return vol.Schema(
        {
            vol.Required(
                OPTION_SYNC_PROBLEM_SENSORS,
                default=current[OPTION_SYNC_PROBLEM_SENSORS],
            ): selector.BooleanSelector(),
            vol.Optional(
                OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES,
                default=current[OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES],
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="binary_sensor",
                    device_class=BinarySensorDeviceClass.PROBLEM,
                    multiple=True,
                )
            ),
            vol.Optional(
                OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES,
                default=current[OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES],
            ): selector.DeviceSelector(selector.DeviceSelectorConfig(multiple=True)),
            vol.Optional(
                OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS,
                default=current[OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS],
            ): selector.AreaSelector(selector.AreaSelectorConfig(multiple=True)),
            vol.Optional(
                OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS,
                default=current[OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS],
            ): selector.LabelSelector(selector.LabelSelectorConfig(multiple=True)),
            # Auto-delete completed one-off tasks this many days after completion;
            # 0 keeps them forever.
            vol.Optional(
                OPTION_ONE_OFF_RETENTION_DAYS,
                default=current[OPTION_ONE_OFF_RETENTION_DAYS],
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=3650, step=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            # The to-do list auto-buy reminders are mirrored onto. Deliberately
            # has no ``default``: clearing the picker then leaves the key out of
            # ``user_input`` entirely, which is how the mirror is turned off —
            # ``options.merge_flow_input`` reads a missing ``FLOW_OPTIONS`` key as
            # "the user cleared this" and resets it to ``""``. Home Keeper's own
            # to-do list is excluded, since mirroring a list onto itself is a loop
            # (and ours accepts no new items anyway).
            vol.Optional(
                OPTION_SHOPPING_LIST_ENTITY,
                description={
                    "suggested_value": current[OPTION_SHOPPING_LIST_ENTITY] or None
                },
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=TODO_DOMAIN,
                    exclude_entities=own_todo_entity_ids(hass),
                )
            ),
        }
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
    """Integration-wide options (problem-sensor syncing, retention, mirroring)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single options step. Saving triggers a reload (see __init__).

        Home Assistant stores what this returns as ``entry.options`` **verbatim** —
        the whole object, not a patch — and the form renders only
        ``options.FLOW_OPTIONS``. So the submission is merged onto the current
        options rather than replacing them: returning ``user_input`` directly deleted
        every saved profile, notification and dismissed companion on each save.
        """
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data=options.merge_flow_input(self.config_entry, user_input),
            )

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(
                self.hass, options.current_options(self.config_entry)
            ),
        )
