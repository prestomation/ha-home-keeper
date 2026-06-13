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

from . import devices, panel, websocket_api
from .assets import AssetValidationError
from .const import DOMAIN, PLATFORMS
from .coordinator import HomeKeeperCoordinator, entity_set_key
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

# Asset (appliance) fields shared by add/update. Dates are plain strings so the
# pure model can validate them; cost is coerced to a float.
_ASSET_FIELDS = {
    vol.Optional("name"): cv.string,
    vol.Optional("kind"): cv.string,
    vol.Optional("device_id"): cv.string,
    vol.Optional("area_id"): cv.string,
    vol.Optional("manufacturer"): cv.string,
    vol.Optional("model"): cv.string,
    vol.Optional("serial_number"): cv.string,
    vol.Optional("manufacture_date"): cv.string,
    vol.Optional("purchase_date"): cv.string,
    vol.Optional("install_date"): cv.string,
    vol.Optional("warranty_expiry"): cv.string,
    vol.Optional("warranty_provider"): cv.string,
    vol.Optional("vendor"): cv.string,
    vol.Optional("cost"): vol.Coerce(float),
    vol.Optional("manual_url"): cv.string,
    vol.Optional("part_numbers"): cv.string,
    vol.Optional("notes"): cv.string,
}
ADD_ASSET_SCHEMA = vol.Schema(_ASSET_FIELDS)
UPDATE_ASSET_SCHEMA = vol.Schema(
    {vol.Required("asset_id"): cv.string, **_ASSET_FIELDS}
)
ASSET_ID_SCHEMA = vol.Schema({vol.Required("asset_id"): cv.string})


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

    # Provision/reconcile virtual asset devices BEFORE forwarding platforms so the
    # registry devices exist when per-task and per-asset entities resolve them.
    await devices.async_reconcile_assets(hass, entry, store)

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
        before = entity_set_key(existing)
        try:
            updated = await coord.store.update_task(task_id, data)
        except KeyError:
            raise ServiceValidationError(f"Task not found: {task_id}") from None
        except TaskValidationError as err:
            raise ServiceValidationError(str(err)) from err
        # Only changes that alter which per-task entities exist (device link or
        # enabled state) need a full entry reload; otherwise a refresh suffices.
        if entity_set_key(updated) != before:
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

    async def handle_add_asset(call: ServiceCall) -> None:
        coord = _coordinator()
        try:
            await coord.store.add_asset(dict(call.data))
        except AssetValidationError as err:
            raise ServiceValidationError(str(err)) from err
        await devices.async_reconcile_assets(hass, coord.entry, coord.store)
        await hass.config_entries.async_reload(coord.entry.entry_id)

    async def handle_update_asset(call: ServiceCall) -> None:
        coord = _coordinator()
        data = dict(call.data)
        asset_id = data.pop("asset_id")
        try:
            await coord.store.update_asset(asset_id, data)
        except KeyError:
            raise ServiceValidationError(f"Asset not found: {asset_id}") from None
        except AssetValidationError as err:
            raise ServiceValidationError(str(err)) from err
        await devices.async_reconcile_assets(hass, coord.entry, coord.store)
        await hass.config_entries.async_reload(coord.entry.entry_id)

    async def handle_delete_asset(call: ServiceCall) -> None:
        coord = _coordinator()
        await _delete_asset(hass, coord, call.data["asset_id"])

    async def handle_list_assets(call: ServiceCall) -> dict[str, Any]:
        coord = _coordinator()
        return {"assets": coord.store.list_assets()}

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
    hass.services.async_register(
        DOMAIN, "add_asset", handle_add_asset, ADD_ASSET_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "update_asset", handle_update_asset, UPDATE_ASSET_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "delete_asset", handle_delete_asset, ASSET_ID_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        "list_assets",
        handle_list_assets,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )


async def _delete_asset(
    hass: HomeAssistant, coord: HomeKeeperCoordinator, asset_id: str
) -> None:
    """Delete an asset, remove its virtual device, and detach orphaned tasks.

    Shared by the service and websocket handlers so both clean up identically.
    """
    asset = await coord.store.delete_asset(asset_id)
    if asset is None:
        return
    removed_device_id = await devices.async_remove_asset_device(hass, asset)
    if removed_device_id:
        await coord.store.detach_tasks_from_device(removed_device_id)
    await hass.config_entries.async_reload(coord.entry.entry_id)


# Asset CRUD service names paired with the task services for teardown.
_SERVICES = (
    "add_task",
    "update_task",
    "delete_task",
    "complete_task",
    "list_tasks",
    "add_asset",
    "update_asset",
    "delete_asset",
    "list_assets",
)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    # Only tear down the panel/services when the last entry goes away.
    if unloaded and not hass.config_entries.async_entries(DOMAIN):
        panel.async_unregister_panel(hass)
        for service in _SERVICES:
            hass.services.async_remove(DOMAIN, service)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove all Home Keeper data when the integration is deleted.

    Virtual asset devices (and per-task self-owned devices) are tied to this config
    entry, so Home Assistant removes them automatically. Here we additionally drop
    our stored tasks/assets document so no residue is left behind.
    """
    store = HomeKeeperStore(hass)
    await store.async_remove()
