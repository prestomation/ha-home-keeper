"""The Home Keeper integration.

Tracks home maintenance and chores. Administration happens in a dedicated sidebar
panel; usage (viewing/completing tasks) is surfaced through native HA entities
(todo, calendar) and per-task device-page entities (button/sensor/binary_sensor).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_CORE_CONFIG_UPDATE
from homeassistant.core import (
    Event,
    HomeAssistant,
    ServiceCall,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from . import (
    card,
    companions,
    devices,
    inventory,
    manuals,
    notifier,
    options,
    panel,
    websocket_api,
)
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
    PLATFORMS,
)
from .coordinator import (
    HomeKeeperCoordinator,
    discard_edge_state,
    entity_set_key,
    task_has_entities,
)
from .models import TaskValidationError
from .problem_sync import ProblemSensorSync
from .sensor_watcher import SensorTaskWatcher
from .store import HomeKeeperStore

_LOGGER = logging.getLogger(__name__)

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
    await card.async_register_card(hass)
    manuals.async_register_http(hass)
    websocket_api.async_register(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Platforms have removed entities for deleted/excluded tasks; drop Home Keeper
    # from any device that no longer carries one of our entities so disabling Problem
    # Sensor Sync (or an exclusion) leaves no empty device card behind.
    await devices.async_prune_orphaned_devices(hass, entry)

    _register_services(hass)
    # Now that the register_companion service exists, ask companions to (re-)announce
    # themselves and run a catalog-detection pass. Companions that set up before Home
    # Keeper listen for this ping; those that set up after register at their own setup.
    companions.async_request_registration(hass)
    # React to options-flow changes (e.g. toggling problem-sensor syncing) by
    # reloading the entry, which re-runs this setup with the new options.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    # Relocalize reconciler-generated task names when the HA language changes. The
    # generated wear-part name is baked into storage in the configured language at
    # write time (see store.reconcile_part_tasks); reloading the entry re-runs setup,
    # which reconciles with the new language and recreates the per-task entities under
    # their new names. Captured at setup, so the reload re-baselines to the new value.
    setup_language = hass.config.language

    async def _relocalize_on_language_change(event: Event) -> None:
        if hass.config.language == setup_language:
            return  # some other core-config change (unit system, name, …) — ignore
        _LOGGER.debug(
            "HA language changed %s -> %s; reloading Home Keeper to relocalize "
            "generated task names",
            setup_language,
            hass.config.language,
        )
        await hass.config_entries.async_reload(entry.entry_id)

    entry.async_on_unload(
        hass.bus.async_listen(EVENT_CORE_CONFIG_UPDATE, _relocalize_on_language_change)
    )
    # Now that platforms are up, start the live problem-sensor listeners (these may
    # reload the entry when a synced task is created/removed, so they run last).
    problem_sync.async_start_listeners()
    # Sensor-based tasks: baseline the watcher's edge state / usage meters BEFORE
    # attaching it to the coordinator, so the first evaluation only reacts to genuine
    # transitions (an already-over-threshold sensor at boot does not arm). Then start
    # its live state listeners.
    sensor_watcher = SensorTaskWatcher(hass, entry, coordinator)
    await sensor_watcher.async_baseline()
    coordinator.sensor_watcher = sensor_watcher
    sensor_watcher.async_start_listeners()
    # Listen for actionable-notification taps (mobile_app_notification_action) so a
    # Mark done / Snooze / Skip button routes back into the store and advances a walk.
    entry.async_on_unload(notifier.async_setup_notifications(hass, entry, coordinator))
    # Setup is complete: the refreshes above have baselined current overdue/due-soon
    # state silently, so start firing those events only for transitions from here on.
    coordinator.enable_transition_events()
    # One evaluation pass now that everything is wired: arms any usage task whose meter
    # is already past target (e.g. it advanced while HA was down) and fires the genuine
    # overdue/due-soon events for it.
    await coordinator.async_request_refresh()
    # Flip the companion registry live only once HA has fully started, so companions
    # that self-register during startup (and catalog upstreams already installed) are
    # baselined silently — an HA restart never replays a companion_connected storm.
    entry.async_on_unload(async_at_started(hass, _async_companions_go_live))
    return True


@callback
def _async_companions_go_live(hass: HomeAssistant) -> None:
    """Baseline current companions silently, then start firing discovery events."""
    registry = companions.async_get_registry(hass)
    registry.reconcile()  # capture whatever registered during startup (still silent)
    registry.set_live()


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
        # Reachable transiently mid-reload (the entry is momentarily unloaded while
        # its services are still registered). Surface a localized HA error rather than
        # a bare RuntimeError that would present as an opaque 500.
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="integration_not_loaded"
        )

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
        # Only reload when the new task owns per-task entities; otherwise a refresh
        # avoids a full teardown/rebuild (e.g. a companion seeding many device-less
        # tasks would otherwise flap every entity unavailable N times).
        if task_has_entities(task):
            await hass.config_entries.async_reload(coord.entry.entry_id)
        else:
            await coord.async_request_refresh()
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
        existing = coord.store.get_task(call.data["task_id"])
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
        # Reload only if the deleted task owned per-task entities that must be removed.
        if task_has_entities(existing):
            await hass.config_entries.async_reload(coord.entry.entry_id)
        else:
            await coord.async_request_refresh()

    def _completion_metadata(data: dict) -> dict[str, Any]:
        """Lift the per-completion metadata keys out of a service call's data."""
        return {k: data[k] for k in _COMPLETION_METADATA_KEYS if k in data}

    async def handle_complete_task(call: ServiceCall) -> None:
        coord = _coordinator()
        try:
            await coord.store.complete_task(
                call.data["task_id"],
                call.data.get("completed_at"),
                origin=call.data.get("origin"),
                metadata=_completion_metadata(call.data),
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

    async def handle_update_completion(call: ServiceCall) -> None:
        coord = _coordinator()
        try:
            await coord.store.update_completion(
                call.data["task_id"],
                call.data["ts"],
                _completion_metadata(call.data),
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

    async def handle_delete_completion(call: ServiceCall) -> None:
        coord = _coordinator()
        try:
            await coord.store.delete_completion(call.data["task_id"], call.data["ts"])
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

    async def handle_delete_archived_completion(call: ServiceCall) -> None:
        coord = _coordinator()
        try:
            await coord.store.delete_archived_completion(
                call.data["asset_id"], call.data["task_id"], call.data["ts"]
            )
        except KeyError:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="asset_not_found",
                translation_placeholders={"asset_id": call.data["asset_id"]},
            ) from None
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

    async def handle_set_task_consumable(call: ServiceCall) -> None:
        coord = _coordinator()
        try:
            await coord.store.set_task_consumable(
                call.data["task_id"],
                call.data.get("asset_id") or None,
                call.data.get("part_id") or None,
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
        # Linking only rewrites the task's source; the per-task entity set is
        # unchanged, so a refresh is enough — no entry reload.
        await coord.async_request_refresh()

    async def handle_snooze_task(call: ServiceCall) -> None:
        coord = _coordinator()
        until = dt_util.now() + timedelta(hours=call.data["hours"])
        try:
            await coord.store.snooze_task(
                call.data["task_id"], until, origin=call.data.get("origin")
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
        # Snooze only moves next_due (dormant <-> active timing); the per-task entity
        # set is unchanged, so a refresh is enough — no entry reload.
        await coord.async_request_refresh()

    async def handle_skip_task(call: ServiceCall) -> None:
        coord = _coordinator()
        try:
            await coord.store.skip_task(
                call.data["task_id"], origin=call.data.get("origin")
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

    async def handle_notify(call: ServiceCall) -> dict[str, Any]:
        coord = _coordinator()
        response, error = await notifier.async_run_notify(hass, coord, dict(call.data))
        if error is not None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=error["key"],
                translation_placeholders=error["placeholders"],
            )
        return response

    async def handle_list_tasks(call: ServiceCall) -> dict[str, Any]:
        coord = _coordinator()
        return {"tasks": coord.store.list_tasks()}

    async def handle_list_profiles(call: ServiceCall) -> dict[str, Any]:
        coord = _coordinator()
        return {
            "profiles": options.current_options(coord.entry).get(OPTION_PROFILES, [])
        }

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

    async def handle_remove_part_file(call: ServiceCall) -> None:
        coord = _coordinator()
        try:
            await coord.store.remove_part_file(
                call.data["asset_id"], call.data["part_id"]
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

    async def handle_add_asset_document(call: ServiceCall) -> None:
        coord = _coordinator()
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
        try:
            await coord.store.add_asset_document(call.data["asset_id"], document)
        except KeyError:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="asset_not_found",
                translation_placeholders={"asset_id": call.data["asset_id"]},
            ) from None
        except AssetValidationError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_asset",
                translation_placeholders={"error": str(err)},
            ) from err
        # Documents touch no device/entity/task; the store already saved and fired the
        # event, so no device reconcile or entry reload is needed.

    async def handle_remove_asset_document(call: ServiceCall) -> None:
        coord = _coordinator()
        try:
            await coord.store.remove_asset_document(
                call.data["asset_id"], call.data["document_id"]
            )
        except KeyError:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="asset_not_found",
                translation_placeholders={"asset_id": call.data["asset_id"]},
            ) from None

    async def handle_update_asset_document(call: ServiceCall) -> None:
        coord = _coordinator()
        try:
            await coord.store.update_asset_document(
                call.data["asset_id"],
                call.data["document_id"],
                dict(call.data["changes"]),
            )
        except KeyError:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="asset_not_found",
                translation_placeholders={"asset_id": call.data["asset_id"]},
            ) from None
        except AssetValidationError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_asset",
                translation_placeholders={"error": str(err)},
            ) from err
        # Documents touch no device/entity/task; the store save + event is the job.

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
        DOMAIN, "update_completion", handle_update_completion, UPDATE_COMPLETION_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "delete_completion", handle_delete_completion, DELETE_COMPLETION_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        "delete_archived_completion",
        handle_delete_archived_completion,
        DELETE_ARCHIVED_COMPLETION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, "trigger_task", handle_trigger_task, TRIGGER_TASK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "snooze_task", handle_snooze_task, SNOOZE_TASK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "skip_task", handle_skip_task, SKIP_TASK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        "set_task_consumable",
        handle_set_task_consumable,
        SET_TASK_CONSUMABLE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "notify",
        handle_notify,
        NOTIFY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "list_tasks",
        handle_list_tasks,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "list_profiles",
        handle_list_profiles,
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
    hass.services.async_register(
        DOMAIN,
        "remove_part_file",
        handle_remove_part_file,
        REMOVE_PART_FILE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "add_asset_document",
        handle_add_asset_document,
        ADD_ASSET_DOCUMENT_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "remove_asset_document",
        handle_remove_asset_document,
        REMOVE_ASSET_DOCUMENT_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        "update_asset_document",
        handle_update_asset_document,
        UPDATE_ASSET_DOCUMENT_SCHEMA,
    )

    async def handle_set_options(call: ServiceCall) -> None:
        coord = _coordinator()
        await options.async_set_options(hass, coord.entry, dict(call.data))

    async def handle_register_companion(call: ServiceCall) -> dict[str, Any]:
        """Record a companion integration that works with Home Keeper.

        The push half of companion discovery: a Home-Keeper-aware integration
        announces itself so it surfaces in the panel's Companions list (and an
        automation can react to ``home_keeper_companion_connected``). Home Keeper
        stores the descriptor verbatim and never imports the companion. See
        docs/INTEGRATING.md and companions.py.
        """
        companions.async_register_companion(hass, dict(call.data))
        return {"ok": True}

    async def handle_list_companions(call: ServiceCall) -> dict[str, Any]:
        return {"companions": companions.async_list_companions(hass)}

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
    hass.services.async_register(
        DOMAIN,
        "register_companion",
        handle_register_companion,
        companions.REGISTER_COMPANION_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "list_companions",
        handle_list_companions,
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
    "update_completion",
    "delete_completion",
    "delete_archived_completion",
    "trigger_task",
    "snooze_task",
    "skip_task",
    "set_task_consumable",
    "notify",
    "list_tasks",
    "list_profiles",
    "add_asset",
    "update_asset",
    "delete_asset",
    "list_assets",
    "adjust_part_stock",
    "remove_part_file",
    "add_asset_document",
    "remove_asset_document",
    "update_asset_document",
    "export_inventory",
    "set_options",
    "register_companion",
    "list_companions",
)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    # Only tear down the panel/services when the last entry goes away. Gate on
    # *loaded* entries, not ``async_entries``: HA removes the entry from the registry
    # only *after* this unload returns (and a disabled entry stays registered), so
    # ``async_entries(DOMAIN)`` is never empty here and the teardown was dead code —
    # leaving the panel pointing at a dead backend and all services registered until
    # restart. ``async_loaded_entries`` excludes the entry currently unloading.
    if unloaded and not hass.config_entries.async_loaded_entries(DOMAIN):
        panel.async_unregister_panel(hass)
        for service in _SERVICES:
            hass.services.async_remove(DOMAIN, service)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove all Home Keeper data when the integration is deleted.

    Virtual asset devices (and per-task self-owned devices) are tied to this config
    entry, so Home Assistant removes them automatically. Here we additionally drop
    our stored tasks/assets document and the uploaded-documents blob tree so no
    residue is left behind.
    """
    discard_edge_state(hass, entry.entry_id)
    store = HomeKeeperStore(hass)
    await store.async_remove()
    await manuals.async_delete_all_documents(hass)
