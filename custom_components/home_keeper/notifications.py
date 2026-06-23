"""Pure helpers for actionable notifications (no Home Assistant imports).

Everything here is HA-free so it can be unit-tested in isolation (like
``recurrence.py`` / ``events.py``): profile normalization, the shared task **filter
predicate**, the **due queue** a profile walks, the mobile-app **payload builder**,
and the **action-string** encode/decode used to route a notification tap back to the
right task and profile. The HA-aware sending and the action-event listener live in
``notifier.py``; the coordinator drives the automatic source.

See ``docs/ACTIONABLE_NOTIFICATIONS_PLAN.md``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from . import recurrence
from .transitions import DUE_SOON_WINDOW

# Notification action verbs (the button behaviours) and how a profile's button set is
# spelled. ``open`` is a client-side URI deep-link (no backend callback).
ACTION_COMPLETE = "complete"
ACTION_SNOOZE = "snooze"
ACTION_SKIP = "skip"
ACTION_OPEN = "open"
ACTIONS = (ACTION_COMPLETE, ACTION_SNOOZE, ACTION_SKIP, ACTION_OPEN)
DEFAULT_ACTIONS = [ACTION_COMPLETE, ACTION_SNOOZE, ACTION_OPEN]

# Per-profile delivery style.
STYLE_WALK = "walk"  # one task at a time; each action advances to the next
STYLE_DIGEST = "digest"  # a single informational summary of everything due
STYLES = (STYLE_WALK, STYLE_DIGEST)

# Filter status: which due-state a task must be in to belong to a profile's list.
STATUS_ALL = "all"  # any active (enabled, scheduled) task
STATUS_OVERDUE = "overdue"  # only overdue
STATUS_DUE_SOON = "due_soon"  # overdue or within the due-soon window
STATUSES = (STATUS_ALL, STATUS_OVERDUE, STATUS_DUE_SOON)

DEFAULT_SNOOZE_HOURS = 24

# Action-string scheme: ``home_keeper::<verb>::<task_id>::<profile_id>``. The action
# string is the only field reliably echoed back in ``mobile_app_notification_action``,
# so the verb, task, and profile are all encoded into it. The prefix scopes ours on a
# global event bus that also carries other integrations' actions.
_ACTION_PREFIX = "home_keeper"
_ACTION_SEP = "::"


def encode_action(verb: str, task_id: str, profile_id: str) -> str:
    """Build the action identifier carried on a notification button."""
    return _ACTION_SEP.join((_ACTION_PREFIX, verb, task_id, profile_id))


def decode_action(action: str | None) -> tuple[str, str, str] | None:
    """Parse one of our action strings into ``(verb, task_id, profile_id)``.

    Returns ``None`` for anything that isn't a well-formed Home Keeper action (a
    foreign integration's action, or a malformed/empty value) so the listener can
    ignore it.
    """
    if not action:
        return None
    parts = action.split(_ACTION_SEP)
    if len(parts) != 4 or parts[0] != _ACTION_PREFIX:
        return None
    _, verb, task_id, profile_id = parts
    if verb not in ACTIONS or not task_id or not profile_id:
        return None
    return verb, task_id, profile_id


# ── profile normalization ──────────────────────────────────────────────────────


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
    """Coerce one raw profile dict to the stored, fully-defaulted shape.

    Generates a stable ``id`` when absent (so action strings can reference it across
    edits), clamps the action set to known verbs (preserving order, de-duplicated),
    and defaults every field so the panel form and senders never special-case a
    missing key.
    """
    raw = raw if isinstance(raw, dict) else {}
    actions: list[str] = []
    for a in _str_list(raw.get("actions")):
        if a in ACTIONS and a not in actions:
            actions.append(a)
    auto = raw.get("auto") if isinstance(raw.get("auto"), dict) else {}
    try:
        snooze_hours = int(raw.get("snooze_hours", DEFAULT_SNOOZE_HOURS))
    except (TypeError, ValueError):
        snooze_hours = DEFAULT_SNOOZE_HOURS
    if snooze_hours < 1:
        snooze_hours = DEFAULT_SNOOZE_HOURS
    style = raw.get("style")
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex),
        "name": str(raw.get("name") or "Notifications"),
        "targets": _str_list(raw.get("targets")),
        "filter": normalize_filter(raw.get("filter")),
        "actions": actions or list(DEFAULT_ACTIONS),
        "snooze_hours": snooze_hours,
        "style": style if style in STYLES else STYLE_WALK,
        "auto": {
            "overdue": bool(auto.get("overdue", False)),
            "due_soon": bool(auto.get("due_soon", False)),
        },
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
    ``status`` due-state.
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
    """The ordered list of tasks a profile should surface, most-overdue first."""
    matched = [t for t in tasks if matches_filter(t, filt, now=now, window=window)]
    return sorted(matched, key=_due_key)


# ── payload building ────────────────────────────────────────────────────────────


def profile_tag(profile_id: str) -> str:
    """The stable mobile-app ``tag`` for a profile's rolling notification.

    One tag per profile means a fresh send (the next task in a walk, or a rebuilt
    digest) *replaces* the previous notification in place rather than stacking, and
    lets the listener clear it when the queue empties.
    """
    return f"home_keeper_{profile_id}"


def _overdue_phrase(task: dict[str, Any], *, now: datetime) -> str:
    next_due = datetime.fromisoformat(task["next_due"])
    if now >= next_due:
        days = (now - next_due).days
        if days <= 0:
            return "Due now."
        return f"Overdue by {days} day{'s' if days != 1 else ''}."
    return "Due soon."


def _open_uri(task: dict[str, Any]) -> str:
    return f"/home-keeper/tasks/{task['id']}"


def _action_button(verb: str, task: dict[str, Any], profile: dict[str, Any]) -> dict:
    """Build one mobile-app action button for *verb* on *task*."""
    action_id = encode_action(verb, task["id"], profile["id"])
    if verb == ACTION_COMPLETE:
        return {"action": action_id, "title": "Mark done"}
    if verb == ACTION_SNOOZE:
        return {"action": action_id, "title": f"Snooze {profile['snooze_hours']}h"}
    if verb == ACTION_SKIP:
        return {"action": action_id, "title": "Skip"}
    # open — a URI deep-link into the panel (handled client-side, no callback).
    return {"action": action_id, "title": "Open", "uri": _open_uri(task)}


def build_notification(
    task: dict[str, Any], *, profile: dict[str, Any], now: datetime
) -> dict[str, Any]:
    """Build the ``notify`` service data for a single task in a *walk* profile."""
    actions = [_action_button(v, task, profile) for v in profile["actions"]]
    return {
        "title": str(task.get("name") or "Home Keeper"),
        "message": _overdue_phrase(task, now=now),
        "data": {
            "tag": profile_tag(profile["id"]),
            "group": "home_keeper",
            "actions": actions,
        },
    }


def build_digest(
    queue: list[dict[str, Any]], *, profile: dict[str, Any], now: datetime
) -> dict[str, Any]:
    """Build a single summary ``notify`` payload listing everything due."""
    names = [str(t.get("name") or "?") for t in queue]
    shown = names[:5]
    more = len(names) - len(shown)
    body = "\n".join(f"• {n}" for n in shown)
    if more > 0:
        body += f"\n…and {more} more"
    count = len(queue)
    return {
        "title": f"{count} task{'s' if count != 1 else ''} due",
        "message": body,
        "data": {
            "tag": profile_tag(profile["id"]),
            "group": "home_keeper",
        },
    }


def build_all_clear(profile: dict[str, Any]) -> dict[str, Any]:
    """The closing notification when a walk empties its queue."""
    return {
        "title": "All caught up",
        "message": "No tasks due right now. 🎉",
        "data": {"tag": profile_tag(profile["id"]), "group": "home_keeper"},
    }
