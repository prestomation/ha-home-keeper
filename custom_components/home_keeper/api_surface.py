"""The single index of every surface an integrator can build on.

Home Keeper's public API is spread across four registries that have no reason to
know about each other: services registered in ``__init__.py``, bus events named in
``const.py`` with payloads built in ``events.py``, device triggers in
``device_trigger.py``, and entity platforms in ``const.PLATFORMS``. Nothing tied
them together, so a surface could be added in one place and forgotten everywhere
else — which is exactly how ``set_task_meter`` shipped registered but absent from
the teardown list.

This module is that tie. It declares every surface once; the runtime *consumes* it
(``__init__.async_unload_entry`` iterates :data:`SERVICE_NAMES`,
``device_trigger`` builds its maps from :func:`triggers_for`), the generator
``ci/generate_api_docs.py`` renders the Developer Guide reference from it, and
``tests/unit/test_api_surface.py`` fails when the source and the model disagree.

**It declares names and structure only.** Every human-readable string that Home
Assistant already localizes — service and field labels, trigger labels, entity
names, option labels, error messages — is resolved at generation time from
``services.yaml`` / ``strings.json``, so the reference and the Home Assistant UI
read from one source and cannot say different things. Never restate that prose
here. The one exception is :attr:`EventSpec.summary`: a bus event has no Home
Assistant string source, so its one-line "fires when" lives in this table.

Pure, and deliberately *light*: it imports nothing from Home Assistant and
nothing from the integration beyond ``const``, so ``tests/conftest.py`` can load
it alongside the rest of the pure core and ``ci/generate_api_docs.py`` can import
it on a docs runner that has none of the integration's dependencies installed.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import const

# ── Descriptors ──────────────────────────────────────────────────────────────
#
# Every table below is a ``tuple``, never a ``set``. The generator renders them in
# order, so set iteration leaking in here would make the generated page differ
# between runs.


@dataclass(frozen=True, slots=True)
class Field:
    """One key in an event payload or entity attribute map."""

    name: str
    type: str = ""
    """Rendered verbatim (``"str | None"``, ``"list[dict]"``); never parsed."""
    note: str = ""


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    """A ``home_keeper.*`` action.

    ``name`` is the one key shared by the ``hass.services.async_register`` call,
    ``services.yaml`` and ``strings.json``'s ``services`` section — all three are
    checked against it.
    """

    name: str
    admin_only: bool = False
    response: str = "none"
    """``"none"`` | ``"optional"`` | ``"only"``, mirroring ``SupportsResponse``."""


@dataclass(frozen=True, slots=True)
class EventSpec:
    """A bus event Home Keeper fires, or a Home Assistant event it listens for."""

    name: str
    """The ``const`` attribute's *value*, referenced — never a re-typed literal."""
    const_name: str
    """The ``const`` attribute holding it, so the model is pinned to ``const.py``."""
    direction: str
    """``"fired"`` | ``"listened"``."""
    payload: str
    """Which spine in :data:`PAYLOAD_SPINES`, or ``"none"``."""
    summary: str = ""
    """The "fires when" one-liner. Required for every fired event."""
    extra: tuple[Field, ...] = ()
    """Per-event keys merged onto the spine."""


@dataclass(frozen=True, slots=True)
class DeviceTriggerSpec:
    """A device-automation trigger wrapping one bus event."""

    type: str
    """Key under ``strings.json`` → ``device_automation.trigger_type``."""
    event: str
    scope: str
    """``"task"`` | ``"asset"`` — which devices offer it."""


@dataclass(frozen=True, slots=True)
class EntityPlatformSpec:
    """One entity platform and the state attributes its entities expose."""

    platform: str
    translation_keys: tuple[str, ...] = ()
    """Keys under ``strings.json`` → ``entity.<platform>``; empty when the platform
    names its entities with ``_attr_name`` instead."""
    attributes: tuple[Field, ...] = ()


@dataclass(frozen=True, slots=True)
class WebsocketSpec:
    """A panel websocket command.

    Internal: a UI-latency optimization over the equivalent service, never a
    substitute for it (see ``.amazonq/rules/architecture-and-code.md``). Modelled
    and tested so it can't drift; deliberately not published in the reference.
    """

    type: str
    admin_only: bool = False
    service: str | None = None
    """The ``home_keeper.*`` service it delegates to, when there is one."""


@dataclass(frozen=True, slots=True)
class HttpViewSpec:
    """An HTTP route the integration registers. Internal, like the websocket."""

    name: str
    url: str
    methods: tuple[str, ...]
    requires_auth: bool = True


@dataclass(frozen=True, slots=True)
class OptionSpec:
    """A config-entry option key."""

    key: str
    in_flow: bool
    """Whether the options-flow form renders it (the rest are panel-only)."""


@dataclass(frozen=True, slots=True)
class SurfaceKind:
    """One of Home Assistant's integration surfaces, and Home Keeper's stance on it.

    The point of this table is the rows that say *no*. Listing only what we offer
    can't tell you what we forgot; listing the whole space, with a reason attached
    to every absence, can. Adding a new kind of surface means adding a row here
    first.
    """

    kind: str
    status: str
    """``"published"`` | ``"internal"`` | ``"not_applicable"`` | ``"deferred"``."""
    note: str
    """One sentence. Required."""


STATUSES = ("published", "internal", "not_applicable", "deferred")


# ── Services ─────────────────────────────────────────────────────────────────

SERVICES: tuple[ServiceSpec, ...] = (
    ServiceSpec("add_task", response="optional"),
    ServiceSpec("update_task"),
    ServiceSpec("delete_task"),
    ServiceSpec("complete_task"),
    ServiceSpec("update_completion"),
    ServiceSpec("delete_completion"),
    ServiceSpec("move_completion"),
    ServiceSpec("delete_archived_completion"),
    ServiceSpec("trigger_task"),
    ServiceSpec("set_task_meter"),
    ServiceSpec("snooze_task"),
    ServiceSpec("skip_task"),
    ServiceSpec("set_task_consumable"),
    ServiceSpec("notify", response="optional"),
    ServiceSpec("list_tasks", response="only"),
    ServiceSpec("list_profiles", response="only"),
    ServiceSpec("add_asset", admin_only=True),
    ServiceSpec("update_asset", admin_only=True),
    ServiceSpec("delete_asset", admin_only=True),
    ServiceSpec("archive_asset", admin_only=True),
    ServiceSpec("restore_asset", admin_only=True),
    ServiceSpec("list_assets", response="only"),
    ServiceSpec("adjust_part_stock", admin_only=True),
    ServiceSpec("remove_part_file", admin_only=True),
    ServiceSpec("add_asset_document", admin_only=True),
    ServiceSpec("remove_asset_document", admin_only=True),
    ServiceSpec("update_asset_document", admin_only=True),
    ServiceSpec("sign_document_url", response="only"),
    ServiceSpec("sign_part_file_url", response="only"),
    ServiceSpec("export_inventory", admin_only=True, response="only"),
    ServiceSpec("set_options", admin_only=True),
    ServiceSpec("register_companion", response="optional"),
    ServiceSpec("list_companions", response="only"),
)

SERVICE_NAMES: tuple[str, ...] = tuple(spec.name for spec in SERVICES)
"""Every registered service name, in registration order.

``__init__.async_unload_entry`` iterates this rather than a second hand-written
tuple. That second tuple is how ``set_task_meter`` went unregistered-on-unload:
a list nobody derives is a list somebody forgets.
"""


# ── Event payloads ───────────────────────────────────────────────────────────
#
# One entry per builder in ``events.py``. ``test_api_surface`` probes those
# builders and compares key order against these tuples, so a field added to a
# payload without being described here fails rather than shipping undocumented.

PAYLOAD_SPINES: dict[str, tuple[Field, ...]] = {
    "task": (
        Field("task_id", "str"),
        Field("name", "str"),
        Field(
            "device_id",
            "str | None",
            "the task's registry device id, or None when it's a standalone task "
            "(its entities then live on a self-owned device)",
        ),
        Field("area_id", "str | None"),
        Field(
            "recurrence_type", "str", "floating / fixed / one-off / triggered / sensor"
        ),
        Field(
            "next_due",
            "str | None",
            "ISO; None for a dormant triggered/sensor task or a completed one-off",
        ),
        Field("enabled", "bool"),
        Field(
            "labels",
            "list[str]",
            "HA label-registry ids attached to the task (empty when none)",
        ),
        Field("source", "dict | None", "opaque provenance, echoed verbatim"),
        Field("managed_by", "dict | None", "well-known ownership block, or None"),
        Field(
            "task_chips",
            "list[dict]",
            "integration-provided metadata chips; each has label, optional icon "
            "(mdi: name) and optional url (http(s)://)",
        ),
        Field(
            "tag_id",
            "str | None",
            "the HA tag whose scan completes the task, or None when none is linked",
        ),
    ),
    "stock": (
        Field("asset_id", "str"),
        Field("asset_name", "str"),
        Field("device_id", "str | None"),
        Field("part_id", "str"),
        Field("part_name", "str"),
        Field("part_number", "str"),
        Field("vendor", "str"),
        Field("stock", "float", "on-hand quantity; can be fractional"),
        Field("reorder_at", "float", "the low-stock threshold"),
        Field(
            "unit",
            "str",
            'what the part counts itself in ("ml", "bottles"), or "" for whole spares',
        ),
    ),
    "asset": (
        Field("asset_id", "str"),
        Field("asset_name", "str"),
        Field(
            "device_id",
            "str | None",
            "None until a virtual appliance's device is provisioned",
        ),
    ),
    "companion": (
        Field("domain", "str"),
        Field("name", "str"),
        Field("status", "str", "connected / suggested"),
        Field(
            "config_entry_id",
            "str | None",
            "the companion's config entry, for a connected companion",
        ),
        Field(
            "upstream_domain",
            "str | None",
            "the detected upstream, for a catalog-suggested glue",
        ),
    ),
}


_CHANGED_FIELDS = Field(
    "changed_fields", "list[str]", "which stored fields actually changed"
)


# ── Events ───────────────────────────────────────────────────────────────────
#
# ``summary`` is the "fires when" line the Developer Guide renders. It lives here
# rather than in docs/EVENTS.md because that table and this list were two
# hand-maintained copies of one fact; EVENTS.md now carries the semantics prose
# (edge-triggering, startup baselining, worked automations) and nothing else.

EVENTS: tuple[EventSpec, ...] = (
    EventSpec(
        const.EVENT_TASK_CREATED,
        "EVENT_TASK_CREATED",
        "fired",
        "task",
        "a task is created, from the panel, a service, a contributing integration, "
        "or as a wear-part task generated from an appliance",
    ),
    EventSpec(
        const.EVENT_TASK_UPDATED,
        "EVENT_TASK_UPDATED",
        "fired",
        "task",
        "a task actually changes",
        extra=(_CHANGED_FIELDS,),
    ),
    EventSpec(
        const.EVENT_TASK_DELETED,
        "EVENT_TASK_DELETED",
        "fired",
        "task",
        "a task is removed, directly or because its appliance or part was",
    ),
    EventSpec(
        const.EVENT_TASK_COMPLETED,
        "EVENT_TASK_COMPLETED",
        "fired",
        "task",
        "a task is completed from any surface: the to-do checkbox, a device button, "
        "a tag scan, or complete_task",
        extra=(
            Field("completed_at", "str", "ISO completion time"),
            Field("origin", "str | None", "the opaque caller marker"),
            Field("note", "str", "present only when the completion recorded one"),
            Field("cost", "float", "present only when the completion recorded one"),
            Field("photo", "str", "present only when the completion recorded one"),
            Field("who", "str", "present only when the completion recorded one"),
            Field(
                "reading",
                "float",
                "the bound sensor's value, captured for a usage/threshold sensor task",
            ),
        ),
    ),
    EventSpec(
        const.EVENT_TASK_UNCOMPLETED,
        "EVENT_TASK_UNCOMPLETED",
        "fired",
        "task",
        "a completion is undone and next_due is re-derived; undoing a timestamp that "
        "isn't in the history changes nothing and fires nothing",
        extra=(
            Field("ts", "str", "the removed completion's timestamp"),
            Field("origin", "str | None", "the marker the caller passed"),
        ),
    ),
    EventSpec(
        const.EVENT_TASK_COMPLETION_UPDATED,
        "EVENT_TASK_COMPLETION_UPDATED",
        "fired",
        "task",
        "a recorded completion's detail is edited after the fact; the schedule is "
        "untouched",
        extra=(
            Field("ts", "str", "the edited completion's timestamp"),
            Field(
                "meter_baseline",
                "float",
                "present when the edit re-anchored a usage task's meter",
            ),
        ),
    ),
    EventSpec(
        const.EVENT_TASK_TRIGGERED,
        "EVENT_TASK_TRIGGERED",
        "fired",
        "task",
        "a condition-driven or sensor-based task is armed, moving from dormant to "
        "due-now",
    ),
    EventSpec(
        const.EVENT_TASK_SNOOZED,
        "EVENT_TASK_SNOOZED",
        "fired",
        "task",
        "a task's due date is deferred without recording a completion; only next_due "
        "moves, the recurrence is untouched",
        extra=(Field("snoozed_until", "str", "the new due date, ISO"),),
    ),
    EventSpec(
        const.EVENT_TASK_SKIPPED,
        "EVENT_TASK_SKIPPED",
        "fired",
        "task",
        "a task is advanced to its next occurrence without recording a completion",
    ),
    EventSpec(
        const.EVENT_TASK_OVERDUE,
        "EVENT_TASK_OVERDUE",
        "fired",
        "task",
        "a task passes its due date, at most once per due date while HA runs",
        extra=(Field("days_overdue", "int"),),
    ),
    EventSpec(
        const.EVENT_TASK_DUE_SOON,
        "EVENT_TASK_DUE_SOON",
        "fired",
        "task",
        "a task enters the three-day due-soon window, at most once per due date",
        extra=(Field("due_in_hours", "int"),),
    ),
    EventSpec(
        const.EVENT_PART_LOW_STOCK,
        "EVENT_PART_LOW_STOCK",
        "fired",
        "stock",
        "a part's on-hand stock crosses down to its reorder threshold",
    ),
    EventSpec(
        const.EVENT_PART_OUT_OF_STOCK,
        "EVENT_PART_OUT_OF_STOCK",
        "fired",
        "stock",
        "a part's stock reaches zero; this wins over low stock on a single step",
    ),
    EventSpec(
        const.EVENT_PART_RESTOCKED,
        "EVENT_PART_RESTOCKED",
        "fired",
        "stock",
        "a part's stock rises back above its reorder threshold",
    ),
    EventSpec(
        const.EVENT_ASSET_CREATED,
        "EVENT_ASSET_CREATED",
        "fired",
        "asset",
        "an appliance is created",
    ),
    EventSpec(
        const.EVENT_ASSET_UPDATED,
        "EVENT_ASSET_UPDATED",
        "fired",
        "asset",
        "an appliance changes, including its documents, parts and archived history",
        extra=(_CHANGED_FIELDS,),
    ),
    EventSpec(
        const.EVENT_ASSET_DELETED,
        "EVENT_ASSET_DELETED",
        "fired",
        "asset",
        "an appliance is removed",
    ),
    EventSpec(
        const.EVENT_ASSET_ARCHIVED,
        "EVENT_ASSET_ARCHIVED",
        "fired",
        "asset",
        "an appliance is archived, hiding it without deleting its data",
    ),
    EventSpec(
        const.EVENT_ASSET_RESTORED,
        "EVENT_ASSET_RESTORED",
        "fired",
        "asset",
        "an archived appliance is restored",
    ),
    EventSpec(
        const.EVENT_COMPANION_CONNECTED,
        "EVENT_COMPANION_CONNECTED",
        "fired",
        "companion",
        "a companion integration newly becomes connected, by self-registering or by "
        "a known glue being detected installed",
    ),
    EventSpec(
        const.EVENT_COMPANION_SUGGESTED,
        "EVENT_COMPANION_SUGGESTED",
        "fired",
        "companion",
        "a curated upstream is newly detected installed while its glue isn't",
    ),
    EventSpec(
        const.EVENT_REGISTER_COMPANIONS,
        "EVENT_REGISTER_COMPANIONS",
        "fired",
        "none",
        "Home Keeper has set up and asks companions to re-announce themselves by "
        "calling register_companion; carries no payload",
    ),
    EventSpec(
        const.EVENT_HA_TAG_SCANNED,
        "EVENT_HA_TAG_SCANNED",
        "listened",
        "none",
        "Home Assistant's own tag integration fired a scan; Home Keeper completes "
        "the task bound to that tag_id",
    ),
)


# ── Device triggers ──────────────────────────────────────────────────────────

DEVICE_TRIGGERS: tuple[DeviceTriggerSpec, ...] = (
    DeviceTriggerSpec("task_completed", const.EVENT_TASK_COMPLETED, "task"),
    DeviceTriggerSpec("task_overdue", const.EVENT_TASK_OVERDUE, "task"),
    DeviceTriggerSpec("task_due_soon", const.EVENT_TASK_DUE_SOON, "task"),
    DeviceTriggerSpec("task_created", const.EVENT_TASK_CREATED, "task"),
    DeviceTriggerSpec("task_updated", const.EVENT_TASK_UPDATED, "task"),
    DeviceTriggerSpec("task_snoozed", const.EVENT_TASK_SNOOZED, "task"),
    DeviceTriggerSpec("task_skipped", const.EVENT_TASK_SKIPPED, "task"),
    DeviceTriggerSpec("part_low_stock", const.EVENT_PART_LOW_STOCK, "asset"),
    DeviceTriggerSpec("part_out_of_stock", const.EVENT_PART_OUT_OF_STOCK, "asset"),
    DeviceTriggerSpec("part_restocked", const.EVENT_PART_RESTOCKED, "asset"),
)


# ── Entity platforms ─────────────────────────────────────────────────────────
#
# ``todo`` and ``calendar`` are singletons named with ``_attr_name`` and
# ``has_entity_name = False``, so they have no ``strings.json`` entity section.

ENTITY_PLATFORMS: tuple[EntityPlatformSpec, ...] = (
    EntityPlatformSpec("todo"),
    EntityPlatformSpec("calendar"),
    EntityPlatformSpec("button", ("mark_done",)),
    EntityPlatformSpec(
        "sensor",
        ("next_due",),
        attributes=(
            Field("task_id", "str"),
            Field("task_name", "str"),
            Field("recurrence_type", "str"),
            Field("last_completed", "str | None", "ISO"),
            Field("completions_count", "int"),
            Field(
                "last_completion_*",
                "str | float",
                "one key per recorded detail on the latest completion: "
                "last_completion_note / _cost / _photo / _who / _reading",
            ),
            Field(
                "usage_*",
                "float | str",
                "meter progress on a usage sensor task: usage_target, usage_unit, "
                "usage_baseline, usage_consumed, usage_remaining, usage_percent, "
                "plus backstop_due; absent on every other task",
            ),
        ),
    ),
    EntityPlatformSpec(
        "binary_sensor",
        ("overdue", "part_low_stock"),
        attributes=(
            Field("task_id", "str", "overdue sensor"),
            Field("due_soon", "bool", "overdue sensor; within the three-day window"),
            Field("next_due", "str | None", "overdue sensor; ISO"),
            Field("asset_id", "str", "part low-stock sensor"),
            Field("part_id", "str", "part low-stock sensor"),
            Field("stock", "float", "part low-stock sensor"),
            Field("reorder_at", "float", "part low-stock sensor"),
            Field("unit", "str", "part low-stock sensor"),
        ),
    ),
    EntityPlatformSpec("number", ("part_spares",)),
)


# ── Internal surfaces (modelled and tested, not published) ───────────────────

WEBSOCKET_COMMANDS: tuple[WebsocketSpec, ...] = (
    WebsocketSpec("home_keeper/get_tasks", service="list_tasks"),
    WebsocketSpec("home_keeper/add_task", service="add_task"),
    WebsocketSpec("home_keeper/update_task", service="update_task"),
    WebsocketSpec("home_keeper/delete_task", service="delete_task"),
    WebsocketSpec("home_keeper/set_task_consumable", service="set_task_consumable"),
    WebsocketSpec("home_keeper/complete_task", service="complete_task"),
    WebsocketSpec("home_keeper/update_completion", service="update_completion"),
    WebsocketSpec("home_keeper/move_completion", service="move_completion"),
    WebsocketSpec("home_keeper/delete_completion", service="delete_completion"),
    WebsocketSpec(
        "home_keeper/delete_archived_completion", service="delete_archived_completion"
    ),
    WebsocketSpec("home_keeper/get_assets", service="list_assets"),
    WebsocketSpec("home_keeper/add_asset", admin_only=True, service="add_asset"),
    WebsocketSpec("home_keeper/update_asset", admin_only=True, service="update_asset"),
    WebsocketSpec("home_keeper/delete_asset", admin_only=True, service="delete_asset"),
    WebsocketSpec(
        "home_keeper/archive_asset", admin_only=True, service="archive_asset"
    ),
    WebsocketSpec(
        "home_keeper/restore_asset", admin_only=True, service="restore_asset"
    ),
    WebsocketSpec(
        "home_keeper/adjust_part_stock", admin_only=True, service="adjust_part_stock"
    ),
    WebsocketSpec(
        "home_keeper/add_asset_document", admin_only=True, service="add_asset_document"
    ),
    WebsocketSpec(
        "home_keeper/remove_asset_document",
        admin_only=True,
        service="remove_asset_document",
    ),
    WebsocketSpec(
        "home_keeper/update_asset_document",
        admin_only=True,
        service="update_asset_document",
    ),
    WebsocketSpec("home_keeper/sign_document_url", service="sign_document_url"),
    WebsocketSpec(
        "home_keeper/remove_part_file", admin_only=True, service="remove_part_file"
    ),
    WebsocketSpec("home_keeper/sign_part_file_url", service="sign_part_file_url"),
    WebsocketSpec(
        "home_keeper/export_inventory", admin_only=True, service="export_inventory"
    ),
    WebsocketSpec("home_keeper/get_options"),
    WebsocketSpec("home_keeper/set_options", admin_only=True, service="set_options"),
    WebsocketSpec("home_keeper/get_companions", service="list_companions"),
    WebsocketSpec("home_keeper/get_profiles", service="list_profiles"),
)

HTTP_VIEWS: tuple[HttpViewSpec, ...] = (
    HttpViewSpec(
        "api:home_keeper:document",
        const.DOCUMENT_URL_PREFIX + "/{asset_id}/{document_id}",
        ("GET", "POST"),
    ),
    HttpViewSpec(
        "api:home_keeper:part_document",
        const.PART_FILE_URL_PREFIX + "/{asset_id}/{part_id}",
        ("GET", "POST"),
    ),
)


# ── Config entry options ─────────────────────────────────────────────────────
#
# ``options._empty_options()`` stays the one definition of which keys exist, and
# ``options.FLOW_OPTIONS`` of which the form renders; these are pinned to both by
# ``test_options_match_the_options_module``. They are restated rather than derived
# on purpose: importing ``options`` for two tuples of strings would pull in the
# whole normalization chain (``notifications`` → Babel), and this module has to
# stay importable by tooling — ``ci/generate_api_docs.py`` on a docs runner — that
# has none of the integration's dependencies installed. See
# ``test_api_surface_imports_stay_light``.

OPTIONS: tuple[OptionSpec, ...] = (
    OptionSpec(const.OPTION_SYNC_PROBLEM_SENSORS, in_flow=True),
    OptionSpec(const.OPTION_ONE_OFF_RETENTION_DAYS, in_flow=True),
    OptionSpec(const.OPTION_SHOPPING_LIST_ENTITY, in_flow=True),
    OptionSpec(const.OPTION_PROFILES, in_flow=False),
    OptionSpec(const.OPTION_NOTIFICATIONS, in_flow=False),
    OptionSpec(const.OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES, in_flow=True),
    OptionSpec(const.OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES, in_flow=True),
    OptionSpec(const.OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS, in_flow=True),
    OptionSpec(const.OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS, in_flow=True),
    OptionSpec(const.OPTION_DISMISSED_COMPANIONS, in_flow=False),
)


# ── Surface coverage ─────────────────────────────────────────────────────────

SURFACE_KINDS: tuple[SurfaceKind, ...] = (
    SurfaceKind(
        "Actions (services)",
        "published",
        "Every operation that mutates or exports Home Keeper data ships as a "
        "`home_keeper.*` service — the interoperability contract.",
    ),
    SurfaceKind(
        "Bus events",
        "published",
        "Every observable state change fires a `home_keeper_<noun>_<verb>` event, "
        "built by a pure function so the shipped payload and the documented one "
        "are the same object.",
    ),
    SurfaceKind(
        "Device triggers",
        "published",
        "Ten of the bus events are offered in the visual automation editor on "
        "Home Keeper's own appliance and task devices.",
    ),
    SurfaceKind(
        "Device conditions",
        "not_applicable",
        "Task state is readable from the per-task sensor and binary_sensor, so a "
        "separate condition platform would add a second way to ask one question.",
    ),
    SurfaceKind(
        "Device actions",
        "not_applicable",
        "The services cover every device-scoped operation and take a task or asset "
        "id directly.",
    ),
    SurfaceKind(
        "Entity platforms",
        "published",
        "todo, calendar, sensor, binary_sensor, button and number — usage surfaces, "
        "as opposed to the admin-only panel.",
    ),
    SurfaceKind(
        "Entity attributes",
        "published",
        "The per-task sensors carry enough state that an automation rarely needs to "
        "call a service to read anything.",
    ),
    SurfaceKind(
        "Config entry options",
        "published",
        "Three surfaces write them — the options flow, the `set_options` service and "
        "the panel — through one merge path.",
    ),
    SurfaceKind(
        "Config flow",
        "published",
        "A single-instance UI setup flow with an options flow; no YAML configuration.",
    ),
    SurfaceKind(
        "Errors",
        "published",
        "User-facing failures raise localized exceptions keyed into strings.json, so "
        "they read in the user's language wherever they surface.",
    ),
    SurfaceKind(
        "Diagnostics",
        "published",
        "Config entry and device diagnostics download from the integration page, with "
        "serial numbers, notes and completion detail redacted.",
    ),
    SurfaceKind(
        "Companion discovery",
        "published",
        "Integrations that work with Home Keeper self-register via "
        "`register_companion`, or are detected from a curated catalog.",
    ),
    SurfaceKind(
        "Test helper",
        "published",
        "`home_keeper.testing` ships a fake store built on the same event builders, so "
        "an integrator tests against the shipped payloads.",
    ),
    SurfaceKind(
        "Lovelace card",
        "published",
        "The dashboard task card registers itself as a Lovelace resource on "
        "storage-mode installs.",
    ),
    SurfaceKind(
        "WebSocket commands",
        "internal",
        "A latency optimization for the panel that delegates to the same store "
        "methods; build on the services instead, which are the contract.",
    ),
    SurfaceKind(
        "HTTP views",
        "internal",
        "Two authenticated routes for document and part-file upload and download — a "
        "binary can't ride a service call, so this is the one non-service mutation "
        "path.",
    ),
    SurfaceKind(
        "Sidebar panel",
        "internal",
        "The admin-only management UI, served from a static path; it is a client of "
        "the surfaces above, not one itself.",
    ),
    SurfaceKind(
        "Dispatcher signals",
        "deferred",
        "`SIGNAL_TASK_CONTRIBUTION` is reserved for a future upsert/reconcile "
        "contribution API and is not connected to anything yet.",
    ),
    SurfaceKind(
        "Intents",
        "deferred",
        "Voice control would go through the intent platform; not built, and the "
        "services are reachable from a script in the meantime.",
    ),
    SurfaceKind(
        "Repairs",
        "deferred",
        "No repair issues are raised yet; problems surface as localized exceptions "
        "and log entries.",
    ),
    SurfaceKind(
        "Conversation",
        "not_applicable",
        "Home Keeper exposes no conversation agent of its own.",
    ),
    SurfaceKind(
        "Backup platform",
        "not_applicable",
        "State is one JSON document under `.storage`, which Home Assistant's own "
        "backup already covers.",
    ),
    SurfaceKind(
        "Media source",
        "not_applicable",
        "Uploaded documents are served by the integration's own authenticated view, "
        "not browsable as media.",
    ),
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def triggers_for(scope: str) -> dict[str, str]:
    """Return ``{trigger_type: event_name}`` for one device scope.

    ``device_trigger.py`` builds ``TASK_TRIGGERS`` / ``ASSET_TRIGGERS`` from this
    rather than repeating the mapping, so the triggers it offers and the ones the
    reference documents are the same dict.
    """
    return {spec.type: spec.event for spec in DEVICE_TRIGGERS if spec.scope == scope}


def events_by_payload(payload: str) -> tuple[EventSpec, ...]:
    """Return every fired event sharing one payload shape, in declaration order."""
    return tuple(
        spec for spec in EVENTS if spec.direction == "fired" and spec.payload == payload
    )


__all__ = [
    "DEVICE_TRIGGERS",
    "ENTITY_PLATFORMS",
    "EVENTS",
    "HTTP_VIEWS",
    "OPTIONS",
    "PAYLOAD_SPINES",
    "SERVICES",
    "SERVICE_NAMES",
    "STATUSES",
    "SURFACE_KINDS",
    "WEBSOCKET_COMMANDS",
    "DeviceTriggerSpec",
    "EntityPlatformSpec",
    "EventSpec",
    "Field",
    "HttpViewSpec",
    "OptionSpec",
    "ServiceSpec",
    "SurfaceKind",
    "WebsocketSpec",
    "events_by_payload",
    "triggers_for",
]
