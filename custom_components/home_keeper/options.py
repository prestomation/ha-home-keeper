"""Shared read/write helpers for the config-entry ``options``.

Three surfaces edit the same options object — the **options flow**
(``config_flow.HomeKeeperOptionsFlow``), the **``set_options`` service**, and the
**panel's Settings tab** (over the ``home_keeper/get_options`` /
``home_keeper/set_options`` websocket commands). The key list, defaults, and
normalization live here so they can't drift. Writing options goes through
``hass.config_entries.async_update_entry``, which fires the entry's update listener
(wired in ``__init__``). The listener calls the coordinator's ``async_apply_options``,
which applies the change live, or reloads the entry when the change adds, removes or
renames an entity (``reload_needed``, #467). The service / websocket path
(``async_set_options``) additionally *awaits* that apply so the caller sees the
reconciled task set immediately (the options flow, which updates the entry directly,
still relies on the update listener).

Two of those three surfaces send a *partial* update, which ``_normalize`` merges onto
what is already stored. The options flow can't: Home Assistant stores whatever an
options flow returns from ``async_create_entry`` as ``entry.options`` **verbatim** —
the whole object, not a patch — and its form renders only ``FLOW_OPTIONS``. So it goes
through ``merge_flow_input``, which turns the submission back into a partial update.

This module imports Home Assistant only for type annotations, so the unit tier can
exercise the merge rules without the HA test harness. Keep it that way — see
``tests/unit/test_options.py``.
"""

from __future__ import annotations

from datetime import time
from typing import TYPE_CHECKING, Any

from . import cost_summary, notifications, profiles, shopping
from .const import (
    DEFAULT_DUE_TIME,
    DUE_TIME_MODE_COMPLETION,
    DUE_TIME_MODE_SET_TIME,
    DUE_TIME_MODES,
    MAX_ONE_OFF_RETENTION_DAYS,
    OPTION_ALLOW_DUE_TODAY,
    OPTION_ALLOW_SKIP,
    OPTION_ALLOW_SNOOZE,
    OPTION_COST_SUMMARY_PANEL,
    OPTION_COST_WINDOWS,
    OPTION_DISMISSED_COMPANIONS,
    OPTION_DUE_TIME,
    OPTION_DUE_TIME_MODE,
    OPTION_HIDDEN_PANEL_TABS,
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
    OPTION_TASK_DEVICE_ENTITIES,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

# The exclusion options, the dismissed-companions list and the hidden panel tabs are
# id/domain lists.
_LIST_OPTIONS = (
    OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS,
    OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS,
    OPTION_DISMISSED_COMPANIONS,
    OPTION_HIDDEN_PANEL_TABS,
)

# The plain on/off options. ``_normalize`` coerces each with ``bool()`` when a
# submission carries it, so they share one branch rather than accumulating an ``if``
# apiece. Note their *defaults* differ (see ``_empty_options``): problem-sensor syncing
# is opt-in, while snooze, skip and due today are on until someone turns them off.
_BOOL_OPTIONS = (
    OPTION_SYNC_PROBLEM_SENSORS,
    OPTION_ALLOW_SNOOZE,
    OPTION_ALLOW_SKIP,
    OPTION_ALLOW_DUE_TODAY,
    OPTION_COST_SUMMARY_PANEL,
    OPTION_TASK_DEVICE_ENTITIES,
)


def _empty_options() -> dict[str, Any]:
    """Every option key at its default: lists empty, pickers cleared.

    The single definition of *which keys exist* and *what each looks like holding
    nothing*. ``current_options`` builds on it and ``merge_flow_input`` resets a
    cleared form field to its entry here, so a default and a "cleared" value can
    never disagree. Returns a fresh dict each call — the list values are handed out
    to callers.

    "Nothing" is not always ``False``. ``allow_snooze`` / ``allow_skip`` /
    ``allow_due_today`` default to **True**, so a document written before they
    existed — every existing install — reads back with every verb available, which is
    what those installs already have. ``task_device_entities`` defaults to **True**
    for the same reason: each install had the per-task entities before the switch.
    """
    return {
        OPTION_SYNC_PROBLEM_SENSORS: False,
        OPTION_ALLOW_SNOOZE: True,
        OPTION_ALLOW_SKIP: True,
        OPTION_ALLOW_DUE_TODAY: True,
        OPTION_DUE_TIME_MODE: DUE_TIME_MODE_COMPLETION,
        OPTION_DUE_TIME: DEFAULT_DUE_TIME,
        OPTION_ONE_OFF_RETENTION_DAYS: 0,
        OPTION_SHOPPING_LIST_ENTITY: "",
        OPTION_SHOPPING_LINE_STYLE: shopping.LINE_STYLE_WITH_VERB,
        OPTION_PROFILES: [],
        OPTION_NOTIFICATIONS: [],
        OPTION_COST_WINDOWS: list(cost_summary.DEFAULT_WINDOWS),
        OPTION_COST_SUMMARY_PANEL: True,
        OPTION_TASK_DEVICE_ENTITIES: True,
        **{key: [] for key in _LIST_OPTIONS},
    }


# Every option key, in the order ``_empty_options`` declares them. A key missing from
# there is invisible to every reader and silently dropped by every writer, so
# ``tests/unit/test_options.py`` asserts this covers every ``const.OPTION_*``.
ALL_OPTIONS: tuple[str, ...] = tuple(_empty_options())

# The keys the options flow's form renders (``config_flow._options_schema``), in form
# order. A key here that a submission *omits* was cleared by the user and resets; a key
# **not** here is not the form's to touch and is preserved verbatim. Pinned to the
# schema by ``tests/unit/test_config_flow.py`` and to ``strings.json`` by
# ``tests/unit/test_options.py``.
FLOW_OPTIONS: tuple[str, ...] = (
    OPTION_SYNC_PROBLEM_SENSORS,
    OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS,
    OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS,
    OPTION_ONE_OFF_RETENTION_DAYS,
    OPTION_SHOPPING_LIST_ENTITY,
    OPTION_SHOPPING_LINE_STYLE,
    OPTION_DUE_TIME_MODE,
    OPTION_DUE_TIME,
)

# What a live options change asks of the running entry (#467). An options change
# that keeps the entity set is applied without a reload, because a reload writes
# ``unavailable`` for each entity and fills the logbook. Most readers read
# ``entry.options`` each time, so the coordinator refresh after the change is enough
# for them. The readers that keep a value from setup get a step.
APPLY_DUE_TIME = "due_time"  # the store keeps the set due time
APPLY_NOTIFICATIONS = "notifications"  # warn about a dropped notify target
APPLY_PROBLEM_SYNC = "problem_sync"  # the state listener and the synced tasks
APPLY_SHOPPING = "shopping"  # the shopping-list listener, then 1 pass
APPLY_TODO_LISTS = "todo_lists"  # the to-do list listeners, then 1 pass
APPLY_TASK_ENTITIES = "task_entities"  # disable or enable them in the registry

# The steps a change to each option needs. ``tests/unit/test_options_apply.py``
# asserts this covers every key, so a new option must say how it applies.
_APPLY_STEPS: dict[str, tuple[str, ...]] = {
    OPTION_SYNC_PROBLEM_SENSORS: (APPLY_PROBLEM_SYNC,),
    OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES: (APPLY_PROBLEM_SYNC,),
    OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES: (APPLY_PROBLEM_SYNC,),
    OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS: (APPLY_PROBLEM_SYNC,),
    OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS: (APPLY_PROBLEM_SYNC,),
    OPTION_DUE_TIME_MODE: (APPLY_DUE_TIME,),
    OPTION_DUE_TIME: (APPLY_DUE_TIME,),
    OPTION_SHOPPING_LIST_ENTITY: (APPLY_SHOPPING,),
    OPTION_SHOPPING_LINE_STYLE: (APPLY_SHOPPING,),
    # The count sensors read their filter live. A profile's to-do list sync is in
    # the profile.
    OPTION_PROFILES: (APPLY_TODO_LISTS,),
    OPTION_NOTIFICATIONS: (APPLY_NOTIFICATIONS,),
    OPTION_ALLOW_SNOOZE: (),
    OPTION_ALLOW_SKIP: (),
    OPTION_ALLOW_DUE_TODAY: (),
    OPTION_ONE_OFF_RETENTION_DAYS: (),
    OPTION_COST_WINDOWS: (),
    OPTION_COST_SUMMARY_PANEL: (),
    OPTION_TASK_DEVICE_ENTITIES: (APPLY_TASK_ENTITIES,),
    OPTION_DISMISSED_COMPANIONS: (),
    OPTION_HIDDEN_PANEL_TABS: (),
}


def options_entity_key(opts: dict[str, Any]) -> tuple[frozenset[Any], frozenset[Any]]:
    """The part of normalized *opts* that decides which entities exist.

    1 spend sensor exists for each cost window, and 1 count sensor for each profile,
    with the profile name in the entity name. The order of either list makes no
    entity, so the key holds sets.
    """
    return (
        frozenset(opts[OPTION_COST_WINDOWS]),
        frozenset((p["id"], p["name"]) for p in opts[OPTION_PROFILES]),
    )


def reload_needed(old: dict[str, Any], new: dict[str, Any]) -> bool:
    """Whether a change from normalized *old* to *new* must reload the entry.

    Only the platform setup adds, removes or renames an entity.
    """
    return options_entity_key(old) != options_entity_key(new)


def apply_steps(old: dict[str, Any], new: dict[str, Any]) -> frozenset[str]:
    """The live steps a change from normalized *old* to *new* needs."""
    return frozenset(
        step
        for key, steps in _APPLY_STEPS.items()
        if old.get(key) != new.get(key)
        for step in steps
    )


# Entry ids whose options change an explicit caller (the ``set_options`` service /
# the panel's websocket command) is already applying. The config-entry update
# listener (``__init__._async_options_updated``) consults this so it doesn't apply
# the same change a *second* time.
_CALLER_APPLYING: set[str] = set()


def caller_is_applying(entry_id: str) -> bool:
    """Whether an ``async_set_options`` caller is already applying *entry_id*."""
    return entry_id in _CALLER_APPLYING


# Entry ids whose last ``async_set_options`` write lowered the one-off retention. The
# coordinator skips the purge once for each, in the first refresh after the write.
# A lower retention deletes tasks for good, so it takes effect one periodic tick
# after the write, not in the refresh of the write. A value that is only on its way to
# a higher number (the "3" of "30") then deletes no task, because the next write
# replaces it before the purge reads it.
_RETENTION_GRACE: set[str] = set()


def retention_lowered(old: int, new: int) -> bool:
    """Whether a retention change from *old* to *new* can delete more tasks.

    ``0`` keeps completed one-offs forever, so any positive value lowers it.
    """
    return new > 0 and (old == 0 or new < old)


def take_retention_grace(entry_id: str) -> bool:
    """Return True once after a write lowered *entry_id*'s retention, then False."""
    if entry_id in _RETENTION_GRACE:
        _RETENTION_GRACE.discard(entry_id)
        return True
    return False


def normalize_due_time(value: Any) -> str:
    """*value* as a local ``"HH:MM"``, or ``DEFAULT_DUE_TIME`` when it is not a time.

    A time selector sends ``"HH:MM:SS"``, and a service caller may send ``"8:00"``.
    Seconds are dropped: a due time is a time of day, not a moment.
    """
    return _parse_due_time(value) or DEFAULT_DUE_TIME


def _parse_due_time(value: Any) -> str | None:
    """*value* as a local ``"HH:MM"``, or ``None`` when it is not a time."""
    if isinstance(value, time):
        return f"{value.hour:02d}:{value.minute:02d}"
    parts = str(value or "").strip().split(":")
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        return None
    hour, minute = int(parts[0]), int(parts[1])
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def due_time_of(opts: dict[str, Any]) -> time | None:
    """The set due time of normalized *opts*, or ``None`` in the ``completion`` mode."""
    if opts.get(OPTION_DUE_TIME_MODE) != DUE_TIME_MODE_SET_TIME:
        return None
    hour, minute = normalize_due_time(opts.get(OPTION_DUE_TIME)).split(":")
    return time(int(hour), int(minute))


def current_options(entry: ConfigEntry) -> dict[str, Any]:
    """Return the entry's options with every key defaulted (toggle off, lists empty).

    A fully-populated dict keeps the panel form and the options flow simple — they
    never have to special-case a missing key.

    Reading is just ``_normalize`` over the defaults: what's stored is a partial
    update onto an empty options object. Sharing the one coercion table means a read
    and a write can't disagree about a key's shape, which is what makes
    ``async_set_options``' ``merged == base`` short-circuit trustworthy.
    """
    return _normalize(dict(entry.options), _empty_options(), read=True)


# The device-id lists in a profile filter. A profile filter matches a task on these.
_PROFILE_DEVICE_KEYS = ("devices", "exclude_devices")


def _repoint_ids(ids: Any, mapping: dict[str, str]) -> list[str] | None:
    """*ids* with each id in *mapping* replaced; ``None`` when nothing changed.

    Keeps the order and removes a duplicate that the replacement makes (two dead ids
    of one device map to one live id).
    """
    if not isinstance(ids, list) or not any(i in mapping for i in ids):
        return None
    values: list[str] = ids
    return list(dict.fromkeys(mapping.get(i, i) for i in values))


def device_ids_in_options(options: dict[str, Any]) -> set[str]:
    """Every device id that *options* refers to.

    These are the problem-sensor device exclusions and the device lists of each
    profile filter. The device-split repair in ``devices.py`` resolves them.
    """
    found = set(options.get(OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES) or [])
    for profile in options.get(OPTION_PROFILES) or []:
        filt = profile.get("filter") if isinstance(profile, dict) else None
        if not isinstance(filt, dict):
            continue
        for key in _PROFILE_DEVICE_KEYS:
            found.update(filt.get(key) or [])
    return found


def repoint_device_ids(
    options: dict[str, Any], mapping: dict[str, str]
) -> dict[str, Any] | None:
    """*options* with each dead device id in *mapping* set to its live id.

    Home Assistant 2026.8 gave some devices a new id (#183). The repair moves the
    tasks and the appliances to the new id, and this moves the options that refer to
    a device: the problem-sensor device exclusions and the profile device filters.
    Returns a new options dict, or ``None`` when no id changed, so the caller writes
    the entry only when it must. *options* is not changed.
    """
    result = dict(options)
    # None reads as False in the return below, so that mutant is equivalent.
    changed = False  # pragma: no mutate
    excluded = _repoint_ids(options.get(OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES), mapping)
    if excluded is not None:
        result[OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES] = excluded
        changed = True
    new_profiles: list[Any] = []
    for profile in options.get(OPTION_PROFILES) or []:
        filt = profile.get("filter") if isinstance(profile, dict) else None
        if not isinstance(filt, dict):
            new_profiles.append(profile)
            continue
        new_filt = dict(filt)
        for key in _PROFILE_DEVICE_KEYS:
            ids = _repoint_ids(filt.get(key), mapping)
            if ids is not None:
                new_filt[key] = ids
                changed = True
        new_profiles.append({**profile, "filter": new_filt})
    if OPTION_PROFILES in options:
        result[OPTION_PROFILES] = new_profiles
    return result if changed else None


def _coerce_days(value: Any) -> int:
    """Coerce a retention-days value to an int in ``0..MAX_ONE_OFF_RETENTION_DAYS``.

    Garbage and negatives read as ``0``. A value above the maximum reads as the
    maximum. This is the read path too, so a value stored before the clamp existed
    reads back clamped, and the entry loads again with no user action.
    """
    try:
        days = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    # ``>= 0`` is equivalent: min(0, MAX) is 0 as well.
    return min(days, MAX_ONE_OFF_RETENTION_DAYS) if days > 0 else 0  # pragma: no mutate


def _normalize(
    updates: dict[str, Any], base: dict[str, Any], *, read: bool = False
) -> dict[str, Any]:
    """Merge *updates* onto *base*, coercing to the stored shape (bool/int/id list).

    The one coercion table, shared by every read and every write. Each branch exists
    because the value can arrive from a form, a service call or an automation, none of
    which is obliged to send the stored shape:

    - **the on/off toggles** — anything truthy becomes a real ``bool``
    - **retention days** — a ``NumberSelector`` sends a float, garbage becomes ``0``
    - **the shopping target** — anything unusable collapses to ``""``, the off switch
    - **the shopping line style** — anything unknown reads as ``with_verb``
    - **the due time mode** — anything unknown reads as ``completion``; the due time
      reads as ``"HH:MM"``, and anything that is not a time as ``08:00``
    - **profiles / notifications** — their own normalizers fill in per-item defaults
      (a profile's to-do-list sync block among them)
    - **id lists** — stringified, and empties dropped: no registry id is falsy, and
      without the filter a ``None`` in the list would be stored as ``"None"``. A
      value that is not a list is refused and the value from *base* stays, so a
      string is not split into 1-character ids. ``None`` clears the list

    A key absent from *updates* keeps its value from *base*, which is what makes an
    update partial.

    *read* is ``True`` on the read path, so a dropped notify target is not logged
    again on each read (B16-11).
    """
    merged = dict(base)
    for key in _BOOL_OPTIONS:
        if key in updates:
            merged[key] = bool(updates[key])
    if OPTION_ONE_OFF_RETENTION_DAYS in updates:
        merged[OPTION_ONE_OFF_RETENTION_DAYS] = _coerce_days(
            updates[OPTION_ONE_OFF_RETENTION_DAYS]
        )
    if OPTION_SHOPPING_LIST_ENTITY in updates:
        # ``normalize_target`` collapses anything unusable (a cleared picker, an
        # entity outside the ``todo`` domain) to ``""``, the off switch. The
        # driver's registry check is the gate that also refuses Home Keeper's own
        # to-do list — a pure coercion cannot see entity platforms.
        merged[OPTION_SHOPPING_LIST_ENTITY] = shopping.normalize_target(
            updates[OPTION_SHOPPING_LIST_ENTITY]
        )
    if OPTION_DUE_TIME_MODE in updates:
        mode = updates[OPTION_DUE_TIME_MODE]
        merged[OPTION_DUE_TIME_MODE] = (
            mode if mode in DUE_TIME_MODES else DUE_TIME_MODE_COMPLETION
        )
    if OPTION_DUE_TIME in updates:
        merged[OPTION_DUE_TIME] = normalize_due_time(updates[OPTION_DUE_TIME])
    if OPTION_SHOPPING_LINE_STYLE in updates:
        merged[OPTION_SHOPPING_LINE_STYLE] = shopping.normalize_line_style(
            updates[OPTION_SHOPPING_LINE_STYLE]
        )
    if OPTION_COST_WINDOWS in updates:
        merged[OPTION_COST_WINDOWS] = cost_summary.normalize_windows(
            updates[OPTION_COST_WINDOWS]
        )
    if OPTION_PROFILES in updates:
        merged[OPTION_PROFILES] = profiles.normalize_profiles(updates[OPTION_PROFILES])
    if OPTION_NOTIFICATIONS in updates:
        merged[OPTION_NOTIFICATIONS] = notifications.normalize_notifications(
            updates[OPTION_NOTIFICATIONS], warn=not read
        )
    for key in _LIST_OPTIONS:
        if key not in updates:
            continue
        value = updates[key]
        if value is None:
            merged[key] = []
        elif isinstance(value, list):
            merged[key] = [str(x) for x in value if x]
    return merged


def coerce_value(key: str, value: Any) -> Any:
    """*value* in the stored shape of the option *key*, as ``_normalize`` writes it."""
    return _normalize({key: value}, _empty_options(), read=True)[key]


def value_refused(key: str, value: Any) -> bool:
    """Whether *value* is not a value of the option *key*.

    ``_normalize`` reads any value, and changes a bad value to a default. A value that
    it must change to store is refused here, so the settings import can warn about it.
    A due time in another time format, such as ``"8:00"``, is a value.
    """
    if key == OPTION_DUE_TIME:
        return _parse_due_time(value) is None
    stored = coerce_value(key, value)
    return type(stored) is not type(value) or stored != value


def merge_flow_input(entry: ConfigEntry, user_input: dict[str, Any]) -> dict[str, Any]:
    """Merge an options-*flow* submission onto *entry*'s current options.

    Home Assistant stores whatever an options flow returns from
    ``async_create_entry`` as ``entry.options`` **verbatim** — the whole object, not a
    patch. The form renders only ``FLOW_OPTIONS``, so returning the submission as-is
    deleted every saved profile, notification and dismissed companion on each save,
    and notifications then stopped firing (``notifier`` reads a missing key back as an
    empty list, so there was nothing on screen to say why). Start from
    ``current_options`` and change nothing the form doesn't own.

    A ``FLOW_OPTIONS`` key *missing* from *user_input* was **cleared** by the user and
    resets to its ``_empty_options`` value — the opposite of a key the form doesn't
    render, which is preserved. That distinction is load-bearing:
    ``shopping_list_entity`` is declared with no voluptuous ``default`` precisely so a
    cleared picker drops out of the submission, and that absence is how the
    shopping-list mirror is turned off. A plain ``{**current, **user_input}`` would
    resurrect the old entity id instead.

    Keys outside ``FLOW_OPTIONS`` are ignored even when present: the form can only
    change what the form owns.

    This is the options flow's entry point and nothing else's. The ``set_options``
    service and the panel's Settings tab already send partial updates, so they go
    through ``async_set_options``, which persists and applies as well.
    """
    empty = _empty_options()
    submitted = {
        key: user_input[key] if key in user_input else empty[key]
        for key in FLOW_OPTIONS
    }
    return _normalize(submitted, current_options(entry))


class ProfileInUseError(ValueError):
    """A save removes a profile that a surviving notification still names.

    A notification points at a profile by ``profile_id`` to say which tasks it sends.
    Delete the profile and the notification keeps the id but finds nothing behind it,
    so ``notifier`` sends nothing and the person who made the notification gets no
    signal. This is raised in place of that silence.

    A ``ValueError`` subclass, the same as ``models.TaskValidationError`` and
    ``assets.AssetValidationError``: this module stays free of Home Assistant imports
    at run time, so it cannot raise ``ServiceValidationError`` itself. The two callers
    of :func:`async_set_options` each convert it. The joined, de-duplicated strings are
    attributes so both callers fill in the same translation placeholders and neither
    builds a message of its own.
    """

    def __init__(self, blocked: list[tuple[str, str]]) -> None:
        self.profiles = ", ".join(dict.fromkeys(name for name, _ in blocked))
        self.notifications = ", ".join(dict.fromkeys(name for _, name in blocked))
        super().__init__(f"{self.profiles}: {self.notifications}")


def profile_removals_in_use(
    base: dict[str, Any], merged: dict[str, Any]
) -> list[tuple[str, str]]:
    """Pairs of (profile name, notification name) that *merged* would strand.

    The question is not "which notifications use profile X" but "which profiles does
    **this save** remove, and does a notification that **survives the same save** still
    name one". That is a before-and-after question, which is why it lives here rather
    than in ``profiles.py`` (deliberately decoupled from notifications) or in
    ``notifications.py`` (which sees one list, at one moment).

    Four reads carry the behaviour:

    - what **existed** comes from *base*, what **survives** from *merged*, so a save
      that sends no ``profiles`` key removes nothing and can never block
    - the references come from ***merged*'s** notifications, never *base*'s, so one
      save that deletes a profile together with its notifications is allowed
    - only a reference that resolved before this save is a candidate, so an options
      document that already holds a dangling ``profile_id`` still reads and writes —
      that state is designed (``notifier._notification_profile``), documented, and
      reachable from a backup
    - a reference resolves the way the notifier resolves it, with
      ``profiles.resolve_profile``: by id, then by name. A notification that names
      its profile is then blocked like one that holds the id, and for that
      notification a rename is a removal (B19-3). For an id, a rename is not a
      removal

    Both arguments are **normalized** documents — ``current_options`` and
    ``_normalize`` are the only two things that produce them, and both hold every
    option key and give every profile an ``id`` and a ``name`` (see
    ``profiles.normalize_profile``). So this indexes rather than defending: a missing
    key here is a bug in the caller, and a ``KeyError`` says so instead of quietly
    returning "nothing is in the way" and writing the save through.
    """
    before_profiles = base[OPTION_PROFILES]
    after_profiles = merged[OPTION_PROFILES]
    blocked: list[tuple[str, str]] = []
    for notification in merged[OPTION_NOTIFICATIONS]:
        # ``profile_id`` is None for a notification that covers every due task. That
        # is a **valid** value, not malformed input, and it has to fall through: such
        # a notification names no profile, so no profile removal can strand it.
        # ``resolve_profile`` answers None for it. Do not "harden" this into a string
        # check — that would make a None read as a blocker.
        # ``test_a_notification_with_no_profile_is_never_a_blocker`` pins it.
        reference = notification["profile_id"]
        before = profiles.resolve_profile(before_profiles, reference)
        if before is None:
            continue
        if profiles.resolve_profile(after_profiles, reference) is None:
            blocked.append((before["name"], notification["name"]))
    return blocked


async def async_set_options(
    hass: HomeAssistant, entry: ConfigEntry, updates: dict[str, Any]
) -> dict[str, Any]:
    """Apply a partial options *updates* to *entry* and persist; returns the merged set.

    Only the keys present in *updates* change (the panel saves the whole form, but
    the service / an automation may set just one).

    When the options actually change we **await** the coordinator's
    ``async_apply_options``, so the caller observes the reconciled state — synced
    problem-sensor tasks created/removed for the new exclusions — by the time this
    returns. That applies the change live, or reloads the entry when the entity set
    changes (#467). An entry that is not loaded has no coordinator, so it is
    reloaded, which sets it up with the new options. The entry is flagged for the
    duration so the update listener does not apply the change again.
    """
    base = current_options(entry)
    merged = _normalize(updates, base)
    if merged == base:
        # No effective change — nothing to persist, and nothing to apply.
        return merged
    if blocked := profile_removals_in_use(base, merged):
        # Before the write, so a refused save changes nothing, and after the
        # short-circuit above, because a save that changes nothing removes nothing.
        # The guard is on this write path only: ``_normalize`` and ``current_options``
        # are also the **read** path, and an options document that already holds a
        # dangling ``profile_id`` has to keep reading back.
        raise ProfileInUseError(blocked)
    if retention_lowered(
        base[OPTION_ONE_OFF_RETENTION_DAYS], merged[OPTION_ONE_OFF_RETENTION_DAYS]
    ):
        _RETENTION_GRACE.add(entry.entry_id)
    _CALLER_APPLYING.add(entry.entry_id)
    try:
        hass.config_entries.async_update_entry(entry, options=merged)
        coordinator = getattr(entry, "runtime_data", None)
        if coordinator is None:
            await hass.config_entries.async_reload(entry.entry_id)
        else:
            await coordinator.async_apply_options()
    finally:
        _CALLER_APPLYING.discard(entry.entry_id)
    return merged
