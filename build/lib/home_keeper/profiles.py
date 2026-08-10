"""Pure helpers for **profiles** — named, reusable task filters (no HA imports).

A *profile* is a saved filter (``{id, name, filter}``) that answers "which tasks am I
interested in" — a status (overdue / due-soon / all) plus optional label/area/device
filters. It is deliberately **decoupled from notifications**: notifications
(``notifications.py``) are one consumer that references a profile by id, but the same
profile also drives the panel's admin list filter and the Lovelace card.

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
    """Coerce a profile ``filter`` block to its stored shape."""
    raw = raw if isinstance(raw, dict) else {}
    status = raw.get("status")
    return {
        "labels": _str_list(raw.get("labels")),
        "areas": _str_list(raw.get("areas")),
        "devices": _str_list(raw.get("devices")),
        "status": status if status in STATUSES else STATUS_OVERDUE,
    }


def normalize_profile(raw: Any) -> dict[str, Any]:
    """Coerce one raw profile to the stored, fully-defaulted ``{id, name, filter}``.

    Generates a stable ``id`` when absent (so notifications/cards can reference it
    across edits) and defaults every field so forms and consumers never special-case a
    missing key.
    """
    raw = raw if isinstance(raw, dict) else {}
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex),
        "name": str(raw.get("name") or "Tasks"),
        "filter": normalize_filter(raw.get("filter")),
    }


def normalize_profiles(raw: Any) -> list[dict[str, Any]]:
    """Coerce the stored profile list, dropping non-dict entries."""
    if not isinstance(raw, (list, tuple)):
        return []
    return [normalize_profile(p) for p in raw if isinstance(p, dict)]


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


def _is_problem_sensor(task: dict[str, Any]) -> bool:
    source = task.get("source")
    return isinstance(source, dict) and "problem_sensor" in source


def matches_filter(
    task: dict[str, Any],
    filt: dict[str, Any],
    *,
    now: datetime,
    window: timedelta = DUE_SOON_WINDOW,
) -> bool:
    """Whether *task* belongs to a profile's list under *filt* at *now*.

    A task qualifies only if it is actionable now: enabled, scheduled (a non-``None``
    ``next_due``), and not a synced ``problem`` sensor (those can't be completed from
    Home Keeper). On top of that it must clear the label/area/device filters (each is
    an OR within the list, AND across the lists; an empty list means "any") and the
    ``status`` due-state. This pure matcher reads the ``labels``/``area_id``/
    ``device_id`` on the task dict; the HA-aware caller
    (``notifier._effective_filter_tasks``) enriches those with **effective**
    (device/area-inherited) ids before calling, so a Profile selects the same tasks here
    as it does on the panel/card, which resolve inheritance inline. The shared
    ``tests/fixtures/profile_filter_cases.json`` pins this agreement.
    """
    if not task.get("enabled", True):
        return False
    if task.get("next_due") is None:
        return False
    if _is_problem_sensor(task):
        return False

    status = filt.get("status", STATUS_OVERDUE)
    overdue = recurrence.is_overdue(task, now=now)
    if status == STATUS_OVERDUE and not overdue:
        return False
    if status == STATUS_DUE_SOON and not (
        overdue or recurrence.is_due_soon(task, window, now=now)
    ):
        return False

    labels = filt.get("labels") or []
    if labels and not (set(task.get("labels") or []) & set(labels)):
        return False
    areas = filt.get("areas") or []
    if areas and task.get("area_id") not in areas:
        return False
    devices = filt.get("devices") or []
    return not (devices and task.get("device_id") not in devices)


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
