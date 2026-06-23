"""Device automation triggers for Home Keeper.

Surfaces the Home Keeper bus events (see ``docs/EVENTS.md``) in Home Assistant's
**visual automation editor**: on a task's device page you can pick *"Task became
overdue"*; on an appliance you can pick *"Spare part out of stock"* — no need to know
the raw event name. Each device trigger is a thin wrapper over the corresponding bus
event, filtered to the chosen device.

The filter key depends on the device kind, because a self-owned task device carries
``device_id: null`` in its task events (the task has no attached ``device_id``):

* **Self-owned task device** — registry identifier ``(DOMAIN, task_id)``. Its events
  can only be matched by ``task_id``; filtering by ``device_id`` would match nothing
  and leak every other standalone task. → filter on ``task_id``.
* **Existing device with attached tasks**, or a **virtual appliance device** — shared
  by potentially several tasks/parts; their events carry the registry ``device_id``.
  → filter on ``device_id``.

Global (non-device) automations use a plain ``platform: event`` trigger instead; see
``docs/EVENTS.md``.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import (
    ASSET_IDENTIFIER_PREFIX,
    DOMAIN,
    EVENT_PART_LOW_STOCK,
    EVENT_PART_OUT_OF_STOCK,
    EVENT_PART_RESTOCKED,
    EVENT_TASK_COMPLETED,
    EVENT_TASK_CREATED,
    EVENT_TASK_DUE_SOON,
    EVENT_TASK_OVERDUE,
    EVENT_TASK_SKIPPED,
    EVENT_TASK_SNOOZED,
    EVENT_TASK_UPDATED,
)
from .coordinator import HomeKeeperCoordinator

# trigger_type -> bus event. Task triggers are offered for any device with Home Keeper
# tasks; appliance (stock) triggers for any Home Keeper appliance device.
TASK_TRIGGERS = {
    "task_completed": EVENT_TASK_COMPLETED,
    "task_overdue": EVENT_TASK_OVERDUE,
    "task_due_soon": EVENT_TASK_DUE_SOON,
    "task_created": EVENT_TASK_CREATED,
    "task_updated": EVENT_TASK_UPDATED,
    "task_snoozed": EVENT_TASK_SNOOZED,
    "task_skipped": EVENT_TASK_SKIPPED,
}
ASSET_TRIGGERS = {
    "part_low_stock": EVENT_PART_LOW_STOCK,
    "part_out_of_stock": EVENT_PART_OUT_OF_STOCK,
    "part_restocked": EVENT_PART_RESTOCKED,
}
_EVENT_BY_TYPE = {**TASK_TRIGGERS, **ASSET_TRIGGERS}

# Sentinel filter that can never match a real event id — used when a device has lost
# the tasks/assets that made a trigger offerable, so the automation simply never fires
# rather than erroring.
_NO_MATCH = {"task_id": "\0home_keeper_no_match"}

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {vol.Required(CONF_TYPE): vol.In(set(_EVENT_BY_TYPE))}
)


def _coordinator(hass: HomeAssistant) -> HomeKeeperCoordinator | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        coord = getattr(entry, "runtime_data", None)
        if isinstance(coord, HomeKeeperCoordinator):
            return coord
    return None


def _hk_identifier(device: dr.DeviceEntry) -> str | None:
    """Return the Home Keeper registry identifier value for *device*, or None."""
    for domain, value in device.identifiers:
        if domain == DOMAIN:
            return value
    return None


def _filters(hass: HomeAssistant, device_id: str) -> tuple[dict | None, dict | None]:
    """Return ``(task_filter, asset_filter)`` event-data filters for *device_id*.

    Either is ``None`` when the device has no Home Keeper tasks / appliance parts of
    that kind (so that trigger type isn't offered). See the module docstring for why the
    task filter keys on ``task_id`` for a self-owned device but ``device_id`` otherwise.
    """
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None, None
    coord = _coordinator(hass)
    tasks = list(coord.store.get_tasks().values()) if coord else []
    assets = coord.store.list_assets() if coord else []
    ident = _hk_identifier(device)
    asset_prefix = f"{ASSET_IDENTIFIER_PREFIX}_"

    task_filter: dict | None = None
    asset_filter: dict | None = None

    if ident is not None and not ident.startswith(asset_prefix):
        # Self-owned task device: identifier is the bare task id; its events carry no
        # device_id, so match on task_id.
        if any(task.get("id") == ident for task in tasks):
            task_filter = {"task_id": ident}
    else:
        # Virtual appliance device, or an existing/foreign device tasks & assets attach
        # to: their events carry this registry device_id.
        if any(task.get("device_id") == device_id for task in tasks):
            task_filter = {"device_id": device_id}
        if any(asset.get("device_id") == device_id for asset in assets):
            asset_filter = {"device_id": device_id}

    return task_filter, asset_filter


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, str]]:
    """List the Home Keeper device triggers available for *device_id*."""
    task_filter, asset_filter = _filters(hass, device_id)
    base = {CONF_PLATFORM: "device", CONF_DOMAIN: DOMAIN, CONF_DEVICE_ID: device_id}
    triggers: list[dict[str, str]] = []
    if task_filter is not None:
        triggers += [{**base, CONF_TYPE: t} for t in TASK_TRIGGERS]
    if asset_filter is not None:
        triggers += [{**base, CONF_TYPE: t} for t in ASSET_TRIGGERS]
    return triggers


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a Home Keeper device trigger by delegating to the event trigger."""
    trigger_type = config[CONF_TYPE]
    task_filter, asset_filter = _filters(hass, config[CONF_DEVICE_ID])
    event_data = asset_filter if trigger_type in ASSET_TRIGGERS else task_filter

    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: _EVENT_BY_TYPE[trigger_type],
            event_trigger.CONF_EVENT_DATA: event_data
            if event_data is not None
            else _NO_MATCH,
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )
