"""Pure helpers for actionable **notifications** — the delivery layer (no HA imports).

A *notification* is a delivery binding: it references a **profile** (the saved filter
in ``profiles.py`` that decides *which* tasks) by ``profile_id`` and adds *how* to
deliver them — mobile targets, the button set, snooze duration, style (walk/digest),
automatic triggers, and how loudly it lands (channel + urgency, expanded into both the
Android and iOS payload vocabularies by :func:`payload_data`). This module owns only
that delivery concern: notification normalization, the mobile-app **payload builders**,
and the **action-string**
encode/decode that routes a notification tap back to the right task and notification
(and tells a fresh tap from a stale one — see :func:`is_current_action`).
The filter/queue live in ``profiles.py``; HA-aware sending in ``notifier.py``.

See ``docs/PROFILES_REFACTOR_PLAN.md`` / ``docs/ACTIONABLE_NOTIFICATIONS_PLAN.md``.
"""

from __future__ import annotations

import functools
import json
import logging
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from babel import Locale
from babel.core import UnknownLocaleError

from .transitions import DUE_SOON_WINDOW

_LOGGER = logging.getLogger(__name__)

# The notify services Home Keeper delivers to. Actionable payloads go to the
# companion app's legacy per-device ``notify.mobile_app_*`` services (the newer
# notify entity API doesn't carry ``data.actions``, which every button rides on);
# ``persistent_notification`` is allowed alongside them as the one sink that stays
# *inside* Home Assistant — it drops the buttons but shows the text, and it cannot
# carry anything off the instance.
TARGET_PREFIX = "mobile_app_"
TARGET_PERSISTENT = "persistent_notification"

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

# What a send does when its profile matches nothing. The default keeps the long-
# standing promise that ``home_keeper.notify`` costs nothing on a quiet day, so an
# automation that runs every 30 minutes stays silent. ``all_clear`` is what the panel's
# Test button asks for: a delivery that always lands, so the target, the channel and
# the urgency can be checked before any task is due.
WHEN_EMPTY_SKIP = "skip"
WHEN_EMPTY_ALL_CLEAR = "all_clear"
WHEN_EMPTY = (WHEN_EMPTY_SKIP, WHEN_EMPTY_ALL_CLEAR)
DEFAULT_WHEN_EMPTY = WHEN_EMPTY_SKIP

# How loudly a notification lands. Home Keeper stores one platform-neutral value and
# expands it into *both* vocabularies at payload-build time (see :func:`payload_data`),
# because the two platforms model this differently and neither name belongs in the
# panel: Android has notification *channels* carrying an ``importance``, and iOS has no
# channels at all, only a per-notification ``interruption-level``.
URGENCY_QUIET = "quiet"
URGENCY_NORMAL = "normal"
URGENCY_HIGH = "high"
URGENCY_CRITICAL = "critical"
URGENCIES = (URGENCY_QUIET, URGENCY_NORMAL, URGENCY_HIGH, URGENCY_CRITICAL)
DEFAULT_URGENCY = URGENCY_NORMAL

# Android channel importance, and iOS interruption level, per urgency. ``normal`` is
# absent from both tables on purpose: it is each platform's own default, so a
# notification nobody has configured sends exactly the payload it sent before these
# fields existed.
_ANDROID_IMPORTANCE = {
    URGENCY_QUIET: "low",
    URGENCY_HIGH: "high",
    URGENCY_CRITICAL: "max",
}
_IOS_INTERRUPTION = {
    URGENCY_QUIET: "passive",
    URGENCY_HIGH: "time-sensitive",
    URGENCY_CRITICAL: "critical",
}
# Urgencies that must not wait for the next maintenance window. Android batches a
# normal-priority FCM message on an idle phone, which is the opposite of what these two
# mean; ``ttl: 0`` plus ``priority: high`` is the companion app's documented way to say
# "deliver this now or not at all".
_WAKE_URGENCIES = (URGENCY_HIGH, URGENCY_CRITICAL)
# iOS demotes a critical alert to a normal one unless the user has granted Critical
# Alerts to the Home Assistant app, so this is a request rather than a guarantee. Full
# volume because an alert worth overriding the mute switch is worth hearing.
_IOS_CRITICAL_SOUND = {"name": "default", "critical": 1, "volume": 1.0}

# Action-string scheme:
# ``home_keeper::<verb>::<task_id>::<notification_id>::<due_token>``. The action string
# is the only field reliably echoed back in ``mobile_app_notification_action``, so the
# verb, task, notification and a freshness token are all encoded into it. The prefix
# scopes ours on a global event bus that also carries other integrations' actions.
#
# The trailing ``due_token`` is the task's ``next_due`` at send time (see
# :func:`due_token`), which makes the button a snapshot that can be checked against the
# live task on tap — see :func:`is_current_action`. Notifications delivered *before*
# tokens existed carry the older four-field form, which still decodes (with no token)
# so buttons already sitting on someone's phone keep working.
_ACTION_PREFIX = "home_keeper"
_ACTION_SEP = "::"


def due_token(task: dict[str, Any]) -> str:
    """The freshness token for *task* — its ``next_due``, verbatim.

    Raw rather than hashed on purpose: ISO-8601 never contains the ``::`` separator,
    the values compare as exact strings with no parsing or timezone normalization, and
    it reads plainly in a debug log or a hand-written test action string.
    """
    return str(task.get("next_due") or "")


def is_current_action(
    task: dict[str, Any], token: str | None, *, tokenless_ok: bool
) -> bool:
    """Whether a tapped action still matches the task state its button was built from.

    *token* is the ``next_due`` snapshot the button carried. A mismatch means the task
    moved between the send and the tap — completed, snoozed, skipped or rescheduled,
    whether from this notification, a second card for the same task, or another surface
    entirely — so the tap is stale and must not act on the task again.

    Comparing against the task's *live* ``next_due`` (rather than anything scoped to the
    notification the tap came from) is what makes two independent cards for one task
    invalidate each other: they encode the same token, so whichever is tapped first
    advances the task and strands the other.

    A notification delivered before tokens existed carries ``token is None``. There is
    nothing to compare, so the caller's own due-state check (*tokenless_ok*) decides.
    """
    if token is None:
        return tokenless_ok
    return token == due_token(task)


def encode_action(verb: str, task_id: str, notification_id: str, token: str) -> str:
    """Build the action identifier carried on a notification button.

    *token* is the task's freshness token — see :func:`due_token`.
    """
    return _ACTION_SEP.join((_ACTION_PREFIX, verb, task_id, notification_id, token))


def decode_action(action: str | None) -> tuple[str, str, str, str | None] | None:
    """Parse an action string into ``(verb, task_id, notification_id, due_token)``.

    Accepts both the current five-field form and the legacy four-field one, whose
    ``due_token`` comes back as ``None``. Returns ``None`` for anything that isn't a
    well-formed Home Keeper action (a foreign integration's action, or a
    malformed/empty value) so the listener can ignore it.
    """
    if not action:
        return None
    parts = action.split(_ACTION_SEP)
    if len(parts) not in (4, 5) or parts[0] != _ACTION_PREFIX:
        return None
    verb, task_id, notification_id = parts[1], parts[2], parts[3]
    token = parts[4] if len(parts) == 5 else None
    if verb not in ACTIONS or not task_id or not notification_id:
        return None
    if token is not None and not token:
        # Our builder always encodes a real ``next_due`` (a task only reaches a
        # notification with one), so an empty token is malformed, not legacy.
        return None
    return verb, task_id, notification_id, token


# ── notification normalization ───────────────────────────────────────────────────


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v) for v in value if v not in (None, "")]


def is_allowed_target(target: str) -> bool:
    """Whether Home Keeper may deliver to the ``notify.<target>`` service."""
    return target.startswith(TARGET_PREFIX) or target == TARGET_PERSISTENT


def split_targets(value: Any) -> tuple[list[str], list[str]]:
    """Partition raw notify targets into ``(accepted, rejected)``.

    The picker in the panel only ever offers ``mobile_app_*`` services, but that is a
    UI courtesy — nothing stopped a stored notification (or a ``target:`` override on
    ``home_keeper.notify``) from naming *any* notify service the admin has set up:
    SMTP, Telegram, a webhook. That turns Home Keeper into a confused deputy, relaying
    text an unprivileged caller controls out through a channel they could not reach
    themselves. So the allowlist is enforced where the value is *stored*, not only
    where it is displayed.

    ``persistent_notification`` is allowed because it is the one destination that
    never leaves the instance: what it delivers, an HA user could already read.
    """
    accepted: list[str] = []
    rejected: list[str] = []
    for target in _str_list(value):
        (accepted if is_allowed_target(target) else rejected).append(target)
    return accepted, rejected


def normalize_notification(raw: Any) -> dict[str, Any]:
    """Coerce one raw notification to its stored, fully-defaulted shape.

    A notification references a profile (``profile_id``) and carries delivery: an id
    (stable, referenced by action strings), a name, mobile ``targets``, the ordered
    ``actions`` button set (clamped to known verbs, de-duplicated), ``snooze_hours``,
    ``style`` (walk/digest), ``auto`` triggers, and how it lands on the phone —
    ``channel`` (the Android notification channel, threading reminders on iOS) and
    ``urgency`` (clamped to :data:`URGENCIES`).
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
    urgency = raw.get("urgency")
    targets, rejected = split_targets(raw.get("targets"))
    if rejected:
        _LOGGER.warning(
            "Home Keeper dropped notify target(s) %s: only %s* and %s are supported",
            ", ".join(rejected),
            TARGET_PREFIX,
            TARGET_PERSISTENT,
        )
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex),
        "name": str(raw.get("name") or "Notification"),
        "profile_id": str(raw["profile_id"]) if raw.get("profile_id") else None,
        "targets": targets,
        "actions": actions or list(DEFAULT_ACTIONS),
        "snooze_hours": snooze_hours,
        "style": style if style in STYLES else STYLE_WALK,
        "channel": str(raw.get("channel") or "").strip(),
        "urgency": urgency if urgency in URGENCIES else DEFAULT_URGENCY,
        "auto": {
            "overdue": bool(auto.get("overdue", False)),
            "due_soon": bool(auto.get("due_soon", False)),
        },
    }


def sends_when_empty(when_empty: Any) -> bool:
    """Whether a queue that matched nothing should still deliver the all-clear.

    A predicate rather than a clamp because the service schema validates the field
    against :data:`WHEN_EMPTY` before it reaches here, so there is nothing left to
    coerce. It lives in this module rather than inline in ``notifier`` so the decision
    sits on the mutation-scored surface: the same comparison written in ``notifier.py``
    would never be mutated, and "an empty queue still sends" is exactly the branch worth
    proving a test would catch.
    """
    return when_empty == WHEN_EMPTY_ALL_CLEAR


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


# ── per-task button sets ────────────────────────────────────────────────────────


def is_completion_blocked(task: dict[str, Any]) -> bool:
    """Whether nothing in Home Keeper can mark *task* done.

    Reads ``managed_by.completion_blocked`` rather than the ``problem_sensor`` source,
    matching what the panel and the card already use to hide *Done*, so a future
    completion-blocked source is covered without another edit here.
    """
    managed_by = task.get("managed_by")
    return isinstance(managed_by, dict) and bool(managed_by.get("completion_blocked"))


def actions_for(task: dict[str, Any], actions: list[str]) -> list[str]:
    """The subset of *actions* that can actually act on *task*, in configured order.

    A completion-blocked task (today, a ``problem``-sensor mirror) rejects *Mark done*
    and *Skip* in the store: both assert the problem is dealt with, and only the
    originating integration can decide that. Offering buttons the store will refuse
    is worse than offering none — ``notifier`` swallows the rejection, so the tap
    reads as a dead button.

    *Snooze* is the one mutating verb that stays honest on such a task: it defers the
    reminder and leaves the problem standing. So it is offered here **even when the
    notification's own button set leaves it out** — a walk advances only on a
    successful action, and without Snooze one of these at the head of the queue would
    re-send forever and never reach the tasks behind it (#248).
    """
    if not is_completion_blocked(task):
        return list(actions)
    kept = [verb for verb in actions if verb in (ACTION_SNOOZE, ACTION_OPEN)]
    if ACTION_SNOOZE not in kept:
        # Deliberately overriding the user's button set, which is the one place this
        # function adds rather than subtracts. `open` is a client-side URI that never
        # calls back, so a set of only `open` (or an empty one) leaves a walk with
        # nothing that advances it and it re-sends this task forever. One button the
        # user did not ask for beats a notification that can never be got past.
        kept.insert(0, ACTION_SNOOZE)
    return kept


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


def payload_data(
    notification: dict[str, Any], *, actions: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """The shared mobile-app ``data`` block every payload in this module carries.

    Home Keeper stores one platform-neutral ``(channel, urgency)`` pair and emits *both*
    vocabularies here: Android reads ``channel`` and ``importance``, iOS reads
    ``push.thread-id`` and ``push.interruption-level``, and each app ignores the keys it
    does not know. That is what lets the panel ask "how urgent is this?" once instead of
    asking which phone the household carries.

    An unconfigured notification (no channel, ``normal`` urgency) adds nothing, so it
    sends byte-for-byte what it sent before these fields existed — the tables above
    leave ``normal`` out precisely so this stays true.

    One caveat worth knowing when reading this: on Android a channel's importance is
    fixed when the channel is *created*. Raising the urgency later re-sends the key, but
    the phone keeps the setting the channel already has (only the user can change it, in
    the phone's own settings). Renaming the channel is what starts one over.
    """
    data: dict[str, Any] = {
        "tag": notification_tag(notification["id"]),
        # Every Home Keeper notification stacks together in the shade regardless of
        # channel: the channel decides how a reminder *behaves*, the group decides where
        # it *sits*, and splitting the pile per channel was not what was asked for.
        "group": "home_keeper",
    }
    if actions is not None:
        data["actions"] = actions
    push: dict[str, Any] = {}
    channel = str(notification.get("channel") or "")
    if channel:
        data["channel"] = channel  # Android: the notification channel, created on use
        push["thread-id"] = channel  # iOS: no channels, so thread by the same name
    urgency = notification.get("urgency") or DEFAULT_URGENCY
    if importance := _ANDROID_IMPORTANCE.get(urgency):
        data["importance"] = importance
    if level := _IOS_INTERRUPTION.get(urgency):
        push["interruption-level"] = level
    if urgency in _WAKE_URGENCIES:
        data["ttl"] = 0
        data["priority"] = "high"
    if urgency == URGENCY_CRITICAL:
        push["sound"] = dict(_IOS_CRITICAL_SOUND)
    if push:
        data["push"] = push
    return data


def _overdue_phrase(
    task: dict[str, Any],
    *,
    now: datetime,
    lang: str = _DEFAULT_LANG,
    window: timedelta = DUE_SOON_WINDOW,
) -> str:
    """The one-line body of a walk notification: how late, or how far off, *task* is.

    Three cases, in the order a reader meets them: already due, due inside the
    due-soon *window*, or further out than that.

    The third case is the reason *window* is a parameter. Until a notification could
    carry a task that is not due yet, "not overdue" and "due soon" were the same
    thing and everything else read "Due soon." — including a task due in six months.
    ``home_keeper.notify`` can now be asked for every task a profile covers
    (``status: all``), which makes that the common case rather than a corner, so
    anything past the window says how far off it is instead. The window is threaded
    through rather than read from the module so this agrees with
    ``profiles.matches_filter``, which takes it the same way and decides what
    "due soon" means for the queue this phrase describes.
    """
    next_due = datetime.fromisoformat(task["next_due"])
    if now >= next_due:
        days = (now - next_due).days
        if days <= 0:
            return _t(lang, "due_now")
        return _tn(lang, "overdue", days, days=days)
    remaining = next_due - now
    if remaining <= window:
        return _t(lang, "due_soon")
    # Floored, matching the overdue side above: a task 3.5 days out reads "3 days",
    # the same way one 3.5 days late reads "overdue by 3 days".
    days = remaining.days
    return _tn(lang, "due_in", days, days=days)


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
    action_id = encode_action(verb, task["id"], notification["id"], due_token(task))
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
    window: timedelta = DUE_SOON_WINDOW,
) -> dict[str, Any]:
    """Build the ``notify`` service data for a single task in a *walk* notification."""
    actions = [
        _action_button(v, task, notification, lang=lang)
        for v in actions_for(task, notification["actions"])
    ]
    return {
        "title": str(task.get("name") or "Home Keeper"),
        "message": _overdue_phrase(task, now=now, lang=lang, window=window),
        "data": payload_data(notification, actions=actions),
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
        "data": payload_data(notification),
    }


def build_all_clear(
    notification: dict[str, Any], *, lang: str = _DEFAULT_LANG
) -> dict[str, Any]:
    """The closing notification when a walk empties its queue."""
    return {
        "title": _t(lang, "all_clear_title"),
        "message": _t(lang, "all_clear_message"),
        "data": payload_data(notification),
    }
