"""HA-aware delivery for actionable notifications.

Sends profile notifications to ``notify.mobile_app_*`` targets, listens for the
``mobile_app_notification_action`` events that tapping a button fires, routes each
back to the right task/profile (Mark done → ``complete_task``, Snooze →
``snooze_task``, Skip → ``skip_task``), and **advances the walk** by re-sending the
profile's next due task on each action. The pure payload/queue/decoding logic lives
in :mod:`notifications`; this module is the thin Home Assistant boundary.

See ``docs/ACTIONABLE_NOTIFICATIONS_PLAN.md``.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from . import notifications
from .const import OPTION_NOTIFY_PROFILES, ORIGIN_NOTIFICATION_ACTION
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
    profiles = current_options(entry).get(OPTION_NOTIFY_PROFILES, [])
    return profiles if isinstance(profiles, list) else []


async def _send_payload(
    hass: HomeAssistant, targets: list[str], payload: dict[str, Any]
) -> None:
    """Best-effort fan-out of *payload* to each notify target (failures logged)."""
    for target in targets:
        try:
            await hass.services.async_call("notify", target, payload, blocking=False)
        except Exception as err:  # a bad/renamed target must not break the send loop
            _LOGGER.debug("Home Keeper notify target %r failed: %s", target, err)


async def async_send_for_profile(
    hass: HomeAssistant,
    coord: HomeKeeperCoordinator,
    profile: dict[str, Any],
    *,
    reason: str = "manual",
) -> tuple[int, str | None]:
    """Send *profile*'s notification(s) for what's due now.

    Returns ``(matched, sent_task_id)`` — how many tasks matched the profile filter,
    and the id of the task surfaced in a *walk* (``None`` for an empty queue or a
    digest). A walk sends only the head of the queue; a digest sends one summary.
    """
    now = dt_util.now()
    queue = notifications.due_queue(
        list(coord.store.get_tasks().values()), profile["filter"], now=now
    )
    if not queue:
        return 0, None
    if profile["style"] == notifications.STYLE_DIGEST:
        payload = notifications.build_digest(queue, profile=profile, now=now)
        sent_id: str | None = None
    else:
        head = queue[0]
        payload = notifications.build_notification(head, profile=profile, now=now)
        sent_id = head["id"]
    await _send_payload(hass, profile["targets"], payload)
    _LOGGER.debug(
        "Home Keeper sent %s notification for profile %r (%d due, reason=%s)",
        profile["style"],
        profile["name"],
        len(queue),
        reason,
    )
    return len(queue), sent_id


async def async_send_auto(
    hass: HomeAssistant, coord: HomeKeeperCoordinator, fired_kinds: set[str]
) -> None:
    """Send to every profile whose automatic trigger matches a fired transition.

    *fired_kinds* is a subset of ``{"overdue", "due_soon"}`` for the transitions that
    fired this refresh. Each matching profile sends once (the profile's own filter
    decides the content), so a burst of crossings collapses to one notification per
    profile rather than one per task.
    """
    for profile in _profiles(coord.entry):
        auto = profile["auto"]
        if ("overdue" in fired_kinds and auto["overdue"]) or (
            "due_soon" in fired_kinds and auto["due_soon"]
        ):
            await async_send_for_profile(hass, coord, profile, reason="auto")


async def async_run_notify(
    hass: HomeAssistant, coord: HomeKeeperCoordinator, data: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Resolve the ``home_keeper.notify`` call to a profile and send it.

    Returns ``(response, error)`` — on success ``response`` is ``{"matched", "sent"}``
    and ``error`` is ``None``; when a named profile can't be found ``error`` is a
    ``{"key", "placeholders"}`` mapping the service handler turns into a localized
    ``ServiceValidationError`` (keeping this module HA-exception-free).
    """
    profiles = _profiles(coord.entry)
    base: dict[str, Any] | None = None
    if data.get("profile"):
        base = notifications.resolve_profile(profiles, data["profile"])
        if base is None:
            return {}, {
                "key": "notify_profile_not_found",
                "placeholders": {"profile": str(data["profile"])},
            }

    overrides: dict[str, Any] = {}
    if "target" in data:
        overrides["targets"] = data["target"]
    filt = {
        out: data[in_]
        for in_, out in (
            ("labels", "labels"),
            ("areas", "areas"),
            ("devices", "devices"),
            ("status", "status"),
        )
        if in_ in data
    }
    if filt:
        overrides["filter"] = {**(base or {}).get("filter", {}), **filt}
    for key in ("actions", "snooze_hours", "style"):
        if key in data:
            overrides[key] = data[key]

    if base is None:
        profile = notifications.normalize_profile({"name": "ad-hoc", **overrides})
    else:
        profile = notifications.normalize_profile({**base, **overrides})

    matched, sent = await async_send_for_profile(hass, coord, profile, reason="service")
    return {"matched": matched, "sent": sent}, None


def async_setup_notifications(
    hass: HomeAssistant, entry: ConfigEntry, coord: HomeKeeperCoordinator
) -> CALLBACK_TYPE:
    """Subscribe to mobile-app action events; returns the unsubscribe callback."""

    async def _handle(verb: str, task_id: str, profile_id: str) -> None:
        profile = notifications.resolve_profile(_profiles(entry), profile_id)
        now = dt_util.now()
        try:
            if verb == notifications.ACTION_COMPLETE:
                await coord.store.complete_task(
                    task_id, origin=ORIGIN_NOTIFICATION_ACTION
                )
            elif verb == notifications.ACTION_SNOOZE:
                hours = (
                    profile["snooze_hours"]
                    if profile
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
        # the profile's next due task replaces the notification in place; an empty
        # queue closes with an "all caught up" note.
        if profile is not None and profile["style"] == notifications.STYLE_WALK:
            matched, _ = await async_send_for_profile(
                hass, coord, profile, reason="walk-advance"
            )
            if matched == 0:
                await _send_payload(
                    hass, profile["targets"], notifications.build_all_clear(profile)
                )

    @callback
    def _on_action(event: Event) -> None:
        decoded = notifications.decode_action(event.data.get("action"))
        if decoded is None:
            return
        verb, task_id, profile_id = decoded
        hass.async_create_task(_handle(verb, task_id, profile_id))

    return hass.bus.async_listen(EVENT_MOBILE_APP_ACTION, _on_action)
