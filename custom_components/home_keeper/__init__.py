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
from homeassistant.util import dt as dt_util

from . import card, devices, inventory, options, panel, websocket_api
from .assets import AssetValidationError
from .const import (
    DOMAIN,
    OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS,
    OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS,
    OPTION_SYNC_PROBLEM_SENSORS,
    PLATFORMS,
)
from .coordinator import HomeKeeperCoordinator, entity_set_key
from .models import TaskValidationError
from .problem_sync import ProblemSensorSync
from .store import HomeKeeperStore

_LOGGER = logging.getLogger(__name__)

# ``source`` is opaque provenance owned by the integration that created the task
# (e.g. ``{"my_integration": {...}}``). Home Keeper stores and echoes it verbatim and
# never inspects it. See docs/INTEGRATING.md.
# ``managed_by`` is a well-known ownership block that Home Keeper DOES inspect: it
# controls which fields are locked in the UI, deletion protection, and display metadata.
# Set at creation time; ignored by update_task. See docs/INTEGRATING.md §6.
ADD_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Optional("notes"): cv.string,
        vol.Optional("recurrence_type"): cv.string,
        vol.Optional("interval"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("unit"): cv.string,
        vol.Optional("freq"): cv.string,
        vol.Optional("anchor"): cv.string,
        # Optional "last done" seed: records an initial completion so a floating task
        # starts measured from this date instead of due-now. See docs/INTEGRATING.md.
        vol.Optional("last_completed"): cv.datetime,
        vol.Optional("device_id"): cv.string,
        vol.Optional("area_id"): cv.string,
        # HA label-registry ids; used (with device/area labels) to scope the card.
        vol.Optional("labels"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("source"): dict,
        vol.Optional("managed_by"): dict,
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
        vol.Optional("labels"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("source"): dict,
    }
)
TASK_ID_SCHEMA = vol.Schema({vol.Required("task_id"): cv.string})
# Arm a condition-driven (triggered) task so it reads as due-now. The owner-facing
# counterpart to complete_task (which clears it back to dormant). See INTEGRATING.md.
TRIGGER_TASK_SCHEMA = vol.Schema({vol.Required("task_id"): cv.string})
# ``force`` bypasses managed-task deletion protection — the escape hatch for cleaning
# up a task whose managing integration is gone or misbehaving. See docs/INTEGRATING.md.
DELETE_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Optional("force", default=False): cv.boolean,
    }
)
# ``origin`` is a free-form marker the caller passes so it can recognise (and ignore)
# the completion event it triggered. Home Keeper only echoes it back in the event.
COMPLETE_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Optional("completed_at"): cv.datetime,
        vol.Optional("origin"): cv.string,
    }
)

# Structured part (wear item) for the add/update asset schema.
_PART_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): cv.string,
        vol.Required("name"): cv.string,
        vol.Optional("part_number"): cv.string,
        vol.Optional("type"): cv.string,
        vol.Optional("vendor"): cv.string,
        vol.Optional("cost"): vol.Coerce(float),
        vol.Optional("notes"): cv.string,
        vol.Optional("replace_interval"): vol.Coerce(int),
        vol.Optional("replace_unit"): cv.string,
        vol.Optional("last_replaced"): cv.string,
        vol.Optional("stock"): vol.Coerce(int),
        vol.Optional("reorder_at"): vol.Coerce(int),
    }
)

# Free-form metadata entry for the add/update asset schema. ``value`` is a plain
# string (the pure model validates it per type — date / link / text).
_METADATA_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): cv.string,
        vol.Optional("type"): cv.string,
        vol.Required("label"): cv.string,
        vol.Optional("value"): cv.string,
        vol.Optional("track"): cv.boolean,
    }
)

# Asset (appliance) fields shared by add/update. Descriptive/temporal details live
# in the free-form ``metadata`` list; only the fields that wire into Home Assistant
# stay structured — ``manufacturer``/``model`` (device card), ``manual_url`` (device
# configuration_url) and ``cost`` (inventory value rollup). Cost is coerced to float.
_ASSET_FIELDS: dict[Any, Any] = {
    vol.Optional("name"): cv.string,
    vol.Optional("kind"): cv.string,
    vol.Optional("device_id"): cv.string,
    vol.Optional("area_id"): cv.string,
    vol.Optional("icon"): cv.string,
    vol.Optional("manufacturer"): cv.string,
    vol.Optional("model"): cv.string,
    vol.Optional("cost"): vol.Coerce(float),
    vol.Optional("manual_url"): cv.string,
    vol.Optional("metadata"): [_METADATA_SCHEMA],
    vol.Optional("parts"): [_PART_SCHEMA],
    vol.Optional("parent_asset_id"): cv.string,
    vol.Optional("related_device_ids"): [cv.string],
}
ADD_ASSET_SCHEMA = vol.Schema(_ASSET_FIELDS)
UPDATE_ASSET_SCHEMA = vol.Schema({vol.Required("asset_id"): cv.string, **_ASSET_FIELDS})
ASSET_ID_SCHEMA = vol.Schema({vol.Required("asset_id"): cv.string})

# Adjust a part's on-hand spare count by a (signed) delta; clamped at zero.
ADJUST_PART_STOCK_SCHEMA = vol.Schema(
    {
        vol.Required("asset_id"): cv.string,
        vol.Required("part_id"): cv.string,
        vol.Required("delta"): vol.Coerce(int),
    }
)
EXPORT_INVENTORY_SCHEMA = vol.Schema({})

# Integration-wide options, also editable from the panel's Settings tab and the
# options flow. Every field is optional so an automation can flip just one (e.g.
# turn syncing off) without restating the exclusion lists. See options.py.
SET_OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(OPTION_SYNC_PROBLEM_SENSORS): cv.boolean,
        vol.Optional(OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES): vol.All(
            cv.ensure_list, [cv.string]
        ),
        vol.Optional(OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS): vol.All(
            cv.ensure_list, [cv.string]
        ),
        vol.Optional(OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS): vol.All(
            cv.ensure_list, [cv.string]
        ),
    }
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

    # Provision/reconcile virtual asset devices and the tasks derived from wear
    # parts BEFORE forwarding platforms so the registry devices and per-task
    # entities exist when the platforms set up. The same applies to the tasks
    # mirroring ``device_class: problem`` binary sensors (when syncing is enabled).
    await devices.async_reconcile_assets(hass, entry, store)
    await store.reconcile_part_tasks()
    problem_sync = ProblemSensorSync(hass, entry, coordinator)
    await problem_sync.async_initial_reconcile()
    coordinator.problem_sync = problem_sync
    await coordinator.async_request_refresh()

    await panel.async_register_panel(hass)
    card.async_register_card(hass)
    websocket_api.async_register(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _register_services(hass)
    # React to options-flow changes (e.g. toggling problem-sensor syncing) by
    # reloading the entry, which re-runs this setup with the new options.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    # Now that platforms are up, start the live problem-sensor listeners (these may
    # reload the entry when a synced task is created/removed, so they run last).
    problem_sync.async_start_listeners()
    # Setup is complete: the refreshes above have baselined current overdue/due-soon
    # state silently, so start firing those events only for transitions from here on.
    coordinator.enable_transition_events()
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change.

    The options *flow* updates the entry directly, so this listener performs the
    reload. The service / panel path goes through ``options.async_set_options``,
    which awaits its own reload so the caller observes the reconciled task set — it
    flags the entry while doing so, so we don't fire a second, overlapping reload.
    """
    if options.caller_is_reloading(entry.entry_id):
        return
    await hass.config_entries.async_reload(entry.entry_id)


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

    def _check_area(data: dict) -> None:
        if not devices.area_exists(hass, data.get("area_id")):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_area",
                translation_placeholders={"area_id": str(data.get("area_id"))},
            )

    async def handle_add_task(call: ServiceCall) -> dict[str, Any]:
        coord = _coordinator()
        _check_area(call.data)
        try:
            task = await coord.store.add_task(dict(call.data))
        except TaskValidationError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_task",
                translation_placeholders={"error": str(err)},
            ) from err
        await hass.config_entries.async_reload(coord.entry.entry_id)
        return {"task_id": task["id"]}

    async def handle_update_task(call: ServiceCall) -> None:
        coord = _coordinator()
        _check_area(call.data)
        data = dict(call.data)
        task_id = data.pop("task_id")
        existing = coord.store.get_task(task_id)
        before = entity_set_key(existing)
        try:
            updated = await coord.store.update_task(task_id, data)
        except KeyError:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="task_not_found",
                translation_placeholders={"task_id": task_id},
            ) from None
        except TaskValidationError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_task",
                translation_placeholders={"error": str(err)},
            ) from err
        # Only changes that alter which per-task entities exist (device link or
        # enabled state) need a full entry reload; otherwise a refresh suffices.
        if entity_set_key(updated) != before:
            await hass.config_entries.async_reload(coord.entry.entry_id)
        else:
            await coord.async_request_refresh()

    async def handle_delete_task(call: ServiceCall) -> None:
        coord = _coordinator()
        try:
            await coord.store.delete_task(
                call.data["task_id"], force=call.data.get("force", False)
            )
        except TaskValidationError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_task",
                translation_placeholders={"error": str(err)},
            ) from err
        await hass.config_entries.async_reload(coord.entry.entry_id)

    async def handle_complete_task(call: ServiceCall) -> None:
        coord = _coordinator()
        try:
            await coord.store.complete_task(
                call.data["task_id"],
                call.data.get("completed_at"),
                origin=call.data.get("origin"),
            )
        except KeyError:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="task_not_found",
                translation_placeholders={"task_id": call.data["task_id"]},
            ) from None
        except TaskValidationError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_task",
                translation_placeholders={"error": str(err)},
            ) from err
        await coord.async_request_refresh()

    async def handle_trigger_task(call: ServiceCall) -> None:
        coord = _coordinator()
        try:
            await coord.store.trigger_task(call.data["task_id"])
        except KeyError:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="task_not_found",
                translation_placeholders={"task_id": call.data["task_id"]},
            ) from None
        except TaskValidationError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_task",
                translation_placeholders={"error": str(err)},
            ) from err
        # Arming only flips next_due (dormant <-> active); the per-task entity set is
        # unchanged, so a refresh is enough — no entry reload (mirrors complete_task).
        await coord.async_request_refresh()

    async def handle_list_tasks(call: ServiceCall) -> dict[str, Any]:
        coord = _coordinator()
        return {"tasks": coord.store.list_tasks()}

    async def handle_add_asset(call: ServiceCall) -> None:
        coord = _coordinator()
        _check_area(call.data)
        try:
            await coord.store.add_asset(dict(call.data))
        except AssetValidationError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_asset",
                translation_placeholders={"error": str(err)},
            ) from err
        await devices.async_apply_asset_change(hass, coord.entry, coord.store)

    async def handle_update_asset(call: ServiceCall) -> None:
        coord = _coordinator()
        _check_area(call.data)
        data = dict(call.data)
        asset_id = data.pop("asset_id")
        try:
            await coord.store.update_asset(asset_id, data)
        except KeyError:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="asset_not_found",
                translation_placeholders={"asset_id": asset_id},
            ) from None
        except AssetValidationError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_asset",
                translation_placeholders={"error": str(err)},
            ) from err
        await devices.async_apply_asset_change(hass, coord.entry, coord.store)

    async def handle_delete_asset(call: ServiceCall) -> None:
        coord = _coordinator()
        await _delete_asset(hass, coord, call.data["asset_id"])

    async def handle_list_assets(call: ServiceCall) -> dict[str, Any]:
        coord = _coordinator()
        return {"assets": coord.store.list_assets()}

    async def handle_adjust_part_stock(call: ServiceCall) -> None:
        coord = _coordinator()
        try:
            await coord.store.adjust_part_stock(
                call.data["asset_id"], call.data["part_id"], call.data["delta"]
            )
        except KeyError:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_part",
                translation_placeholders={
                    "asset_id": call.data["asset_id"],
                    "part_id": call.data["part_id"],
                },
            ) from None
        await coord.async_request_refresh()

    async def handle_export_inventory(call: ServiceCall) -> dict[str, Any]:
        coord = _coordinator()
        report = inventory.build_inventory(
            coord.store.list_assets(),
            area_names=devices.area_names(hass),
            today=dt_util.now().date(),
        )
        return {"inventory": report, "csv": inventory.inventory_to_csv(report)}

    hass.services.async_register(
        DOMAIN,
        "add_task",
        handle_add_task,
        ADD_TASK_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, "update_task", handle_update_task, UPDATE_TASK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "delete_task", handle_delete_task, DELETE_TASK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "complete_task", handle_complete_task, COMPLETE_TASK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "trigger_task", handle_trigger_task, TRIGGER_TASK_SCHEMA
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
    hass.services.async_register(
        DOMAIN, "adjust_part_stock", handle_adjust_part_stock, ADJUST_PART_STOCK_SCHEMA
    )

    async def handle_set_options(call: ServiceCall) -> None:
        coord = _coordinator()
        await options.async_set_options(hass, coord.entry, dict(call.data))

    hass.services.async_register(
        DOMAIN,
        "export_inventory",
        handle_export_inventory,
        EXPORT_INVENTORY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "set_options", handle_set_options, SET_OPTIONS_SCHEMA
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
    "trigger_task",
    "list_tasks",
    "add_asset",
    "update_asset",
    "delete_asset",
    "list_assets",
    "adjust_part_stock",
    "export_inventory",
    "set_options",
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
