"""Constants for the Home Keeper integration."""

DOMAIN = "home_keeper"

# Entity platforms forwarded from the config entry.
PLATFORMS = ["todo", "calendar", "button", "sensor", "binary_sensor", "number"]

# Frontend panel.
# PANEL_VERSION is the single source of truth that release.yml validates against
# manifest.json's "version" (mirrors Pawsistant's CARD_VERSION check).
PANEL_VERSION = "0.9.0b1"
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
MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
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
# Catalog glue domains the user dismissed from the Settings → Companions
# "Suggested" list. A list of domain strings; dismissing only silences a
# *suggestion* (a connected pairing is always shown). See companions.py.
OPTION_DISMISSED_COMPANIONS = "dismissed_companions"
# Profiles: named, reusable task filters (status + label/area/device). Standalone and
# notification-agnostic — consumed by notifications, the panel's admin list filter, and
# the Lovelace card. A list of ``{id, name, filter}``. See profiles.py.
OPTION_PROFILES = "profiles"
# Notifications: delivery bindings that reference a profile by ``profile_id`` and add
# how to deliver (targets, button set, snooze duration, style, automatic triggers).
# Edited from the panel's Settings → Notifications card and the set_options service;
# consumed by the notify service, the action listener, and the coordinator's automatic
# source. See notifications.py and docs/PROFILES_REFACTOR_PLAN.md.
OPTION_NOTIFICATIONS = "notifications"

# Opaque ``origin`` marker the actionable-notification action listener passes to
# ``complete_task`` / ``snooze_task`` / ``skip_task`` so an automation can recognise
# (and ignore) the completion/snooze it triggered from a notification tap.
ORIGIN_NOTIFICATION_ACTION = f"{DOMAIN}_notification_action"


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
# numeric sensor rather than the clock. Like ``triggered`` its ``next_due`` *is* its
# state (``None`` = dormant, a timestamp = armed/due-now), but Home Keeper itself —
# not an external owner — arms it via a pure evaluator fed by the live reading. The
# binding lives in ``task["sensor"]`` (see ``models.normalize_sensor`` /
# ``sensor_tasks.py``). Two modes: ``usage`` (a meter — due after the reading
# advances ``target`` units since the last completion) and ``threshold`` (due when
# the reading crosses a comparison). See docs/SENSOR_TASKS_PLAN.md.
REC_SENSOR = "sensor"
RECURRENCE_TYPES = [REC_FLOATING, REC_FIXED, REC_TRIGGERED, REC_ONE_OFF, REC_SENSOR]

# Sensor-based task modes.
SENSOR_MODE_USAGE = "usage"  # meter: arm when reading - baseline >= target
SENSOR_MODE_THRESHOLD = "threshold"  # arm on a numeric crossing of value
SENSOR_MODES = [SENSOR_MODE_USAGE, SENSOR_MODE_THRESHOLD]

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
