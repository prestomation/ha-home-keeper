"""Constants for the Home Keeper integration."""

DOMAIN = "home_keeper"

# Entity platforms forwarded from the config entry.
PLATFORMS = ["todo", "calendar", "button", "sensor", "binary_sensor", "number"]

# Frontend panel.
# PANEL_VERSION is the single source of truth that release.yml validates against
# manifest.json's "version" (mirrors Pawsistant's CARD_VERSION check).
PANEL_VERSION = "0.24.0b3"
PANEL_URL_PATH = "home-keeper"  # sidebar route -> /home-keeper
PANEL_STATIC_URL = "/home_keeper_panel"  # static path that serves the JS bundle
PANEL_JS_FILENAME = "home-keeper-panel.js"
PANEL_TITLE = "Home Keeper"
PANEL_ICON = "mdi:home-clock"
WEBCOMPONENT_NAME = "home-keeper-panel"

# Dashboard card. Served from the same static path as the panel and
# auto-registered as a Lovelace resource so it appears in the "Add card" picker
# with no manual setup (see card.py).
CARD_JS_FILENAME = "home-keeper-card.js"

# Storage.
STORAGE_KEY = "home_keeper"
STORAGE_VERSION = 1

# Offline document storage. Uploaded asset documents (manuals / warranties / receipts)
# are stored as files on disk under the HA config dir — they are too large for the JSON
# store and are streamed back through an authenticated HTTP view, not the websocket.
#   • MANUALS_SUBDIR     — per-asset blob tree under ``<config>/`` (one dir per asset,
#     so deleting an asset is a single ``rmtree``).
#   • DOCUMENT_URL_PREFIX — the HomeKeeperDocumentView route; the panel uploads via a
#     multipart POST and opens files via an ``async_sign_path`` signed GET URL.
#   • MAX_DOCUMENT_BYTES  — hard per-file upload ceiling.
MANUALS_SUBDIR = "home_keeper/documents"
DOCUMENT_URL_PREFIX = "/api/home_keeper/document"
MAX_DOCUMENT_BYTES = 100 * 1024 * 1024
# A part's single attached file (receipt / spec sheet / photo) reuses the same
# documents.py/manuals.py storage and validation, keyed by the part's own id instead
# of a document id — it lives under the same per-asset directory (asset deletion's
# rmtree cleans it up for free) and is served by a sibling HTTP view.
PART_FILE_URL_PREFIX = "/api/home_keeper/part_document"
# How many completion timestamps to retain per task. Generous so the panel's task
# history shows years of cadence (e.g. 500 monthly completions ≈ 40 years) while
# still bounding the stored list. When a task that belongs to an appliance is
# deleted, this history is archived onto the appliance
# (see ``assets.append_task_history``).
MAX_COMPLETION_HISTORY = 500

# An author-chosen stable key on a task or an appliance, used by the import/export
# document (``transfer.py``) as the second step of its primary-key ladder: id first,
# then this, then the name. It is the key a migration script or a generated document
# sets so a re-run updates the same records rather than duplicating them. Home Keeper
# never reads it for anything else — it is opaque, and empty when unset.
MAX_EXTERNAL_ID_LEN = 128

# How many records one import document may carry per section. A bound on the work a
# single service call can ask for, not a statement about how many tasks Home Keeper
# holds; a bigger migration splits into several documents.
MAX_IMPORT_RECORDS = 2000

# The largest import document Home Keeper reads, in bytes. Checked before the parser
# runs, because the parser is what a huge file attacks: ``MAX_IMPORT_RECORDS`` counts
# records, and a document is already expanded in memory by the time there are records
# to count. 8 MiB holds a very large migration.
#
# This is the ceiling on the *service* (``home_keeper.import_data``), which is the
# path a script or an automation takes. The panel cannot reach it — see
# ``MAX_IMPORT_WS_BYTES``.
MAX_IMPORT_BYTES = 8 * 1024 * 1024

# The largest websocket frame Home Assistant will accept, in bytes.
#
# Home Assistant builds its ``WebSocketResponse`` without passing ``max_msg_size``, so
# aiohttp's own 4 MiB default applies, and the check is on the *decompressed* frame.
# Going over it does not fail the command: aiohttp raises during the read, and Home
# Assistant closes the whole connection with "Decompressed message exceeds size limit
# 4194304". The panel therefore loses its link to Home Assistant rather than getting an
# answer, which is why the size has to be caught in the browser before the send.
#
# It is half of ``MAX_IMPORT_BYTES`` on purpose, and the two are not interchangeable: a
# document between the two sizes imports through the service and cannot be pasted into
# the panel. ``frontend/src/limits.ts`` mirrors this and
# ``tests/unit/test_upload_limit_parity.py`` fails the build if the two drift.
MAX_IMPORT_WS_BYTES = 4 * 1024 * 1024

# The format version of the import/export document. Bumped only when the meaning of
# an existing key changes — adding a section or a field is additive and does not.
# ``transfer.py`` refuses a document declaring a newer version than this.
#
# Serialization is not shape: the document became YAML in 0.23.0 and stayed format 1,
# so every file written by an earlier build still imports.
TRANSFER_FORMAT = 1

# Where the published JSON Schema for that format lives. Two consumers, so they cannot
# disagree: ``transfer.document_to_yaml`` writes it as the first line of every export
# (the ``yaml-language-server`` convention, which makes an exported file self-validating
# in an editor), and ``ci/generate_schema.py`` writes it as the schema's own ``$id``.
#
# The version is in the filename on purpose. A file exported today keeps pointing at
# the schema it was written for, so bumping ``TRANSFER_FORMAT`` must *add* a file
# rather than replace one — see the warning in ``ci/generate_schema.py``.
TRANSFER_SCHEMA_URL = (
    "https://prestomation.github.io/ha-home-keeper"
    f"/schema/home-keeper-{TRANSFER_FORMAT}.schema.json"
)

# Event fired on the HA event bus whenever a task is completed (from any surface:
# the to-do list, a device mark-done button, or the complete_task service). This is
# the public, client-agnostic hook other integrations subscribe to in order to mirror
# completions. The payload carries the task's opaque ``source`` and ``origin`` verbatim;
# Home Keeper never inspects either. See docs/INTEGRATING.md.
EVENT_TASK_COMPLETED = f"{DOMAIN}_task_completed"

# Event fired when a stock-tracked spare part drops to (or below) its reorder
# threshold — either because a wear-part replacement was completed (consuming a
# spare) or because stock was manually adjusted down. Lets users automate a
# shopping-list add / reorder / notification without Home Keeper owning any
# shopping integration. Payload is built in events.low_stock_event_data.
EVENT_PART_LOW_STOCK = f"{DOMAIN}_part_low_stock"

# Comprehensive event catalog (see docs/EVENTS.md). Every observable Home Keeper
# state change fires a bus event built by a pure function in events.py, so
# automations and other integrations can react to the full lifecycle — not just
# completion and low-stock. Names follow ``{DOMAIN}_<noun>_<verb>``; payloads share
# the common "spine" (events.task_event_data / events.asset_event_data).
#
# Task lifecycle — fired at the store.py mutation chokepoints.
EVENT_TASK_CREATED = f"{DOMAIN}_task_created"
EVENT_TASK_UPDATED = f"{DOMAIN}_task_updated"  # payload carries ``changed_fields``
EVENT_TASK_DELETED = f"{DOMAIN}_task_deleted"
EVENT_TASK_UNCOMPLETED = f"{DOMAIN}_task_uncompleted"  # a completion was undone
EVENT_TASK_TRIGGERED = f"{DOMAIN}_task_triggered"  # a triggered task was armed
# Snooze pushes a task's ``next_due`` forward without recording a completion or
# advancing recurrence; the payload adds ``snoozed_until``. Skip advances a task to
# its next occurrence without recording a completion. Both ride the task spine and,
# because they change ``next_due``, re-arm the edge-triggered overdue/due-soon events
# for the new date. Driven by the snooze_task / skip_task services (and the actionable
# notification handler). See docs/EVENTS.md.
EVENT_TASK_SNOOZED = f"{DOMAIN}_task_snoozed"  # + ``snoozed_until``
EVENT_TASK_SKIPPED = f"{DOMAIN}_task_skipped"
# Due today moves a task's ``next_due`` to now, the mirror image of snooze — same
# untouched recurrence/last_completed, same re-arming of the edge-triggered events,
# just the other direction on the calendar. Driven by the set_due_today service.
# See docs/EVENTS.md.
EVENT_TASK_DUE_TODAY_SET = f"{DOMAIN}_task_due_today_set"
# Time-based transitions — fired (edge-triggered) from the coordinator. A task is
# announced at most once per ``next_due`` value while HA is running; see
# transitions.detect_transitions and coordinator._async_update_data.
EVENT_TASK_OVERDUE = f"{DOMAIN}_task_overdue"  # + ``days_overdue``
EVENT_TASK_DUE_SOON = f"{DOMAIN}_task_due_soon"  # + ``due_in_hours``
# Stock transitions — the siblings of EVENT_PART_LOW_STOCK, edge-triggered the same
# way (see assets.stock_transition). out_of_stock wins over low on a single step.
EVENT_PART_OUT_OF_STOCK = f"{DOMAIN}_part_out_of_stock"
EVENT_PART_RESTOCKED = f"{DOMAIN}_part_restocked"
# Fired when a recorded completion's detail (note/cost/photo/who/reading) is edited
# after the fact — a state change distinct from completing/uncompleting. Carries
# the task spine plus the edited completion's ``ts``, and ``meter_baseline`` when the
# edit re-anchored a usage meter (see store.update_completion). See docs/EVENTS.md.
EVENT_TASK_COMPLETION_UPDATED = f"{DOMAIN}_task_completion_updated"
# The skip log's edit events, mirroring the two above. ``_skip_updated`` carries the
# edited skip's ``ts`` (its ``old_ts`` after a move) plus ``meter_baseline`` when the
# edit re-anchored a usage meter; ``_skip_removed`` carries the ``ts`` undone. There is
# no re-add pair for a move: nothing downstream mirrors a skip the way an integration
# mirrors a completion. See docs/EVENTS.md.
EVENT_TASK_SKIP_UPDATED = f"{DOMAIN}_task_skip_updated"
EVENT_TASK_SKIP_REMOVED = f"{DOMAIN}_task_skip_removed"
# Asset (appliance) lifecycle — fired at the store.py asset chokepoints.
EVENT_ASSET_CREATED = f"{DOMAIN}_asset_created"
EVENT_ASSET_UPDATED = f"{DOMAIN}_asset_updated"  # payload carries ``changed_fields``
EVENT_ASSET_DELETED = f"{DOMAIN}_asset_deleted"
EVENT_ASSET_ARCHIVED = f"{DOMAIN}_asset_archived"  # hidden without deleting its data
EVENT_ASSET_RESTORED = f"{DOMAIN}_asset_restored"  # an archived appliance is restored

# Assets / appliances (virtual devices + asset metadata).
# A virtual asset device is registered with identifier
# (DOMAIN, f"{ASSET_IDENTIFIER_PREFIX}_{asset_id}"); the prefix keeps it from
# colliding with the per-task self-owned devices, which key on the bare task id.
ASSET_IDENTIFIER_PREFIX = "asset"
ASSET_KIND_VIRTUAL = "virtual"  # Home Keeper provisions the registry device
ASSET_KIND_EXISTING = "existing"  # metadata attached to another integration's device
ASSET_KINDS = [ASSET_KIND_VIRTUAL, ASSET_KIND_EXISTING]

# Structured parts / wear items on an asset. A "consumable" is a stocked spare; a
# "wear" item degrades over time and, when given a replacement interval, drives a
# maintenance task (reusing the recurrence engine + per-task entities).
PART_CONSUMABLE = "consumable"
PART_WEAR = "wear"
PART_TYPES = [PART_CONSUMABLE, PART_WEAR]

# What a wear part's generated maintenance task is *called*. A wear item is not always
# replaced: a jacket is renewed, a chain is cleaned, a blade is sharpened, tyres are
# rotated. The action picks the name template (see ACTION_TASK_NAME_TEMPLATES) and
# changes nothing else about the task. ``replace`` is the default, so every part
# written before this existed keeps the name it already had.
PART_ACTION_REPLACE = "replace"
PART_ACTION_CLEAN = "clean"
PART_ACTION_SERVICE = "service"
PART_ACTION_RENEW = "renew"
PART_ACTION_SHARPEN = "sharpen"
PART_ACTION_ROTATE = "rotate"
PART_ACTION_INSPECT = "inspect"
PART_ACTIONS = [
    PART_ACTION_REPLACE,
    PART_ACTION_CLEAN,
    PART_ACTION_SERVICE,
    PART_ACTION_RENEW,
    PART_ACTION_SHARPEN,
    PART_ACTION_ROTATE,
    PART_ACTION_INSPECT,
]

# The two roles a reconciler-derived part task can have, stored at
# ``task["source"]["part"]["role"]``. An **absent** role reads as ``replace``, which is
# what every task written before counted wear items existed carries — so there is no
# migration. The role is also what keeps one part's 2 tasks apart in the reconciler's
# index and stops a *use* completion from consuming a spare (see
# ``store._stamp_part_replacement``).
PART_ROLE_USE = "use"
PART_ROLE_REPLACE = "replace"

# Marker on a task dict identifying it as derived from an asset part, so the
# part-task reconciler owns it: ``task["source"] = {"asset_id", "part_id"}``.
TASK_SOURCE_PART = "part"

# Marker on a task dict identifying it as an auto-created "buy" reminder for a low
# spare part: ``task["source"] = {"buy": {"asset_id", "part_id"}}``. Owned entirely
# by the buy-task reconciler (``reconcile.reconcile_buy_tasks``) — created while the
# part is low (``stock <= reorder_at``) and the part opts in, removed once restocked.
# A one-off task; completing it bumps the part's stock by ``restock_quantity``. Like
# the wear-part/problem-sensor sources it is reserved: ``add_task`` rejects it.
TASK_SOURCE_BUY = "buy"

# Marker on a task dict identifying it as synced from a ``device_class: problem``
# binary sensor: ``task["source"] = {"problem_sensor": {"entity_id": ...}}``. Such
# a task is a condition-driven (triggered) mirror of the sensor — armed while the
# sensor reports a problem, dormant once it clears. It is owned entirely by the
# problem-sensor reconciler and CANNOT be completed from inside Home Keeper: the
# originating integration must resolve the real-world problem (the sensor goes
# back to ``off``), at which point Home Keeper auto-clears the task. See
# ``problem_tasks.py`` / ``problem_sync.py``.
TASK_SOURCE_PROBLEM_SENSOR = "problem_sensor"

# Opaque ``origin`` marker the problem-sensor sync passes to ``complete_task`` /
# ``trigger_task`` to authorize the otherwise-blocked arm/clear of a synced task.
# Every user-facing completion surface (to-do, button, service, websocket, panel)
# omits it, so they are rejected; only the internal sync can drive these tasks.
ORIGIN_PROBLEM_SENSOR_SYNC = f"{DOMAIN}_problem_sensor_sync"

# Config-entry options keys (set via the options flow). Syncing is opt-in.
OPTION_SYNC_PROBLEM_SENSORS = "sync_problem_sensors"  # bool, default False
# Exclusion filters narrowing which ``device_class: problem`` binary sensors are
# synced when the option is on. Lists of entity ids / device ids / area ids /
# label ids.
OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES = "problem_sensor_exclude_entities"
OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES = "problem_sensor_exclude_devices"
OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS = "problem_sensor_exclude_areas"
OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS = "problem_sensor_exclude_labels"
# Auto-delete a completed one-off task this many days after its completion. ``0``
# (the default) keeps completed one-offs forever; ``N > 0`` purges them once
# ``last_completed + N days`` has passed, via the coordinator's periodic refresh.
OPTION_ONE_OFF_RETENTION_DAYS = "one_off_retention_days"
# Whether Home Keeper *offers* Snooze and Skip. Both default **on**: they are
# long-standing verbs, and defaulting them off would hide a feature people already
# struggle to find (#268). Turning one off withdraws it from the surfaces Home Keeper
# controls — the panel's task actions and a notification's button set — but never from
# ``home_keeper.snooze_task`` / ``skip_task``. Services are the interoperability
# contract, and silently breaking an automation someone already wrote is not a setting.
# One documented exception: ``notifications.actions_for`` still forces Snooze onto a
# completion-blocked task, because a notification walk only advances on a successful
# action and such a task can be neither completed nor skipped (#248).
OPTION_ALLOW_SNOOZE = "allow_snooze"  # bool, default True
OPTION_ALLOW_SKIP = "allow_skip"  # bool, default True
OPTION_ALLOW_DUE_TODAY = "allow_due_today"  # bool, default True
# Catalog glue domains the user dismissed from the Settings → Companions
# "Suggested" list. A list of domain strings; dismissing only silences a
# *suggestion* (a connected pairing is always shown). See companions.py.
OPTION_DISMISSED_COMPANIONS = "dismissed_companions"
# Profiles: named, reusable task filters (status + label/area/device). Standalone and
# notification-agnostic — consumed by notifications, the panel's admin list filter, and
# the Lovelace card. A list of ``{id, name, filter, sync}``, where ``sync`` pairs the
# profile with one external ``todo.*`` list (``{entity_id, two_way,
# vanish_as_completed}``; ``entity_id: ""`` is the off switch) so the tasks it selects
# reach Todoist, Google Tasks or a local family list. See profiles.py, and
# todo_list.py / todo_list_sync.py for what the sync block drives.
OPTION_PROFILES = "profiles"
# Notifications: delivery bindings that reference a profile by ``profile_id`` and add
# how to deliver (targets, button set, snooze duration, style, automatic triggers), how
# loudly it lands (channel, urgency) and how it looks (icon, color).
# Edited from the panel's Settings → Notifications card and the set_options service;
# consumed by the notify service, the action listener, and the coordinator's automatic
# source. See notifications.py and docs/PROFILES_REFACTOR_PLAN.md.
OPTION_NOTIFICATIONS = "notifications"
# An existing Home Assistant to-do list (a ``todo.*`` entity id) that auto-buy
# reminders are mirrored onto — a shopping list, so "go buy more" reaches voice
# assistants and list widgets. ``""`` (the default) turns the mirror off. The
# mirror is two-way: ticking the item off there completes the Home Keeper
# reminder, which restocks the part. See shopping.py / shopping_sync.py.
OPTION_SHOPPING_LIST_ENTITY = "shopping_list_entity"

# Opaque ``origin`` marker the shopping-list mirror passes to ``complete_task``
# when a mirrored buy reminder is ticked off on the external list. Like
# ``ORIGIN_SENSOR_RECOVER`` this authorizes nothing — a buy reminder is
# completable by hand — it exists so an automation can tell "somebody ticked it
# off at the shop" apart from "somebody pressed Done".
ORIGIN_SHOPPING_LIST = f"{DOMAIN}_shopping_list"

# Opaque ``origin`` marker the to-do list sync passes to ``complete_task`` when a
# synced task is ticked off on an external to-do list. Like
# ``ORIGIN_SHOPPING_LIST`` it authorizes nothing — it exists so an automation can
# tell "checked off on a to-do list" apart from "somebody pressed Done", and it is
# how the sync's own completions stay recognisable in the event stream. See
# todo_list_sync.py.
ORIGIN_TODO_SYNC = f"{DOMAIN}_todo_sync"

# Opaque ``origin`` marker the actionable-notification action listener passes to
# ``complete_task`` / ``snooze_task`` / ``skip_task`` so an automation can recognise
# (and ignore) the completion/snooze it triggered from a notification tap.
ORIGIN_NOTIFICATION_ACTION = f"{DOMAIN}_notification_action"

# Opaque ``origin`` marker the sensor watcher passes to ``complete_task`` when a
# ``clear_on_recover`` sensor task clears itself because its bound entity went back to
# normal. Unlike ``ORIGIN_PROBLEM_SENSOR_SYNC`` this authorizes nothing — the task is
# user-owned and completable by hand — it exists so an automation can tell "Home Keeper
# noticed the condition cleared" apart from "somebody pressed Done".
ORIGIN_SENSOR_RECOVER = f"{DOMAIN}_sensor_recover"

# Opaque ``origin`` marker the tag listener passes to ``complete_task`` when an
# NFC/RFID tag scan completes the tasks bound to it. Like
# ``ORIGIN_PROBLEM_SENSOR_SYNC`` this one *authorizes*: a task with
# ``require_tag_scan`` refuses every human-initiated completion surface (to-do,
# button, notification, panel, bare service) and only accepts a completion carrying
# a system marker, of which this is the one a real scan produces. See ``tags.py``.
ORIGIN_TAG_SCAN = f"{DOMAIN}_tag_scan"

# The bus event Home Assistant core's ``tag`` integration fires when a tag is
# scanned; its ``tag_id`` field is the scanned tag's id. Named here rather than
# imported from ``homeassistant.components.tag`` because that integration may not be
# loaded at all — Home Keeper only listens for the event, so it must not pull the
# component in.
EVENT_HA_TAG_SCANNED = "tag_scanned"


# Recurrence types.
REC_FLOATING = "floating"
REC_FIXED = "fixed"
# A condition-driven task with no schedule. An owner integration arms it (via
# ``trigger_task`` or by creating it) when a condition becomes true and clears it
# (via ``complete_task``) when the condition resolves. Its ``next_due`` *is* its
# state: ``None`` = dormant (invisible to every time surface), a timestamp =
# active/due-now. See docs/INTEGRATING.md "Condition-driven (triggered) tasks".
REC_TRIGGERED = "triggered"
# A user-scheduled do-once task. It carries its own ``due`` datetime (the chosen
# due date); ``compute_next_due`` reads it back, and completing the task sets
# ``next_due = None`` permanently (no rescheduling) — it goes dormant like a
# triggered task, but undoing the completion re-arms it to ``due`` (its state is
# history-driven, not condition-driven). See docs/EVENTS.md / README.
REC_ONE_OFF = "one-off"
# A sensor-based task: Home Keeper derives its armed/dormant state from a bound
# entity rather than the clock. Like ``triggered`` its ``next_due`` *is* its
# state (``None`` = dormant, a timestamp = armed/due-now), but Home Keeper itself —
# not an external owner — arms it via a pure evaluator fed by the live reading. The
# binding lives in ``task["sensor"]`` (see ``models.normalize_sensor`` /
# ``sensor_tasks.py``). Three modes: ``usage`` (a meter — due after the reading
# advances ``target`` units since the last completion), ``threshold`` (due when
# the reading crosses a numeric comparison) and ``state`` (due when the entity enters
# a given state). See docs/SENSOR_TASKS_PLAN.md.
REC_SENSOR = "sensor"
# A counted wear item's *use* task: the one surface a household taps to say "I wore
# it / I used it once". It has no cadence and no due date at all — ``next_due`` is
# ``None`` for its whole life, so it stays off the calendar, off the overdue
# ``binary_sensor`` and out of every Profile tier but ``all``, while staying on the
# to-do list as an undated item. Its ``completions`` list *is* the count: the
# replacement task beside it arms once enough entries accumulate since the last
# replacement (see ``reconcile.uses_since_replacement``). Distinct from
# ``triggered``, which an owner arms and clears, and from ``sensor``, which reads a
# number: nothing ever arms a use task. See docs/COUNTED_WEAR_ITEMS_PLAN.md.
REC_USE = "use"
RECURRENCE_TYPES = [
    REC_FLOATING,
    REC_FIXED,
    REC_TRIGGERED,
    REC_ONE_OFF,
    REC_SENSOR,
    REC_USE,
]

# Sensor-based task modes.
SENSOR_MODE_USAGE = "usage"  # meter: arm when reading - baseline >= target
SENSOR_MODE_THRESHOLD = "threshold"  # arm on a numeric crossing of value
# ``state`` compares the entity's *state string* rather than a number, which is what
# makes a binary sensor usable at all: "water tank low" / "battery almost empty"
# report ``on``/``off``, never a figure. It is not binary-only — any state-y entity
# works (``vacuum.x == "docked"``, ``sensor.washer == "finished"``).
SENSOR_MODE_STATE = "state"
# ``availability`` inverts the "no reading = do nothing" policy the other three modes
# share: it arms *because* the entity is ``unavailable``/``unknown`` (or a bound
# ``attribute`` is missing) for at least ``for_seconds``. This is the mode a
# user-authored companion uses to say "task me when an entity goes offline"; no
# shipped preset uses it today. Baseline: an entity that starts life unavailable
# does NOT arm a fresh task (matches ``problem_sync`` "indeterminate does not
# fabricate").
SENSOR_MODE_AVAILABILITY = "availability"
SENSOR_MODES = [
    SENSOR_MODE_USAGE,
    SENSOR_MODE_THRESHOLD,
    SENSOR_MODE_STATE,
    SENSOR_MODE_AVAILABILITY,
]

# Max length of a ``state`` binding's target state. Home Assistant caps a state string
# at 255 characters, so anything longer could never match a real entity.
MAX_SENSOR_STATE_LEN = 255

# How a usage task's meter target combines with its optional time backstop
# (``sensor["also_every"]``): ``any`` = whichever comes first (the common
# "every 300 hours or 6 months" service interval), ``all`` = both must be met
# (a "no earlier than" floor, e.g. a monthly test run that also needs 100 hours).
SENSOR_COMBINATOR_ANY = "any"
SENSOR_COMBINATOR_ALL = "all"
SENSOR_COMBINATORS = [SENSOR_COMBINATOR_ANY, SENSOR_COMBINATOR_ALL]

# Max length of a usage binding's optional ``unit`` (a display label only — the
# meter arithmetic is unit-agnostic, so this exists to caption "300" as "300 h").
MAX_SENSOR_UNIT_LEN = 16

# Threshold comparison operators (stored verbatim in ``task["sensor"]["comparison"]``).
SENSOR_CMP_GE = ">="
SENSOR_CMP_LE = "<="
SENSOR_CMP_GT = ">"
SENSOR_CMP_LT = "<"
SENSOR_CMP_EQ = "=="
SENSOR_CMP_NE = "!="
SENSOR_COMPARISONS = [
    SENSOR_CMP_GE,
    SENSOR_CMP_LE,
    SENSOR_CMP_GT,
    SENSOR_CMP_LT,
    SENSOR_CMP_EQ,
    SENSOR_CMP_NE,
]

# Per-task capture mode for completion metadata (note / cost / photo / who).
# ``none`` keeps the existing one-click "Done" (the default, so existing tasks and
# automations are unchanged); ``optional`` pops a details dialog on completion with
# every field optional; ``required`` pops the dialog and makes the task's
# ``completion_required_fields`` mandatory before it can be marked done.
COMPLETION_DETAIL_NONE = "none"
COMPLETION_DETAIL_OPTIONAL = "optional"
COMPLETION_DETAIL_REQUIRED = "required"
COMPLETION_DETAIL_MODES = [
    COMPLETION_DETAIL_NONE,
    COMPLETION_DETAIL_OPTIONAL,
    COMPLETION_DETAIL_REQUIRED,
]
# The metadata a single completion can carry — also the allowed members of a task's
# ``completion_required_fields`` list. That list (not a hard-coded "note") is the
# single source of truth the panel reads to gate a required completion, so a future
# per-task "which fields are required" editor needs only to populate the list — no
# storage migration. v1 derives it from the mode (required -> ["note"]).
COMPLETION_METADATA_FIELDS = ["note", "cost", "photo", "who"]

# Completion fields Home Keeper *captures* rather than asks for: ``reading`` is the
# bound sensor's value at the moment a sensor task was completed ("the odometer read
# 45,000"). Deliberately NOT in COMPLETION_METADATA_FIELDS, which doubles as the
# allowlist for ``completion_required_fields``: a task can't demand a number the user
# never types, and a floating task with no sensor at all could otherwise be marked as
# requiring one and become uncompletable from the panel. Editable after the fact (a
# back-dated completion records today's reading, so it often needs correcting) — just
# never mandatory.
COMPLETION_CAPTURED_FIELDS = ["reading"]

# Every key a completion history entry may carry beside its mandatory ``ts``. This is
# the list to iterate when lifting/echoing/persisting a completion's fields; only
# ``completion_required_fields`` validation uses the narrower metadata list above.
COMPLETION_ENTRY_FIELDS = [*COMPLETION_METADATA_FIELDS, *COMPLETION_CAPTURED_FIELDS]

# Every key a *skip* entry may carry beside its mandatory ``ts``. A skip answers "why
# did this occurrence go by?", so it takes the note and the person, plus the meter
# ``reading`` it was taken at. It has no ``cost`` or ``photo``: nothing was bought and
# there is nothing to show — a narrower list, not an oversight.
SKIP_ENTRY_FIELDS = ["note", "who", "reading"]

# Floating interval units.
UNIT_DAYS = "days"
UNIT_WEEKS = "weeks"
UNIT_MONTHS = "months"
UNITS = [UNIT_DAYS, UNIT_WEEKS, UNIT_MONTHS]

# A wear part's ``replace_unit`` accepts one value the recurrence engine does not:
# ``uses``, which counts completions of a use task instead of measuring time. It is a
# **separate list on purpose**. ``assets._normalize_part`` used to validate
# ``replace_unit`` against ``UNITS``, the very list ``models.normalize_fields`` reads
# for a floating task's ``unit`` — so adding ``uses`` there would have made
# ``recurrence_type: "floating", unit: "uses"`` a valid task that no branch of
# ``compute_next_due`` can compute.
UNIT_USES = "uses"
PART_REPLACE_UNITS = [*UNITS, UNIT_USES]

# Fixed schedule frequencies.
FREQ_DAILY = "DAILY"
FREQ_WEEKLY = "WEEKLY"
FREQ_MONTHLY = "MONTHLY"
FREQS = [FREQ_DAILY, FREQ_WEEKLY, FREQ_MONTHLY]

# How far ahead the calendar expands fixed occurrences, and a hard iteration cap
# to guard against runaway expansion loops.
MAX_EXPAND_ITERATIONS = 500

# Upper bound on a recurrence interval / wear-part replacement interval. Generous
# (e.g. 10000 days ≈ 27 years, 10000 months ≈ 833 years) but low enough to keep
# date arithmetic well clear of datetime/timedelta overflow.
MAX_INTERVAL = 10_000

# Upper bound on a wear part's target when it is counted in ``uses``, and the floor
# under the derived retention window.
#
# ``MAX_INTERVAL`` cannot serve here. ``recurrence._record_entry`` trims *every*
# completion list to ``MAX_COMPLETION_HISTORY`` (500), blindly and on every write —
# long before the use-task trim rule gets a look. A 5,000-use target would therefore
# lose the very entries the count is derived from and read low forever, with nothing
# to show the user why. 250 is the largest target whose load-bearing window
# (2 x target, what ``usage_interval_stats`` needs) still lands inside that cap.
MAX_USE_TARGET = 250
MIN_USE_RETENTION = 50

# A part's ``use_noun`` is a short label rendered beside a number ("17 of 25 wears"),
# not prose. Same budget as a stock unit.
MAX_USE_NOUN_LEN = 16

# DEFERRED (not implemented this prototype): a stable cross-integration contribution
# interface so integrations like Battery Notes can push maintenance tasks without
# this integration knowing anything about them. The intended hook is a dispatcher
# signal plus a `home_keeper.contribute_task` service. See docs/DESIGN.md.
SIGNAL_TASK_CONTRIBUTION = f"{DOMAIN}_task_contribution"

# ── Companion discovery ──────────────────────────────────────────────────────
# A "companion" is another integration that works with Home Keeper. They surface
# in the panel's Settings → Companions section so users discover the ecosystem.
# Two paths feed the registry (see companions.py / companions_catalog.py):
#   • Push: a Home-Keeper-aware integration self-registers via the
#     ``home_keeper.register_companion`` service (Pawsistant, the Battery Notes glue).
#   • Pull: Home Keeper detects a popular *upstream* (e.g. Battery Notes) from a
#     curated catalog and *suggests* the glue that bridges it.
#
# Where the in-memory companion registry lives (survives entry reloads; rebuilt on
# HA restart as companions re-announce).
DATA_COMPANIONS = f"{DOMAIN}_companions"
# Upper bound on how many distinct companion domains the in-memory registry will hold,
# so a misbehaving/compromised companion can't register unbounded domains (each
# descriptor is stored verbatim). Generous — no real ecosystem approaches this — and
# updates to an already-registered domain are always allowed past the cap.
MAX_COMPANIONS = 50
# Bus event Home Keeper fires when it has set up (and on reload) asking companions
# to (re-)announce themselves. Best-effort: registration survives entry reloads via
# ``hass.data``, but a full HA restart sets every integration up fresh and ordering
# isn't guaranteed, so companions both register at their own setup *and* listen for
# this ping. Carries no data.
EVENT_REGISTER_COMPANIONS = f"{DOMAIN}_register_companions"
# Fired (edge-triggered, deduped per domain) when a companion first becomes
# connected (self-registered or a known glue is detected installed) or when a known
# upstream's glue is first suggested. Payload built by events.companion_event_data.
EVENT_COMPANION_CONNECTED = f"{DOMAIN}_companion_connected"
EVENT_COMPANION_SUGGESTED = f"{DOMAIN}_companion_suggested"

# ── Declarative companions ─────────────────────────────────────────────────────
# A **declarative companion** is a Home-Keeper-owned recipe (target integration +
# entity filters + sensor-task trigger + Jinja-templated task fields) that expands
# into one managed sensor task per matching entity. Unlike a hand-coded glue
# integration (see EVENT_REGISTER_COMPANIONS above) it needs no separate repo —
# users create them from the panel, or install one from a shipped preset (see
# declarative_presets.py). The reconciler (declarative_companion_sync.py) enumerates
# matches from the entity registry, renders templates, and delegates trigger
# evaluation to the existing SensorTaskWatcher. Managed tasks carry
# ``managed_by.integration = home_keeper`` and
# ``source = {"declarative_companion":
# {"spec_id", "entity_registry_id", "entity_id"}}``.
# Dedupe is on ``entity_registry_id`` so a rename does not churn the task.
#
# Upper bound on how many declarative-companion specs are stored.
# Matches MAX_COMPANIONS.
MAX_DECLARATIVE_COMPANIONS = 50
# Length bounds on user-visible strings on a spec — prevents runaway names/notes/regex
# from wedging the panel or blowing the JSON store.
MAX_DECLARATIVE_SPEC_NAME_LEN = 100
MAX_DECLARATIVE_SPEC_DESCRIPTION_LEN = 500
MAX_DECLARATIVE_ENTITY_REGEX_LEN = 200
MAX_DECLARATIVE_NAME_TEMPLATE_LEN = 200
MAX_DECLARATIVE_NOTES_TEMPLATE_LEN = 2000
# Cap the number of tasks a single declarative spec can materialize. A poorly
# narrowed regex (``.*``) against a big HA config would otherwise fan out to
# hundreds of tasks silently. The preview warns at WARN and hard-fails at HARD so
# a runaway spec cannot be saved.
MAX_DECLARATIVE_MATCH_WARN = 50
MAX_DECLARATIVE_MATCH_HARD = 500
# Provenance key on a managed task's ``source`` dict identifying it as materialized
# by a declarative-companion spec: ``task["source"] = {"declarative_companion":
# {"spec_id", "entity_registry_id", "entity_id"}}``. The reconciler exclusively
# owns these tasks; ``entity_registry_id`` is the survives-rename dedupe key.
TASK_SOURCE_DECLARATIVE_COMPANION = "declarative_companion"
# Dispatcher signal the store fires when a spec is added / updated / deleted /
# toggled; the reconciler subscribes to re-materialize managed tasks without
# needing a config-entry reload.
SIGNAL_DECLARATIVE_SPECS_CHANGED = f"{DOMAIN}_declarative_specs_changed"
# Bus events fired on spec-level mutations. Managed tasks still emit the standard
# ``home_keeper_task_*`` events; automations filter to declarative tasks via
# ``managed_by.integration == "home_keeper"`` +
# ``source.declarative_companion.spec_id``. Payload built by
# ``events.declarative_companion_event_data``.
EVENT_DECLARATIVE_COMPANION_ADDED = f"{DOMAIN}_declarative_companion_added"
EVENT_DECLARATIVE_COMPANION_UPDATED = f"{DOMAIN}_declarative_companion_updated"
EVENT_DECLARATIVE_COMPANION_REMOVED = f"{DOMAIN}_declarative_companion_removed"

# Well-known field on a task dict that Home Keeper inspects (unlike the opaque
# ``source`` field). Declares the integration that owns the task: which fields
# are locked, whether deletion is protected, and display metadata for the UI.
TASK_MANAGED_BY = "managed_by"

# ── Localized name for reconciler-generated wear-part tasks ─────────────────────
# The wear-part reconciler auto-generates a maintenance task name like
# "Replace {part} ({asset})". Unlike the panel's static UI (translated client-side
# per viewer), a task's ``name`` is server-side global data — a single value shared
# by every to-do item, calendar event, notification, device-page entity, and API
# consumer. So we translate it once, at write time, into Home Assistant's configured
# language (``hass.config.language`` — the household's primary language), and store
# that. ``store.reconcile_part_tasks`` resolves these and hands them to the pure
# reconciler; a language change relocalizes every generated name via an entry reload
# (see ``__init__`` EVENT_CORE_CONFIG_UPDATE listener). The 16 languages match the
# panel's shipped locales. ``{part}``/``{asset}`` are filled from the wear part and
# its appliance.
DEFAULT_LANGUAGE = "en"
WEAR_TASK_NAME_TEMPLATES: dict[str, str] = {
    "en": "Replace {part} ({asset})",
    "ca": "Substituir {part} ({asset})",
    "cs": "Vyměnit {part} ({asset})",
    "da": "Udskift {part} ({asset})",
    "de": "{part} ersetzen ({asset})",
    "es": "Reemplazar {part} ({asset})",
    "fi": "Vaihda {part} ({asset})",
    "fr": "Remplacer {part} ({asset})",
    "it": "Sostituire {part} ({asset})",
    "nb": "Bytt {part} ({asset})",
    "nl": "{part} vervangen ({asset})",
    "pl": "Wymień {part} ({asset})",
    "pt-BR": "Trocar {part} ({asset})",
    "ru": "Замена {part} ({asset})",
    "sv": "Byt {part} ({asset})",
    "zh-Hans": "更换 {part}（{asset}）",  # noqa: RUF001 — full-width parens are zh-Hans convention
}
# Localized name for reconciler-generated *buy* tasks — "Buy {part}". Same rationale
# as the wear-part template above: a task name is server-side global data, so it's
# resolved once (to ``hass.config.language``) at write time. Only ``{part}`` is
# substituted (the appliance isn't named in the buy reminder).
BUY_TASK_NAME_TEMPLATES: dict[str, str] = {
    "en": "Buy {part}",
    "ca": "Comprar {part}",
    "cs": "Koupit {part}",
    "da": "Køb {part}",
    "de": "{part} kaufen",
    "es": "Comprar {part}",
    "fi": "Osta {part}",
    "fr": "Acheter {part}",
    "it": "Comprare {part}",
    "nb": "Kjøp {part}",
    "nl": "{part} kopen",
    "pl": "Kup {part}",
    "pt-BR": "Comprar {part}",
    "ru": "Купить {part}",
    "sv": "Köp {part}",
    "zh-Hans": "购买 {part}",
}
# Localized name for the *use* task of a counted wear item — "Use {asset}". Same
# rationale as the templates above: a task name is server-side global data, resolved
# once to ``hass.config.language`` at write time. Only ``{asset}`` is substituted; the
# part is not named, because the household taps this task to record using the thing
# itself ("Wear rain jacket"), not the part that wears out. A part may override it
# outright with ``use_task_name``.
USE_TASK_NAME_TEMPLATES: dict[str, str] = {
    "en": "Use {asset}",
    "ca": "Utilitzar {asset}",
    "cs": "Použít {asset}",
    "da": "Brug {asset}",
    "de": "{asset} benutzen",
    "es": "Usar {asset}",
    "fi": "Käytä {asset}",
    "fr": "Utiliser {asset}",
    "it": "Usare {asset}",
    "nb": "Bruk {asset}",
    "nl": "{asset} gebruiken",
    "pl": "Użyj {asset}",
    "pt-BR": "Usar {asset}",
    "ru": "Использование {asset}",
    "sv": "Använd {asset}",
    "zh-Hans": "使用 {asset}",
}
# One name template per wear-part action, per language. ``replace`` reuses
# WEAR_TASK_NAME_TEMPLATES rather than repeating it, so the default action keeps the
# exact string every existing wear part already generated. The other 6 let a wear item
# be renewed, cleaned, serviced, sharpened, rotated or inspected instead of replaced —
# which is what makes a wear item fit a jacket, a chain or a knife.
ACTION_TASK_NAME_TEMPLATES: dict[str, dict[str, str]] = {
    PART_ACTION_REPLACE: WEAR_TASK_NAME_TEMPLATES,
    PART_ACTION_CLEAN: {
        "en": "Clean {part} ({asset})",
        "ca": "Netejar {part} ({asset})",
        "cs": "Vyčistit {part} ({asset})",
        "da": "Rengør {part} ({asset})",
        "de": "{part} reinigen ({asset})",
        "es": "Limpiar {part} ({asset})",
        "fi": "Puhdista {part} ({asset})",
        "fr": "Nettoyer {part} ({asset})",
        "it": "Pulire {part} ({asset})",
        "nb": "Rengjør {part} ({asset})",
        "nl": "{part} reinigen ({asset})",
        "pl": "Wyczyść {part} ({asset})",
        "pt-BR": "Limpar {part} ({asset})",
        "ru": "Очистка {part} ({asset})",
        "sv": "Rengör {part} ({asset})",
        "zh-Hans": "清洁 {part}（{asset}）",  # noqa: RUF001 — full-width parens are zh-Hans convention
    },
    PART_ACTION_SERVICE: {
        "en": "Service {part} ({asset})",
        "ca": "Revisar {part} ({asset})",
        "cs": "Servis {part} ({asset})",
        "da": "Servicer {part} ({asset})",
        "de": "{part} warten ({asset})",
        "es": "Revisar {part} ({asset})",
        "fi": "Huolla {part} ({asset})",
        "fr": "Réviser {part} ({asset})",
        "it": "Revisionare {part} ({asset})",
        "nb": "Service {part} ({asset})",
        "nl": "{part} onderhouden ({asset})",
        "pl": "Serwisuj {part} ({asset})",
        "pt-BR": "Revisar {part} ({asset})",
        "ru": "Обслуживание {part} ({asset})",
        "sv": "Serva {part} ({asset})",
        "zh-Hans": "保养 {part}（{asset}）",  # noqa: RUF001 — full-width parens are zh-Hans convention
    },
    PART_ACTION_RENEW: {
        "en": "Renew {part} ({asset})",
        "ca": "Renovar {part} ({asset})",
        "cs": "Obnovit {part} ({asset})",
        "da": "Forny {part} ({asset})",
        "de": "{part} erneuern ({asset})",
        "es": "Renovar {part} ({asset})",
        "fi": "Uusi {part} ({asset})",
        "fr": "Renouveler {part} ({asset})",
        "it": "Rinnovare {part} ({asset})",
        "nb": "Forny {part} ({asset})",
        "nl": "{part} vernieuwen ({asset})",
        "pl": "Odnów {part} ({asset})",
        "pt-BR": "Renovar {part} ({asset})",
        "ru": "Обновление {part} ({asset})",
        "sv": "Förnya {part} ({asset})",
        "zh-Hans": "翻新 {part}（{asset}）",  # noqa: RUF001 — full-width parens are zh-Hans convention
    },
    PART_ACTION_SHARPEN: {
        "en": "Sharpen {part} ({asset})",
        "ca": "Esmolar {part} ({asset})",
        "cs": "Nabrousit {part} ({asset})",
        "da": "Slib {part} ({asset})",
        "de": "{part} schärfen ({asset})",
        "es": "Afilar {part} ({asset})",
        "fi": "Teroita {part} ({asset})",
        "fr": "Affûter {part} ({asset})",
        "it": "Affilare {part} ({asset})",
        "nb": "Slip {part} ({asset})",
        "nl": "{part} slijpen ({asset})",
        "pl": "Naostrz {part} ({asset})",
        "pt-BR": "Afiar {part} ({asset})",
        "ru": "Заточка {part} ({asset})",
        "sv": "Slipa {part} ({asset})",
        "zh-Hans": "磨利 {part}（{asset}）",  # noqa: RUF001 — full-width parens are zh-Hans convention
    },
    PART_ACTION_ROTATE: {
        "en": "Rotate {part} ({asset})",
        "ca": "Rotar {part} ({asset})",
        "cs": "Prohodit {part} ({asset})",
        "da": "Rotér {part} ({asset})",
        "de": "{part} rotieren ({asset})",
        "es": "Rotar {part} ({asset})",
        "fi": "Kierrätä {part} ({asset})",
        "fr": "Permuter {part} ({asset})",
        "it": "Ruotare {part} ({asset})",
        "nb": "Roter {part} ({asset})",
        "nl": "{part} roteren ({asset})",
        "pl": "Rotuj {part} ({asset})",
        "pt-BR": "Rodiziar {part} ({asset})",
        "ru": "Ротация {part} ({asset})",
        "sv": "Rotera {part} ({asset})",
        "zh-Hans": "换位 {part}（{asset}）",  # noqa: RUF001 — full-width parens are zh-Hans convention
    },
    PART_ACTION_INSPECT: {
        "en": "Inspect {part} ({asset})",
        "ca": "Inspeccionar {part} ({asset})",
        "cs": "Zkontrolovat {part} ({asset})",
        "da": "Efterse {part} ({asset})",
        "de": "{part} prüfen ({asset})",
        "es": "Inspeccionar {part} ({asset})",
        "fi": "Tarkasta {part} ({asset})",
        "fr": "Inspecter {part} ({asset})",
        "it": "Ispezionare {part} ({asset})",
        "nb": "Kontroller {part} ({asset})",
        "nl": "{part} inspecteren ({asset})",
        "pl": "Sprawdź {part} ({asset})",
        "pt-BR": "Inspecionar {part} ({asset})",
        "ru": "Проверка {part} ({asset})",
        "sv": "Inspektera {part} ({asset})",
        "zh-Hans": "检查 {part}（{asset}）",  # noqa: RUF001 — full-width parens are zh-Hans convention
    },
}
# The word substituted for ``{asset}`` when an appliance has no name yet. Mirrors the
# panel's ``appliance.fallbackName`` locale key so the two stay consistent.
APPLIANCE_FALLBACK_NAMES: dict[str, str] = {
    "en": "Appliance",
    "ca": "Electrodomèstic",
    "cs": "Spotřebič",
    "da": "Apparat",
    "de": "Gerät",
    "es": "Electrodoméstico",
    "fi": "Laite",
    "fr": "Appareil",
    "it": "Elettrodomestico",
    "nb": "Apparat",
    "nl": "Apparaat",
    "pl": "Urządzenie",
    "pt-BR": "Eletrodoméstico",
    "ru": "Устройство",
    "sv": "Apparat",
    "zh-Hans": "电器",
}


def _pick_localized(table: dict[str, str], language: str | None) -> str:
    """Resolve *language* against *table*: exact → case-insensitive → base → English.

    Mirrors the panel's ``i18n.resolve`` so a code like ``"pt-BR"`` matches exactly,
    ``"en-GB"`` falls back to ``"en"``, and anything unknown lands on English. Pure —
    safe to unit-test without a Home Assistant runtime.
    """
    lang = language or DEFAULT_LANGUAGE
    if lang in table:
        return table[lang]
    low = lang.lower()
    for key, value in table.items():
        if key.lower() == low:
            return value
    base = low.split("-")[0]
    for key, value in table.items():
        if key.lower() == base:
            return value
    return table[DEFAULT_LANGUAGE]


def resolve_wear_task_naming(language: str | None) -> tuple[str, str]:
    """Return ``(name_template, appliance_fallback)`` for *language*.

    Used by ``store.reconcile_part_tasks`` to localize the generated wear-part task
    name to Home Assistant's configured language before handing the strings to the
    pure reconciler.
    """
    return (
        _pick_localized(WEAR_TASK_NAME_TEMPLATES, language),
        _pick_localized(APPLIANCE_FALLBACK_NAMES, language),
    )


def resolve_buy_task_naming(language: str | None) -> str:
    """Return the ``"Buy {part}"`` name template for *language*.

    Used by ``store.reconcile_buy_tasks`` to localize the generated buy-task name to
    Home Assistant's configured language before handing it to the pure reconciler.
    """
    return _pick_localized(BUY_TASK_NAME_TEMPLATES, language)


def resolve_use_task_naming(language: str | None) -> str:
    """Return the ``"Use {asset}"`` name template for *language*.

    Used by ``store.reconcile_part_tasks`` to localize a counted wear item's use-task
    name before handing it to the pure reconciler. A part that sets ``use_task_name``
    overrides the result outright.
    """
    return _pick_localized(USE_TASK_NAME_TEMPLATES, language)


def resolve_action_task_naming(action: str | None, language: str | None) -> str:
    """Return the ``"<Action> {part} ({asset})"`` template for *action* in *language*.

    An unknown or absent action falls back to ``replace``, which is what every wear
    part written before actions existed carries. That fallback is the whole migration:
    the resolved string for such a part is byte-identical to the one it already had.
    """
    table = ACTION_TASK_NAME_TEMPLATES.get(action or PART_ACTION_REPLACE)
    if table is None:
        table = ACTION_TASK_NAME_TEMPLATES[PART_ACTION_REPLACE]
    return _pick_localized(table, language)
