"""The Home Keeper integration.

Tracks home maintenance and chores. Administration happens in a dedicated sidebar
panel; usage (viewing/completing tasks) is surfaced through native HA entities
(todo, calendar) and per-task device-page entities (button/sensor/binary_sensor).
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from . import panel, websocket_api
from .const import DOMAIN, PLATFORMS
from .coordinator import HomeKeeperCoordinator
from .models import TaskValidationError
from .store import HomeKeeperStore

_LOGGER = logging.getLogger(__name__)

ADD_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Optional("notes"): cv.string,
        vol.Optional("recurrence_type"): cv.string,
        vol.Optional("interval"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("unit"): cv.string,
        vol.Optional("freq"): cv.string,
        vol.Optional("anchor"): cv.string,
        vol.Optional("device_id"): cv.string,
        vol.Optional("area_id"): cv.string,
    }
)
UPDATE_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional("notes"): cv.string,
        vol.Optional("recurrence_type"): cv.string,
        vol.Optional("interval"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("unit"): cv.string,
        vol.Optional("freq"): cv.string,
        vol.Optional("anchor"): cv.string,
        vol.Optional("device_id"): cv.string,
        vol.Optional("area_id"): cv.string,
    }
)
TASK_ID_SCHEMA = vol.Schema({vol.Required("task_id"): cv.string})
COMPLETE_TASK_SCHEMA = vol.Schema(
    {vol.Required("task_id"): cv.string, vol.Optional("completed_at"): cv.datetime}
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration (config-entry only)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Home Keeper from a config entry."""
    store = HomeKeeperStore(hass)
    await store.load()

    coordinator = HomeKeeperCoordinator(hass, entry, store)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await panel.async_register_panel(hass)
    websocket_api.async_register(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _register_services(hass)
    return True


def _register_services(hass: HomeAssistant) -> None:
    """Register Home Keeper services (idempotent across reloads).

    These are the automation-facing surface and the same store methods the panel
    and entities use. DEFERRED: a `home_keeper.contribute_task` service (plus the
    `SIGNAL_TASK_CONTRIBUTION` dispatcher) would let other integrations push tasks
    here without coupling — see IDEAS.md.
    """

    def _coordinator() -> HomeKeeperCoordinator:
        for entry in hass.config_entries.async_entries(DOMAIN):
            coord = getattr(entry, "runtime_data", None)
            if isinstance(coord, HomeKeeperCoordinator):
                return coord
        raise RuntimeError("No active Home Keeper coordinator found")

    async def handle_add_task(call: ServiceCall) -> None:
        coord = _coordinator()
        try:
            await coord.store.add_task(dict(call.data))
        except TaskValidationError as err:
            raise ServiceValidationError(str(err)) from err
        await hass.config_entries.async_reload(coord.entry.entry_id)

    async def handle_update_task(call: ServiceCall) -> None:
        coord = _coordinator()
        data = dict(call.data)
        task_id = data.pop("task_id")
        existing = coord.store.get_task(task_id)
        old_device = existing.get("device_id") if existing else None
        try:
            updated = await coord.store.update_task(task_id, data)
        except KeyError:
            raise ServiceValidationError(f"Task not found: {task_id}") from None
        except TaskValidationError as err:
            raise ServiceValidationError(str(err)) from err
        # Only a device_id change alters which per-task entities exist, so only
        # then do we pay for a full entry reload; otherwise a refresh suffices.
        if updated.get("device_id") != old_device:
            await hass.config_entries.async_reload(coord.entry.entry_id)
        else:
            await coord.async_request_refresh()

    async def handle_delete_task(call: ServiceCall) -> None:
        coord = _coordinator()
        await coord.store.delete_task(call.data["task_id"])
        await hass.config_entries.async_reload(coord.entry.entry_id)

    async def handle_complete_task(call: ServiceCall) -> None:
        coord = _coordinator()
        try:
            await coord.store.complete_task(
                call.data["task_id"], call.data.get("completed_at")
            )
        except KeyError:
            raise ServiceValidationError(
                f"Task not found: {call.data['task_id']}"
            ) from None
        await coord.async_request_refresh()

    async def handle_list_tasks(call: ServiceCall) -> dict[str, Any]:
        coord = _coordinator()
        return {"tasks": coord.store.list_tasks()}

    hass.services.async_register(DOMAIN, "add_task", handle_add_task, ADD_TASK_SCHEMA)
    hass.services.async_register(
        DOMAIN, "update_task", handle_update_task, UPDATE_TASK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "delete_task", handle_delete_task, TASK_ID_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "complete_task", handle_complete_task, COMPLETE_TASK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        "list_tasks",
        handle_list_tasks,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    # Only tear down the panel/services when the last entry goes away.
    if unloaded and not hass.config_entries.async_entries(DOMAIN):
        panel.async_unregister_panel(hass)
        for service in ("add_task", "update_task", "delete_task", "complete_task", "list_tasks"):
            hass.services.async_remove(DOMAIN, service)
    return unloaded
