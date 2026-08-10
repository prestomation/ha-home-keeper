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

import functools
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from babel import Locale
from babel.core import UnknownLocaleError

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


# ── payload text translation ─────────────────────────────────────────────────────
#
# Notification payloads go straight to the mobile app, outside HA's own frontend
# translation loading, so the strings must be resolved here rather than left for the
# frontend to localize. They are NOT part of strings.json/translations/<lang>.json —
# hassfest validates that tree against a fixed set of categories (config, services,
# entity, ...) and rejects anything else — so they get their own bundled
# ``notification_strings/<lang>.json`` files, flat dotted-key tables read directly
# (no HA import, keeping this module pure), the same convention
# ``frontend/src/locales/*.json`` uses for the panel. Pluralization uses Babel's CLDR
# plural rules (one/few/many/other) the same way ``frontend/src/i18n.ts`` uses the
# browser's ``Intl.PluralRules``: a pluralizable key is stored as ``<key>.<category>``
# and looked up by the category *n* resolves to, falling back to ``<key>.other``.

_DEFAULT_LANG = "en"
_STRINGS_DIR = Path(__file__).parent / "notification_strings"
_TOKEN_RE = re.compile(r"\{(\w+)\}")


@functools.cache
def _notification_strings(lang: str) -> dict[str, str]:
    """Load the flat notification string table for *lang*, caching by language."""
    path = _STRINGS_DIR / f"{lang}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@functools.cache
def _babel_locale(lang: str) -> Locale:
    try:
        return Locale.parse(lang.replace("-", "_"))
    except (UnknownLocaleError, ValueError):
        return Locale.parse(_DEFAULT_LANG)


def _interpolate(template: str, params: dict[str, Any]) -> str:
    return _TOKEN_RE.sub(
        lambda m: str(params[m.group(1)]) if m.group(1) in params else m.group(0),
        template,
    )


def _t(lang: str, key: str, **params: Any) -> str:
    """Translate a plain (non-plural) string, falling back to English then the key."""
    template = _notification_strings(lang).get(key) or _notification_strings(
        _DEFAULT_LANG
    ).get(key, key)
    return _interpolate(template, params)


def _tn(lang: str, key: str, n: int, **params: Any) -> str:
    """Translate a pluralizable string, selecting the CLDR category for *n*."""
    category = _babel_locale(lang).plural_form(n)
    strings = _notification_strings(lang)
    en_strings = _notification_strings(_DEFAULT_LANG)
    template = (
        strings.get(f"{key}.{category}")
        or strings.get(f"{key}.other")
        or en_strings.get(f"{key}.{category}")
        or en_strings.get(f"{key}.other", key)
    )
    return _interpolate(template, params)


# ── payload building ────────────────────────────────────────────────────────────


def notification_tag(notification_id: str) -> str:
    """The stable mobile-app ``tag`` for a notification's rolling message.

    One tag per notification means a fresh send (the next task in a walk, or a rebuilt
    digest) *replaces* the previous notification in place rather than stacking, and
    lets the listener clear it when the queue empties.
    """
    return f"home_keeper_{notification_id}"


def _overdue_phrase(
    task: dict[str, Any], *, now: datetime, lang: str = _DEFAULT_LANG
) -> str:
    next_due = datetime.fromisoformat(task["next_due"])
    if now >= next_due:
        days = (now - next_due).days
        if days <= 0:
            return _t(lang, "due_now")
        return _tn(lang, "overdue", days, days=days)
    return _t(lang, "due_soon")


def _open_uri(task: dict[str, Any]) -> str:
    return f"/home-keeper/tasks/{task['id']}"


def _action_button(
    verb: str,
    task: dict[str, Any],
    notification: dict[str, Any],
    *,
    lang: str = _DEFAULT_LANG,
) -> dict[str, Any]:
    """Build one mobile-app action button for *verb* on *task*."""
    action_id = encode_action(verb, task["id"], notification["id"])
    if verb == ACTION_COMPLETE:
        return {"action": action_id, "title": _t(lang, "action_complete")}
    if verb == ACTION_SNOOZE:
        title = _t(lang, "action_snooze", hours=notification["snooze_hours"])
        return {"action": action_id, "title": title}
    if verb == ACTION_SKIP:
        return {"action": action_id, "title": _t(lang, "action_skip")}
    # open — a URI deep-link into the panel (handled client-side, no callback).
    return {
        "action": action_id,
        "title": _t(lang, "action_open"),
        "uri": _open_uri(task),
    }


def build_notification(
    task: dict[str, Any],
    *,
    notification: dict[str, Any],
    now: datetime,
    lang: str = _DEFAULT_LANG,
) -> dict[str, Any]:
    """Build the ``notify`` service data for a single task in a *walk* notification."""
    actions = [
        _action_button(v, task, notification, lang=lang)
        for v in notification["actions"]
    ]
    return {
        "title": str(task.get("name") or "Home Keeper"),
        "message": _overdue_phrase(task, now=now, lang=lang),
        "data": {
            "tag": notification_tag(notification["id"]),
            "group": "home_keeper",
            "actions": actions,
        },
    }


def build_digest(
    queue: list[dict[str, Any]],
    *,
    notification: dict[str, Any],
    now: datetime,
    lang: str = _DEFAULT_LANG,
) -> dict[str, Any]:
    """Build a single summary ``notify`` payload listing everything due."""
    names = [str(t.get("name") or "?") for t in queue]
    shown = names[:5]
    more = len(names) - len(shown)
    body = "\n".join(_t(lang, "digest_item", name=n) for n in shown)
    if more > 0:
        body += "\n" + _t(lang, "digest_more", more=more)
    count = len(queue)
    return {
        "title": _tn(lang, "digest_title", count, count=count),
        "message": body,
        "data": {
            "tag": notification_tag(notification["id"]),
            "group": "home_keeper",
        },
    }


def build_all_clear(
    notification: dict[str, Any], *, lang: str = _DEFAULT_LANG
) -> dict[str, Any]:
    """The closing notification when a walk empties its queue."""
    return {
        "title": _t(lang, "all_clear_title"),
        "message": _t(lang, "all_clear_message"),
        "data": {
            "tag": notification_tag(notification["id"]),
            "group": "home_keeper",
        },
    }
