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
from homeassistant.util import dt as dt_util

from . import companions, devices, inventory, notifier, options
from .assets import AssetValidationError
from .const import DOMAIN
from .coordinator import HomeKeeperCoordinator, entity_set_key
from .models import TaskValidationError


def _coordinator(hass: HomeAssistant) -> HomeKeeperCoordinator | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        coord = getattr(entry, "runtime_data", None)
        if isinstance(coord, HomeKeeperCoordinator):
            return coord
    return None


def _area_ok(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    payload: dict,
) -> bool:
    """Validate a payload's area_id against HA areas; send an error if unknown."""
    area_id = payload.get("area_id")
    if devices.area_exists(hass, area_id):
        return True
    connection.send_error(msg["id"], "invalid_area", f"Unknown area_id: {area_id}")
    return False


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register all Home Keeper websocket commands."""
    websocket_api.async_register_command(hass, ws_get_tasks)
    websocket_api.async_register_command(hass, ws_add_task)
    websocket_api.async_register_command(hass, ws_update_task)
    websocket_api.async_register_command(hass, ws_delete_task)
    websocket_api.async_register_command(hass, ws_complete_task)
    websocket_api.async_register_command(hass, ws_update_completion)
    websocket_api.async_register_command(hass, ws_delete_completion)
    websocket_api.async_register_command(hass, ws_delete_archived_completion)
    websocket_api.async_register_command(hass, ws_get_assets)
    websocket_api.async_register_command(hass, ws_add_asset)
    websocket_api.async_register_command(hass, ws_update_asset)
    websocket_api.async_register_command(hass, ws_delete_asset)
    websocket_api.async_register_command(hass, ws_adjust_part_stock)
    websocket_api.async_register_command(hass, ws_export_inventory)
    websocket_api.async_register_command(hass, ws_get_options)
    websocket_api.async_register_command(hass, ws_set_options)
    websocket_api.async_register_command(hass, ws_get_companions)


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
    if not _area_ok(hass, connection, msg, msg["task"]):
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
    if not _area_ok(hass, connection, msg, msg["updates"]):
        return
    before = entity_set_key(coord.store.get_task(msg["task_id"]))
    try:
        task = await coord.store.update_task(msg["task_id"], msg["updates"])
    except KeyError:
        connection.send_error(msg["id"], "not_found", "Unknown task_id")
        return
    except TaskValidationError as err:
        connection.send_error(msg["id"], "invalid_task", str(err))
        return
    # Only changes that alter which per-task entities exist (device link or
    # enabled state) need a reload; otherwise a coordinator refresh is enough.
    if entity_set_key(task) != before:
        await hass.config_entries.async_reload(coord.entry.entry_id)
    else:
        await coord.async_request_refresh()
    connection.send_result(msg["id"], {"task": task})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/delete_task",
        vol.Required("task_id"): str,
        vol.Optional("force", default=False): bool,
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
    try:
        await coord.store.delete_task(msg["task_id"], force=msg.get("force", False))
    except TaskValidationError as err:
        connection.send_error(msg["id"], "invalid_task", str(err))
        return
    await hass.config_entries.async_reload(coord.entry.entry_id)
    connection.send_result(msg["id"], {"ok": True})


def _ws_metadata(msg: dict[str, Any]) -> dict[str, Any]:
    """Lift the optional per-completion metadata keys out of a websocket message."""
    return {k: msg[k] for k in ("note", "cost", "photo", "who") if k in msg}


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/complete_task",
        vol.Required("task_id"): str,
        vol.Optional("note"): str,
        vol.Optional("cost"): vol.Coerce(float),
        vol.Optional("photo"): str,
        vol.Optional("who"): str,
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
        task = await coord.store.complete_task(
            msg["task_id"], metadata=_ws_metadata(msg)
        )
    except KeyError:
        connection.send_error(msg["id"], "not_found", "Unknown task_id")
        return
    except TaskValidationError as err:
        connection.send_error(msg["id"], "not_allowed", str(err))
        return
    await coord.async_request_refresh()
    connection.send_result(msg["id"], {"task": task})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/update_completion",
        vol.Required("task_id"): str,
        vol.Required("ts"): str,
        vol.Optional("note"): str,
        vol.Optional("cost"): vol.Coerce(float),
        vol.Optional("photo"): str,
        vol.Optional("who"): str,
    }
)
@websocket_api.async_response
async def ws_update_completion(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        connection.send_error(msg["id"], "not_loaded", "Home Keeper is not loaded")
        return
    try:
        task = await coord.store.update_completion(
            msg["task_id"], msg["ts"], _ws_metadata(msg)
        )
    except KeyError:
        connection.send_error(msg["id"], "not_found", "Unknown task_id")
        return
    except TaskValidationError as err:
        connection.send_error(msg["id"], "not_allowed", str(err))
        return
    await coord.async_request_refresh()
    connection.send_result(msg["id"], {"task": task})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/delete_completion",
        vol.Required("task_id"): str,
        vol.Required("ts"): str,
    }
)
@websocket_api.async_response
async def ws_delete_completion(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        connection.send_error(msg["id"], "not_loaded", "Home Keeper is not loaded")
        return
    try:
        task = await coord.store.delete_completion(msg["task_id"], msg["ts"])
    except KeyError:
        connection.send_error(msg["id"], "not_found", "Unknown task_id")
        return
    except TaskValidationError as err:
        connection.send_error(msg["id"], "not_allowed", str(err))
        return
    await coord.async_request_refresh()
    connection.send_result(msg["id"], {"task": task})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/delete_archived_completion",
        vol.Required("asset_id"): str,
        vol.Required("task_id"): str,
        vol.Required("ts"): str,
    }
)
@websocket_api.async_response
async def ws_delete_archived_completion(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        connection.send_error(msg["id"], "not_loaded", "Home Keeper is not loaded")
        return
    try:
        asset = await coord.store.delete_archived_completion(
            msg["asset_id"], msg["task_id"], msg["ts"]
        )
    except KeyError:
        connection.send_error(msg["id"], "not_found", "Unknown asset_id")
        return
    await coord.async_request_refresh()
    connection.send_result(msg["id"], {"asset": asset})


@websocket_api.websocket_command({vol.Required("type"): "home_keeper/get_assets"})
@websocket_api.async_response
async def ws_get_assets(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        connection.send_error(msg["id"], "not_loaded", "Home Keeper is not loaded")
        return
    connection.send_result(msg["id"], {"assets": coord.store.list_assets()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/add_asset",
        vol.Required("asset"): dict,
    }
)
@websocket_api.async_response
async def ws_add_asset(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        connection.send_error(msg["id"], "not_loaded", "Home Keeper is not loaded")
        return
    if not _area_ok(hass, connection, msg, msg["asset"]):
        return
    try:
        asset = await coord.store.add_asset(msg["asset"])
    except AssetValidationError as err:
        connection.send_error(msg["id"], "invalid_asset", str(err))
        return
    await devices.async_apply_asset_change(hass, coord.entry, coord.store)
    # Re-read so the response carries the provisioned device_id.
    connection.send_result(
        msg["id"], {"asset": coord.store.get_asset(asset["id"]) or asset}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/update_asset",
        vol.Required("asset_id"): str,
        vol.Required("updates"): dict,
    }
)
@websocket_api.async_response
async def ws_update_asset(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        connection.send_error(msg["id"], "not_loaded", "Home Keeper is not loaded")
        return
    if not _area_ok(hass, connection, msg, msg["updates"]):
        return
    try:
        asset = await coord.store.update_asset(msg["asset_id"], msg["updates"])
    except KeyError:
        connection.send_error(msg["id"], "not_found", "Unknown asset_id")
        return
    except AssetValidationError as err:
        connection.send_error(msg["id"], "invalid_asset", str(err))
        return
    await devices.async_apply_asset_change(hass, coord.entry, coord.store)
    connection.send_result(
        msg["id"], {"asset": coord.store.get_asset(asset["id"]) or asset}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/delete_asset",
        vol.Required("asset_id"): str,
    }
)
@websocket_api.async_response
async def ws_delete_asset(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        connection.send_error(msg["id"], "not_loaded", "Home Keeper is not loaded")
        return
    asset = await coord.store.delete_asset(msg["asset_id"])
    if asset is not None:
        removed_device_id = await devices.async_remove_asset_device(hass, asset)
        if removed_device_id:
            await coord.store.detach_tasks_from_device(removed_device_id)
        await hass.config_entries.async_reload(coord.entry.entry_id)
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/adjust_part_stock",
        vol.Required("asset_id"): str,
        vol.Required("part_id"): str,
        vol.Required("delta"): int,
    }
)
@websocket_api.async_response
async def ws_adjust_part_stock(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        connection.send_error(msg["id"], "not_loaded", "Home Keeper is not loaded")
        return
    try:
        asset = await coord.store.adjust_part_stock(
            msg["asset_id"], msg["part_id"], msg["delta"]
        )
    except KeyError:
        connection.send_error(msg["id"], "not_found", "Unknown asset_id or part_id")
        return
    await coord.async_request_refresh()
    connection.send_result(msg["id"], {"asset": asset})


@websocket_api.websocket_command({vol.Required("type"): "home_keeper/export_inventory"})
@websocket_api.async_response
async def ws_export_inventory(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the home-inventory report (for insurance) plus a ready-to-save CSV."""
    coord = _coordinator(hass)
    if coord is None:
        connection.send_error(msg["id"], "not_loaded", "Home Keeper is not loaded")
        return
    report = inventory.build_inventory(
        coord.store.list_assets(),
        area_names=devices.area_names(hass),
        today=dt_util.now().date(),
    )
    connection.send_result(
        msg["id"],
        {"inventory": report, "csv": inventory.inventory_to_csv(report)},
    )


@websocket_api.websocket_command({vol.Required("type"): "home_keeper/get_options"})
@websocket_api.async_response
async def ws_get_options(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the config-entry options for the panel's Settings tab.

    Also returns ``notify_targets`` — the ``mobile_app_*`` notify services available
    right now — so the Notifications card can offer them as a checklist instead of
    making the user type service names.
    """
    coord = _coordinator(hass)
    if coord is None:
        connection.send_error(msg["id"], "not_loaded", "Home Keeper is not loaded")
        return
    connection.send_result(
        msg["id"],
        {
            "options": options.current_options(coord.entry),
            "notify_targets": notifier.available_targets(hass),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/set_options",
        vol.Required("options"): dict,
    }
)
@websocket_api.async_response
async def ws_set_options(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Persist options from the Settings tab (delegates to the shared service path).

    ``async_set_options`` updates the entry, which reloads it and re-runs the
    problem-sensor sync. Mirrors the ``home_keeper.set_options`` service.
    """
    coord = _coordinator(hass)
    if coord is None:
        connection.send_error(msg["id"], "not_loaded", "Home Keeper is not loaded")
        return
    merged = await options.async_set_options(hass, coord.entry, msg["options"])
    connection.send_result(msg["id"], {"options": merged})


@websocket_api.websocket_command({vol.Required("type"): "home_keeper/get_companions"})
@websocket_api.async_response
async def ws_get_companions(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the companion rows for the Settings → Companions section.

    Merges self-registered companions (the push path) with catalog detection of
    popular upstreams whose glue isn't installed yet (the pull path). See
    companions.py.
    """
    if _coordinator(hass) is None:
        connection.send_error(msg["id"], "not_loaded", "Home Keeper is not loaded")
        return
    connection.send_result(
        msg["id"], {"companions": companions.async_list_companions(hass)}
    )
