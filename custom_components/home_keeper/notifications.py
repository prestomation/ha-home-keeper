"""Pure helpers for actionable **notifications** — the delivery layer (no HA imports).

A *notification* is a delivery binding: it references a **profile** (the saved filter
in ``profiles.py`` that decides *which* tasks) by ``profile_id`` and adds *how* to
deliver them — mobile targets, the button set, snooze duration, style (walk/digest),
and automatic triggers. This module owns only that delivery concern: notification
normalization, the mobile-app **payload builders**, and the **action-string**
encode/decode that routes a notification tap back to the right task and notification.
The filter/queue live in ``profiles.py``; HA-aware sending in ``notifier.py``.

See ``docs/PROFILES_REFACTOR_PLAN.md`` / ``docs/ACTIONABLE_NOTIFICATIONS_PLAN.md``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

# Notification action verbs (the button behaviours). ``open`` is a client-side URI
# deep-link (no backend callback).
ACTION_COMPLETE = "complete"
ACTION_SNOOZE = "snooze"
ACTION_SKIP = "skip"
ACTION_OPEN = "open"
ACTIONS = (ACTION_COMPLETE, ACTION_SNOOZE, ACTION_SKIP, ACTION_OPEN)
DEFAULT_ACTIONS = [ACTION_COMPLETE, ACTION_SNOOZE, ACTION_OPEN]

# Per-notification delivery style.
STYLE_WALK = "walk"  # one task at a time; each action advances to the next
STYLE_DIGEST = "digest"  # a single informational summary of everything due
STYLES = (STYLE_WALK, STYLE_DIGEST)

DEFAULT_SNOOZE_HOURS = 24

# Action-string scheme: ``home_keeper::<verb>::<task_id>::<notification_id>``. The
# action string is the only field reliably echoed back in
# ``mobile_app_notification_action``, so the verb, task, and notification are all
# encoded into it. The prefix scopes ours on a global event bus that also carries
# other integrations' actions.
_ACTION_PREFIX = "home_keeper"
_ACTION_SEP = "::"


def encode_action(verb: str, task_id: str, notification_id: str) -> str:
    """Build the action identifier carried on a notification button."""
    return _ACTION_SEP.join((_ACTION_PREFIX, verb, task_id, notification_id))


def decode_action(action: str | None) -> tuple[str, str, str] | None:
    """Parse one of our action strings into ``(verb, task_id, notification_id)``.

    Returns ``None`` for anything that isn't a well-formed Home Keeper action (a
    foreign integration's action, or a malformed/empty value) so the listener can
    ignore it.
    """
    if not action:
        return None
    parts = action.split(_ACTION_SEP)
    if len(parts) != 4 or parts[0] != _ACTION_PREFIX:
        return None
    _, verb, task_id, notification_id = parts
    if verb not in ACTIONS or not task_id or not notification_id:
        return None
    return verb, task_id, notification_id


# ── notification normalization ───────────────────────────────────────────────────


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v) for v in value if v not in (None, "")]


def normalize_notification(raw: Any) -> dict[str, Any]:
    """Coerce one raw notification to its stored, fully-defaulted shape.

    A notification references a profile (``profile_id``) and carries delivery: an id
    (stable, referenced by action strings), a name, mobile ``targets``, the ordered
    ``actions`` button set (clamped to known verbs, de-duplicated), ``snooze_hours``,
    ``style`` (walk/digest), and ``auto`` triggers.
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
        "name": str(raw.get("name") or "Notification"),
        "profile_id": str(raw["profile_id"]) if raw.get("profile_id") else None,
        "targets": _str_list(raw.get("targets")),
        "actions": actions or list(DEFAULT_ACTIONS),
        "snooze_hours": snooze_hours,
        "style": style if style in STYLES else STYLE_WALK,
        "auto": {
            "overdue": bool(auto.get("overdue", False)),
            "due_soon": bool(auto.get("due_soon", False)),
        },
    }


def normalize_notifications(raw: Any) -> list[dict[str, Any]]:
    """Coerce the stored notification list, dropping non-dict entries."""
    if not isinstance(raw, (list, tuple)):
        return []
    return [normalize_notification(n) for n in raw if isinstance(n, dict)]


def resolve_notification(
    notifications: list[dict[str, Any]], key: str | None
) -> dict[str, Any] | None:
    """Find a notification by ``id`` (preferred) or, failing that, by ``name``."""
    if not key:
        return None
    for notification in notifications:
        if notification.get("id") == key:
            return notification
    for notification in notifications:
        if notification.get("name") == key:
            return notification
    return None


# ── payload building ────────────────────────────────────────────────────────────


def notification_tag(notification_id: str) -> str:
    """The stable mobile-app ``tag`` for a notification's rolling message.

    One tag per notification means a fresh send (the next task in a walk, or a rebuilt
    digest) *replaces* the previous notification in place rather than stacking, and
    lets the listener clear it when the queue empties.
    """
    return f"home_keeper_{notification_id}"


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


def _action_button(
    verb: str, task: dict[str, Any], notification: dict[str, Any]
) -> dict:
    """Build one mobile-app action button for *verb* on *task*."""
    action_id = encode_action(verb, task["id"], notification["id"])
    if verb == ACTION_COMPLETE:
        return {"action": action_id, "title": "Mark done"}
    if verb == ACTION_SNOOZE:
        return {"action": action_id, "title": f"Snooze {notification['snooze_hours']}h"}
    if verb == ACTION_SKIP:
        return {"action": action_id, "title": "Skip"}
    # open — a URI deep-link into the panel (handled client-side, no callback).
    return {"action": action_id, "title": "Open", "uri": _open_uri(task)}


def build_notification(
    task: dict[str, Any], *, notification: dict[str, Any], now: datetime
) -> dict[str, Any]:
    """Build the ``notify`` service data for a single task in a *walk* notification."""
    actions = [_action_button(v, task, notification) for v in notification["actions"]]
    return {
        "title": str(task.get("name") or "Home Keeper"),
        "message": _overdue_phrase(task, now=now),
        "data": {
            "tag": notification_tag(notification["id"]),
            "group": "home_keeper",
            "actions": actions,
        },
    }


def build_digest(
    queue: list[dict[str, Any]], *, notification: dict[str, Any], now: datetime
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
            "tag": notification_tag(notification["id"]),
            "group": "home_keeper",
        },
    }


def build_all_clear(notification: dict[str, Any]) -> dict[str, Any]:
    """The closing notification when a walk empties its queue."""
    return {
        "title": "All caught up",
        "message": "No tasks due right now. 🎉",
        "data": {
            "tag": notification_tag(notification["id"]),
            "group": "home_keeper",
        },
    }
