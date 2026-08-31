"""WebSocket API for the Home Keeper sidebar panel.

The admin panel uses these typed commands for snappy reads and CRUD without
round-tripping through entities. Each mutation refreshes the coordinator (and
reloads the entry on add/delete so per-task entities appear/disappear).
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from . import companions, devices, inventory, manuals, notifier, options
from .assets import AssetValidationError, card_projection
from .backend_i18n import resolve_exception
from .const import COMPLETION_ENTRY_FIELDS, DOMAIN, OPTION_PROFILES
from .coordinator import HomeKeeperCoordinator, entity_set_key, task_has_entities
from .models import TaskValidationError
from .shopping_sync import own_todo_entity_ids


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


# The three-argument shape Home Assistant calls a command with, and the
# four-argument one the handlers below are written against — same thing plus the
# resolved coordinator. ``_with_coordinator`` turns the second into the first.
_Command = Callable[
    [HomeAssistant, websocket_api.ActiveConnection, dict[str, Any]], Awaitable[None]
]
_Handler = Callable[
    [
        HomeAssistant,
        websocket_api.ActiveConnection,
        dict[str, Any],
        HomeKeeperCoordinator,
    ],
    Awaitable[None],
]

# Which ``exceptions`` string a store KeyError reports under, per id field.
_NOT_FOUND_KEYS = {"task_id": "task_not_found", "asset_id": "asset_not_found"}


def _with_coordinator(
    *, not_found: str | None = None
) -> Callable[[_Handler], _Command]:
    """Resolve the coordinator for a command, and translate the store's exceptions.

    Every command needs the loaded coordinator and answers ``integration_not_loaded``
    without one; nearly every mutating one then turns the same store exceptions into
    the same websocket errors. Both live here rather than pasted at the top of each
    handler. The wrapped handler receives the coordinator as a fourth argument and
    the decorated result keeps the three-argument signature HA calls.

    ``not_found`` names the message field a store ``KeyError`` reports (``task_id``
    or ``asset_id``); omit it and a ``KeyError`` propagates, which is what a handler
    with its own not-found message (``unknown_part``, ``unknown_document``) wants.
    """

    def decorate(handler: _Handler) -> _Command:
        @functools.wraps(handler)
        async def wrapped(
            hass: HomeAssistant,
            connection: websocket_api.ActiveConnection,
            msg: dict[str, Any],
        ) -> None:
            coord = _coordinator(hass)
            if coord is None:
                _not_loaded(hass, connection, msg)
                return
            try:
                await handler(hass, connection, msg, coord)
            except KeyError:
                if not_found is None:
                    raise
                _err(
                    hass,
                    connection,
                    msg,
                    "not_found",
                    _NOT_FOUND_KEYS[not_found],
                    **{not_found: msg[not_found]},
                )
            except TaskValidationError as err:
                _err(
                    hass,
                    connection,
                    msg,
                    "invalid_task",
                    "invalid_task",
                    error=str(err),
                )
            except AssetValidationError as err:
                _err(
                    hass,
                    connection,
                    msg,
                    "invalid_asset",
                    "invalid_asset",
                    error=str(err),
                )

        return wrapped

    return decorate


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
    websocket_api.async_register_command(hass, ws_archive_asset)
    websocket_api.async_register_command(hass, ws_restore_asset)
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
@_with_coordinator()
async def ws_get_tasks(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    connection.send_result(msg["id"], {"tasks": coord.store.list_tasks()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/add_task",
        vol.Required("task"): dict,
    }
)
@websocket_api.async_response
@_with_coordinator()
async def ws_add_task(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    if not _area_ok(hass, connection, msg, msg["task"]):
        return
    task = await coord.store.add_task(msg["task"])
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
@_with_coordinator(not_found="task_id")
async def ws_update_task(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    if not _area_ok(hass, connection, msg, msg["updates"]):
        return
    before = entity_set_key(coord.store.get_task(msg["task_id"]))
    task = await coord.store.update_task(msg["task_id"], msg["updates"])
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
@_with_coordinator()
async def ws_delete_task(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    existing = coord.store.get_task(msg["task_id"])
    await coord.store.delete_task(msg["task_id"], force=msg.get("force", False))
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
@_with_coordinator(not_found="task_id")
async def ws_set_task_consumable(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    task = await coord.store.set_task_consumable(
        msg["task_id"], msg["asset_id"], msg["part_id"]
    )
    # Linking only rewrites the task's source; the per-task entity set is unchanged,
    # so a refresh is enough (no entry reload).
    await coord.async_request_refresh()
    connection.send_result(msg["id"], {"task": task})


def _ws_metadata(msg: dict[str, Any]) -> dict[str, Any]:
    """Lift the optional per-completion keys out of a websocket message.

    Driven off the shared field list rather than a local literal so a new completion
    field reaches the store instead of being silently dropped here.
    """
    return {k: msg[k] for k in COMPLETION_ENTRY_FIELDS if k in msg}


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/complete_task",
        vol.Required("task_id"): str,
        vol.Optional("completed_at"): str,
        vol.Optional("note"): str,
        vol.Optional("cost"): vol.Coerce(float),
        vol.Optional("photo"): str,
        vol.Optional("who"): str,
        vol.Optional("reading"): vol.Coerce(float),
    }
)
@websocket_api.async_response
@_with_coordinator(not_found="task_id")
async def ws_complete_task(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
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
    except TaskValidationError as err:
        # Not the decorator's generic "that task is invalid": a refused completion
        # (a required field missing, a tag scan demanded) reads differently.
        _err(hass, connection, msg, "not_allowed", "complete_failed", error=str(err))
        return
    # Completing an auto-buy task bumps stock (restocked) → its reminder is removed;
    # settle so those device entities are (un)registered (else a plain refresh).
    await coord.async_settle_buy_tasks()
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
        vol.Optional("reading"): vol.Coerce(float),
    }
)
@websocket_api.async_response
@_with_coordinator(not_found="task_id")
async def ws_update_completion(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    task = await coord.store.update_completion(
        msg["task_id"], msg["ts"], _ws_metadata(msg)
    )
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
@_with_coordinator(not_found="task_id")
async def ws_move_completion(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    task = await coord.store.move_completion(
        msg["task_id"], msg["old_ts"], msg["new_ts"]
    )
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
@_with_coordinator(not_found="task_id")
async def ws_delete_completion(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    task = await coord.store.delete_completion(msg["task_id"], msg["ts"])
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
@_with_coordinator(not_found="asset_id")
async def ws_delete_archived_completion(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    asset = await coord.store.delete_archived_completion(
        msg["asset_id"], msg["task_id"], msg["ts"]
    )
    await coord.async_request_refresh()
    connection.send_result(msg["id"], {"asset": asset})


@websocket_api.websocket_command({vol.Required("type"): "home_keeper/get_assets"})
@websocket_api.async_response
@_with_coordinator()
async def ws_get_assets(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    """Return the appliances — in full for an admin, projected for anyone else.

    Not ``require_admin``: the dashboard card is a usage surface open to every
    household member and it reads appliance data to resolve a task's card links. So
    a non-admin gets :func:`assets.card_projection` — the link-rendering subset —
    rather than the costs and serial numbers ``export_inventory`` is gated on.
    """
    assets = coord.store.list_assets()
    if not connection.user.is_admin:
        assets = card_projection(assets)
    connection.send_result(msg["id"], {"assets": assets})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/add_asset",
        vol.Required("asset"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
@_with_coordinator()
async def ws_add_asset(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    if not _area_ok(hass, connection, msg, msg["asset"]):
        return
    asset = await coord.store.add_asset(msg["asset"])
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
@websocket_api.require_admin
@websocket_api.async_response
@_with_coordinator(not_found="asset_id")
async def ws_update_asset(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    if not _area_ok(hass, connection, msg, msg["updates"]):
        return
    asset = await coord.store.update_asset(msg["asset_id"], msg["updates"])
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
@websocket_api.require_admin
@websocket_api.async_response
@_with_coordinator()
async def ws_delete_asset(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    # Lazy: ``__init__`` imports this module at setup, so a module-level import
    # back would be a cycle (the same idiom ``store``/``manuals`` use).
    from . import _delete_asset

    await _delete_asset(hass, coord, msg["asset_id"])
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/archive_asset",
        vol.Required("asset_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
@_with_coordinator()
async def ws_archive_asset(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    asset = await coord.store.archive_asset(msg["asset_id"])
    if asset is None:
        _err(
            hass,
            connection,
            msg,
            "not_found",
            "asset_not_found",
            asset_id=msg["asset_id"],
        )
        return
    connection.send_result(msg["id"], {"asset": asset})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/restore_asset",
        vol.Required("asset_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
@_with_coordinator()
async def ws_restore_asset(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    asset = await coord.store.restore_asset(msg["asset_id"])
    if asset is None:
        _err(
            hass,
            connection,
            msg,
            "not_found",
            "asset_not_found",
            asset_id=msg["asset_id"],
        )
        return
    connection.send_result(msg["id"], {"asset": asset})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/adjust_part_stock",
        vol.Required("asset_id"): str,
        vol.Required("part_id"): str,
        # Fractional, like stock itself — 0.33 of a bottle is a real adjustment.
        vol.Required("delta"): vol.Coerce(float),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
@_with_coordinator()
async def ws_adjust_part_stock(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    try:
        asset = await coord.store.adjust_part_stock(
            msg["asset_id"], msg["part_id"], msg["delta"]
        )
    except KeyError:
        # Names the part, not the appliance: the asset is known here, the part isn't.
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
@websocket_api.require_admin
@websocket_api.async_response
@_with_coordinator(not_found="asset_id")
async def ws_add_asset_document(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    document = dict(msg["document"])
    # Files are uploaded through the HTTP view; this command only adds links.
    if document.get("kind", "link") != "link":
        _err(hass, connection, msg, "invalid_asset", "link_documents_only")
        return
    document["kind"] = "link"
    await coord.store.add_asset_document(msg["asset_id"], document)
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
@websocket_api.require_admin
@websocket_api.async_response
@_with_coordinator()
async def ws_remove_asset_document(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    try:
        asset = await coord.store.remove_asset_document(
            msg["asset_id"], msg["document_id"]
        )
    except KeyError:
        # Names the document, not the appliance (either being missing lands here).
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
@websocket_api.require_admin
@websocket_api.async_response
@_with_coordinator()
async def ws_update_asset_document(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    try:
        await coord.store.update_asset_document(
            msg["asset_id"], msg["document_id"], msg["changes"]
        )
    except KeyError:
        # Names the document, not the appliance (either being missing lands here).
        _err(
            hass,
            connection,
            msg,
            "not_found",
            "unknown_document",
            document_id=msg["document_id"],
        )
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
@_with_coordinator()
async def ws_sign_document_url(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    """Mint a short-lived signed URL the browser can open for a file document."""
    signed = await manuals.async_sign_document_url(
        hass, msg["asset_id"], msg["document_id"]
    )
    if signed is None:
        _err(
            hass,
            connection,
            msg,
            "not_found",
            "unknown_document",
            document_id=msg["document_id"],
        )
        return
    connection.send_result(msg["id"], {"url": signed})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "home_keeper/remove_part_file",
        vol.Required("asset_id"): str,
        vol.Required("part_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
@_with_coordinator()
async def ws_remove_part_file(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    try:
        asset = await coord.store.remove_part_file(msg["asset_id"], msg["part_id"])
    except KeyError:
        # Names the part, not the appliance: the asset is known here, the part isn't.
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
@_with_coordinator()
async def ws_sign_part_file_url(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    """Mint a short-lived signed URL the browser can open for a part's file."""
    signed = await manuals.async_sign_part_file_url(
        hass, msg["asset_id"], msg["part_id"]
    )
    if signed is None:
        _err(hass, connection, msg, "not_found", "unknown_part_file")
        return
    connection.send_result(msg["id"], {"url": signed})


@websocket_api.websocket_command({vol.Required("type"): "home_keeper/export_inventory"})
@websocket_api.require_admin
@websocket_api.async_response
@_with_coordinator()
async def ws_export_inventory(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    """Return the home-inventory report (for insurance) plus a ready-to-save CSV.

    Admin-only: the report exposes every asset's serial numbers, purchase costs and
    value totals, which a non-admin household member shouldn't be able to exfiltrate.
    """
    report = inventory.build_inventory(
        coord.store.list_assets(),
        area_names=devices.area_names(hass),
        today=dt_util.now().date(),
    )
    csv = inventory.inventory_to_csv(report, lang=hass.config.language)
    connection.send_result(msg["id"], {"inventory": report, "csv": csv})


@websocket_api.websocket_command({vol.Required("type"): "home_keeper/get_options"})
@websocket_api.async_response
@_with_coordinator()
async def ws_get_options(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    """Return the config-entry options for the panel's Settings tab.

    Also returns ``notify_targets`` — the ``mobile_app_*`` notify services available
    right now — so the Notifications card can offer them as a checklist instead of
    making the user type service names, and ``own_todo_entities``, which the
    shopping-list picker excludes so it can't be pointed at Home Keeper's own list.
    """
    connection.send_result(
        msg["id"],
        {
            "options": options.current_options(coord.entry),
            "notify_targets": notifier.available_targets(hass),
            "own_todo_entities": own_todo_entity_ids(hass),
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
@_with_coordinator()
async def ws_set_options(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    """Persist options from the Settings tab (delegates to the shared service path).

    ``async_set_options`` updates the entry, which reloads it and re-runs the
    problem-sensor sync. Mirrors the ``home_keeper.set_options`` service. Admin-only:
    mutating config-entry options (profiles, notification targets, problem-sensor
    exclusions) is administration, which HA core reserves for admins — a non-admin
    could otherwise wipe another user's saved settings.
    """
    merged = await options.async_set_options(hass, coord.entry, msg["options"])
    connection.send_result(msg["id"], {"options": merged})


@websocket_api.websocket_command({vol.Required("type"): "home_keeper/get_companions"})
@websocket_api.async_response
@_with_coordinator()
async def ws_get_companions(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    """Return the companion rows for the Settings → Companions section.

    Merges self-registered companions (the push path) with catalog detection of
    popular upstreams whose glue isn't installed yet (the pull path). See
    companions.py. The registry is keyed off ``hass``, not the coordinator, which is
    only wanted here for the loaded check every other command makes.
    """
    connection.send_result(
        msg["id"], {"companions": companions.async_list_companions(hass)}
    )


@websocket_api.websocket_command({vol.Required("type"): "home_keeper/get_profiles"})
@websocket_api.async_response
@_with_coordinator()
async def ws_get_profiles(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coord: HomeKeeperCoordinator,
) -> None:
    """Return the saved profiles (filters) for the dashboard card's profile picker.

    A lightweight read so the Lovelace card can resolve a selected profile without
    pulling the whole options object. The panel itself reads profiles from
    ``get_options``.
    """
    connection.send_result(
        msg["id"],
        {"profiles": options.current_options(coord.entry).get(OPTION_PROFILES, [])},
    )
