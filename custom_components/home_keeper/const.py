"""Constants for the Home Keeper integration."""

DOMAIN = "home_keeper"

# Entity platforms forwarded from the config entry.
PLATFORMS = ["todo", "calendar", "button", "sensor", "binary_sensor"]

# Frontend panel.
# PANEL_VERSION is the single source of truth that release.yml validates against
# manifest.json's "version" (mirrors Pawsistant's CARD_VERSION check).
PANEL_VERSION = "0.1.0b1"
PANEL_URL_PATH = "home-keeper"  # sidebar route -> /home-keeper
PANEL_STATIC_URL = "/home_keeper_panel"  # static path that serves the JS bundle
PANEL_JS_FILENAME = "home-keeper-panel.js"
PANEL_TITLE = "Home Keeper"
PANEL_ICON = "mdi:home-clock"
WEBCOMPONENT_NAME = "home-keeper-panel"

# Storage.
STORAGE_KEY = "home_keeper"
STORAGE_VERSION = 1
MAX_COMPLETION_HISTORY = 50

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

# DEFERRED (not implemented this prototype): a stable cross-integration contribution
# interface so integrations like Battery Notes can push maintenance tasks without
# this integration knowing anything about them. The intended hook is a dispatcher
# signal plus a `home_keeper.contribute_task` service. See docs/DESIGN.md.
SIGNAL_TASK_CONTRIBUTION = f"{DOMAIN}_task_contribution"  # noqa: F841  (reserved)
