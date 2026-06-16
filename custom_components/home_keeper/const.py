"""Constants for the Home Keeper integration."""

DOMAIN = "home_keeper"

# Entity platforms forwarded from the config entry.
PLATFORMS = ["todo", "calendar", "button", "sensor", "binary_sensor"]

# Frontend panel.
# PANEL_VERSION is the single source of truth that release.yml validates against
# manifest.json's "version" (mirrors Pawsistant's CARD_VERSION check).
PANEL_VERSION = "0.2.0"
PANEL_URL_PATH = "home-keeper"  # sidebar route -> /home-keeper
PANEL_STATIC_URL = "/home_keeper_panel"  # static path that serves the JS bundle
PANEL_JS_FILENAME = "home-keeper-panel.js"
PANEL_TITLE = "Home Keeper"
PANEL_ICON = "mdi:home-clock"
WEBCOMPONENT_NAME = "home-keeper-panel"

# Storage.
STORAGE_KEY = "home_keeper"
STORAGE_VERSION = 1
# How many completion timestamps to retain per task. Generous so the panel's task
# history shows years of cadence (e.g. 500 monthly completions ≈ 40 years) while
# still bounding the stored list. When a task that belongs to an appliance is
# deleted, this history is archived onto the appliance (see ``assets.append_task_history``).
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


# Recurrence types.
REC_FLOATING = "floating"
REC_FIXED = "fixed"
RECURRENCE_TYPES = [REC_FLOATING, REC_FIXED]

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
SIGNAL_TASK_CONTRIBUTION = f"{DOMAIN}_task_contribution"  # noqa: F841  (reserved)

# Well-known field on a task dict that Home Keeper inspects (unlike the opaque
# ``source`` field). Declares the integration that owns the task: which fields
# are locked, whether deletion is protected, and display metadata for the UI.
TASK_MANAGED_BY = "managed_by"
