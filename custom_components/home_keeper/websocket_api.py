"""WebSocket API for the Home Keeper sidebar panel.

The admin panel uses these typed commands for snappy reads and CRUD without
round-tripping through entities. Each mutation refreshes the coordinator (and
reloads the entry on add/delete so per-task entities appear/disappear).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from . import companions, devices, inventory, manuals, notifier, options
from .assets import AssetValidationError
from .backend_i18n import resolve_exception
from .const import DOMAIN, OPTION_PROFILES
from .coordinator import HomeKeeperCoordinator, entity_set_key, task_has_entities
from .models import TaskValidationError

# How long a signed document URL stays valid. The dashboard card pre-signs file
# documents and embeds the URL as a plain <a href> (so a tap opens natively — the iOS
# app's WKWebView blocks an async window.open), so the URL must outlive a reasonably
# idle dashboard, not just a click. The card re-signs well before this on refresh.
_DOCUMENT_URL_TTL = timedelta(hours=1)


def _coordinator(hass: HomeAssistant) -> HomeKeeperCoordinator | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        coord = getattr(entry, "runtime_data", None)
        if isinstance(coord, HomeKeeperCoordinator):
            return coord
    return None


def _err(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    code: str,
    key: str,
    **params: Any,
) -> None:
    """Send a websocket error with text localized to ``hass.config.language``.

    ``connection.send_error`` needs the final string immediately — unlike a
    ``ServiceValidationError``'s ``translation_key``, nothing downstream localizes
    it later — so it's resolved here from the same ``exceptions`` strings.json
    category via :func:`backend_i18n.resolve_exception`. See ``backend_i18n.py``.
    """
    text = resolve_exception(hass.config.language, key, **params)
    connection.send_error(msg["id"], code, text)


def _not_loaded(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    _err(hass, connection, msg, "not_loaded", "integration_not_loaded")


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
    _err(hass, connection, msg, "invalid_area", "unknown_area", area_id=area_id)
    return False


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register all Home Keeper websocket commands."""
    websocket_api.async_register_command(hass, ws_get_tasks)
    websocket_api.async_register_command(hass, ws_add_task)
    websocket_api.async_register_command(hass, ws_update_task)
    websocket_api.async_register_command(hass, ws_delete_task)
    websocket_api.async_register_command(hass, ws_set_task_consumable)
    websocket_api.async_register_command(hass, ws_complete_task)
    websocket_api.async_register_command(hass, ws_update_completion)
    websocket_api.async_register_command(hass, ws_move_completion)
    websocket_api.async_register_command(hass, ws_delete_completion)
    websocket_api.async_register_command(hass, ws_delete_archived_completion)
    websocket_api.async_register_command(hass, ws_get_assets)
    websocket_api.async_register_command(hass, ws_add_asset)
    websocket_api.async_register_command(hass, ws_update_asset)
    websocket_api.async_register_command(hass, ws_delete_asset)
    websocket_api.async_register_command(hass, ws_adjust_part_stock)
    websocket_api.async_register_command(hass, ws_add_asset_document)
    websocket_api.async_register_command(hass, ws_remove_asset_document)
    websocket_api.async_register_command(hass, ws_update_asset_document)
    websocket_api.async_register_command(hass, ws_sign_document_url)
    websocket_api.async_register_command(hass, ws_remove_part_file)
    websocket_api.async_register_command(hass, ws_sign_part_file_url)
    websocket_api.async_register_command(hass, ws_export_inventory)
    websocket_api.async_register_command(hass, ws_get_options)
    websocket_api.async_register_command(hass, ws_set_options)
    websocket_api.async_register_command(hass, ws_get_companions)
    websocket_api.async_register_command(hass, ws_get_profiles)


@websocket_api.websocket_command({vol.Required("type"): "home_keeper/get_tasks"})
@websocket_api.async_response
async def ws_get_tasks(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        _not_loaded(hass, connection, msg)
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
        _not_loaded(hass, connection, msg)
        return
    if not _area_ok(hass, connection, msg, msg["task"]):
        return
    try:
        task = await coord.store.add_task(msg["task"])
    except TaskValidationError as err:
        _err(hass, connection, msg, "invalid_task", "invalid_task", error=str(err))
        return
    # Reload only when the new task owns per-task entities; else a refresh suffices.
    if task_has_entities(task):
        await hass.config_entries.async_reload(coord.entry.entry_id)
    else:
        await coord.async_request_refresh()
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
        _not_loaded(hass, connection, msg)
        return
    if not _area_ok(hass, connection, msg, msg["updates"]):
        return
    before = entity_set_key(coord.store.get_task(msg["task_id"]))
    try:
        task = await coord.store.update_task(msg["task_id"], msg["updates"])
    except KeyError:
        _err(
            hass, connection, msg, "not_found", "task_not_found", task_id=msg["task_id"]
        )
        return
    except TaskValidationError as err:
        _err(hass, connection, msg, "invalid_task", "invalid_task", error=str(err))
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
        _not_loaded(hass, connection, msg)
        return
    existing = coord.store.get_task(msg["task_id"])
    try:
        await coord.store.delete_task(msg["task_id"], force=msg.get("force", False))
    except TaskValidationError as err:
        _err(hass, connection, msg, "invalid_task", "invalid_task", error=str(err))
        return
    # Reload only if the deleted task owned per-task entities that must be removed.
    if task_has_entities(existing):
        await hass.config_entries.async_reload(coord.entry.entry_id)
    else:
        await coord.async_request_refresh()
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/set_task_consumable",
        vol.Required("task_id"): str,
        # Both null clears the link; both set links the task to that part.
        vol.Required("asset_id"): vol.Any(str, None),
        vol.Required("part_id"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_set_task_consumable(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        _not_loaded(hass, connection, msg)
        return
    try:
        task = await coord.store.set_task_consumable(
            msg["task_id"], msg["asset_id"], msg["part_id"]
        )
    except KeyError:
        _err(
            hass, connection, msg, "not_found", "task_not_found", task_id=msg["task_id"]
        )
        return
    except TaskValidationError as err:
        _err(hass, connection, msg, "invalid_task", "invalid_task", error=str(err))
        return
    # Linking only rewrites the task's source; the per-task entity set is unchanged,
    # so a refresh is enough (no entry reload).
    await coord.async_request_refresh()
    connection.send_result(msg["id"], {"task": task})


def _ws_metadata(msg: dict[str, Any]) -> dict[str, Any]:
    """Lift the optional per-completion metadata keys out of a websocket message."""
    return {k: msg[k] for k in ("note", "cost", "photo", "who") if k in msg}


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/complete_task",
        vol.Required("task_id"): str,
        vol.Optional("completed_at"): str,
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
        _not_loaded(hass, connection, msg)
        return
    completed_at = None
    if "completed_at" in msg:
        completed_at = dt_util.parse_datetime(msg["completed_at"])
        if completed_at is None:
            _err(hass, connection, msg, "invalid_format", "invalid_completed_at")
            return
    try:
        task = await coord.store.complete_task(
            msg["task_id"], completed_at, metadata=_ws_metadata(msg)
        )
    except KeyError:
        _err(
            hass, connection, msg, "not_found", "task_not_found", task_id=msg["task_id"]
        )
        return
    except TaskValidationError as err:
        _err(hass, connection, msg, "not_allowed", "complete_failed", error=str(err))
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
        _not_loaded(hass, connection, msg)
        return
    try:
        task = await coord.store.update_completion(
            msg["task_id"], msg["ts"], _ws_metadata(msg)
        )
    except KeyError:
        _err(
            hass, connection, msg, "not_found", "task_not_found", task_id=msg["task_id"]
        )
        return
    except TaskValidationError as err:
        _err(hass, connection, msg, "not_allowed", "invalid_task", error=str(err))
        return
    await coord.async_request_refresh()
    connection.send_result(msg["id"], {"task": task})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/move_completion",
        vol.Required("task_id"): str,
        vol.Required("old_ts"): str,
        vol.Required("new_ts"): str,
    }
)
@websocket_api.async_response
async def ws_move_completion(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        _not_loaded(hass, connection, msg)
        return
    try:
        task = await coord.store.move_completion(
            msg["task_id"], msg["old_ts"], msg["new_ts"]
        )
    except KeyError:
        _err(
            hass, connection, msg, "not_found", "task_not_found", task_id=msg["task_id"]
        )
        return
    except TaskValidationError as err:
        _err(hass, connection, msg, "not_allowed", "invalid_task", error=str(err))
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
        _not_loaded(hass, connection, msg)
        return
    try:
        task = await coord.store.delete_completion(msg["task_id"], msg["ts"])
    except KeyError:
        _err(
            hass, connection, msg, "not_found", "task_not_found", task_id=msg["task_id"]
        )
        return
    except TaskValidationError as err:
        _err(hass, connection, msg, "not_allowed", "invalid_task", error=str(err))
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
        _not_loaded(hass, connection, msg)
        return
    try:
        asset = await coord.store.delete_archived_completion(
            msg["asset_id"], msg["task_id"], msg["ts"]
        )
    except KeyError:
        _err(
            hass,
            connection,
            msg,
            "not_found",
            "asset_not_found",
            asset_id=msg["asset_id"],
        )
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
        _not_loaded(hass, connection, msg)
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
        _not_loaded(hass, connection, msg)
        return
    if not _area_ok(hass, connection, msg, msg["asset"]):
        return
    try:
        asset = await coord.store.add_asset(msg["asset"])
    except AssetValidationError as err:
        _err(hass, connection, msg, "invalid_asset", "invalid_asset", error=str(err))
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
        _not_loaded(hass, connection, msg)
        return
    if not _area_ok(hass, connection, msg, msg["updates"]):
        return
    try:
        asset = await coord.store.update_asset(msg["asset_id"], msg["updates"])
    except KeyError:
        _err(
            hass,
            connection,
            msg,
            "not_found",
            "asset_not_found",
            asset_id=msg["asset_id"],
        )
        return
    except AssetValidationError as err:
        _err(hass, connection, msg, "invalid_asset", "invalid_asset", error=str(err))
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
        _not_loaded(hass, connection, msg)
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
        _not_loaded(hass, connection, msg)
        return
    try:
        asset = await coord.store.adjust_part_stock(
            msg["asset_id"], msg["part_id"], msg["delta"]
        )
    except KeyError:
        _err(
            hass,
            connection,
            msg,
            "not_found",
            "unknown_part",
            asset_id=msg["asset_id"],
            part_id=msg["part_id"],
        )
        return
    # A crossing may create/remove an auto-buy task; settle it (reload if a buy task's
    # device entities changed, else refresh).
    await coord.async_settle_buy_tasks()
    connection.send_result(msg["id"], {"asset": asset})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/add_asset_document",
        vol.Required("asset_id"): str,
        vol.Required("document"): dict,
    }
)
@websocket_api.async_response
async def ws_add_asset_document(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        _not_loaded(hass, connection, msg)
        return
    document = dict(msg["document"])
    # Files are uploaded through the HTTP view; this command only adds links.
    if document.get("kind", "link") != "link":
        _err(hass, connection, msg, "invalid_asset", "link_documents_only")
        return
    document["kind"] = "link"
    try:
        await coord.store.add_asset_document(msg["asset_id"], document)
    except KeyError:
        _err(
            hass,
            connection,
            msg,
            "not_found",
            "asset_not_found",
            asset_id=msg["asset_id"],
        )
        return
    except AssetValidationError as err:
        _err(hass, connection, msg, "invalid_asset", "invalid_asset", error=str(err))
        return
    # Documents touch no device/entity/task; the store already saved and fired the
    # event, so no device reconcile or entry reload is needed.
    connection.send_result(msg["id"], {"asset": coord.store.get_asset(msg["asset_id"])})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/remove_asset_document",
        vol.Required("asset_id"): str,
        vol.Required("document_id"): str,
    }
)
@websocket_api.async_response
async def ws_remove_asset_document(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        _not_loaded(hass, connection, msg)
        return
    try:
        asset = await coord.store.remove_asset_document(
            msg["asset_id"], msg["document_id"]
        )
    except KeyError:
        _err(
            hass,
            connection,
            msg,
            "not_found",
            "unknown_document",
            document_id=msg["document_id"],
        )
        return
    # Documents touch no device/entity/task; no device reconcile or entry reload needed.
    connection.send_result(msg["id"], {"asset": asset})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/update_asset_document",
        vol.Required("asset_id"): str,
        vol.Required("document_id"): str,
        vol.Required("changes"): dict,
    }
)
@websocket_api.async_response
async def ws_update_asset_document(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        _not_loaded(hass, connection, msg)
        return
    try:
        await coord.store.update_asset_document(
            msg["asset_id"], msg["document_id"], msg["changes"]
        )
    except KeyError:
        _err(
            hass,
            connection,
            msg,
            "not_found",
            "unknown_document",
            document_id=msg["document_id"],
        )
        return
    except AssetValidationError as err:
        _err(hass, connection, msg, "invalid_asset", "invalid_asset", error=str(err))
        return
    connection.send_result(msg["id"], {"asset": coord.store.get_asset(msg["asset_id"])})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/sign_document_url",
        vol.Required("asset_id"): str,
        vol.Required("document_id"): str,
    }
)
@websocket_api.async_response
async def ws_sign_document_url(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Mint a short-lived signed URL the browser can open for a file document."""
    coord = _coordinator(hass)
    if coord is None:
        _not_loaded(hass, connection, msg)
        return
    asset = coord.store.get_asset(msg["asset_id"])
    document = next(
        (
            d
            for d in (asset or {}).get("documents", [])
            if d.get("id") == msg["document_id"] and d.get("kind") == "file"
        ),
        None,
    )
    if document is None:
        _err(
            hass,
            connection,
            msg,
            "not_found",
            "unknown_document",
            document_id=msg["document_id"],
        )
        return
    path = manuals.document_path(msg["asset_id"], msg["document_id"])
    signed = async_sign_path(
        hass,
        path,
        _DOCUMENT_URL_TTL,
        refresh_token_id=connection.refresh_token_id,
    )
    connection.send_result(msg["id"], {"url": signed})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/remove_part_file",
        vol.Required("asset_id"): str,
        vol.Required("part_id"): str,
    }
)
@websocket_api.async_response
async def ws_remove_part_file(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    coord = _coordinator(hass)
    if coord is None:
        _not_loaded(hass, connection, msg)
        return
    try:
        asset = await coord.store.remove_part_file(msg["asset_id"], msg["part_id"])
    except KeyError:
        _err(
            hass,
            connection,
            msg,
            "not_found",
            "unknown_part",
            asset_id=msg["asset_id"],
            part_id=msg["part_id"],
        )
        return
    connection.send_result(msg["id"], {"asset": asset})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/sign_part_file_url",
        vol.Required("asset_id"): str,
        vol.Required("part_id"): str,
    }
)
@websocket_api.async_response
async def ws_sign_part_file_url(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Mint a short-lived signed URL the browser can open for a part's file."""
    coord = _coordinator(hass)
    if coord is None:
        _not_loaded(hass, connection, msg)
        return
    asset = coord.store.get_asset(msg["asset_id"])
    part = next(
        (
            p
            for p in (asset or {}).get("parts", [])
            if p.get("id") == msg["part_id"] and p.get("file_name")
        ),
        None,
    )
    if part is None:
        _err(hass, connection, msg, "not_found", "unknown_part_file")
        return
    path = manuals.part_file_path(msg["asset_id"], msg["part_id"])
    signed = async_sign_path(
        hass,
        path,
        _DOCUMENT_URL_TTL,
        refresh_token_id=connection.refresh_token_id,
    )
    connection.send_result(msg["id"], {"url": signed})


@websocket_api.websocket_command({vol.Required("type"): "home_keeper/export_inventory"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_export_inventory(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the home-inventory report (for insurance) plus a ready-to-save CSV.

    Admin-only: the report exposes every asset's serial numbers, purchase costs and
    value totals, which a non-admin household member shouldn't be able to exfiltrate.
    """
    coord = _coordinator(hass)
    if coord is None:
        _not_loaded(hass, connection, msg)
        return
    report = inventory.build_inventory(
        coord.store.list_assets(),
        area_names=devices.area_names(hass),
        today=dt_util.now().date(),
    )
    csv = inventory.inventory_to_csv(report, lang=hass.config.language)
    connection.send_result(msg["id"], {"inventory": report, "csv": csv})


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
        _not_loaded(hass, connection, msg)
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
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set_options(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Persist options from the Settings tab (delegates to the shared service path).

    ``async_set_options`` updates the entry, which reloads it and re-runs the
    problem-sensor sync. Mirrors the ``home_keeper.set_options`` service. Admin-only:
    mutating config-entry options (profiles, notification targets, problem-sensor
    exclusions) is administration, which HA core reserves for admins — a non-admin
    could otherwise wipe another user's saved settings.
    """
    coord = _coordinator(hass)
    if coord is None:
        _not_loaded(hass, connection, msg)
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
        _not_loaded(hass, connection, msg)
        return
    connection.send_result(
        msg["id"], {"companions": companions.async_list_companions(hass)}
    )


@websocket_api.websocket_command({vol.Required("type"): "home_keeper/get_profiles"})
@websocket_api.async_response
async def ws_get_profiles(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the saved profiles (filters) for the dashboard card's profile picker.

    A lightweight read so the Lovelace card can resolve a selected profile without
    pulling the whole options object. The panel itself reads profiles from
    ``get_options``.
    """
    coord = _coordinator(hass)
    if coord is None:
        _not_loaded(hass, connection, msg)
        return
    connection.send_result(
        msg["id"],
        {"profiles": options.current_options(coord.entry).get(OPTION_PROFILES, [])},
    )
