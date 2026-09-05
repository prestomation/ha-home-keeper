"""Pure helpers for **profiles** — named, reusable task filters (no HA imports).

A *profile* is a saved filter (``{id, name, filter, sync}``) that answers "which tasks
am I interested in" — a status (overdue / due-soon / all) plus optional
label/area/device filters. It is deliberately **decoupled from notifications**:
notifications (``notifications.py``) are one consumer that references a profile by id,
but the same profile also drives the panel's admin list filter and the Lovelace card.

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


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v) for v in value if v not in (None, "")]


def normalize_filter(raw: Any) -> dict[str, Any]:
    """Coerce a profile ``filter`` block to its stored shape.

    This rebuilds the block from a fixed key set rather than merging, so it doubles as
    the allowlist: a key absent here never survives a save. The ``exclude_*`` keys are
    additive and default to off, which is why a profile stored before they existed
    needs no migration — ``options.current_options`` re-normalizes on every read.
    """
    raw = raw if isinstance(raw, dict) else {}
    status = raw.get("status")
    return {
        "labels": _str_list(raw.get("labels")),
        "areas": _str_list(raw.get("areas")),
        "devices": _str_list(raw.get("devices")),
        "companions": _str_list(raw.get("companions")),
        "exclude_labels": _str_list(raw.get("exclude_labels")),
        "exclude_areas": _str_list(raw.get("exclude_areas")),
        "exclude_devices": _str_list(raw.get("exclude_devices")),
        "exclude_companions": _str_list(raw.get("exclude_companions")),
        "exclude_shopping": bool(raw.get("exclude_shopping")),
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


# ── filtering & queueing ────────────────────────────────────────────────────────


def matches_filter(
    task: dict[str, Any],
    filt: dict[str, Any],
    *,
    now: datetime,
    window: timedelta = DUE_SOON_WINDOW,
) -> bool:
    """Whether *task* belongs to a profile's list under *filt* at *now*.

    A task qualifies only if it is live now: enabled and scheduled (a non-``None``
    ``next_due``). On top of that it must clear the label/area/device filters (each is
    an OR within the list, AND across the lists; an empty list means "any") and the
    ``status`` due-state.

    A ``problem``-sensor-synced task is an ordinary member of that set. It is armed —
    ``next_due`` set to the moment the sensor went bad, so it reads as overdue — while
    the sensor reports a problem, and dormant (``next_due is None``, excluded by the
    check above) once the sensor clears. Dropping the armed ones outright hid a whole
    class of overdue work from every Profile, in the panel and on the card, under every
    status (#248). They are still left out of *walk* notifications, but that belongs to
    delivery rather than to the filter — see ``notifications.is_walkable``.

    The ``exclude_labels``/``exclude_areas``/``exclude_devices``/``exclude_companions``
    lists then subtract: any hit drops the task even when it satisfied every include
    list, so exclusions win.
    An empty exclude list excludes nothing. Exclusions read the same **effective** ids
    as the include lists, so excluding a label also drops a task that merely inherits
    it from its device or area.

    ``companions`` scopes by the integration that owns the task — the ``integration``
    of its ``managed_by`` block — so "only the battery tasks" is one profile rather
    than a label every companion has to learn to apply. A task no integration claims
    has no companion: a ``companions`` list never selects it, and an
    ``exclude_companions`` list never drops it.

    ``exclude_shopping`` subtracts alongside them, but by *kind*: it drops the
    auto-created "Buy {part}" reminders, which have no id of their own to name. Off by
    default, so a profile saved before it existed keeps every task it had.

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

    labels = filt.get("labels") or []
    if labels and not (task_labels & set(labels)):
        return False
    areas = filt.get("areas") or []
    if areas and area_id not in areas:
        return False
    devices = filt.get("devices") or []
    if devices and device_id not in devices:
        return False
    companions = filt.get("companions") or []
    if companions and companion not in companions:
        return False

    # Exclusions are applied last and win: a task that cleared every include list is
    # still dropped if it carries an excluded label, sits in an excluded area, or hangs
    # off an excluded device. That's what makes "everything I can do myself" expressible
    # as one profile instead of labelling every task that *isn't* a call-out.
    # An unset area/device/companion can never be listed: ``_str_list`` drops
    # ``None``/``""``, so a task with no area — or one no integration claims — is not
    # swept up by a non-empty ``exclude_areas`` / ``exclude_companions``.
    if task_labels & set(filt.get("exclude_labels") or []):
        return False
    if area_id in (filt.get("exclude_areas") or []):
        return False
    if device_id in (filt.get("exclude_devices") or []):
        return False
    # Shopping is excluded by *kind* rather than by id, because an auto-created buy
    # reminder carries no label or area of its own to name — it inherits the
    # appliance's. Without this the only way to keep "Buy softener" out of a spoken
    # digest was a script filtering on ``source.buy`` by hand (#220).
    if filt.get("exclude_shopping") and buy_source(task) is not None:
        return False
    return companion not in (filt.get("exclude_companions") or [])


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
