"""HA-aware delivery for actionable notifications.

A **notification** (delivery) references a **profile** (filter) by ``profile_id``.
This module resolves that pairing, sends to ``notify.mobile_app_*`` targets, listens
for the ``mobile_app_notification_action`` events a button tap fires, routes each back
to the right task (Mark done → ``complete_task``, Snooze → ``snooze_task``, Skip →
``skip_task``), and **advances the walk** by re-sending the notification's next due
task. The pure filter/queue live in :mod:`profiles`, the payload/decoding in
:mod:`notifications`; this is the thin Home Assistant boundary.

See ``docs/PROFILES_REFACTOR_PLAN.md`` / ``docs/ACTIONABLE_NOTIFICATIONS_PLAN.md``.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from . import notifications, profiles
from .const import (
    OPTION_NOTIFICATIONS,
    OPTION_PROFILES,
    ORIGIN_NOTIFICATION_ACTION,
)
from .models import TaskValidationError
from .options import current_options

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .coordinator import HomeKeeperCoordinator

_LOGGER = logging.getLogger(__name__)

# The bus event the HA companion app fires when an actionable-notification button is
# tapped. Its ``action`` field carries the string we encoded into the button.
EVENT_MOBILE_APP_ACTION = "mobile_app_notification_action"

# notify services we can target with actionable payloads (the legacy per-device
# services — the newer notify entity API doesn't carry ``data.actions``).
_TARGET_PREFIX = "mobile_app_"


def available_targets(hass: HomeAssistant) -> list[str]:
    """Sorted list of ``mobile_app_*`` notify service names available right now.

    Surfaced to the panel (via ``get_options``) and the options flow so the user
    picks targets from a live list rather than typing service names.
    """
    services = hass.services.async_services().get("notify", {})
    return sorted(name for name in services if name.startswith(_TARGET_PREFIX))


def _profiles(entry: ConfigEntry) -> list[dict[str, Any]]:
    value = current_options(entry).get(OPTION_PROFILES, [])
    return value if isinstance(value, list) else []


def _notifications(entry: ConfigEntry) -> list[dict[str, Any]]:
    value = current_options(entry).get(OPTION_NOTIFICATIONS, [])
    return value if isinstance(value, list) else []


async def _send_payload(
    hass: HomeAssistant, targets: list[str], payload: dict[str, Any]
) -> None:
    """Best-effort fan-out of *payload* to each notify target (failures logged)."""
    for target in targets:
        try:
            await hass.services.async_call("notify", target, payload, blocking=False)
        except Exception as err:  # a bad/renamed target must not break the send loop
            _LOGGER.debug("Home Keeper notify target %r failed: %s", target, err)


async def _send(
    hass: HomeAssistant,
    coord: HomeKeeperCoordinator,
    notification: dict[str, Any],
    profile: dict[str, Any],
    *,
    reason: str,
) -> tuple[int, str | None]:
    """Send *notification* for what's due under *profile*'s filter.

    Returns ``(matched, sent_task_id)`` — how many tasks matched and the id of the task
    surfaced in a *walk* (``None`` for an empty queue or a digest).
    """
    now = dt_util.now()
    queue = profiles.due_queue(
        list(coord.store.get_tasks().values()), profile["filter"], now=now
    )
    if not queue:
        return 0, None
    if notification["style"] == notifications.STYLE_DIGEST:
        payload = notifications.build_digest(queue, notification=notification, now=now)
        sent_id: str | None = None
    else:
        head = queue[0]
        payload = notifications.build_notification(
            head, notification=notification, now=now
        )
        sent_id = head["id"]
    await _send_payload(hass, notification["targets"], payload)
    _LOGGER.debug(
        "Home Keeper sent %s notification %r (%d due, reason=%s)",
        notification["style"],
        notification["name"],
        len(queue),
        reason,
    )
    return len(queue), sent_id


async def async_send_for_notification(
    hass: HomeAssistant,
    coord: HomeKeeperCoordinator,
    notification: dict[str, Any],
    *,
    reason: str = "manual",
) -> tuple[int, str | None]:
    """Resolve *notification*'s profile and send what's due. No-op if it has none."""
    profile = profiles.resolve_profile(
        _profiles(coord.entry), notification.get("profile_id")
    )
    if profile is None:
        _LOGGER.debug(
            "Home Keeper notification %r has no resolvable profile (%s)",
            notification.get("name"),
            notification.get("profile_id"),
        )
        return 0, None
    return await _send(hass, coord, notification, profile, reason=reason)


async def async_send_auto(
    hass: HomeAssistant, coord: HomeKeeperCoordinator, fired_kinds: set[str]
) -> None:
    """Send every notification whose automatic trigger matches a fired transition.

    *fired_kinds* is a subset of ``{"overdue", "due_soon"}`` for the transitions that
    fired this refresh. Each matching notification sends once (its profile's filter
    decides the content), so a burst of crossings collapses to one push per
    notification rather than one per task.
    """
    for notification in _notifications(coord.entry):
        auto = notification["auto"]
        if ("overdue" in fired_kinds and auto["overdue"]) or (
            "due_soon" in fired_kinds and auto["due_soon"]
        ):
            await async_send_for_notification(hass, coord, notification, reason="auto")


async def async_run_notify(
    hass: HomeAssistant, coord: HomeKeeperCoordinator, data: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Resolve the ``home_keeper.notify`` call and send it.

    Accepts a saved ``notification`` (id/name → its profile + delivery), or a
    ``profile`` (id/name) plus inline delivery, or pure inline overrides for an ad-hoc
    send. Returns ``(response, error)`` — on success ``response`` is
    ``{"matched", "sent"}``; when a named notification/profile can't be found ``error``
    is a ``{"key", "placeholders"}`` mapping the handler turns into a localized
    ``ServiceValidationError`` (keeping this module HA-exception-free).
    """
    base_notif: dict[str, Any] | None = None
    base_profile: dict[str, Any] | None = None

    if data.get("notification"):
        base_notif = notifications.resolve_notification(
            _notifications(coord.entry), data["notification"]
        )
        if base_notif is None:
            return {}, {
                "key": "notify_notification_not_found",
                "placeholders": {"notification": str(data["notification"])},
            }
        base_profile = profiles.resolve_profile(
            _profiles(coord.entry), base_notif.get("profile_id")
        )
    if data.get("profile"):
        base_profile = profiles.resolve_profile(_profiles(coord.entry), data["profile"])
        if base_profile is None:
            return {}, {
                "key": "notify_profile_not_found",
                "placeholders": {"profile": str(data["profile"])},
            }

    # Effective profile (filter) = base profile + inline filter overrides.
    filt_over = {
        out: data[in_]
        for in_, out in (
            ("labels", "labels"),
            ("areas", "areas"),
            ("devices", "devices"),
            ("status", "status"),
        )
        if in_ in data
    }
    profile_raw: dict[str, Any] = {"name": "ad-hoc", **(base_profile or {})}
    if filt_over:
        profile_raw["filter"] = {**(base_profile or {}).get("filter", {}), **filt_over}
    profile = profiles.normalize_profile(profile_raw)

    # Effective notification (delivery) = base notification + inline overrides.
    notif_raw: dict[str, Any] = {"name": "ad-hoc", **(base_notif or {})}
    if "target" in data:
        notif_raw["targets"] = data["target"]
    for key in ("actions", "snooze_hours", "style"):
        if key in data:
            notif_raw[key] = data[key]
    notif_raw["profile_id"] = profile["id"]
    notification = notifications.normalize_notification(notif_raw)

    matched, sent = await _send(hass, coord, notification, profile, reason="service")
    return {"matched": matched, "sent": sent}, None


def async_setup_notifications(
    hass: HomeAssistant, entry: ConfigEntry, coord: HomeKeeperCoordinator
) -> CALLBACK_TYPE:
    """Subscribe to mobile-app action events; returns the unsubscribe callback."""

    async def _handle(verb: str, task_id: str, notification_id: str) -> None:
        notification = notifications.resolve_notification(
            _notifications(entry), notification_id
        )
        now = dt_util.now()
        try:
            if verb == notifications.ACTION_COMPLETE:
                await coord.store.complete_task(
                    task_id, origin=ORIGIN_NOTIFICATION_ACTION
                )
            elif verb == notifications.ACTION_SNOOZE:
                hours = (
                    notification["snooze_hours"]
                    if notification
                    else notifications.DEFAULT_SNOOZE_HOURS
                )
                await coord.store.snooze_task(
                    task_id,
                    now + timedelta(hours=hours),
                    origin=ORIGIN_NOTIFICATION_ACTION,
                )
            elif verb == notifications.ACTION_SKIP:
                await coord.store.skip_task(task_id, origin=ORIGIN_NOTIFICATION_ACTION)
            else:  # ACTION_OPEN — the URI deep-link is handled on the device
                return
        except (KeyError, TaskValidationError) as err:
            _LOGGER.debug(
                "Home Keeper notification action %s on %s ignored: %s",
                verb,
                task_id,
                err,
            )
            return
        await coord.async_request_refresh()
        # Advance the walk: the just-actioned task has left the due set, so re-sending
        # the notification's next due task replaces it in place; an empty queue closes
        # with an "all caught up" note. (Only for a saved walk notification.)
        if notification is not None and (
            notification["style"] == notifications.STYLE_WALK
        ):
            matched, _ = await async_send_for_notification(
                hass, coord, notification, reason="walk-advance"
            )
            if matched == 0:
                await _send_payload(
                    hass,
                    notification["targets"],
                    notifications.build_all_clear(notification),
                )

    @callback
    def _on_action(event: Event) -> None:
        decoded = notifications.decode_action(event.data.get("action"))
        if decoded is None:
            return
        verb, task_id, notification_id = decoded
        hass.async_create_task(_handle(verb, task_id, notification_id))

    return hass.bus.async_listen(EVENT_MOBILE_APP_ACTION, _on_action)
