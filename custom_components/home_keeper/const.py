"""Constants for the Home Keeper integration."""

DOMAIN = "home_keeper"

# Entity platforms forwarded from the config entry.
PLATFORMS = ["todo", "calendar", "button", "sensor", "binary_sensor"]

# Frontend panel.
# PANEL_VERSION is the single source of truth that release.yml validates against
# manifest.json's "version" (mirrors Pawsistant's CARD_VERSION check).
PANEL_VERSION = "0.3.0b12"
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
# How many completion timestamps to retain per task. Generous so the panel's task
# history shows years of cadence (e.g. 500 monthly completions ≈ 40 years) while
# still bounding the stored list. When a task that belongs to an appliance is
# deleted, this history is archived onto the appliance
# (see ``assets.append_task_history``).
MAX_COMPLETION_HISTORY = 500

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
# Time-based transitions — fired (edge-triggered) from the coordinator. A task is
# announced at most once per ``next_due`` value while HA is running; see
# transitions.detect_transitions and coordinator._async_update_data.
EVENT_TASK_OVERDUE = f"{DOMAIN}_task_overdue"  # + ``days_overdue``
EVENT_TASK_DUE_SOON = f"{DOMAIN}_task_due_soon"  # + ``due_in_hours``
# Stock transitions — the siblings of EVENT_PART_LOW_STOCK, edge-triggered the same
# way (see assets.stock_transition). out_of_stock wins over low on a single step.
EVENT_PART_OUT_OF_STOCK = f"{DOMAIN}_part_out_of_stock"
EVENT_PART_RESTOCKED = f"{DOMAIN}_part_restocked"
# Fired when a recorded completion's metadata (note/cost/photo/who) is edited
# after the fact — a state change distinct from completing/uncompleting. Carries
# the task spine plus the edited completion's ``ts``. See docs/EVENTS.md.
EVENT_TASK_COMPLETION_UPDATED = f"{DOMAIN}_task_completion_updated"
# Asset (appliance) lifecycle — fired at the store.py asset chokepoints.
EVENT_ASSET_CREATED = f"{DOMAIN}_asset_created"
EVENT_ASSET_UPDATED = f"{DOMAIN}_asset_updated"  # payload carries ``changed_fields``
EVENT_ASSET_DELETED = f"{DOMAIN}_asset_deleted"

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

# Marker on a task dict identifying it as derived from an asset part, so the
# part-task reconciler owns it: ``task["source"] = {"asset_id", "part_id"}``.
TASK_SOURCE_PART = "part"

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
# synced when the option is on. Lists of entity ids / area ids / label ids.
OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES = "problem_sensor_exclude_entities"
OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS = "problem_sensor_exclude_areas"
OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS = "problem_sensor_exclude_labels"
# Auto-delete a completed one-off task this many days after its completion. ``0``
# (the default) keeps completed one-offs forever; ``N > 0`` purges them once
# ``last_completed + N days`` has passed, via the coordinator's periodic refresh.
OPTION_ONE_OFF_RETENTION_DAYS = "one_off_retention_days"


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
RECURRENCE_TYPES = [REC_FLOATING, REC_FIXED, REC_TRIGGERED, REC_ONE_OFF]

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

# Floating interval units.
UNIT_DAYS = "days"
UNIT_WEEKS = "weeks"
UNIT_MONTHS = "months"
UNITS = [UNIT_DAYS, UNIT_WEEKS, UNIT_MONTHS]

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

# DEFERRED (not implemented this prototype): a stable cross-integration contribution
# interface so integrations like Battery Notes can push maintenance tasks without
# this integration knowing anything about them. The intended hook is a dispatcher
# signal plus a `home_keeper.contribute_task` service. See docs/DESIGN.md.
SIGNAL_TASK_CONTRIBUTION = f"{DOMAIN}_task_contribution"

# Well-known field on a task dict that Home Keeper inspects (unlike the opaque
# ``source`` field). Declares the integration that owns the task: which fields
# are locked, whether deletion is protected, and display metadata for the UI.
TASK_MANAGED_BY = "managed_by"
