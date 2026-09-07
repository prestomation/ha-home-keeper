"""Pure helpers for **profiles** — named, reusable task filters (no HA imports).

A *profile* is a saved filter (``{id, name, filter, sync}``) that answers "which tasks
am I interested in" — a status (overdue / due-soon / all) plus a list of **groups**.
A group is one set of include and exclude lists, AND-ed together; the groups are OR-ed,
so "the kitchen chores, plus anything the battery companion owns, wherever it is" is
one profile rather than two. A profile is deliberately **decoupled from
notifications**: notifications (``notifications.py``) are one consumer that references
a profile by id, but the same profile also drives the panel's admin list filter and the
Lovelace card.

The groups replaced a single flat set of include/exclude keys. Nothing reads those keys
any more — ``migrate_filter_v1`` converts one stored filter, ``migrate_options_v1``
converts a whole options blob, and the config entry's major-version migration
(``async_migrate_entry``) runs them once. ``check_profiles_use_groups`` then refuses a
legacy filter on every write path, so an old automation fails loudly rather than saving
a filter no matcher reads.

The ``sync`` block is a second consumer living *inside* the profile rather than beside
it: it names one external ``todo.*`` list the profile's tasks are synced onto, so a
household gets at most one list per profile and no second id to keep in step. Clearing
``entity_id`` is the off switch — and the delete. ``todo_list.py`` reads it.

Everything here is HA-free so it's unit-testable in isolation (like ``recurrence.py``).
The filter semantics are the single source of truth that the TS side (``card-filter``)
must match — see ``tests/fixtures/profile_filter_cases.json`` and
``docs/PROFILES_REFACTOR_PLAN.md``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from . import recurrence
from .reconcile import buy_source
from .shopping import normalize_target
from .transitions import DUE_SOON_WINDOW

# Filter status: which due-state a task must be in to belong to a profile's list.
STATUS_ALL = "all"  # any active (enabled, scheduled) task
STATUS_OVERDUE = "overdue"  # only overdue
STATUS_DUE_SOON = "due_soon"  # overdue or within the due-soon window
STATUSES = (STATUS_ALL, STATUS_OVERDUE, STATUS_DUE_SOON)

# A fourth status that selects nothing. It is deliberately **absent** from STATUSES,
# so ``normalize_filter`` rejects it and no saved profile can be set to match nothing —
# a profile that selects nothing is a broken profile, not a useful one. It exists for
# one caller: ``home_keeper.notify``, where "match nothing" plus
# ``when_empty: all_clear`` is how the panel asks for the "All caught up" card on
# demand. See SERVICE_STATUSES.
STATUS_NONE = "none"

# The status vocabulary the ``home_keeper.notify`` service accepts on a single call.
# Wider than STATUSES by exactly STATUS_NONE, which is what keeps the service able to
# ask for something a stored profile is not allowed to be.
SERVICE_STATUSES = (*STATUSES, STATUS_NONE)

# The four axes a group selects on, and the four that subtract. Both tuples are read
# as the key set of a group: ``normalize_group`` builds from them, ``_group_active``
# asks whether any of them carries a value, and ``check_profiles_use_groups`` refuses
# a filter that still carries them at the top level.
INCLUDE_KEYS = ("labels", "areas", "devices", "companions")
EXCLUDE_KEYS = (
    "exclude_labels",
    "exclude_areas",
    "exclude_devices",
    "exclude_companions",
)

# How a group reads its ``labels`` list. "any" is the historical rule (one listed label
# is enough) and stays the default; "all" wants every listed label on the task, which
# is how "the outdoor jobs that are also mine" becomes one group.
LABELS_MATCH_ANY = "any"
LABELS_MATCH_ALL = "all"
LABELS_MATCHES = (LABELS_MATCH_ANY, LABELS_MATCH_ALL)

# The keys a pre-groups filter carried at its top level. A stored filter is migrated
# once; a filter arriving on a write path is rejected (see check_profiles_use_groups).
_LEGACY_FILTER_KEYS = (*INCLUDE_KEYS, *EXCLUDE_KEYS, "exclude_shopping")

_LEGACY_FILTER_ERROR = (
    "profile filter uses groups since 0.22.0b4; move labels/areas/devices/companions "
    "and exclude_* into filter.groups"
)


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v) for v in value if v not in (None, "")]


def normalize_group(raw: Any) -> dict[str, Any]:
    """Coerce one filter **group** — an AND-ed set of include and exclude lists.

    Rebuilt from a fixed key set like every other normalizer here, so the group doubles
    as its own allowlist: a key absent from this shape never survives a save. Every
    list defaults to empty, which reads as "any" for an include list and "nothing" for
    an exclude list, so an empty group selects the whole status tier.

    ``labels_match`` is clamped to :data:`LABELS_MATCHES` and falls back to
    :data:`LABELS_MATCH_ANY`, the historical rule — an unknown value must widen the
    group rather than silently demanding every label.
    """
    raw = raw if isinstance(raw, dict) else {}
    labels_match = raw.get("labels_match")
    return {
        "labels": _str_list(raw.get("labels")),
        "labels_match": (
            LABELS_MATCH_ALL if labels_match == LABELS_MATCH_ALL else LABELS_MATCH_ANY
        ),
        "areas": _str_list(raw.get("areas")),
        "devices": _str_list(raw.get("devices")),
        "companions": _str_list(raw.get("companions")),
        "exclude_labels": _str_list(raw.get("exclude_labels")),
        "exclude_areas": _str_list(raw.get("exclude_areas")),
        "exclude_devices": _str_list(raw.get("exclude_devices")),
        "exclude_companions": _str_list(raw.get("exclude_companions")),
        "exclude_shopping": bool(raw.get("exclude_shopping")),
    }


def normalize_groups(raw: Any) -> list[dict[str, Any]]:
    """Coerce a filter's ``groups`` list, always returning at least one group.

    Non-dict entries are dropped, like ``normalize_profiles`` drops non-dict profiles.
    Anything that leaves nothing behind — not a list, an empty list, a list of junk —
    becomes one empty group, so every consumer and every form can read
    ``groups[0]`` without a special case. One empty group and no group at all mean the
    same thing to :func:`matches_filter`: no include gate.
    """
    groups = (
        [normalize_group(g) for g in raw if isinstance(g, dict)]
        if isinstance(raw, (list, tuple))
        else []
    )
    return groups or [normalize_group(None)]


def normalize_filter(raw: Any) -> dict[str, Any]:
    """Coerce a profile ``filter`` block to its stored shape.

    This rebuilds the block from a fixed key set rather than merging, so it doubles as
    the allowlist: a key absent here never survives a save. The pre-groups
    include/exclude keys are therefore *dropped* rather than lifted — a stored filter
    is converted once by :func:`migrate_filter_v1`, and a filter that reaches a write
    path still carrying them is refused by :func:`check_profiles_use_groups` instead of
    being half-read here.

    The status clamp is checked against :data:`STATUSES`, which leaves
    :data:`STATUS_NONE` out. That is the boundary that keeps "match nothing" a
    per-call option on ``home_keeper.notify`` and never a saved profile: a stored
    ``none`` reads back as ``overdue`` here rather than as a profile that selects
    nothing.
    """
    raw = raw if isinstance(raw, dict) else {}
    status = raw.get("status")
    return {
        "groups": normalize_groups(raw.get("groups")),
        "status": status if status in STATUSES else STATUS_OVERDUE,
    }


def normalize_sync(raw: Any) -> dict[str, Any]:
    """Coerce a profile's ``sync`` block — the to-do list it syncs onto — to shape.

    Rebuilt from a fixed key set like :func:`normalize_filter`, so a profile saved
    before the block existed reads back as sync **off** and needs no migration.
    ``entity_id`` goes through ``shopping.normalize_target``, the same coercion the
    shopping list's target uses: anything unusable — a cleared picker, an entity
    outside the ``todo`` domain, a typo — collapses to ``""``, which is both the off
    switch and, since a sync *is* its profile, the delete. Both toggles default on,
    because a household that picks a list means the obvious thing by it.
    """
    raw = raw if isinstance(raw, dict) else {}
    return {
        "entity_id": normalize_target(raw.get("entity_id")),
        "two_way": bool(raw.get("two_way", True)),
        "vanish_as_completed": bool(raw.get("vanish_as_completed", True)),
    }


def normalize_profile(raw: Any) -> dict[str, Any]:
    """Coerce one raw profile to the stored ``{id, name, filter, sync}``.

    Generates a stable ``id`` when absent (so notifications/cards can reference it
    across edits — and so the sync's bookkeeping keys survive an edit) and defaults
    every field so forms and consumers never special-case a missing key.
    """
    raw = raw if isinstance(raw, dict) else {}
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex),
        "name": str(raw.get("name") or "Tasks"),
        "filter": normalize_filter(raw.get("filter")),
        "sync": normalize_sync(raw.get("sync")),
    }


def normalize_profiles(raw: Any) -> list[dict[str, Any]]:
    """Coerce the stored profile list, dropping non-dict entries."""
    if not isinstance(raw, (list, tuple)):
        return []
    return [normalize_profile(p) for p in raw if isinstance(p, dict)]


# ── migration to groups ─────────────────────────────────────────────────────────


def migrate_filter_v1(raw: Any) -> dict[str, Any]:
    """Convert one pre-groups ``filter`` block to the groups shape.

    The flat include/exclude lists were one AND-ed set of rules, which is exactly what
    one group is — so the whole conversion is "wrap them in a group", with
    ``labels_match`` set to :data:`LABELS_MATCH_ANY` because that was the only rule the
    flat shape had. ``status`` rides along; the flat keys are dropped.

    Pure and idempotent: a filter that already carries ``groups`` keeps them and loses
    any stray flat key beside them, so running the migration twice is running it once.
    Anything unusable becomes one empty group, since a profile that selects nothing is
    worse than a profile that selects its whole status tier. The result always goes
    through :func:`normalize_filter`, so a migration can only produce a canonical
    filter.
    """
    raw = raw if isinstance(raw, dict) else {}
    if isinstance(raw.get("groups"), list):
        return normalize_filter({"groups": raw["groups"], "status": raw.get("status")})
    # No ``labels_match`` on purpose: the flat shape only ever matched "any", and
    # ``normalize_group`` defaults an absent value to exactly that.
    group = {key: raw.get(key) for key in _LEGACY_FILTER_KEYS}
    return normalize_filter({"groups": [group], "status": raw.get("status")})


def migrate_options_v1(options: dict[str, Any]) -> dict[str, Any]:
    """Convert the ``profiles`` in an options blob, leaving every other key alone.

    This is the whole config-entry v1 -> v2 migration. Only each profile's ``filter``
    changes: ``id``, ``name`` and ``sync`` are copied through untouched, and so is
    every option beside ``profiles`` — the migration must not double as a
    re-normalization, or a key an older version stored loosely would change meaning on
    upgrade. A non-dict profile is passed through as it stands and dropped later by
    ``normalize_profiles``, which is where that rule already lives.
    """
    migrated = dict(options)
    raw = options.get("profiles")
    if not isinstance(raw, (list, tuple)):
        return migrated
    migrated["profiles"] = [
        {**p, "filter": migrate_filter_v1(p.get("filter"))}
        if isinstance(p, dict)
        else p
        for p in raw
    ]
    return migrated


def check_profiles_use_groups(profiles_raw: Any) -> Any:
    """Return *profiles_raw* unchanged, or raise if a filter still uses the flat keys.

    The flat include/exclude keys are not read anywhere any more, so a write carrying
    them would save a filter that quietly selects the profile's whole status tier. That
    is worse than a rejected call: the automation looks like it worked. Every write path
    — the ``home_keeper.set_options`` service and the panel's ``set_options`` websocket
    command — wraps this as a voluptuous validator so the caller gets the message.

    :raises ValueError: if any profile's ``filter`` carries a pre-groups key.
    """
    for profile in profiles_raw if isinstance(profiles_raw, (list, tuple)) else []:
        if not isinstance(profile, dict):
            continue
        filt = profile.get("filter")
        if isinstance(filt, dict) and any(k in filt for k in _LEGACY_FILTER_KEYS):
            raise ValueError(_LEGACY_FILTER_ERROR)
    return profiles_raw


def synced_profiles(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The profiles that actually sync onto a list — the rest have sync off.

    What the driver needs to answer "is any list worth watching", which is a
    different question from what the planner needs: a profile whose picker was
    cleared still has items out there to take back off.
    """
    return [p for p in profiles if str(p["sync"]["entity_id"])]


def resolve_profile(
    profiles: list[dict[str, Any]], key: str | None
) -> dict[str, Any] | None:
    """Find a profile by ``id`` (preferred) or, failing that, by ``name``."""
    if not key:
        return None
    for profile in profiles:
        if profile.get("id") == key:
            return profile
    for profile in profiles:
        if profile.get("name") == key:
            return profile
    return None


def with_status(filt: dict[str, Any], status: str | None) -> dict[str, Any]:
    """Return *filt* with its ``status`` replaced by *status*, for one call only.

    This is how ``home_keeper.notify`` widens (or empties) a saved profile's filter
    without editing the profile: the caller says "send me everything this profile
    covers, not only what is overdue" and the stored profile is untouched. It returns
    a copy for that reason — the profile dict it is handed comes straight out of
    ``current_options``, and mutating it in place would leak a per-call override into
    every later reader.

    *status* is clamped against :data:`SERVICE_STATUSES` rather than :data:`STATUSES`,
    so :data:`STATUS_NONE` is accepted here and nowhere else. Anything unknown — and
    ``None``, the ordinary case of a call that did not ask for an override — leaves the
    filter as it was, matching how every other unrecognized value in this module falls
    back rather than raising.
    """
    if status not in SERVICE_STATUSES:
        return filt
    return {**filt, "status": status}


# ── filtering & queueing ────────────────────────────────────────────────────────


def _group_active(group: Any) -> bool:
    """Whether *group* says anything — an empty group is not a rule, it is a blank row.

    The panel always keeps one group on the form, so "no filtering at all" and "a group
    the user has not filled in yet" are the same object. Reading a blank group as a rule
    would make it match everything and swallow its filled-in siblings, so it is dropped
    from the OR instead. An entry that is not a group at all — the matcher reads what it
    is handed, and only ``normalize_groups`` drops those — is inactive for the same
    reason.
    """
    if not isinstance(group, dict):
        return False
    return bool(
        any(group.get(key) for key in (*INCLUDE_KEYS, *EXCLUDE_KEYS))
        or group.get("exclude_shopping")
    )


def _group_matches(
    group: dict[str, Any],
    *,
    task: dict[str, Any],
    task_labels: set[str],
    area_id: Any,
    device_id: Any,
    companion: Any,
) -> bool:
    """Whether one group selects the task described by the keyword arguments.

    Every include list that carries a value must match (AND across the lists; an empty
    list means "any"), and no exclude list may hit. ``labels`` reads per the group's
    ``labels_match``: ``any`` wants one of the listed labels on the task, ``all`` wants
    every one of them.

    Exclusions are applied last and win **inside this group only**: a task an exclusion
    drops here can still be taken by a sibling group. That is what makes "everything I
    can do myself, plus the call-outs in the garage" expressible as one profile.
    An unset area/device/companion can never be listed — ``_str_list`` drops
    ``None``/``""`` — so a task with no area, or one no integration claims, is not
    swept up by a non-empty ``exclude_areas`` / ``exclude_companions``.
    """
    labels = group.get("labels") or []
    if labels:
        listed = set(labels)
        if group.get("labels_match") == LABELS_MATCH_ALL:
            if not listed <= task_labels:
                return False
        elif not (task_labels & listed):
            return False
    areas = group.get("areas") or []
    if areas and area_id not in areas:
        return False
    devices = group.get("devices") or []
    if devices and device_id not in devices:
        return False
    companions = group.get("companions") or []
    if companions and companion not in companions:
        return False

    if task_labels & set(group.get("exclude_labels") or []):
        return False
    if area_id in (group.get("exclude_areas") or []):
        return False
    if device_id in (group.get("exclude_devices") or []):
        return False
    # Shopping is excluded by *kind* rather than by id, because an auto-created buy
    # reminder carries no label or area of its own to name — it inherits the
    # appliance's. Without this the only way to keep "Buy softener" out of a spoken
    # digest was a script filtering on ``source.buy`` by hand (#220).
    if group.get("exclude_shopping") and buy_source(task) is not None:
        return False
    return companion not in (group.get("exclude_companions") or [])


def matches_filter(
    task: dict[str, Any],
    filt: dict[str, Any],
    *,
    now: datetime,
    window: timedelta = DUE_SOON_WINDOW,
) -> bool:
    """Whether *task* belongs to a profile's list under *filt* at *now*.

    Three gates, in order. A task qualifies only if it is live now: enabled and
    scheduled (a non-``None`` ``next_due``). It must then be in the filter's ``status``
    due-state. Only after that do the **groups** decide.

    A group is one AND-ed set of include and exclude lists (see
    :func:`_group_matches`); the groups are OR-ed, so the task matches when *any*
    active group takes it. A group with nothing in it is not active and is ignored, so
    a filter with no active group has no include gate at all and selects the whole
    status tier. This is why a profile-level rule — the status, the enabled and
    ``next_due`` checks — can never be widened by adding a group: the gates above run
    first and a group only ever narrows what is left.

    A ``problem``-sensor-synced task is an ordinary member of that set. It is armed —
    ``next_due`` set to the moment the sensor went bad, so it reads as overdue — while
    the sensor reports a problem, and dormant (``next_due is None``, excluded by the
    check above) once the sensor clears. Dropping the armed ones outright hid a whole
    class of overdue work from every Profile, in the panel and on the card, under every
    status (#248). They are still left out of *walk* notifications, but that belongs to
    delivery rather than to the filter — see ``notifications.is_walkable``.

    ``companions`` scopes by the integration that owns the task — the ``integration``
    of its ``managed_by`` block — so "only the battery tasks" is one group rather
    than a label every companion has to learn to apply. A task no integration claims
    has no companion: a ``companions`` list never selects it, and an
    ``exclude_companions`` list never drops it.

    This pure matcher reads the ``labels``/``area_id``/
    ``device_id``/``managed_by`` on the task dict; the HA-aware caller
    (``notifier.effective_filter_tasks``) enriches those with **effective**
    (device/area-inherited) ids before calling, so a Profile selects the same tasks here
    as it does on the panel/card, which resolve inheritance inline. The shared
    ``tests/fixtures/profile_filter_cases.json`` pins this agreement.
    """
    if not task.get("enabled", True):
        return False
    if task.get("next_due") is None:
        return False

    status = filt.get("status", STATUS_OVERDUE)
    # A per-call override from ``home_keeper.notify`` (never a saved profile — see
    # STATUS_NONE). Answered before the date work below because no task can satisfy it.
    if status == STATUS_NONE:
        return False
    overdue = recurrence.is_overdue(task, now=now)
    if status == STATUS_OVERDUE and not overdue:
        return False
    if status == STATUS_DUE_SOON and not (
        overdue or recurrence.is_due_soon(task, window, now=now)
    ):
        return False

    task_labels = set(task.get("labels") or [])
    area_id = task.get("area_id")
    device_id = task.get("device_id")
    # The integration that owns this task, from the ``managed_by`` block a companion
    # sets on ``add_task``. That block is the documented ownership contract and the
    # only provenance Home Keeper reads — ``source`` is the integration's own
    # namespace and stays opaque (docs/INTEGRATING.md). A task nobody claims has no
    # companion, so a ``companions`` list never selects it.
    companion = (task.get("managed_by") or {}).get("integration")

    active = [g for g in (filt.get("groups") or []) if _group_active(g)]
    return not active or any(
        _group_matches(
            group,
            task=task,
            task_labels=task_labels,
            area_id=area_id,
            device_id=device_id,
            companion=companion,
        )
        for group in active
    )


def _due_key(task: dict[str, Any]) -> tuple[datetime, str]:
    # next_due is guaranteed non-None by matches_filter; earliest first = most overdue
    # first, with the name as a stable tiebreak.
    return (datetime.fromisoformat(task["next_due"]), str(task.get("name") or ""))


def due_queue(
    tasks: list[dict[str, Any]],
    filt: dict[str, Any],
    *,
    now: datetime,
    window: timedelta = DUE_SOON_WINDOW,
) -> list[dict[str, Any]]:
    """The ordered list of tasks a profile surfaces, most-overdue first."""
    matched = [t for t in tasks if matches_filter(t, filt, now=now, window=window)]
    return sorted(matched, key=_due_key)
