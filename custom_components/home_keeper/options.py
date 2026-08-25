"""Shared read/write helpers for the config-entry ``options``.

Three surfaces edit the same options object — the **options flow**
(``config_flow.HomeKeeperOptionsFlow``), the **``set_options`` service**, and the
**panel's Settings tab** (over the ``home_keeper/get_options`` /
``home_keeper/set_options`` websocket commands). The key list, defaults, and
normalization live here so they can't drift. Writing options goes through
``hass.config_entries.async_update_entry``, which fires the entry's update listener
(wired in ``__init__``) and reloads — re-running the problem-sensor reconcile. The
service / websocket path (``async_set_options``) additionally *awaits* that reload so
the caller sees the reconciled task set immediately (the options flow, which updates
the entry directly, still relies on the update listener).

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

from typing import TYPE_CHECKING, Any

from . import notifications, profiles, shopping, task_mirror
from .const import (
    OPTION_DISMISSED_COMPANIONS,
    OPTION_NOTIFICATIONS,
    OPTION_ONE_OFF_RETENTION_DAYS,
    OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS,
    OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS,
    OPTION_PROFILES,
    OPTION_SHOPPING_LIST_ENTITY,
    OPTION_SYNC_PROBLEM_SENSORS,
    OPTION_TASK_MIRRORS,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

# The exclusion options (and the dismissed-companions list) are id/domain lists;
# the sync toggle is the only boolean.
_LIST_OPTIONS = (
    OPTION_PROBLEM_SENSOR_EXCLUDE_ENTITIES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_DEVICES,
    OPTION_PROBLEM_SENSOR_EXCLUDE_AREAS,
    OPTION_PROBLEM_SENSOR_EXCLUDE_LABELS,
    OPTION_DISMISSED_COMPANIONS,
)


def _empty_options() -> dict[str, Any]:
    """Every option key at its default: toggle off, lists empty, pickers cleared.

    The single definition of *which keys exist* and *what each looks like holding
    nothing*. ``current_options`` builds on it and ``merge_flow_input`` resets a
    cleared form field to its entry here, so a default and a "cleared" value can
    never disagree. Returns a fresh dict each call — the list values are handed out
    to callers.
    """
    return {
        OPTION_SYNC_PROBLEM_SENSORS: False,
        OPTION_ONE_OFF_RETENTION_DAYS: 0,
        OPTION_SHOPPING_LIST_ENTITY: "",
        OPTION_PROFILES: [],
        OPTION_NOTIFICATIONS: [],
        OPTION_TASK_MIRRORS: [],
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
)

# Entry ids whose reload an explicit caller (the ``set_options`` service / the
# panel's websocket command) is already awaiting. The config-entry update
# listener (``__init__._async_options_updated``) consults this so it doesn't fire
# a *second*, overlapping reload for the same change.
_CALLER_RELOADING: set[str] = set()


def caller_is_reloading(entry_id: str) -> bool:
    """Whether an ``async_set_options`` caller is already reloading *entry_id*."""
    return entry_id in _CALLER_RELOADING


def current_options(entry: ConfigEntry) -> dict[str, Any]:
    """Return the entry's options with every key defaulted (toggle off, lists empty).

    A fully-populated dict keeps the panel form and the options flow simple — they
    never have to special-case a missing key.

    Reading is just ``_normalize`` over the defaults: what's stored is a partial
    update onto an empty options object. Sharing the one coercion table means a read
    and a write can't disagree about a key's shape, which is what makes
    ``async_set_options``' ``merged == base`` short-circuit trustworthy.
    """
    return _normalize(dict(entry.options), _empty_options())


def _coerce_days(value: Any) -> int:
    """Coerce a retention-days value to a non-negative int (garbage/negative -> 0)."""
    try:
        days = int(value)
    except (TypeError, ValueError):
        return 0
    return days if days > 0 else 0


def _normalize(updates: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """Merge *updates* onto *base*, coercing to the stored shape (bool/int/id list).

    The one coercion table, shared by every read and every write. Each branch exists
    because the value can arrive from a form, a service call or an automation, none of
    which is obliged to send the stored shape:

    - **the sync toggle** — anything truthy becomes a real ``bool``
    - **retention days** — a ``NumberSelector`` sends a float, garbage becomes ``0``
    - **the shopping target** — anything unusable collapses to ``""``, the off switch
    - **profiles / notifications / task mirrors** — their own normalizers fill in
      per-item defaults
    - **id lists** — stringified, and empties dropped: no registry id is falsy, and
      without the filter a ``None`` in the list would be stored as ``"None"``

    A key absent from *updates* keeps its value from *base*, which is what makes an
    update partial.
    """
    merged = dict(base)
    if OPTION_SYNC_PROBLEM_SENSORS in updates:
        merged[OPTION_SYNC_PROBLEM_SENSORS] = bool(updates[OPTION_SYNC_PROBLEM_SENSORS])
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
    if OPTION_PROFILES in updates:
        merged[OPTION_PROFILES] = profiles.normalize_profiles(updates[OPTION_PROFILES])
    if OPTION_NOTIFICATIONS in updates:
        merged[OPTION_NOTIFICATIONS] = notifications.normalize_notifications(
            updates[OPTION_NOTIFICATIONS]
        )
    if OPTION_TASK_MIRRORS in updates:
        merged[OPTION_TASK_MIRRORS] = task_mirror.normalize_task_mirrors(
            updates[OPTION_TASK_MIRRORS]
        )
    for key in _LIST_OPTIONS:
        if key in updates:
            merged[key] = [str(x) for x in (updates[key] or []) if x]
    return merged


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
    through ``async_set_options``, which persists and reloads as well.
    """
    empty = _empty_options()
    submitted = {
        key: user_input[key] if key in user_input else empty[key]
        for key in FLOW_OPTIONS
    }
    return _normalize(submitted, current_options(entry))


async def async_set_options(
    hass: HomeAssistant, entry: ConfigEntry, updates: dict[str, Any]
) -> dict[str, Any]:
    """Apply a partial options *updates* to *entry* and persist; returns the merged set.

    Only the keys present in *updates* change (the panel saves the whole form, but
    the service / an automation may set just one).

    When the options actually change we **await** the entry reload so the caller
    observes the reconciled state — synced problem-sensor tasks created/removed for
    the new exclusions — by the time this returns, instead of racing the
    fire-and-forget update-listener reload (which left the panel showing stale tasks
    until something else triggered a refresh). The entry is flagged for the duration
    so the update listener skips its own, overlapping reload.
    """
    base = current_options(entry)
    merged = _normalize(updates, base)
    if merged == base:
        # No effective change — nothing to persist, and no reload to await.
        return merged
    _CALLER_RELOADING.add(entry.entry_id)
    try:
        hass.config_entries.async_update_entry(entry, options=merged)
        await hass.config_entries.async_reload(entry.entry_id)
    finally:
        _CALLER_RELOADING.discard(entry.entry_id)
    return merged
