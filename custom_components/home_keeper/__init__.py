"""The Home Keeper integration.

Tracks home maintenance and chores. Administration happens in a dedicated sidebar
panel; usage (viewing/completing tasks) is surfaced through native HA entities
(todo, calendar) and per-task device-page entities (button/sensor/binary_sensor).
"""

from __future__ import annotations

import logging
import math
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
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from . import (
    appliance_report,
    assets,
    backend_i18n,
    card,
    companions,
    declarative_companion_sync,
    devices,
    manuals,
    notifications,
    notifier,
    options,
    panel,
    profiles,
    recurrence,
    sensor_tasks,
    shopping,
    tag_listener,
    transfer,
    websocket_api,
)
from .assets import card_projection, has_archived_completion
from .const import (
    COMPLETION_ENTRY_FIELDS,
    DOMAIN,
    MAX_ONE_OFF_RETENTION_DAYS,
    OPTION_ALLOW_DUE_TODAY,
    OPTION_ALLOW_SKIP,
    OPTION_ALLOW_SNOOZE,
    OPTION_DISMISSED_COMPANIONS,
    OPTION_NOTIFICATIONS,
    OPTION_ONE_OFF_RETENTION_DAYS,
    OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS,
    OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS,
    OPTION_PROFILES,
    OPTION_SHOPPING_LINE_STYLE,
    OPTION_SHOPPING_LIST_ENTITY,
    OPTION_SYNC_PROBLEM_SENSORS,
    PLATFORMS,
    SENSOR_MODE_TEMPLATE,
    SENSOR_MODE_USAGE,
    SKIP_ENTRY_FIELDS,
    TRANSFER_FORMAT,
)
from .coordinator import (
    HomeKeeperCoordinator,
    async_delete_orphaned_tasks,
    discard_edge_state,
    discard_edge_state_if_disabled,
    find_coordinator,
    task_has_entities,
)
from .declarative_companion_sync import DeclarativeCompanionSync
from .problem_sync import ProblemSensorSync
from .resolve import (
    AmbiguousName,
    NotFound,
    looks_like_id,
    resolve_archived_task_id,
    resolve_asset_id,
    resolve_document_id,
    resolve_part_id,
    resolve_task_id,
)
from .sensor_watcher import (
    SensorTaskWatcher,
    async_discard_new_tasks,
    read_sensor_value,
)
from .service_errors import (
    declarative_companion_errors,
    service_error,
    store_errors,
)
from .shopping_sync import ShoppingListSync
from .store import HomeKeeperStore
from .task_entities import entity_set_key
from .todo_list_sync import TodoListSync
from .transfer_runner import (
    async_export_document,
    async_import_document,
)

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
        # The NFC/RFID tag (a Home Assistant tag id) whose scan completes this task,
        # and whether a scan is the only accepted way to complete it. ``None`` clears
        # the link, which is why the value is nullable rather than a bare string.
        vol.Optional("tag_id"): vol.Any(None, cv.string),
        vol.Optional("require_tag_scan"): cv.boolean,
        # How long Snooze moves this task, in hours. ``None`` clears it, and the task
        # then uses the dialog's usual preset and the notification's own length.
        vol.Optional("snooze_hours"): vol.Any(
            None, vol.All(vol.Coerce(int), vol.Range(min=1))
        ),
        # Restrict a floating/fixed task to one or more date ranges each year. A list
        # of ``{"start": "MM-DD", "end": "MM-DD"}`` windows; a single window may be
        # passed as one object, and ``None`` clears the season. Validated by
        # models.normalize_active_season.
        vol.Optional("active_season"): vol.Any(None, dict, [dict]),
        # Off keeps the task and everything recorded on it, and takes it out of every
        # surface that reads a schedule: the to-do list, the calendar, the per-task
        # entities, the profiles, the announcements, the sensor watcher and a tag
        # scan. It does not move ``next_due``, so a task switched back on is as late
        # as its stored date says. Home Keeper offers no switch for this: a service
        # call is what turns a task off, and the panel only turns one back on.
        vol.Optional("enabled"): cv.boolean,
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
        # Send ``tag_id: null`` to unlink the tag (clearing it while
        # ``require_tag_scan`` stays on is rejected — see models.merge_update).
        vol.Optional("tag_id"): vol.Any(None, cv.string),
        vol.Optional("require_tag_scan"): cv.boolean,
        # See ADD_TASK_SCHEMA: ``None`` clears the snooze length.
        vol.Optional("snooze_hours"): vol.Any(
            None, vol.All(vol.Coerce(int), vol.Range(min=1))
        ),
        # See ADD_TASK_SCHEMA: ``None`` clears the season, one object is one window.
        vol.Optional("active_season"): vol.Any(None, dict, [dict]),
        # See ADD_TASK_SCHEMA. Off takes the task out of every schedule surface and
        # leaves ``next_due`` where it was.
        vol.Optional("enabled"): cv.boolean,
        vol.Optional("source"): dict,
        vol.Optional("task_chips"): vol.All(cv.ensure_list, [TASK_CHIP_SCHEMA]),
    }
)
TASK_ID_SCHEMA = vol.Schema({vol.Required("task_id"): cv.string})
# Arm a condition-driven (triggered) task so it reads as due-now. The owner-facing
# counterpart to complete_task (which clears it back to dormant). See INTEGRATING.md.
TRIGGER_TASK_SCHEMA = vol.Schema({vol.Required("task_id"): cv.string})
# Re-anchor a usage (meter) task's baseline without recording a completion — the
# "I already did this before Home Keeper was watching" / "the meter was replaced"
# escape hatch. Omitting ``baseline`` re-anchors to the bound entity's live reading.
SET_TASK_METER_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Optional("baseline"): vol.Coerce(float),
    }
)
# Snooze: defer a task's next due date without recording a completion or advancing
# recurrence. ``origin`` is echoed in the home_keeper_task_snoozed event for loop
# prevention (e.g. an actionable notification action). Skip advances to the next
# occurrence, also without completing, and logs the skip.
#
# The deferral is either ``hours`` (whole hours from now, the original field) or
# ``until`` (an absolute datetime). They are mutually exclusive: passing both is a
# contradiction rather than a precedence puzzle, so voluptuous rejects it. ``hours``
# keeps its default, so every existing caller — and a bare call passing neither — is
# unaffected. ``until`` exists because whole hours cannot express "next Tuesday 09:00"
# across a DST boundary, which the panel's snooze dialog needs.
SNOOZE_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        # Whole hours ≥ 1, matching services.yaml's number selector and the
        # notification snooze_hours contract (normalize_notification / the panel).
        vol.Exclusive("hours", "deferral"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Exclusive("until", "deferral"): cv.datetime,
        vol.Optional("origin"): cv.string,
    }
)
SKIP_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Optional("origin"): cv.string,
        # Why the occurrence was passed over. No ``cost``/``photo``: nothing was
        # bought and there is nothing to show (see const.SKIP_ENTRY_FIELDS).
        vol.Optional("note"): cv.string,
        vol.Optional("who"): cv.string,
        vol.Optional("reading"): vol.Coerce(float),
    }
)
# Pull-forward: move a task's due date to now, independent of its periodic schedule
# — the mirror of snooze. ``origin`` is echoed in the home_keeper_task_due_today_set
# event for loop prevention, matching snooze/skip.
SET_DUE_TODAY_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Optional("origin"): cv.string,
    }
)

# The skip log's edit trio, mirroring the completion trio below. They key on the
# skip's ISO ``ts`` exactly as the completion ones key on a completion's.
UPDATE_SKIP_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Required("ts"): cv.string,
        vol.Optional("note"): cv.string,
        vol.Optional("who"): cv.string,
        vol.Optional("reading"): vol.Coerce(float),
    }
)

DELETE_SKIP_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Required("ts"): cv.string,
    }
)

MOVE_SKIP_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Required("old_ts"): cv.string,
        vol.Required("new_ts"): cv.datetime,
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
        # What this one task takes, when it takes more than the part's own per-use
        # amount (a smoke alarm holding 2 cells of a type other tasks take 1 of).
        # Omitted, the part's ``consume_quantity`` decides, as it always has.
        vol.Optional("quantity"): vol.Coerce(float),
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
# ``photo`` is an image URL and ``who`` a person entity id.
COMPLETE_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Optional("completed_at"): cv.datetime,
        vol.Optional("origin"): cv.string,
        vol.Optional("note"): cv.string,
        vol.Optional("cost"): vol.Coerce(float),
        vol.Optional("photo"): cv.string,
        vol.Optional("who"): cv.string,
        # The bound sensor's value at the moment the work was done. Only meaningful
        # for a sensor task; Home Keeper reads it live when the caller omits it, so
        # pass it explicitly when back-dating (the meter has moved since).
        vol.Optional("reading"): vol.Coerce(float),
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
        vol.Optional("reading"): vol.Coerce(float),
    }
)

DELETE_COMPLETION_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Required("ts"): cv.string,
        vol.Optional("origin"): cv.string,
    }
)

# Re-timestamp a recorded completion (back-date or correct it). Unlike
# UPDATE_COMPLETION_SCHEMA (metadata only), this moves the completion's ``ts``;
# ``new_completed_at`` uses ``cv.datetime`` for parity with ``COMPLETE_TASK_SCHEMA``'s
# ``completed_at`` (accepts an offset-less value, qualified with HA's zone downstream).
MOVE_COMPLETION_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Required("old_ts"): cv.string,
        vol.Required("new_completed_at"): cv.datetime,
    }
)

DELETE_ARCHIVED_COMPLETION_SCHEMA = vol.Schema(
    {
        vol.Required("asset_id"): cv.string,
        vol.Required("task_id"): cv.string,
        vol.Required("ts"): cv.string,
    }
)

# The completion keys shared by complete_task / update_completion, lifted out of a
# service call's data into the ``metadata`` mapping the store expects. Includes the
# captured ``reading`` — the store decides whether the task may carry one.
_COMPLETION_METADATA_KEYS = tuple(COMPLETION_ENTRY_FIELDS)
_SKIP_METADATA_KEYS = tuple(SKIP_ENTRY_FIELDS)

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
        # Spare quantities are floats: a part can be measured in millilitres or in
        # thirds of a bottle. ``assets._round_stock`` collapses a whole value back to
        # an int, so a plain count still stores as one.
        vol.Optional("stock"): vol.Coerce(float),
        vol.Optional("reorder_at"): vol.Coerce(float),
        vol.Optional("stock_unit"): cv.string,
        vol.Optional("consume_quantity"): vol.Coerce(float),
        vol.Optional("create_buy_task"): cv.boolean,
        vol.Optional("restock_quantity"): vol.Coerce(float),
        # A counted wear item: ``replace_unit: "uses"`` above makes the interval a
        # number of uses rather than a span of time, and these 4 shape the pair of
        # tasks it generates. ``replace_also_every`` is the optional time backstop
        # ("or every 12 months, whichever comes first"); the pure model validates its
        # interval and unit, so the schema only asserts the shape.
        vol.Optional("action"): cv.string,
        vol.Optional("use_noun"): cv.string,
        vol.Optional("use_task_name"): cv.string,
        # The NFC/RFID tag bound to the task the wear item generates (the use task of
        # a counted wear item). ``tag_id: null`` clears it; the pure model refuses
        # ``require_tag_scan`` without a tag, as ``add_task`` does.
        vol.Optional("tag_id"): vol.Any(None, cv.string),
        vol.Optional("require_tag_scan"): cv.boolean,
        vol.Optional("replace_also_every"): vol.Any(
            None,
            vol.Schema(
                {
                    vol.Optional("interval"): vol.Coerce(int),
                    vol.Optional("unit"): cv.string,
                }
            ),
        ),
        # A count that arrived with an imported part, because the use task holding the
        # real log is not portable. It has to be *takeable* here as well as storable:
        # the export puts it on the part, so an automation replaying an exported
        # appliance through update_asset hands it straight back, and a strict schema
        # without it would refuse the very payload list_assets just produced.
        vol.Optional("carried_uses"): vol.Coerce(int),
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
# stay structured — ``manufacturer``/``model`` (device card) and ``cost`` (report
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
    vol.Optional("notes"): cv.string,
    vol.Optional("cost"): vol.Coerce(float),
    vol.Optional("documents"): [_DOCUMENT_SCHEMA],
    vol.Optional("metadata"): [_METADATA_SCHEMA],
    vol.Optional("parts"): [_PART_SCHEMA],
    vol.Optional("parent_asset_id"): cv.string,
    vol.Optional("related_device_ids"): [cv.string],
    # Opaque provenance, namespaced by the integration that created the appliance —
    # the appliance twin of ``add_task``'s ``source``, create-only. Like
    # ``managed_by`` below it is an integrator's field, documented in
    # docs/INTEGRATING.md rather than in ``services.yaml``, so the UI draws no
    # control for it.
    vol.Optional("source"): dict,
}
# ``managed_by`` is create-only, so it is named per action rather than in the shared
# field set: on an add it declares ownership (which fields the owner keeps — see
# ``const.ASSET_LOCKED_FIELDS`` — and whether the appliance is deletion-protected).
ADD_ASSET_SCHEMA = vol.Schema({**_ASSET_FIELDS, vol.Optional("managed_by"): dict})
UPDATE_ASSET_SCHEMA = vol.Schema(
    {
        vol.Required("asset_id"): cv.string,
        **_ASSET_FIELDS,
        # On an update only ``None`` acts, and it clears the block: an integration
        # being removed hands its appliance back, and the household keeps a plain
        # appliance with its stock counts. Any other value is ignored, so an
        # appliance cannot be taken over by updating it.
        vol.Optional("managed_by"): vol.Any(None, dict),
    }
)
ASSET_ID_SCHEMA = vol.Schema({vol.Required("asset_id"): cv.string})
# ``force`` bypasses a managed appliance's deletion protection, exactly as it does
# for a task — the escape hatch when the owning integration is gone or misbehaving.
DELETE_ASSET_SCHEMA = vol.Schema(
    {
        vol.Required("asset_id"): cv.string,
        vol.Optional("force", default=False): cv.boolean,
    }
)
# The owner's door into an appliance it manages: the locked name, and the part list
# it owns. Every stock field on each part stays the household's (see
# ``assets.apply_managed_parts``).
UPDATE_MANAGED_ASSET_SCHEMA = vol.Schema(
    {
        vol.Required("asset_id"): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional("parts"): [_PART_SCHEMA],
    }
)

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

# Adjust a part's on-hand spare quantity by a (signed) delta; clamped at zero. The
# delta is a float because stock is: a part measured in millilitres draws down by 250,
# a bottle topped up a third at a time by 0.33.
ADJUST_PART_STOCK_SCHEMA = vol.Schema(
    {
        vol.Required("asset_id"): cv.string,
        vol.Required("part_id"): cv.string,
        # Open bounds at the infinities refuse NaN and both infinities, which
        # Coerce(float) accepts from the text "nan" and "inf" (B05-5).
        vol.Required("delta"): vol.All(
            vol.Coerce(float),
            vol.Range(
                min=-math.inf, max=math.inf, min_included=False, max_included=False
            ),
        ),
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
# Mint a short-lived signed URL for a file document/part file — no auth header
# needed to fetch it (issue #161: lets a caller with no interactive session of its
# own, e.g. an MCP-connected agent, download the actual bytes instead of only
# metadata). See manuals.async_sign_document_url for the signing-identity choice.
SIGN_DOCUMENT_URL_SCHEMA = vol.Schema(
    {
        vol.Required("asset_id"): cv.string,
        vol.Required("document_id"): cv.string,
    }
)
SIGN_PART_FILE_URL_SCHEMA = vol.Schema(
    {
        vol.Required("asset_id"): cv.string,
        vol.Required("part_id"): cv.string,
    }
)
# Task photos (#399). Upload is HTTP-only, like a document; these need no bytes.
TASK_PHOTO_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Required("photo_id"): cv.string,
    }
)
SIGN_TASK_PHOTO_URL_SCHEMA = vol.Schema(
    {
        vol.Required("task_id"): cv.string,
        vol.Required("photo_id"): cv.string,
        vol.Optional("thumbnail", default=False): cv.boolean,
    }
)
EXPORT_APPLIANCE_REPORT_SCHEMA = vol.Schema({})

# The portable document, both directions. ``document`` is deliberately a bare dict or
# string rather than a spelled-out voluptuous shape: ``transfer.plan_import`` validates
# the whole thing against the live store — which a schema cannot see — and reports every
# problem at once with a path, instead of failing on the first key at the edge. A string
# is the whole file as text, which the same function reads; the panel sends that, so
# there is one YAML parser rather than a second one in the browser.
#
# The published JSON Schema is a *separate* declaration, below, for documentation only.
EXPORT_DATA_SCHEMA = vol.Schema(
    {vol.Optional("include"): vol.All(cv.ensure_list, [vol.In(transfer.SECTIONS)])}
)
IMPORT_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("document"): vol.Any(dict, cv.string),
        vol.Optional("dry_run", default=False): cv.boolean,
        vol.Optional("match", default="auto"): vol.In(("auto", "none")),
    }
)


# ── The document's published shape ───────────────────────────────────────────
#
# ``ci/generate_schema.py`` converts the schema below into the JSON Schema published
# at :data:`const.TRANSFER_SCHEMA_URL`, which every exported file names on its first
# line so an editor can check it as you type. The conversion is mechanical
# (``voluptuous_openapi.convert``), which is the whole point: the published contract is
# a transform of the validator the service actually runs, so it cannot drift from it.
#
# It is a *declaration*, not a gate. ``IMPORT_DATA_SCHEMA`` above still takes a bare
# dict, for the reason stated there. ``tests/unit/test_generate_schema.py`` is what
# keeps this declaration honest: it compares the field set against the records
# ``models.build_task`` and ``assets.build_asset`` really build.


# One season window. ``ADD_TASK_SCHEMA`` takes a bare ``dict`` here and leaves the
# checking to ``models.normalize_active_season``, which is the right trade for a
# service call — the normalizer gives a better message than a schema would. A published
# schema has no normalizer to fall back on, so it says the shape: ``MM-DD``, not a full
# date, which is the mistake somebody writing a document by hand actually makes.
_SEASON_WINDOW_SCHEMA = vol.Schema(
    {
        vol.Required("start"): vol.Match(r"^\d{2}-\d{2}$"),
        vol.Required("end"): vol.Match(r"^\d{2}-\d{2}$"),
    }
)


def _entry_schema(fields: list[str], when_key: str) -> vol.Schema:
    """One history or skip entry, typed by the service that records one.

    The field *names* come from ``const``; their *types* are lifted out of
    ``COMPLETE_TASK_SCHEMA`` and ``SKIP_TASK_SCHEMA`` by name, so a completion's
    ``cost`` is a float in the document because it is a float in the service. Writing
    the types out again here would be a second answer to a question already answered
    two hundred lines up.
    """
    known: dict[str, Any] = {}
    for schema in (COMPLETE_TASK_SCHEMA.schema, SKIP_TASK_SCHEMA.schema):
        for marker, validator in schema.items():
            known[str(marker.schema)] = validator
    entry: dict[Any, Any] = {vol.Required(when_key): cv.string}
    for name in fields:
        entry[vol.Optional(name)] = known[name]
    return vol.Schema(entry)


# The keys a record carries that no service takes. Everything else on a record is an
# ``add_task`` / ``add_asset`` field, and types itself from the service schema.
TRANSFER_TASK_RECORD_SCHEMA = vol.Schema(
    {
        **{
            marker: validator
            for marker, validator in ADD_TASK_SCHEMA.schema.items()
            if marker.schema not in transfer.UNPORTABLE_TASK_KEYS
        },
        # Home Keeper's own id, and the caller's. The primary-key ladder tries them
        # in this order, then falls back to the name.
        vol.Optional("id"): cv.string,
        vol.Optional("external_id"): cv.string,
        # An area by name and an appliance by external_id, name or id: a document has
        # to read on an install whose registry ids are all different.
        vol.Optional("area"): cv.string,
        vol.Optional("appliance"): cv.string,
        # Spelled out rather than inherited: ``vol.Any(None, dict, [dict])`` carries no
        # shape at all, and a schema that says "object" would reject the list every
        # export actually writes.
        vol.Optional("active_season"): vol.Any(
            None, _SEASON_WINDOW_SCHEMA, [_SEASON_WINDOW_SCHEMA]
        ),
        vol.Optional("history"): [
            _entry_schema(COMPLETION_ENTRY_FIELDS, "completed_at")
        ],
        vol.Optional("skips"): [_entry_schema(SKIP_ENTRY_FIELDS, "skipped_at")],
    },
    # An unknown field is a named warning on import, not an error, so the schema has
    # to allow one. Same reasoning as the document below.
    extra=vol.ALLOW_EXTRA,
)
TRANSFER_ASSET_RECORD_SCHEMA = vol.Schema(
    {
        **{
            marker: validator
            for marker, validator in ADD_ASSET_SCHEMA.schema.items()
            if marker.schema not in transfer.UNPORTABLE_ASSET_KEYS
        },
        vol.Optional("id"): cv.string,
        vol.Optional("external_id"): cv.string,
        vol.Optional("area"): cv.string,
        vol.Optional("archived"): cv.boolean,
    },
    extra=vol.ALLOW_EXTRA,
)
TRANSFER_DOCUMENT_SCHEMA = vol.Schema(
    {
        vol.Required("home_keeper"): vol.Schema(
            {
                # Optional because ``plan_import`` defaults it: a file a person typed
                # by hand should not be refused for leaving out a number it can guess.
                vol.Optional("format"): vol.All(
                    int, vol.Range(min=1, max=TRANSFER_FORMAT)
                ),
                vol.Optional("version"): cv.string,
                vol.Optional("exported_at"): cv.string,
            },
            extra=vol.ALLOW_EXTRA,
        ),
        vol.Optional("appliances"): [TRANSFER_ASSET_RECORD_SCHEMA],
        vol.Optional("tasks"): [TRANSFER_TASK_RECORD_SCHEMA],
    },
    # An unknown field or an unknown section is a named warning on import, never an
    # error, so the published schema has to allow one too. A schema stricter than the
    # code it describes sends people to fix files that would have imported.
    extra=vol.ALLOW_EXTRA,
)

# Send an actionable notification on demand for what's due now (the pull / "walk"
# entry point). Name a saved notification, or a profile (filter), optionally with a
# target override. Custom filters/delivery live on saved Profiles/Notifications (the
# point of making them reusable), not inline here. All optional so a bare name fires.
NOTIFY_SCHEMA = vol.Schema(
    {
        vol.Optional("notification"): cv.string,
        vol.Optional("profile"): cv.string,
        vol.Optional("target"): vol.All(cv.ensure_list, [cv.string]),
        # Two per-call overrides. Both are fixed vocabularies rather than free text, so
        # they are validated here and never clamped later: a typo in an automation
        # should fail loudly, not send something subtly different. ``status`` widens (or
        # empties) the profile's due-state filter for this call only; ``when_empty``
        # says whether a queue that matched nothing still delivers the all-clear.
        vol.Optional("status"): vol.In(profiles.SERVICE_STATUSES),
        vol.Optional("when_empty"): vol.In(notifications.WHEN_EMPTY),
    }
)

# Integration-wide options, also editable from the panel's Settings tab and the
# options flow. Every field is optional so an automation can flip just one (e.g.
# turn syncing off) without restating the exclusion lists. See options.py.
SET_OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(OPTION_SYNC_PROBLEM_SENSORS): cv.boolean,
        # Whether the panel and notification button sets offer Snooze / Skip /
        # Pull forward. The services themselves stay callable either way (see
        # const.OPTION_ALLOW_SNOOZE).
        vol.Optional(OPTION_ALLOW_SNOOZE): cv.boolean,
        vol.Optional(OPTION_ALLOW_SKIP): cv.boolean,
        vol.Optional(OPTION_ALLOW_DUE_TODAY): cv.boolean,
        vol.Optional(OPTION_ONE_OFF_RETENTION_DAYS): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=MAX_ONE_OFF_RETENTION_DAYS)
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
        # The to-do list auto-buy reminders are mirrored onto; "" turns it off.
        # Anything that isn't a ``todo.*`` entity id normalizes to "" (see
        # shopping.normalize_target), so a typo disables rather than half-works.
        vol.Optional(OPTION_SHOPPING_LIST_ENTITY): cv.string,
        # How a mirrored reminder's line reads on that list (shopping.LINE_STYLES).
        vol.Optional(OPTION_SHOPPING_LINE_STYLE): vol.In(shopping.LINE_STYLES),
        # Catalog glue domains the user dismissed from the Companions "Suggested"
        # list. A list of domain strings.
        vol.Optional(OPTION_DISMISSED_COMPANIONS): vol.All(cv.ensure_list, [cv.string]),
        # Profiles (saved filters, each carrying the to-do list it syncs onto) and
        # notifications (delivery) — the panel saves each whole list; normalization
        # happens in the matching profiles/notifications.normalize_* helper.
        vol.Optional(OPTION_PROFILES): list,
        vol.Optional(OPTION_NOTIFICATIONS): list,
    }
)


# Home Keeper is set up from the UI only. ``async_setup`` exists to register the
# services, so Home Assistant asks for a schema that says so.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration (config-entry only).

    The services are registered here, once for the Home Assistant run, and not in
    ``async_setup_entry`` (B02-1). Home Assistant's ``action-setup`` rule asks for
    this: a reload unloads the entry and sets it up again, and a service that went
    away with the unload made each call in that time fail with "action not found".
    Each handler finds the coordinator when it is called, and raises the localized
    ``integration_not_loaded`` error when no entry is loaded.
    """
    _register_services(hass)
    # Listen for actionable-notification taps (mobile_app_notification_action) so a
    # Mark done / Snooze / Skip button routes back into the store and advances a walk.
    # Listen for tag scans (tag_scanned) so scanning the NFC/RFID tag stuck on the
    # thing completes the tasks bound to it — and unlocks the ones that accept no
    # other way of being completed. Both listen for the Home Assistant run, so an
    # event during an entry reload waits for the new coordinator (X02-5).
    notifier.async_setup_notifications(hass)
    tag_listener.async_setup_tag_listener(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Home Keeper from a config entry."""
    # Read the backend string tables in the executor, before anything on the loop can
    # ask for a string and read them itself. Everything downstream — the coordinator's
    # first refresh, the problem-sensor reconcile, every websocket error reply — then
    # resolves out of a warm cache. See ``backend_i18n.preload`` (#247).
    await hass.async_add_executor_job(backend_i18n.preload, hass.config.language)
    # The shopping-list sync writes amounts with the language's decimal mark, and the
    # first lookup reads Babel's locale data from disk. Do that read here, in the
    # executor, so the sync on the loop gets the cached value.
    await hass.async_add_executor_job(assets.decimal_mark, hass.config.language)

    store = HomeKeeperStore(hass)
    await store.load()

    # Warn once for each setup about a stored notify target that the allowlist drops.
    # A read of the options runs on each refresh and does not warn (B16-11).
    notifications.normalize_notifications(entry.options.get(OPTION_NOTIFICATIONS))

    # Repair device references Home Assistant invalidated when it split devices in
    # 2026.8 (#183). Before the coordinator reads the store, so everything downstream
    # sees healed ids, and before the platforms so entities land on the real device.
    #
    # Never allowed to prevent setup: a repair that hits an edge case should leave the
    # user with the symptoms it meant to fix, not with an integration that won't load.
    # (An early version raised out of here and did exactly that.)
    try:
        await devices.async_heal_split_device_ids(hass, entry, store)
    except Exception:
        _LOGGER.exception(
            "Could not repair device references after the Home Assistant 2026.8 "
            "device split; continuing setup. Please report this with the traceback"
        )

    coordinator = HomeKeeperCoordinator(hass, entry, store)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Provision/reconcile virtual asset devices and the tasks derived from wear
    # parts BEFORE forwarding platforms so the registry devices and per-task
    # entities exist when the platforms set up. The same applies to the tasks
    # mirroring ``device_class: problem`` binary sensors (when syncing is enabled).
    await devices.async_reconcile_assets(hass, entry, store)
    await store.reconcile_part_tasks()
    # Auto-buy reminders for low spare parts — reconcile before platforms forward so
    # any buy task's device-page entities exist at setup (no reload needed here).
    await store.reconcile_buy_tasks()
    problem_sync = ProblemSensorSync(hass, entry, coordinator)
    await problem_sync.async_initial_reconcile()
    coordinator.problem_sync = problem_sync
    # Declarative-companion reconciler materializes managed sensor tasks for every
    # stored spec against the current entity registry. Runs before platforms
    # forward so newly-created tasks' device-page entities are registered by the
    # time platforms fetch the task list.
    declarative_sync = DeclarativeCompanionSync(hass, entry, coordinator)
    await declarative_sync.async_initial_reconcile()
    coordinator.declarative_sync = declarative_sync
    await coordinator.async_request_refresh()

    await panel.async_register_panel(hass)
    await card.async_register_card(hass)
    manuals.async_register_http(hass)
    # Uploads spool to a temp file; a restart mid-upload would otherwise strand it.
    await manuals.async_cleanup_temp_uploads(hass)
    # Photo folders of tasks deleted while the files could not go (#399).
    await manuals.async_sweep_task_photos(hass, store.get_tasks())
    websocket_api.async_register(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Platforms have removed entities for deleted/excluded tasks; drop Home Keeper
    # from any device that no longer carries one of our entities so disabling Problem
    # Sensor Sync (or an exclusion) leaves no empty device card behind.
    #
    # The platforms are set up now, so a failure here must not fail the setup: an
    # entry in setup error keeps its platforms, and the next reload cannot set them
    # up again. A device that is not pruned is the worst result.
    try:
        await devices.async_detach_legacy_merged_devices(hass, entry)
        await devices.async_prune_orphaned_devices(hass, entry)
    except Exception:
        _LOGGER.exception("Could not remove Home Keeper from unused devices")

    # The services exist from ``async_setup``, so ask companions to (re-)announce
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
    # Same for the declarative-companion reconciler: a registry change / spec
    # edit may create or remove managed tasks (with per-task entities), so its
    # listener also triggers reloads.
    declarative_sync.async_start_listeners()
    # Sensor-based tasks: baseline the watcher's edge state / usage meters BEFORE
    # attaching it to the coordinator, so the first evaluation only reacts to genuine
    # transitions (an already-over-threshold sensor at boot does not arm). Then start
    # its live state listeners.
    sensor_watcher = SensorTaskWatcher(hass, entry, coordinator)
    await sensor_watcher.async_baseline()
    coordinator.sensor_watcher = sensor_watcher
    sensor_watcher.async_start_listeners()
    # The shopping-list mirror. Its listeners can start now, but the first pass
    # waits for HA to finish starting: the list it mirrors onto belongs to another
    # integration, which may not have set up yet, and a target that reads as
    # missing would leave the mirror with nothing to do.
    shopping_sync = ShoppingListSync(hass, entry, coordinator)
    coordinator.shopping_sync = shopping_sync
    shopping_sync.async_start_listeners()

    async def _mirror_when_started(_hass: HomeAssistant) -> None:
        await shopping_sync.async_initial_sync()

    entry.async_on_unload(async_at_started(hass, _mirror_when_started))
    # The to-do list syncs — profile-filtered tasks kept in step with existing
    # to-do lists. Same shape and same reasoning as the shopping list above: listeners
    # now, first pass once HA has started, because the lists belong to other
    # integrations that may not have set up yet.
    todo_list_sync = TodoListSync(hass, entry, coordinator)
    coordinator.todo_list_sync = todo_list_sync
    todo_list_sync.async_start_listeners()

    async def _todo_lists_when_started(_hass: HomeAssistant) -> None:
        await todo_list_sync.async_initial_sync()

    entry.async_on_unload(async_at_started(hass, _todo_lists_when_started))
    # Setup is complete: the refreshes above have baselined current overdue/due-soon
    # state silently, so start firing those events only for transitions from here on.
    coordinator.enable_transition_events()
    # The clock for time-based work, also with no entity and with polling off.
    entry.async_on_unload(coordinator.async_start_clock())
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


def _instance_base_url(hass: HomeAssistant) -> str:
    """The base URL to prepend to a signed path for the sign_*_url services.

    Prefers an externally-reachable URL: an MCP-connected agent (issue #161)
    typically isn't on the instance's own network, unlike the frontend, which
    already runs from wherever the browser loaded it and has no such preference.
    ``get_url``'s own internal-vs-external precedence still applies otherwise
    (this only nudges the preference, it doesn't require an external URL to
    exist), so a purely-internal instance keeps working exactly as before —
    the returned URL simply isn't reachable by an off-network caller, same as
    today.
    """
    try:
        return get_url(hass, prefer_external=True)
    except NoURLAvailableError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_instance_url",
        ) from err


def _register_services(hass: HomeAssistant) -> None:
    """Register Home Keeper services, once per Home Assistant run.

    Called from ``async_setup``. The services stay registered while the entry
    reloads or is disabled; a handler raises ``integration_not_loaded`` then.

    These are the automation-facing surface and the same store methods the panel
    and entities use. DEFERRED: a `home_keeper.contribute_task` service (plus the
    `SIGNAL_TASK_CONTRIBUTION` dispatcher) would let other integrations push tasks
    here without coupling — see IDEAS.md.
    """

    def _coordinator() -> HomeKeeperCoordinator:
        if (coord := find_coordinator(hass)) is None:
            # Reachable while the entry reloads, is disabled or failed to set up:
            # the services stay registered (see ``async_setup``). Surface a localized
            # HA error rather than a bare RuntimeError that shows as an opaque 500.
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="integration_not_loaded"
            )
        return coord

    def _ref(kind: str, resolver: Any, container: Any, key: str) -> str:
        """Turn an id-or-name service field into an id.

        Every ``*_id`` field accepts the object's name as well as its id, because
        the ids are uuid4s a person has no way to know — the same bargain HA core
        strikes with ``todo.update_item``'s "Item name or UID".

        A name that matches nothing is handed **back unchanged** so the caller's
        existing not-found path raises its own message quoting what the user
        actually typed. Only ambiguity is raised here: it has no existing path, and
        picking one of two identically named tasks for ``delete_task`` is the one
        outcome worse than an error.
        """
        try:
            return resolver(container, key)
        except AmbiguousName as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=f"{kind}_ambiguous",
                translation_placeholders={"name": key, "ids": ", ".join(err.ids)},
            ) from None
        except NotFound:
            return key

    def _task_ref(coord: HomeKeeperCoordinator, key: str) -> str:
        return _ref("task", resolve_task_id, coord.store.get_tasks(), key)

    def _asset_ref(coord: HomeKeeperCoordinator, key: str) -> str:
        return _ref("asset", resolve_asset_id, coord.store.get_assets(), key)

    def _part_ref(coord: HomeKeeperCoordinator, asset_id: str, key: str) -> str:
        """Resolve a part within *asset_id*, which must already be resolved."""
        asset = coord.store.get_assets().get(asset_id)
        return _ref("part", resolve_part_id, asset, key)

    def _document_ref(coord: HomeKeeperCoordinator, asset_id: str, key: str) -> str:
        """Resolve a document within *asset_id*, which must already be resolved."""
        asset = coord.store.get_assets().get(asset_id)
        return _ref("document", resolve_document_id, asset, key)

    def _with_parent_ref(coord: HomeKeeperCoordinator, data: dict) -> dict:
        """Resolve a ``parent_asset_id`` given as an appliance name, in place."""
        if parent := data.get("parent_asset_id"):
            data["parent_asset_id"] = _asset_ref(coord, parent)
        return data

    async def _caller_is_admin(call: ServiceCall) -> bool:
        """Whether *call* may see/do administrative things.

        ``context.user_id`` is ``None`` for an internal or automation-triggered call
        — there is no user to measure, and HA core treats that as trusted.
        """
        if (user_id := call.context.user_id) is None:
            return True
        user = await hass.auth.async_get_user(user_id)
        return user is not None and user.is_admin

    async def _verify_admin(call: ServiceCall) -> None:
        """Reject a non-admin caller of an administrative service.

        The websocket twins of these services are ``@websocket_api.require_admin``,
        and a service call is the same operation over the same authenticated
        connection — without this, ``call_service`` is a hole straight through that
        decorator. ``context.user_id`` is ``None`` for an internal or
        automation-triggered call (no user to check), which HA core treats as
        trusted; only a call that carries a user is measured against it.

        Raises HA core's ``Unauthorized`` rather than a translated
        ``ServiceValidationError``: this is an auth failure, not bad input, and the
        websocket/REST layers already map it to a 401/``unauthorized`` the frontend
        renders. See ``.amazonq/rules/architecture.md`` → "Privilege model".
        """
        if not await _caller_is_admin(call):
            raise Unauthorized(context=call.context)

    async def _verify_template_binding(call: ServiceCall) -> None:
        """Reject a non-admin caller who sets a ``template``-mode sensor binding.

        ``add_task`` and ``update_task`` are open to every signed-in user on purpose
        — ``docs/SECURITY.md`` says a non-admin can create and complete tasks. A
        ``template`` binding is the one part of a task that is not inert data: Home
        Keeper renders it, and a Jinja template reaches registry helpers
        (``device_attr``, ``area_id``, ``integration_entities``) that a non-admin
        cannot otherwise enumerate. So the mode alone is admin-only, and the rest of
        the service stays open.

        The websocket ``add_task`` and ``update_task`` commands apply the same rule
        in ``websocket_api._check_template_binding``, so neither path walks around
        the other.
        """
        sensor = call.data.get("sensor")
        if not isinstance(sensor, dict):
            return
        if sensor.get("mode") != SENSOR_MODE_TEMPLATE:
            return
        await _verify_admin(call)

    def _check_area(data: dict) -> None:
        if not devices.area_exists(hass, data.get("area_id")):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_area",
                translation_placeholders={"area_id": str(data.get("area_id"))},
            )

    # The store exceptions become localized service errors (see service_errors).
    _store_errors = store_errors

    def _require_asset(coord: HomeKeeperCoordinator, asset_id: str) -> dict:
        """The appliance *asset_id*, or the localized ``asset_not_found`` error."""
        if (asset := coord.store.get_asset(asset_id)) is None:
            raise service_error("asset_not_found", asset_id=asset_id)
        return asset

    def _require_known(kind: str, objects: Any, key: str) -> None:
        """Reject a delete for a name that matches no record (B02-7).

        ``_ref`` gives back a name that matches no record. A delete of an unknown
        id succeeds, because ``docs/INTEGRATING.md`` tells an integration to delete
        every id it stored, and the user can have deleted some of them already. A
        key that is not in the form of an id is a name, so a typo gets an error.
        """
        if key not in objects and not looks_like_id(key):
            raise service_error(f"{kind}_not_found", **{f"{kind}_id": key})

    async def handle_add_task(call: ServiceCall) -> dict[str, Any]:
        coord = _coordinator()
        await _verify_template_binding(call)
        _check_area(call.data)
        with _store_errors():
            task = await coord.store.add_task(dict(call.data))
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
        await _verify_template_binding(call)
        _check_area(call.data)
        data = dict(call.data)
        task_id = _task_ref(coord, data.pop("task_id"))
        existing = coord.store.get_task(task_id)
        before = entity_set_key(existing)
        with _store_errors(task_id=task_id):
            updated = await coord.store.update_task(task_id, data)
        # Only changes that alter which per-task entities exist (device link or
        # enabled state) need a full entry reload; otherwise a refresh suffices.
        if entity_set_key(updated) != before:
            await hass.config_entries.async_reload(coord.entry.entry_id)
        else:
            await coord.async_request_refresh()

    async def handle_delete_task(call: ServiceCall) -> None:
        coord = _coordinator()
        task_id = _task_ref(coord, call.data["task_id"])
        _require_known("task", coord.store.get_tasks(), task_id)
        existing = coord.store.get_task(task_id)
        with _store_errors():
            await coord.store.delete_task(task_id, force=call.data.get("force", False))
        # Reload only if the deleted task owned per-task entities that must be removed.
        if task_has_entities(existing):
            await hass.config_entries.async_reload(coord.entry.entry_id)
        else:
            await coord.async_request_refresh()

    async def handle_delete_orphaned_tasks(call: ServiceCall) -> dict[str, Any]:
        # Admin-only: it deletes tasks in bulk. Mirrors
        # ``ws_delete_orphaned_tasks``'s ``require_admin``.
        await _verify_admin(call)
        deleted = await async_delete_orphaned_tasks(hass, _coordinator())
        return {"deleted": deleted}

    def _completion_metadata(data: dict) -> dict[str, Any]:
        """Lift the per-completion metadata keys out of a service call's data."""
        return {k: data[k] for k in _COMPLETION_METADATA_KEYS if k in data}

    def _skip_metadata(data: dict) -> dict[str, Any]:
        """Lift the per-skip metadata keys out of a service call's data."""
        return {k: data[k] for k in _SKIP_METADATA_KEYS if k in data}

    async def handle_complete_task(call: ServiceCall) -> None:
        coord = _coordinator()
        task_id = _task_ref(coord, call.data["task_id"])
        with _store_errors(task_id=task_id):
            await coord.store.complete_task(
                task_id,
                call.data.get("completed_at"),
                origin=call.data.get("origin"),
                metadata=_completion_metadata(call.data),
            )
        # Completing an auto-buy task bumps stock (restocked) → its reminder is removed;
        # settle so those device entities are (un)registered (else a plain refresh).
        await coord.async_settle_buy_tasks()

    async def handle_update_completion(call: ServiceCall) -> None:
        coord = _coordinator()
        task_id = _task_ref(coord, call.data["task_id"])
        with _store_errors(task_id=task_id):
            await coord.store.update_completion(
                task_id,
                call.data["ts"],
                _completion_metadata(call.data),
            )
        await coord.async_request_refresh()

    async def handle_delete_completion(call: ServiceCall) -> None:
        coord = _coordinator()
        task_id = _task_ref(coord, call.data["task_id"])
        with _store_errors(task_id=task_id):
            await coord.store.delete_completion(
                task_id,
                call.data["ts"],
                origin=call.data.get("origin"),
            )
        # The undo can give stock back to a part and lift it above its reorder point,
        # which removes its Buy task; settle it (else a plain refresh).
        await coord.async_settle_buy_tasks()

    async def handle_move_completion(call: ServiceCall) -> None:
        coord = _coordinator()
        task_id = _task_ref(coord, call.data["task_id"])
        with _store_errors(task_id=task_id):
            await coord.store.move_completion(
                task_id,
                call.data["old_ts"],
                call.data["new_completed_at"].isoformat(),
            )
        await coord.async_request_refresh()

    async def handle_delete_archived_completion(call: ServiceCall) -> None:
        await _verify_admin(call)
        coord = _coordinator()
        asset_id = _asset_ref(coord, call.data["asset_id"])
        asset = _require_asset(coord, asset_id)
        # The task of an archived completion is deleted, so its name resolves
        # against the appliance's own history, not the live tasks (B21-3).
        task_id = _ref("task", resolve_archived_task_id, asset, call.data["task_id"])
        ts = call.data["ts"]
        if not has_archived_completion(asset, task_id, ts):
            raise service_error("archived_completion_not_found", task_id=task_id, ts=ts)
        with _store_errors(asset_id=asset_id):
            await coord.store.delete_archived_completion(asset_id, task_id, ts)
        await coord.async_request_refresh()

    async def handle_trigger_task(call: ServiceCall) -> None:
        coord = _coordinator()
        task_id = _task_ref(coord, call.data["task_id"])
        with _store_errors(task_id=task_id):
            await coord.store.trigger_task(task_id)
        # Arming only flips next_due (dormant <-> active); the per-task entity set is
        # unchanged, so a refresh is enough — no entry reload (mirrors complete_task).
        await coord.async_request_refresh()

    async def handle_set_task_meter(call: ServiceCall) -> None:
        coord = _coordinator()
        task_id = _task_ref(coord, call.data["task_id"])
        task = coord.store.get_tasks().get(task_id)
        if task is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="task_not_found",
                translation_placeholders={"task_id": task_id},
            )
        cfg = sensor_tasks.sensor_config(task)
        if cfg is None or cfg.get("mode") != SENSOR_MODE_USAGE:
            raise service_error("meter_requires_usage_task")
        baseline = call.data.get("baseline")
        if baseline is None:
            baseline = read_sensor_value(hass, cfg)
            if baseline is None:
                raise service_error("meter_has_no_reading")
        # The store rejects NaN and infinity (B02-8).
        with _store_errors(task_id=task_id):
            await coord.store.set_sensor_baseline(
                task_id, float(baseline), silent=False
            )
        await coord.async_request_refresh()

    async def handle_set_task_consumable(call: ServiceCall) -> None:
        coord = _coordinator()
        task_id = _task_ref(coord, call.data["task_id"])
        asset_key = call.data.get("asset_id") or None
        asset_id = _asset_ref(coord, asset_key) if asset_key else None
        part_key = call.data.get("part_id") or None
        part_id = (
            _part_ref(coord, asset_id, part_key) if part_key and asset_id else part_key
        )
        with _store_errors(task_id=task_id):
            await coord.store.set_task_consumable(
                task_id,
                asset_id,
                part_id,
                quantity=call.data.get("quantity"),
            )
        # Linking only rewrites the task's source; the per-task entity set is
        # unchanged, so a refresh is enough — no entry reload.
        await coord.async_request_refresh()

    async def handle_snooze_task(call: ServiceCall) -> None:
        coord = _coordinator()
        task_id = _task_ref(coord, call.data["task_id"])
        # ``hours`` and ``until`` are mutually exclusive (see SNOOZE_TASK_SCHEMA), so
        # at most one is present; neither means the historical default of a day. The
        # default lives here rather than on the field because a schema default would
        # fill ``hours`` in even when the caller passed ``until``, and vol.Exclusive
        # would then reject its own default.
        if (until := call.data.get("until")) is None:
            # The hours count from the due date when that is later than now, so a
            # snooze never moves a task earlier (F10-2).
            now = dt_util.now()
            task = coord.store.get_task(task_id)
            base = recurrence.snooze_from(task, now) if task else now
            until = base + timedelta(hours=call.data.get("hours", 24))
        elif until.tzinfo is None:
            # ``cv.datetime`` parses an offset-less string naively; qualify it with
            # HA's zone so ``next_due`` is never stored naive (see apply_completion).
            until = until.replace(tzinfo=dt_util.now().tzinfo)
        with _store_errors(task_id=task_id):
            await coord.store.snooze_task(
                task_id, until, origin=call.data.get("origin")
            )
        # Snooze only moves next_due (dormant <-> active timing); the per-task entity
        # set is unchanged, so a refresh is enough — no entry reload.
        await coord.async_request_refresh()

    async def handle_skip_task(call: ServiceCall) -> None:
        coord = _coordinator()
        task_id = _task_ref(coord, call.data["task_id"])
        with _store_errors(task_id=task_id):
            await coord.store.skip_task(
                task_id,
                origin=call.data.get("origin"),
                metadata=_skip_metadata(call.data),
            )
        await coord.async_request_refresh()

    async def handle_set_due_today(call: ServiceCall) -> None:
        coord = _coordinator()
        task_id = _task_ref(coord, call.data["task_id"])
        with _store_errors(task_id=task_id):
            await coord.store.set_due_today(task_id, origin=call.data.get("origin"))
        # Pull-forward only moves next_due (like snooze); the per-task entity set is
        # unchanged, so a refresh is enough — no entry reload.
        await coord.async_request_refresh()

    async def handle_update_skip(call: ServiceCall) -> None:
        coord = _coordinator()
        task_id = _task_ref(coord, call.data["task_id"])
        with _store_errors(task_id=task_id):
            await coord.store.update_skip(
                task_id, call.data["ts"], _skip_metadata(call.data)
            )
        await coord.async_request_refresh()

    async def handle_delete_skip(call: ServiceCall) -> None:
        coord = _coordinator()
        task_id = _task_ref(coord, call.data["task_id"])
        with _store_errors(task_id=task_id):
            await coord.store.delete_skip(task_id, call.data["ts"])
        await coord.async_request_refresh()

    async def handle_move_skip(call: ServiceCall) -> None:
        coord = _coordinator()
        task_id = _task_ref(coord, call.data["task_id"])
        with _store_errors(task_id=task_id):
            await coord.store.move_skip(
                task_id, call.data["old_ts"], call.data["new_ts"].isoformat()
            )
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
        await _verify_admin(call)
        coord = _coordinator()
        _check_area(call.data)
        with _store_errors():
            await coord.store.add_asset(_with_parent_ref(coord, dict(call.data)))
        await devices.async_apply_asset_change(hass, coord.entry, coord.store)

    async def handle_update_asset(call: ServiceCall) -> None:
        await _verify_admin(call)
        coord = _coordinator()
        _check_area(call.data)
        data = dict(call.data)
        asset_id = _asset_ref(coord, data.pop("asset_id"))
        _with_parent_ref(coord, data)
        with _store_errors(asset_id=asset_id):
            await coord.store.update_asset(asset_id, data)
        await devices.async_apply_asset_change(hass, coord.entry, coord.store)

    async def handle_update_managed_asset(call: ServiceCall) -> None:
        await _verify_admin(call)
        coord = _coordinator()
        data = dict(call.data)
        asset_id = _asset_ref(coord, data["asset_id"])
        before = dict(coord.store.get_asset(asset_id) or {})
        with _store_errors(asset_id=asset_id):
            updated = await coord.store.update_managed_asset(
                asset_id,
                name=data.get("name"),
                parts=data.get("parts"),
            )
        if all(updated.get(key) == value for key, value in before.items()):
            # The owner restated what is already stored. Its reconciler calls this on
            # a schedule, and the follow-up below reloads the config entry, so a
            # no-op write must stay one.
            return
        # The same follow-up ``update_asset`` does: a renamed appliance re-titles its
        # device, and a new or changed part re-derives its wear/buy tasks.
        await devices.async_apply_asset_change(hass, coord.entry, coord.store)

    async def handle_delete_asset(call: ServiceCall) -> None:
        await _verify_admin(call)
        coord = _coordinator()
        asset_id = _asset_ref(coord, call.data["asset_id"])
        _require_known("asset", coord.store.get_assets(), asset_id)
        with _store_errors(asset_id=asset_id):
            await _delete_asset(
                hass, coord, asset_id, force=call.data.get("force", False)
            )

    async def handle_archive_asset(call: ServiceCall) -> None:
        await _verify_admin(call)
        coord = _coordinator()
        asset_id = _asset_ref(coord, call.data["asset_id"])
        asset = await coord.store.archive_asset(asset_id)
        if asset is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="asset_not_found",
                translation_placeholders={"asset_id": asset_id},
            )

    async def handle_restore_asset(call: ServiceCall) -> None:
        await _verify_admin(call)
        coord = _coordinator()
        asset_id = _asset_ref(coord, call.data["asset_id"])
        asset = await coord.store.restore_asset(asset_id)
        if asset is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="asset_not_found",
                translation_placeholders={"asset_id": asset_id},
            )

    async def handle_list_assets(call: ServiceCall) -> dict[str, Any]:
        # The service twin of ``ws_get_assets``, and gated the same way: a non-admin
        # gets the card-link projection, not the costs and serial numbers
        # ``export_appliance_report`` is admin-only to protect. Without this the
        # projection on the websocket read would be trivially side-stepped by
        # calling the service instead.
        coord = _coordinator()
        assets = coord.store.list_assets()
        if not await _caller_is_admin(call):
            assets = card_projection(assets)
        return {"assets": assets}

    async def handle_adjust_part_stock(call: ServiceCall) -> dict[str, Any]:
        await _verify_admin(call)
        coord = _coordinator()
        asset_id = _asset_ref(coord, call.data["asset_id"])
        part_id = _part_ref(coord, asset_id, call.data["part_id"])
        # The coordinator settles the buy tasks and the stock entities.
        with _store_errors(asset_id=asset_id, part_id=part_id):
            report = await coord.async_adjust_part_stock(
                asset_id, part_id, call.data["delta"]
            )
        # The new count and the delta really applied: the count stops at zero, so a
        # caller that undoes its change later needs ``applied_delta``, not its own.
        return report

    async def handle_remove_part_file(call: ServiceCall) -> None:
        await _verify_admin(call)
        coord = _coordinator()
        asset_id = _asset_ref(coord, call.data["asset_id"])
        part_id = _part_ref(coord, asset_id, call.data["part_id"])
        with _store_errors(asset_id=asset_id, part_id=part_id):
            await coord.store.remove_part_file(asset_id, part_id)

    async def handle_add_asset_document(call: ServiceCall) -> None:
        await _verify_admin(call)
        coord = _coordinator()
        asset_id = _asset_ref(coord, call.data["asset_id"])
        document = dict(call.data["document"])
        # Files are uploaded through the HTTP view; the service only adds links.
        if document.get("kind", "link") != "link":
            raise service_error("link_documents_only")
        document["kind"] = "link"
        with _store_errors(asset_id=asset_id):
            await coord.store.add_asset_document(asset_id, document)
        # Documents touch no device/entity/task; the store already saved and fired the
        # event, so no device reconcile or entry reload is needed.

    async def handle_remove_asset_document(call: ServiceCall) -> None:
        await _verify_admin(call)
        coord = _coordinator()
        asset_id = _asset_ref(coord, call.data["asset_id"])
        _require_asset(coord, asset_id)
        document_id = _document_ref(coord, asset_id, call.data["document_id"])
        # The appliance exists, so a KeyError is for the document (B02-6).
        with _store_errors(document_id=document_id):
            await coord.store.remove_asset_document(asset_id, document_id)

    async def handle_update_asset_document(call: ServiceCall) -> None:
        await _verify_admin(call)
        coord = _coordinator()
        asset_id = _asset_ref(coord, call.data["asset_id"])
        _require_asset(coord, asset_id)
        document_id = _document_ref(coord, asset_id, call.data["document_id"])
        # The appliance exists, so a KeyError is for the document (B02-6).
        with _store_errors(document_id=document_id):
            await coord.store.update_asset_document(
                asset_id,
                document_id,
                dict(call.data["changes"]),
            )
        # Documents touch no device/entity/task; the store save + event is the job.

    async def handle_sign_document_url(call: ServiceCall) -> dict[str, Any]:
        """Mint a short-lived signed URL for a file document (issue #161).

        Unlike ``add_asset_document``/``remove_asset_document`` this reaches actual
        file bytes, not metadata: the missing piece for an MCP-connected agent (or
        any caller with no interactive browser session) to download a manual or
        receipt rather than only list that it exists.
        """
        coord = _coordinator()
        asset_id = _asset_ref(coord, call.data["asset_id"])
        document_id = _document_ref(coord, asset_id, call.data["document_id"])
        signed = await manuals.async_sign_document_url(
            hass,
            asset_id,
            document_id,
            ttl=manuals.SERVICE_DOCUMENT_URL_TTL,
        )
        if signed is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_document",
                translation_placeholders={"document_id": document_id},
            )
        return {
            "url": f"{_instance_base_url(hass)}{signed}",
            "expires_in": int(manuals.SERVICE_DOCUMENT_URL_TTL.total_seconds()),
        }

    async def handle_sign_part_file_url(call: ServiceCall) -> dict[str, Any]:
        """Mint a short-lived signed URL for a part's attached file (issue #161).

        See ``handle_sign_document_url``: same rationale, for a part's single file
        slot instead of an asset document.
        """
        coord = _coordinator()
        asset_id = _asset_ref(coord, call.data["asset_id"])
        part_id = _part_ref(coord, asset_id, call.data["part_id"])
        signed = await manuals.async_sign_part_file_url(
            hass,
            asset_id,
            part_id,
            ttl=manuals.SERVICE_DOCUMENT_URL_TTL,
        )
        if signed is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_part_file",
            )
        return {
            "url": f"{_instance_base_url(hass)}{signed}",
            "expires_in": int(manuals.SERVICE_DOCUMENT_URL_TTL.total_seconds()),
        }

    # The task photo services are open, like ``update_task``: a photo is task data.
    async def handle_remove_task_photo(call: ServiceCall) -> None:
        coord = _coordinator()
        task_id = _task_ref(coord, call.data["task_id"])
        _require_known("task", coord.store.get_tasks(), task_id)
        # The task exists, so a KeyError is for the photo (B02-6).
        with _store_errors(photo_id=call.data["photo_id"]):
            await coord.store.remove_task_photo(task_id, call.data["photo_id"])

    async def handle_set_task_photo_cover(call: ServiceCall) -> None:
        coord = _coordinator()
        task_id = _task_ref(coord, call.data["task_id"])
        _require_known("task", coord.store.get_tasks(), task_id)
        with _store_errors(photo_id=call.data["photo_id"]):
            await coord.store.set_task_photo_cover(task_id, call.data["photo_id"])

    async def handle_sign_task_photo_url(call: ServiceCall) -> dict[str, Any]:
        """Mint a short-lived signed URL for a task photo.

        For a notification that shows the photo, or an agent that reads it. Not
        admin-only, the same as ``sign_document_url``.
        """
        coord = _coordinator()
        task_id = _task_ref(coord, call.data["task_id"])
        _require_known("task", coord.store.get_tasks(), task_id)
        signed = await manuals.async_sign_task_photo_url(
            hass,
            task_id,
            call.data["photo_id"],
            thumb=call.data["thumbnail"],
            ttl=manuals.SERVICE_DOCUMENT_URL_TTL,
        )
        if signed is None:
            raise service_error("unknown_task_photo", photo_id=call.data["photo_id"])
        return {
            "url": f"{_instance_base_url(hass)}{signed}",
            "expires_in": int(manuals.SERVICE_DOCUMENT_URL_TTL.total_seconds()),
        }

    async def handle_export_appliance_report(call: ServiceCall) -> dict[str, Any]:
        # Admin-only: the report carries every asset's serial numbers, purchase costs
        # and value totals. Mirrors ``ws_export_appliance_report``'s ``require_admin``.
        await _verify_admin(call)
        coord = _coordinator()
        report = appliance_report.build_report(
            coord.store.list_assets(),
            area_names=devices.area_names(hass),
            today=dt_util.now().date(),
        )
        # Localize the CSV like ``ws_export_appliance_report`` does — one report,
        # one language.
        csv = appliance_report.report_to_csv(report, lang=hass.config.language)
        return {"report": report, "csv": csv}

    async def handle_export_data(call: ServiceCall) -> dict[str, Any]:
        # Admin-only: the document is every task, note, serial number and cost in
        # the store. Mirrors ``ws_export_data``'s ``require_admin``.
        await _verify_admin(call)
        return await async_export_document(hass, _coordinator(), dict(call.data))

    async def handle_import_data(call: ServiceCall) -> dict[str, Any]:
        # Admin-only: it writes tasks and appliances wholesale. Mirrors
        # ``ws_import_data``'s ``require_admin``.
        await _verify_admin(call)
        with _store_errors():
            return await async_import_document(hass, _coordinator(), dict(call.data))

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
        DOMAIN,
        "delete_orphaned_tasks",
        handle_delete_orphaned_tasks,
        vol.Schema({}),
        supports_response=SupportsResponse.OPTIONAL,
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
        DOMAIN, "move_completion", handle_move_completion, MOVE_COMPLETION_SCHEMA
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
        DOMAIN, "set_task_meter", handle_set_task_meter, SET_TASK_METER_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "snooze_task", handle_snooze_task, SNOOZE_TASK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "skip_task", handle_skip_task, SKIP_TASK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        "set_due_today",
        handle_set_due_today,
        SET_DUE_TODAY_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, "update_skip", handle_update_skip, UPDATE_SKIP_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "delete_skip", handle_delete_skip, DELETE_SKIP_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "move_skip", handle_move_skip, MOVE_SKIP_SCHEMA
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
        DOMAIN,
        "update_managed_asset",
        handle_update_managed_asset,
        UPDATE_MANAGED_ASSET_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, "delete_asset", handle_delete_asset, DELETE_ASSET_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "archive_asset", handle_archive_asset, ASSET_ID_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "restore_asset", handle_restore_asset, ASSET_ID_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        "list_assets",
        handle_list_assets,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "adjust_part_stock",
        handle_adjust_part_stock,
        ADJUST_PART_STOCK_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
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
    hass.services.async_register(
        DOMAIN,
        "sign_document_url",
        handle_sign_document_url,
        SIGN_DOCUMENT_URL_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "sign_part_file_url",
        handle_sign_part_file_url,
        SIGN_PART_FILE_URL_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "remove_task_photo", handle_remove_task_photo, TASK_PHOTO_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "set_task_photo_cover", handle_set_task_photo_cover, TASK_PHOTO_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        "sign_task_photo_url",
        handle_sign_task_photo_url,
        SIGN_TASK_PHOTO_URL_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    async def handle_set_options(call: ServiceCall) -> None:
        # Admin-only: mutating config-entry options is administration, which HA core
        # reserves for admins. Mirrors ``ws_set_options``'s ``require_admin``.
        await _verify_admin(call)
        coord = _coordinator()
        try:
            await options.async_set_options(hass, coord.entry, dict(call.data))
        except options.ProfileInUseError as err:
            # Bad input, not a failure: the call removes a profile that a notification
            # in the same saved document still names. Send both lists so the message
            # says which profile and which notifications.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="profile_in_use",
                translation_placeholders={
                    "profiles": err.profiles,
                    "notifications": err.notifications,
                },
            ) from err

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

    async def handle_add_declarative_companion(
        call: ServiceCall,
    ) -> dict[str, Any]:
        """Create a declarative-companion spec.

        Admin-only: a declarative companion creates managed tasks tied to the
        config entry (deletion-protected) and dispatches an entry reload, both
        of which are administration. Mirrors ``ws_add_declarative_companion``.
        """
        await _verify_admin(call)
        coord = _coordinator()
        with declarative_companion_errors():
            spec = await coord.store.async_add_declarative_companion(dict(call.data))
        await declarative_companion_sync.async_settle(coord)
        return {"companion": spec}

    async def handle_update_declarative_companion(
        call: ServiceCall,
    ) -> dict[str, Any]:
        await _verify_admin(call)
        coord = _coordinator()
        data = dict(call.data)
        spec_id = data.pop("id")
        with declarative_companion_errors(spec_id=spec_id):
            spec = await coord.store.async_update_declarative_companion(spec_id, data)
        await declarative_companion_sync.async_settle(coord)
        return {"companion": spec}

    async def handle_delete_declarative_companion(call: ServiceCall) -> None:
        await _verify_admin(call)
        coord = _coordinator()
        removed = await coord.store.async_delete_declarative_companion(call.data["id"])
        # The pass the delete started runs to its end before the reload replaces
        # the store it writes.
        await declarative_companion_sync.async_settle(coord)
        # B03-2: reload when a removed task had device-page entities, as delete_task
        # does, because only the platform setup prunes them.
        if removed:
            await hass.config_entries.async_reload(coord.entry.entry_id)

    async def handle_list_declarative_companions(
        call: ServiceCall,
    ) -> dict[str, Any]:
        coord = _coordinator()
        return {
            "companions": list(coord.store.get_declarative_companions().values()),
        }

    hass.services.async_register(
        DOMAIN,
        "export_appliance_report",
        handle_export_appliance_report,
        EXPORT_APPLIANCE_REPORT_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "export_data",
        handle_export_data,
        EXPORT_DATA_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "import_data",
        handle_import_data,
        IMPORT_DATA_SCHEMA,
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
    # Declarative-companion CRUD. Schemas kept minimal (dict pass-through) here
    # because the pure normalizer owns every field-level validation. Service
    # docstrings + services.yaml describe the spec shape.
    hass.services.async_register(
        DOMAIN,
        "add_declarative_companion",
        handle_add_declarative_companion,
        schema=vol.Schema({}, extra=vol.ALLOW_EXTRA),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "update_declarative_companion",
        handle_update_declarative_companion,
        schema=vol.Schema(
            {vol.Required("id"): cv.string},
            extra=vol.ALLOW_EXTRA,
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "delete_declarative_companion",
        handle_delete_declarative_companion,
        schema=vol.Schema({vol.Required("id"): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        "list_declarative_companions",
        handle_list_declarative_companions,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )


async def _delete_asset(
    hass: HomeAssistant,
    coord: HomeKeeperCoordinator,
    asset_id: str,
    *,
    force: bool = False,
) -> None:
    """Delete an asset, remove its virtual device, and detach orphaned tasks.

    Shared by the service and websocket handlers so both clean up identically.
    ``force`` bypasses a managed appliance's deletion protection.
    """
    asset = await coord.store.delete_asset(asset_id, force=force)
    if asset is None:
        return
    removed_device_id = await devices.async_remove_asset_device(hass, asset)
    if removed_device_id:
        await coord.store.detach_tasks_from_device(removed_device_id)
    await hass.config_entries.async_reload(coord.entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        # A re-enabled entry baselines in silence, as after a restart (B18-6).
        discard_edge_state_if_disabled(hass, entry)
        # A pass that started before the unload still holds this store. After a
        # reload its save would write the old snapshot over the new store's file, so
        # the store refuses every later save (X02-2).
        coordinator = getattr(entry, "runtime_data", None)
        if coordinator is not None:
            coordinator.store.close()
    # The services are not removed here (B02-1). ``async_setup`` registers them once
    # for the Home Assistant run, as Home Assistant's ``action-setup`` rule asks, and
    # a handler answers ``integration_not_loaded`` while no entry is loaded. Most
    # unloads are the first half of a reload, and removing the services made each
    # call during the reload fail with "action not found".
    #
    # Gate on *loaded* entries, not ``async_entries``: HA removes the entry from the
    # registry only *after* this unload returns (and a disabled entry stays
    # registered). ``async_loaded_entries`` excludes the entry currently unloading.
    #
    # The sidebar panel is deliberately *not* dropped on an ordinary unload,
    # because most unloads are the first half of a reload — and a reload is
    # routine here (saving options, a synced problem sensor appearing, a purged
    # one-off). Removing the panel deletes ``home-keeper`` from ``hass.panels``
    # for as long as setup takes, and Home Assistant's ``partial-panel-resolver``
    # answers a panel disappearing under an open page by navigating to the
    # default one: #247's reporter was thrown back to their dashboard "every 10
    # seconds or so". Nothing about the registration is entry-scoped — it names a
    # static module URL served for the whole HA run and is re-registered
    # identically — so leaving it up costs nothing. ``card.py`` takes the same
    # stance, for the same reason.
    #
    # A *disabled* entry is the one unload that isn't coming back on its own, and
    # HA sets ``disabled_by`` before unloading, so the sidebar entry still goes
    # away when the user turns the integration off. Deleting it is handled in
    # ``async_remove_entry``.
    #
    # The one case this trades away: when the *setup* half of a reload fails, the
    # sidebar entry now stays up against an entry in ``SETUP_ERROR``/``SETUP_RETRY``
    # instead of vanishing. That is the better half of the trade — every websocket
    # command already answers ``integration_not_loaded`` when it finds no loaded
    # coordinator (see ``websocket_api._not_loaded``), so the panel reports the
    # real state, and HA is usually about to retry setup anyway. Dropping the
    # sidebar entry instead would hide that Home Keeper is even installed.
    if (
        unloaded
        and entry.disabled_by is not None
        and not hass.config_entries.async_loaded_entries(DOMAIN)
    ):
        panel.async_unregister_panel(hass)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove all Home Keeper data when the integration is deleted.

    Virtual asset devices (and per-task self-owned devices) are tied to this config
    entry, so Home Assistant removes them automatically. Here we additionally drop
    our stored tasks/assets document and the uploaded-documents blob tree so no
    residue is left behind.
    """
    # Neither the sidebar panel nor the card's Lovelace resource is entry-scoped
    # state, so HA won't reap either. Removal — not unload, which also runs on every
    # reload — is the one point where dropping them is right; left behind, both point
    # at a backend that is never coming back.
    panel.async_unregister_panel(hass)
    await card.async_unregister_card_resource(hass)
    discard_edge_state(hass, entry.entry_id)
    async_discard_new_tasks(hass, entry.entry_id)
    store = HomeKeeperStore(hass)
    await store.async_remove()
    await manuals.async_delete_all_documents(hass)
