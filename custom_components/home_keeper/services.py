"""Home Keeper service registration.

The automation-facing surface: every data action is exposed here as a
``home_keeper.*`` service (the panel's websocket commands are only UI
optimizations that delegate to the same store methods — see AGENTS.md). This
module owns the service schemas, the handlers, and a single registration table
that drives both registration and teardown, so the two can't drift.

Handlers are plain ``async def _handle_*(hass, call)`` functions bound to ``hass``
via :func:`functools.partial` at registration time (``ServiceCall`` does not carry
``hass`` on every supported HA version). The copy-pasted
``KeyError``/``TaskValidationError``/``AssetValidationError`` → localized
``ServiceValidationError`` translation lives once in :func:`_translate_errors`.

DEFERRED: a ``home_keeper.contribute_task`` service (plus the
``SIGNAL_TASK_CONTRIBUTION`` dispatcher) would let other integrations push tasks
here without coupling — see IDEAS.md.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from . import companions, devices, inventory, notifier, options
from .assets import AssetValidationError
from .const import (
    DOMAIN,
    OPTION_DISMISSED_COMPANIONS,
    OPTION_NOTIFICATIONS,
    OPTION_ONE_OFF_RETENTION_DAYS,
    OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS,
    OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS,
    OPTION_PROFILES,
    OPTION_SYNC_PROBLEM_SENSORS,
)
from .coordinator import (
    HomeKeeperCoordinator,
    entity_set_key,
    require_coordinator,
    task_has_entities,
)
from .models import TaskValidationError

# ``source`` is opaque provenance owned by the integration that created the task
# (e.g. ``{"my_integration": {...}}``). Home Keeper stores and echoes it verbatim and
# never inspects it. See docs/INTEGRATING.md.
# ``managed_by`` is a well-known ownership block that Home Keeper DOES inspect: it
# controls which fields are locked in the UI, deletion protection, and display metadata.
# Set at creation time; ignored by update_task. See docs/INTEGRATING.md §6.
# One reference in a task's ``card_links``: an appliance id plus the id of one of
# its link documents / metadata-link entries. The dashboard card resolves the pair
# to a live name/URL and silently drops references that no longer exist.
CARD_LINK_SCHEMA = vol.Schema(
    {
        vol.Required("asset_id"): cv.string,
        vol.Required("entry_id"): cv.string,
    }
)
TASK_CHIP_SCHEMA = vol.Schema(
    {
        vol.Required("label"): cv.string,
        vol.Optional("icon"): cv.string,
        vol.Optional("url"): cv.string,
    }
)
ADD_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Optional("notes"): cv.string,
        vol.Optional("recurrence_type"): cv.string,
        vol.Optional("interval"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("unit"): cv.string,
        vol.Optional("freq"): cv.string,
        vol.Optional("anchor"): cv.string,
        # Due date for a one-off (do-once) task. Optional: defaults to "now" (due
        # today) when omitted. Naive values are interpreted in HA's configured tz.
        vol.Optional("due"): cv.string,
        # Sensor binding for a sensor-based task: a mapping with entity_id, mode
        # (usage|threshold) and the mode's fields (target / comparison+value+
        # for_seconds, optional attribute). Validated by models.normalize_sensor.
        vol.Optional("sensor"): dict,
        # Optional "last done" seed: records an initial completion so a floating task
        # starts measured from this date instead of due-now. See docs/INTEGRATING.md.
        vol.Optional("last_completed"): cv.datetime,
        vol.Optional("device_id"): cv.string,
        vol.Optional("area_id"): cv.string,
        # HA label-registry ids; used (with device/area labels) to scope the card.
        vol.Optional("labels"): vol.All(cv.ensure_list, [cv.string]),
        # Appliance link references (document/metadata links) the dashboard card
        # surfaces on this task's row. See models.normalize_card_links.
        vol.Optional("card_links"): vol.All(cv.ensure_list, [CARD_LINK_SCHEMA]),
        # Per-task completion-capture mode + (optionally) which metadata fields are
        # mandatory. See const.COMPLETION_DETAIL_* / COMPLETION_METADATA_FIELDS.
        vol.Optional("completion_detail"): cv.string,
        vol.Optional("completion_required_fields"): vol.All(
            cv.ensure_list, [cv.string]
        ),
        vol.Optional("source"): dict,
        vol.Optional("managed_by"): dict,
        vol.Optional("task_chips"): vol.All(cv.ensure_list, [TASK_CHIP_SCHEMA]),
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
        vol.Optional("due"): cv.string,
        vol.Optional("sensor"): dict,
        vol.Optional("device_id"): cv.string,
        vol.Optional("area_id"): cv.string,
        vol.Optional("labels"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("card_links"): vol.All(cv.ensure_list, [CARD_LINK_SCHEMA]),
        vol.Optional("completion_detail"): cv.string,
        vol.Optional("completion_required_fields"): vol.All(
            cv.ensure_list, [cv.string]
        ),
        vol.Optional("source"): dict,
        vol.Optional("task_chips"): vol.All(cv.ensure_list, [TASK_CHIP_SCHEMA]),
    }
)
TASK_ID_SCHEMA = vol.Schema({vol.Required("task_id"): cv.string})
# Arm a condition-driven (triggered) task so it reads as due-now. The owner-facing
# counterpart to complete_task (which clears it back to dormant). See INTEGRATING.md.
TRIGGER_TASK_SCHEMA = vol.Schema({vol.Required("task_id"): cv.string})
# Snooze: defer a task's next due date without recording a completion or advancing
# recurrence. ``hours`` is the deferral (defaults to a day). ``origin`` is echoed in
# the home_keeper_task_snoozed event for loop prevention (e.g. an actionable
# notification action). Skip advances to the next occurrence, also without completing.
SNOOZE_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        # Whole hours ≥ 1, matching services.yaml's number selector and the
        # notification snooze_hours contract (normalize_notification / the panel).
        vol.Optional("hours", default=24): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("origin"): cv.string,
    }
)
SKIP_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Optional("origin"): cv.string,
    }
)
# Link a task to an appliance consumable/part (or clear the link). Completing a
# linked task consumes one spare from the part's stock and fires the edge-triggered
# low/out-of-stock events. Omit asset_id/part_id (or pass them empty) to unlink.
SET_TASK_CONSUMABLE_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Optional("asset_id"): vol.Any(cv.string, None),
        vol.Optional("part_id"): vol.Any(cv.string, None),
    }
)
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
# The metadata fields (note/cost/photo/who) are the optional per-completion context;
# ``photo`` is an image-upload id and ``who`` a person entity id.
COMPLETE_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Optional("completed_at"): cv.datetime,
        vol.Optional("origin"): cv.string,
        vol.Optional("note"): cv.string,
        vol.Optional("cost"): vol.Coerce(float),
        vol.Optional("photo"): cv.string,
        vol.Optional("who"): cv.string,
    }
)
# Amend a recorded completion's metadata after the fact (identified by its ``ts``).
UPDATE_COMPLETION_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Required("ts"): cv.string,
        vol.Optional("note"): cv.string,
        vol.Optional("cost"): vol.Coerce(float),
        vol.Optional("photo"): cv.string,
        vol.Optional("who"): cv.string,
    }
)

DELETE_COMPLETION_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Required("ts"): cv.string,
    }
)

DELETE_ARCHIVED_COMPLETION_SCHEMA = vol.Schema(
    {
        vol.Required("asset_id"): cv.string,
        vol.Required("task_id"): cv.string,
        vol.Required("ts"): cv.string,
    }
)

# The completion-metadata keys shared by complete_task / update_completion, lifted
# out of a service call's data into the ``metadata`` mapping the store expects.
_COMPLETION_METADATA_KEYS = ("note", "cost", "photo", "who")

# Structured part (wear item) for the add/update asset schema.
_PART_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): cv.string,
        vol.Required("name"): cv.string,
        vol.Optional("part_number"): cv.string,
        vol.Optional("type"): cv.string,
        vol.Optional("vendor"): cv.string,
        vol.Optional("cost"): vol.Coerce(float),
        vol.Optional("url"): cv.string,
        vol.Optional("notes"): cv.string,
        vol.Optional("replace_interval"): vol.Coerce(int),
        vol.Optional("replace_unit"): cv.string,
        vol.Optional("last_replaced"): cv.string,
        vol.Optional("stock"): vol.Coerce(int),
        vol.Optional("reorder_at"): vol.Coerce(int),
        vol.Optional("create_buy_task"): cv.boolean,
        vol.Optional("restock_quantity"): vol.Coerce(int),
        # file_name/file_content_type/file_size are deliberately absent: a part's
        # attached file is upload-only (see manuals.HomeKeeperPartFileView) and must
        # never be settable through add_asset/update_asset — voluptuous rejects any
        # part payload that includes them (strict schema, no extra keys allowed).
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

# A single document (manual / warranty / receipt) for the add/update asset schema. A
# ``link`` carries a ``url``; a ``file`` is uploaded via the document HTTP view, which
# fills in ``filename``/``content_type``/``size`` — services only add ``link`` docs.
_DOCUMENT_SCHEMA = vol.Schema(
    {
        vol.Optional("id"): cv.string,
        vol.Optional("kind"): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional("url"): cv.string,
        vol.Optional("filename"): cv.string,
        vol.Optional("content_type"): cv.string,
        vol.Optional("size"): vol.Coerce(int),
        vol.Optional("created"): cv.string,
    }
)

# Asset (appliance) fields shared by add/update. Descriptive/temporal details live
# in the free-form ``metadata`` list; only the fields that wire into Home Assistant
# stay structured — ``manufacturer``/``model`` (device card) and ``cost`` (inventory
# value rollup). ``documents`` is the per-asset list of manuals/links. Cost is coerced
# to float.
_ASSET_FIELDS: dict[Any, Any] = {
    vol.Optional("name"): cv.string,
    vol.Optional("kind"): cv.string,
    vol.Optional("device_id"): cv.string,
    vol.Optional("area_id"): cv.string,
    vol.Optional("icon"): cv.string,
    vol.Optional("manufacturer"): cv.string,
    vol.Optional("model"): cv.string,
    vol.Optional("serial_number"): cv.string,
    vol.Optional("cost"): vol.Coerce(float),
    vol.Optional("documents"): [_DOCUMENT_SCHEMA],
    vol.Optional("metadata"): [_METADATA_SCHEMA],
    vol.Optional("parts"): [_PART_SCHEMA],
    vol.Optional("parent_asset_id"): cv.string,
    vol.Optional("related_device_ids"): [cv.string],
}
ADD_ASSET_SCHEMA = vol.Schema(_ASSET_FIELDS)
UPDATE_ASSET_SCHEMA = vol.Schema({vol.Required("asset_id"): cv.string, **_ASSET_FIELDS})
ASSET_ID_SCHEMA = vol.Schema({vol.Required("asset_id"): cv.string})

# Add a link document to an existing asset (file uploads go through the HTTP view).
ADD_ASSET_DOCUMENT_SCHEMA = vol.Schema(
    {
        vol.Required("asset_id"): cv.string,
        vol.Required("document"): _DOCUMENT_SCHEMA,
    }
)
REMOVE_ASSET_DOCUMENT_SCHEMA = vol.Schema(
    {
        vol.Required("asset_id"): cv.string,
        vol.Required("document_id"): cv.string,
    }
)
UPDATE_ASSET_DOCUMENT_SCHEMA = vol.Schema(
    {
        vol.Required("asset_id"): cv.string,
        vol.Required("document_id"): cv.string,
        vol.Required("changes"): vol.Schema(
            {vol.Optional("name"): cv.string, vol.Optional("url"): cv.string}
        ),
    }
)

# Adjust a part's on-hand spare count by a (signed) delta; clamped at zero.
ADJUST_PART_STOCK_SCHEMA = vol.Schema(
    {
        vol.Required("asset_id"): cv.string,
        vol.Required("part_id"): cv.string,
        vol.Required("delta"): vol.Coerce(int),
    }
)
# Detach a part's attached file (upload is HTTP-only — see manuals.py — since a
# service call can't carry binary bytes; removal needs none, so it's a service too).
REMOVE_PART_FILE_SCHEMA = vol.Schema(
    {
        vol.Required("asset_id"): cv.string,
        vol.Required("part_id"): cv.string,
    }
)
EXPORT_INVENTORY_SCHEMA = vol.Schema({})

# Send an actionable notification on demand for what's due now (the pull / "walk"
# entry point). Name a saved notification, or a profile (filter), optionally with a
# target override. Custom filters/delivery live on saved Profiles/Notifications (the
# point of making them reusable), not inline here. All optional so a bare name fires.
NOTIFY_SCHEMA = vol.Schema(
    {
        vol.Optional("notification"): cv.string,
        vol.Optional("profile"): cv.string,
        vol.Optional("target"): vol.All(cv.ensure_list, [cv.string]),
    }
)

# Integration-wide options, also editable from the panel's Settings tab and the
# options flow. Every field is optional so an automation can flip just one (e.g.
# turn syncing off) without restating the exclusion lists. See options.py.
SET_OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(OPTION_SYNC_PROBLEM_SENSORS): cv.boolean,
        vol.Optional(OPTION_ONE_OFF_RETENTION_DAYS): vol.All(
            vol.Coerce(int), vol.Range(min=0)
        ),
        vol.Optional(OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES): vol.All(
            cv.ensure_list, [cv.string]
        ),
        vol.Optional(OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES): vol.All(
            cv.ensure_list, [cv.string]
        ),
        vol.Optional(OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS): vol.All(
            cv.ensure_list, [cv.string]
        ),
        vol.Optional(OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS): vol.All(
            cv.ensure_list, [cv.string]
        ),
        # Catalog glue domains the user dismissed from the Companions "Suggested"
        # list. A list of domain strings.
        vol.Optional(OPTION_DISMISSED_COMPANIONS): vol.All(cv.ensure_list, [cv.string]),
        # Profiles (saved filters) and notifications (delivery) — the panel saves each
        # whole list; normalization happens in profiles/notifications.normalize_*.
        vol.Optional(OPTION_PROFILES): list,
        vol.Optional(OPTION_NOTIFICATIONS): list,
    }
)


_Handler = Callable[[HomeAssistant, ServiceCall], Awaitable[Any]]


def _translate_errors(
    *, not_found: str | None = None
) -> Callable[[_Handler], _Handler]:
    """Map store exceptions to localized ``ServiceValidationError``s.

    Folds the try/except boilerplate that every mutating handler repeated:

    * ``TaskValidationError`` → ``invalid_task`` (placeholder ``error``)
    * ``AssetValidationError`` → ``invalid_asset`` (placeholder ``error``)
    * ``KeyError`` → ``{task,asset}_not_found`` when *not_found* names the missing
      id kind (``"task"`` reads ``call.data["task_id"]``; ``"asset"`` reads
      ``call.data["asset_id"]``). Left ``None``, a ``KeyError`` propagates unchanged
      (the caller either can't hit one or translates it itself, e.g. ``unknown_part``).
    """

    def decorate(handler: _Handler) -> _Handler:
        @functools.wraps(handler)
        async def wrapped(hass: HomeAssistant, call: ServiceCall) -> Any:
            try:
                return await handler(hass, call)
            except KeyError:
                if not_found == "task":
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="task_not_found",
                        translation_placeholders={"task_id": call.data["task_id"]},
                    ) from None
                if not_found == "asset":
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="asset_not_found",
                        translation_placeholders={"asset_id": call.data["asset_id"]},
                    ) from None
                raise
            except TaskValidationError as err:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_task",
                    translation_placeholders={"error": str(err)},
                ) from err
            except AssetValidationError as err:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_asset",
                    translation_placeholders={"error": str(err)},
                ) from err

        return wrapped

    return decorate


def _check_area(hass: HomeAssistant, data: dict) -> None:
    if not devices.area_exists(hass, data.get("area_id")):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_area",
            translation_placeholders={"area_id": str(data.get("area_id"))},
        )


def _completion_metadata(data: dict) -> dict[str, Any]:
    """Lift the per-completion metadata keys out of a service call's data."""
    return {k: data[k] for k in _COMPLETION_METADATA_KEYS if k in data}


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


@_translate_errors()
async def _handle_add_task(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    coord = require_coordinator(hass)
    _check_area(hass, call.data)
    task = await coord.store.add_task(dict(call.data))
    # Only reload when the new task owns per-task entities; otherwise a refresh
    # avoids a full teardown/rebuild (e.g. a companion seeding many device-less
    # tasks would otherwise flap every entity unavailable N times).
    if task_has_entities(task):
        await hass.config_entries.async_reload(coord.entry.entry_id)
    else:
        await coord.async_request_refresh()
    return {"task_id": task["id"]}


@_translate_errors(not_found="task")
async def _handle_update_task(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = require_coordinator(hass)
    _check_area(hass, call.data)
    data = dict(call.data)
    task_id = data.pop("task_id")
    existing = coord.store.get_task(task_id)
    before = entity_set_key(existing)
    updated = await coord.store.update_task(task_id, data)
    # Only changes that alter which per-task entities exist (device link or
    # enabled state) need a full entry reload; otherwise a refresh suffices.
    if entity_set_key(updated) != before:
        await hass.config_entries.async_reload(coord.entry.entry_id)
    else:
        await coord.async_request_refresh()


@_translate_errors()
async def _handle_delete_task(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = require_coordinator(hass)
    existing = coord.store.get_task(call.data["task_id"])
    await coord.store.delete_task(
        call.data["task_id"], force=call.data.get("force", False)
    )
    # Reload only if the deleted task owned per-task entities that must be removed.
    if task_has_entities(existing):
        await hass.config_entries.async_reload(coord.entry.entry_id)
    else:
        await coord.async_request_refresh()


@_translate_errors(not_found="task")
async def _handle_complete_task(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = require_coordinator(hass)
    await coord.store.complete_task(
        call.data["task_id"],
        call.data.get("completed_at"),
        origin=call.data.get("origin"),
        metadata=_completion_metadata(call.data),
    )
    # Completing an auto-buy task bumps stock (restocked) → its reminder is removed;
    # settle so those device entities are (un)registered (else a plain refresh).
    await coord.async_settle_buy_tasks()


@_translate_errors(not_found="task")
async def _handle_update_completion(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = require_coordinator(hass)
    await coord.store.update_completion(
        call.data["task_id"],
        call.data["ts"],
        _completion_metadata(call.data),
    )
    await coord.async_request_refresh()


@_translate_errors(not_found="task")
async def _handle_delete_completion(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = require_coordinator(hass)
    await coord.store.delete_completion(call.data["task_id"], call.data["ts"])
    await coord.async_request_refresh()


@_translate_errors(not_found="asset")
async def _handle_delete_archived_completion(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    coord = require_coordinator(hass)
    await coord.store.delete_archived_completion(
        call.data["asset_id"], call.data["task_id"], call.data["ts"]
    )
    await coord.async_request_refresh()


@_translate_errors(not_found="task")
async def _handle_trigger_task(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = require_coordinator(hass)
    await coord.store.trigger_task(call.data["task_id"])
    # Arming only flips next_due (dormant <-> active); the per-task entity set is
    # unchanged, so a refresh is enough — no entry reload (mirrors complete_task).
    await coord.async_request_refresh()


@_translate_errors(not_found="task")
async def _handle_set_task_consumable(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = require_coordinator(hass)
    await coord.store.set_task_consumable(
        call.data["task_id"],
        call.data.get("asset_id") or None,
        call.data.get("part_id") or None,
    )
    # Linking only rewrites the task's source; the per-task entity set is
    # unchanged, so a refresh is enough — no entry reload.
    await coord.async_request_refresh()


@_translate_errors(not_found="task")
async def _handle_snooze_task(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = require_coordinator(hass)
    until = dt_util.now() + timedelta(hours=call.data["hours"])
    await coord.store.snooze_task(
        call.data["task_id"], until, origin=call.data.get("origin")
    )
    # Snooze only moves next_due (dormant <-> active timing); the per-task entity
    # set is unchanged, so a refresh is enough — no entry reload.
    await coord.async_request_refresh()


@_translate_errors(not_found="task")
async def _handle_skip_task(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = require_coordinator(hass)
    await coord.store.skip_task(call.data["task_id"], origin=call.data.get("origin"))
    await coord.async_request_refresh()


async def _handle_notify(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    coord = require_coordinator(hass)
    response, error = await notifier.async_run_notify(hass, coord, dict(call.data))
    if error is not None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key=error["key"],
            translation_placeholders=error["placeholders"],
        )
    return response


async def _handle_list_tasks(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    coord = require_coordinator(hass)
    return {"tasks": coord.store.list_tasks()}


async def _handle_list_profiles(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, Any]:
    coord = require_coordinator(hass)
    return {"profiles": options.current_options(coord.entry).get(OPTION_PROFILES, [])}


@_translate_errors()
async def _handle_add_asset(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = require_coordinator(hass)
    _check_area(hass, call.data)
    await coord.store.add_asset(dict(call.data))
    await devices.async_apply_asset_change(hass, coord.entry, coord.store)


@_translate_errors(not_found="asset")
async def _handle_update_asset(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = require_coordinator(hass)
    _check_area(hass, call.data)
    data = dict(call.data)
    asset_id = data.pop("asset_id")
    await coord.store.update_asset(asset_id, data)
    await devices.async_apply_asset_change(hass, coord.entry, coord.store)


async def _handle_delete_asset(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = require_coordinator(hass)
    await _delete_asset(hass, coord, call.data["asset_id"])


async def _handle_list_assets(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    coord = require_coordinator(hass)
    return {"assets": coord.store.list_assets()}


async def _handle_adjust_part_stock(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = require_coordinator(hass)
    try:
        await coord.store.adjust_part_stock(
            call.data["asset_id"], call.data["part_id"], call.data["delta"]
        )
    except KeyError:
        # Two placeholders (asset_id + part_id), so this stays outside the shared
        # not_found translation which carries a single id.
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_part",
            translation_placeholders={
                "asset_id": call.data["asset_id"],
                "part_id": call.data["part_id"],
            },
        ) from None
    # A crossing may create/remove an auto-buy task; settle it (reload if a buy
    # task's device entities changed, else refresh).
    await coord.async_settle_buy_tasks()


async def _handle_remove_part_file(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = require_coordinator(hass)
    try:
        await coord.store.remove_part_file(call.data["asset_id"], call.data["part_id"])
    except KeyError:
        # Two placeholders (asset_id + part_id), like adjust_part_stock, so this
        # stays outside the shared single-id not_found translation.
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_part",
            translation_placeholders={
                "asset_id": call.data["asset_id"],
                "part_id": call.data["part_id"],
            },
        ) from None


@_translate_errors(not_found="asset")
async def _handle_add_asset_document(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = require_coordinator(hass)
    document = dict(call.data["document"])
    # Files are uploaded through the HTTP view; the service only adds links.
    if document.get("kind", "link") != "link":
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_asset",
            translation_placeholders={
                "error": "only link documents can be added via this service; "
                "upload files from the panel"
            },
        )
    document["kind"] = "link"
    await coord.store.add_asset_document(call.data["asset_id"], document)
    # Documents touch no device/entity/task; the store already saved and fired the
    # event, so no device reconcile or entry reload is needed.


@_translate_errors(not_found="asset")
async def _handle_remove_asset_document(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = require_coordinator(hass)
    await coord.store.remove_asset_document(
        call.data["asset_id"], call.data["document_id"]
    )


@_translate_errors(not_found="asset")
async def _handle_update_asset_document(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = require_coordinator(hass)
    await coord.store.update_asset_document(
        call.data["asset_id"],
        call.data["document_id"],
        dict(call.data["changes"]),
    )
    # Documents touch no device/entity/task; the store save + event is the job.


async def _handle_export_inventory(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, Any]:
    coord = require_coordinator(hass)
    report = inventory.build_inventory(
        coord.store.list_assets(),
        area_names=devices.area_names(hass),
        today=dt_util.now().date(),
    )
    return {"inventory": report, "csv": inventory.inventory_to_csv(report)}


async def _handle_set_options(hass: HomeAssistant, call: ServiceCall) -> None:
    coord = require_coordinator(hass)
    await options.async_set_options(hass, coord.entry, dict(call.data))


async def _handle_register_companion(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, Any]:
    """Record a companion integration that works with Home Keeper.

    The push half of companion discovery: a Home-Keeper-aware integration
    announces itself so it surfaces in the panel's Companions list (and an
    automation can react to ``home_keeper_companion_connected``). Home Keeper
    stores the descriptor verbatim and never imports the companion. See
    docs/INTEGRATING.md and companions.py.
    """
    companions.async_register_companion(hass, dict(call.data))
    return {"ok": True}


async def _handle_list_companions(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, Any]:
    return {"companions": companions.async_list_companions(hass)}


@dataclass(frozen=True)
class _ServiceDef:
    """One registered ``home_keeper.*`` service.

    The single source of truth for both registration and teardown, so the two can't
    drift (the old hand-maintained ``_SERVICES`` teardown tuple could).
    """

    name: str
    handler: _Handler
    schema: vol.Schema
    response: SupportsResponse = SupportsResponse.NONE


# Registration order matches the historical order in ``__init__.py`` for a clean diff;
# HA does not care about order. ``companions.REGISTER_COMPANION_SCHEMA`` lives with the
# companion registry it validates.
_SERVICE_DEFS: tuple[_ServiceDef, ...] = (
    _ServiceDef(
        "add_task", _handle_add_task, ADD_TASK_SCHEMA, SupportsResponse.OPTIONAL
    ),
    _ServiceDef("update_task", _handle_update_task, UPDATE_TASK_SCHEMA),
    _ServiceDef("delete_task", _handle_delete_task, DELETE_TASK_SCHEMA),
    _ServiceDef("complete_task", _handle_complete_task, COMPLETE_TASK_SCHEMA),
    _ServiceDef(
        "update_completion", _handle_update_completion, UPDATE_COMPLETION_SCHEMA
    ),
    _ServiceDef(
        "delete_completion", _handle_delete_completion, DELETE_COMPLETION_SCHEMA
    ),
    _ServiceDef(
        "delete_archived_completion",
        _handle_delete_archived_completion,
        DELETE_ARCHIVED_COMPLETION_SCHEMA,
    ),
    _ServiceDef("trigger_task", _handle_trigger_task, TRIGGER_TASK_SCHEMA),
    _ServiceDef("snooze_task", _handle_snooze_task, SNOOZE_TASK_SCHEMA),
    _ServiceDef("skip_task", _handle_skip_task, SKIP_TASK_SCHEMA),
    _ServiceDef(
        "set_task_consumable", _handle_set_task_consumable, SET_TASK_CONSUMABLE_SCHEMA
    ),
    _ServiceDef("notify", _handle_notify, NOTIFY_SCHEMA, SupportsResponse.OPTIONAL),
    _ServiceDef(
        "list_tasks", _handle_list_tasks, vol.Schema({}), SupportsResponse.ONLY
    ),
    _ServiceDef(
        "list_profiles", _handle_list_profiles, vol.Schema({}), SupportsResponse.ONLY
    ),
    _ServiceDef("add_asset", _handle_add_asset, ADD_ASSET_SCHEMA),
    _ServiceDef("update_asset", _handle_update_asset, UPDATE_ASSET_SCHEMA),
    _ServiceDef("delete_asset", _handle_delete_asset, ASSET_ID_SCHEMA),
    _ServiceDef(
        "list_assets", _handle_list_assets, vol.Schema({}), SupportsResponse.ONLY
    ),
    _ServiceDef(
        "adjust_part_stock", _handle_adjust_part_stock, ADJUST_PART_STOCK_SCHEMA
    ),
    _ServiceDef("remove_part_file", _handle_remove_part_file, REMOVE_PART_FILE_SCHEMA),
    _ServiceDef(
        "add_asset_document", _handle_add_asset_document, ADD_ASSET_DOCUMENT_SCHEMA
    ),
    _ServiceDef(
        "remove_asset_document",
        _handle_remove_asset_document,
        REMOVE_ASSET_DOCUMENT_SCHEMA,
    ),
    _ServiceDef(
        "update_asset_document",
        _handle_update_asset_document,
        UPDATE_ASSET_DOCUMENT_SCHEMA,
    ),
    _ServiceDef(
        "export_inventory",
        _handle_export_inventory,
        EXPORT_INVENTORY_SCHEMA,
        SupportsResponse.ONLY,
    ),
    _ServiceDef("set_options", _handle_set_options, SET_OPTIONS_SCHEMA),
    _ServiceDef(
        "register_companion",
        _handle_register_companion,
        companions.REGISTER_COMPANION_SCHEMA,
        SupportsResponse.OPTIONAL,
    ),
    _ServiceDef(
        "list_companions",
        _handle_list_companions,
        vol.Schema({}),
        SupportsResponse.ONLY,
    ),
)


def _bind(
    hass: HomeAssistant, handler: _Handler
) -> Callable[[ServiceCall], Coroutine[Any, Any, Any]]:
    """Bind ``hass`` to a ``(hass, call)`` handler, yielding HA's ``(call)`` shape.

    A plain coroutine closure rather than ``functools.partial`` so the registered
    callable is statically typed as returning a coroutine (partial is not).
    ``functools.wraps`` carries the handler's ``__name__``/``__doc__`` onto the bound
    callable so logs/introspection still show the handler, not a bare ``service``.
    """

    @functools.wraps(handler)
    async def service(call: ServiceCall) -> Any:
        return await handler(hass, call)

    return service


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register every Home Keeper service (idempotent across reloads)."""
    for svc in _SERVICE_DEFS:
        hass.services.async_register(
            DOMAIN,
            svc.name,
            _bind(hass, svc.handler),
            schema=svc.schema,
            supports_response=svc.response,
        )


@callback
def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove every Home Keeper service (last entry unloaded)."""
    for svc in _SERVICE_DEFS:
        hass.services.async_remove(DOMAIN, svc.name)
