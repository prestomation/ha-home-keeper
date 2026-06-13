"""WebSocket API for the Home Keeper sidebar panel.

The admin panel uses these typed commands for snappy reads and CRUD without
round-tripping through entities. Each mutation refreshes the coordinator (and
reloads the entry on add/delete so per-task entities appear/disappear).
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .coordinator import HomeKeeperCoordinator
from .models import TaskValidationError


def _coordinator(hass: HomeAssistant) -> HomeKeeperCoordinator | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        coord = getattr(entry, "runtime_data", None)
        if isinstance(coord, HomeKeeperCoordinator):
            return coord
    return None


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register all Home Keeper websocket commands."""
    websocket_api.async_register_command(hass, ws_get_tasks)
    websocket_api.async_register_command(hass, ws_add_task)
    websocket_api.async_register_command(hass, ws_update_task)
    websocket_api.async_register_command(hass, ws_delete_task)
    websocket_api.async_register_command(hass, ws_complete_task)


@websocket_api.websocket_command({vol.Required("type"): "home_keeper/get_tasks"})
@websocket_api.async_response
async def ws_get_tasks(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        connection.send_error(msg["id"], "not_loaded", "Home Keeper is not loaded")
        return
    connection.send_result(msg["id"], {"tasks": coord.store.list_tasks()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/add_task",
        vol.Required("task"): dict,
    }
)
@websocket_api.async_response
async def ws_add_task(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        connection.send_error(msg["id"], "not_loaded", "Home Keeper is not loaded")
        return
    try:
        task = await coord.store.add_task(msg["task"])
    except TaskValidationError as err:
        connection.send_error(msg["id"], "invalid_task", str(err))
        return
    await hass.config_entries.async_reload(coord.entry.entry_id)
    connection.send_result(msg["id"], {"task": task})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/update_task",
        vol.Required("task_id"): str,
        vol.Required("updates"): dict,
    }
)
@websocket_api.async_response
async def ws_update_task(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        connection.send_error(msg["id"], "not_loaded", "Home Keeper is not loaded")
        return
    try:
        task = await coord.store.update_task(msg["task_id"], msg["updates"])
    except KeyError:
        connection.send_error(msg["id"], "not_found", "Unknown task_id")
        return
    except TaskValidationError as err:
        connection.send_error(msg["id"], "invalid_task", str(err))
        return
    # device_id changes affect which entities exist -> reload to re-evaluate.
    await hass.config_entries.async_reload(coord.entry.entry_id)
    connection.send_result(msg["id"], {"task": task})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/delete_task",
        vol.Required("task_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_task(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        connection.send_error(msg["id"], "not_loaded", "Home Keeper is not loaded")
        return
    await coord.store.delete_task(msg["task_id"])
    await hass.config_entries.async_reload(coord.entry.entry_id)
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/complete_task",
        vol.Required("task_id"): str,
    }
)
@websocket_api.async_response
async def ws_complete_task(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        connection.send_error(msg["id"], "not_loaded", "Home Keeper is not loaded")
        return
    try:
        task = await coord.store.complete_task(msg["task_id"])
    except KeyError:
        connection.send_error(msg["id"], "not_found", "Unknown task_id")
        return
    await coord.async_request_refresh()
    connection.send_result(msg["id"], {"task": task})
