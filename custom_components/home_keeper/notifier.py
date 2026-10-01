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

import functools
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from . import notifications, profiles, recurrence
from .const import (
    OPTION_ALLOW_SKIP,
    OPTION_ALLOW_SNOOZE,
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
# services — the newer notify entity API doesn't carry ``data.actions``). The prefix
# lives in :mod:`notifications`, which enforces it on every stored target; here it
# only narrows what the picker offers.
_TARGET_PREFIX = notifications.TARGET_PREFIX


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


def effective_filter_tasks(
    hass: HomeAssistant, tasks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return *tasks* with **effective** label/area ids resolved for filtering.

    A profile filter matches a task's labels/area, but a task inherits both from its
    attached device and (transitively) its area — exactly as the panel and card resolve
    them (``card-filter.ts`` ``taskLabelIds``/``taskAreaId``). The pure
    ``profiles.matches_filter`` only sees a task's *own* fields, so we enrich here, in
    the HA-aware layer that has the registries, before handing tasks to ``due_queue``.
    This keeps the same Profile meaning the same thing in a notification as it does in
    the admin list and the dashboard card ("label = dog" picks up a task on a device or
    area labelled ``dog``). ``device_id`` is unchanged — a device filter matches the
    task's own device, like the frontend.

    Public because the to-do list sync is the second consumer: ``todo_list_sync``
    enriches through this same helper before planning, so a profile selects exactly
    the same tasks for a synced to-do list as it does for a notification.
    """
    dev_reg = dr.async_get(hass)
    area_reg = ar.async_get(hass)
    enriched: list[dict[str, Any]] = []
    for task in tasks:
        labels = set(task.get("labels") or [])
        area_id = task.get("area_id")
        device = dev_reg.async_get(task["device_id"]) if task.get("device_id") else None
        if device is not None:
            labels |= set(device.labels)
            if not area_id:
                area_id = device.area_id
        if area_id:
            area = area_reg.async_get_area(area_id)
            if area is not None:
                labels |= set(area.labels)
        enriched.append({**task, "labels": sorted(labels), "area_id": area_id})
    return enriched


def _notification_profile(
    entry: ConfigEntry, notification: dict[str, Any]
) -> tuple[dict[str, Any] | None, bool]:
    """Resolve a saved notification's effective filter profile.

    Returns ``(profile, misconfigured)``:
      - ``profile_id`` resolves → ``(that profile, False)``;
      - ``profile_id`` unset → ``(the all-due profile, False)`` (a notification with no
        profile covers every due task, as documented);
      - ``profile_id`` set but missing (e.g. the profile was deleted) →
        ``(None, True)`` so callers skip/raise rather than silently fall back to "all
        overdue tasks" and blast every task to the targets.
    """
    pid = notification.get("profile_id")
    profile = profiles.resolve_profile(_profiles(entry), pid)
    if profile is not None:
        return profile, False
    if pid:
        return None, True
    return profiles.normalize_profile({"name": "all"}), False


def _verb_allowed(coord: HomeKeeperCoordinator, verb: str) -> bool:
    """Whether the ``allow_snooze`` / ``allow_skip`` switch still permits *verb*."""
    opts = current_options(coord.entry)
    if verb == notifications.ACTION_SNOOZE:
        return bool(opts[OPTION_ALLOW_SNOOZE])
    if verb == notifications.ACTION_SKIP:
        return bool(opts[OPTION_ALLOW_SKIP])
    return True


async def _send_payload(
    hass: HomeAssistant, targets: list[str], payload: dict[str, Any]
) -> None:
    """Best-effort fan-out of *payload* to each notify target (failures logged)."""
    for target in targets:
        try:
            await hass.services.async_call("notify", target, payload, blocking=False)
        except Exception as err:  # a bad/renamed target must not break the send loop
            _LOGGER.debug("Home Keeper notify target %r failed: %s", target, err)


async def _build_payload(
    hass: HomeAssistant,
    notification: dict[str, Any],
    queue: list[dict[str, Any]],
    *,
    now: datetime,
    lang: str,
    allow_snooze: bool = True,
    allow_skip: bool = True,
) -> tuple[dict[str, Any], str | None]:
    """Build the ``notify`` payload for *queue*, off the event loop.

    ``notifications.build_notification``/``build_digest`` resolve translated strings
    and Babel CLDR plural rules, which do blocking file I/O on first use per language
    (``notifications.py`` stays HA-free on purpose — see its module docstring — so it
    can't call ``hass.async_add_executor_job`` itself). Running that inline here trips
    Home Assistant's blocking-call detector (#150).

    An empty *queue* reaches here only when the caller asked for ``when_empty:
    all_clear`` — ``_send`` returns before this otherwise. The all-clear is built here
    rather than at the call site so this stays the single executor hand-off for payload
    text, which is what ``tests/unit/test_notifier_blocking.py`` asserts on. It suits
    both styles unchanged: it carries no actions, exactly as a digest does, and it is
    already the card a walk closes with.
    """
    if not queue:
        payload = await hass.async_add_executor_job(
            functools.partial(notifications.build_all_clear, notification, lang=lang)
        )
        return payload, None
    if notification["style"] == notifications.STYLE_DIGEST:
        payload = await hass.async_add_executor_job(
            functools.partial(
                notifications.build_digest,
                queue,
                notification=notification,
                now=now,
                lang=lang,
            )
        )
        return payload, None
    head = queue[0]
    payload = await hass.async_add_executor_job(
        functools.partial(
            notifications.build_notification,
            head,
            notification=notification,
            now=now,
            lang=lang,
            allow_snooze=allow_snooze,
            allow_skip=allow_skip,
        )
    )
    return payload, head["id"]


async def _send(
    hass: HomeAssistant,
    coord: HomeKeeperCoordinator,
    notification: dict[str, Any],
    profile: dict[str, Any],
    *,
    reason: str,
    when_empty: str = notifications.WHEN_EMPTY_SKIP,
    exclude_task_id: str | None = None,
) -> tuple[int, str | None]:
    """Send *notification* for what's due under *profile*'s filter.

    Returns ``(matched, sent_task_id)`` — how many tasks matched and the id of the task
    surfaced in a *walk* (``None`` for an empty queue or a digest).

    *when_empty* decides what an empty queue means. The default keeps the long-standing
    contract that a send costs nothing on a quiet day, so the automatic triggers and
    every existing automation are unaffected. ``all_clear`` is what the panel's Test
    button asks for: it delivers the "All caught up" card instead of nothing, so the
    target, channel and urgency can be checked before any task is due.

    *exclude_task_id* keeps one task out of the queue. The walk-advance sets it to the
    task the user just acted on: under a ``due_soon`` or ``all`` status that task can
    still be in the queue, and to send it again with new buttons lets a second tap act
    on it again (B16-5).
    """
    now = dt_util.now()
    tasks = effective_filter_tasks(
        hass,
        [
            task
            for task in coord.store.get_tasks().values()
            if exclude_task_id is None or task.get("id") != exclude_task_id
        ],
    )
    queue = profiles.due_queue(tasks, profile["filter"], now=now)
    if not queue and not notifications.sends_when_empty(when_empty):
        return 0, None
    if not notification["targets"]:
        # Matched tasks but nowhere to send them — a profile is only a filter; the
        # delivery target lives on a Notification. Warn rather than silently no-op so a
        # misconfigured auto/walk notification is diagnosable. (The notify *service*
        # rejects this loudly before reaching here — see async_run_notify.)
        #
        # Only for a queue that actually matched: an empty one under ``all_clear`` has
        # no misconfiguration to report beyond the missing target itself, and warning
        # about "0 task(s)" would read as a bug.
        if queue:
            _LOGGER.warning(
                "Home Keeper notification %r matched %d task(s) but has no notify "
                "target, so nothing was sent. Add a 'Send to' device in "
                "Settings → Notifications.",
                notification["name"],
                len(queue),
            )
        return len(queue), None
    lang = hass.config.language
    opts = current_options(coord.entry)
    payload, sent_id = await _build_payload(
        hass,
        notification,
        queue,
        now=now,
        lang=lang,
        allow_snooze=bool(opts[OPTION_ALLOW_SNOOZE]),
        allow_skip=bool(opts[OPTION_ALLOW_SKIP]),
    )
    await _send_payload(hass, notification["targets"], payload)
    # The payload itself, not only a summary of it: the ``data`` block is where the
    # channel and the urgency live, and it is the only place a report of "the channel
    # did nothing on my phone" can be settled. Home Keeper builds that block, the
    # companion app reads it, and nothing in between is visible from here — so the log
    # says exactly what left Home Assistant.
    _LOGGER.debug(
        "Home Keeper sent %s notification %r to %s (%d due, reason=%s): %s",
        notification["style"],
        notification["name"],
        notification["targets"],
        len(queue),
        reason,
        payload,
    )
    return len(queue), sent_id


async def async_send_for_notification(
    hass: HomeAssistant,
    coord: HomeKeeperCoordinator,
    notification: dict[str, Any],
    *,
    reason: str = "manual",
    when_empty: str = notifications.WHEN_EMPTY_SKIP,
    exclude_task_id: str | None = None,
) -> tuple[int, str | None]:
    """Resolve *notification*'s profile and send what's due.

    No-op if its ``profile_id`` is set but no longer resolves (a deleted profile) —
    sending "all overdue tasks" in that case would be a surprising blast.
    """
    profile, misconfigured = _notification_profile(coord.entry, notification)
    if misconfigured:
        _LOGGER.debug(
            "Home Keeper notification %r references a missing profile (%s); skipping",
            notification.get("name"),
            notification.get("profile_id"),
        )
        return 0, None
    assert profile is not None  # not misconfigured => resolved or the all-due profile
    return await _send(
        hass,
        coord,
        notification,
        profile,
        reason=reason,
        when_empty=when_empty,
        exclude_task_id=exclude_task_id,
    )


async def async_send_auto(
    hass: HomeAssistant,
    coord: HomeKeeperCoordinator,
    crossed: list[tuple[str, str]],
) -> None:
    """Send every notification whose automatic trigger matches a fired transition.

    *crossed* holds one ``(kind, task_id)`` pair for each transition that fired this
    refresh, where *kind* is ``"overdue"`` or ``"due_soon"``. A notification sends
    only when a task that crossed a kind it listens for also passes its profile's
    filter. A crossing outside the profile does not send it again (B16-1). Each
    matching notification sends once (its profile's filter decides the content), so a
    burst of crossings collapses to one push per notification rather than one per
    task.
    """
    notifications_list = _notifications(coord.entry)
    if not notifications_list or not crossed:
        return
    task_map = coord.store.get_tasks()
    crossed_ids = {task_id for _, task_id in crossed}
    enriched = {
        task["id"]: task
        for task in effective_filter_tasks(
            hass, [task_map[tid] for tid in crossed_ids if tid in task_map]
        )
    }
    now = dt_util.now()
    for notification in notifications_list:
        auto = notification["auto"]
        ids = {task_id for kind, task_id in crossed if auto.get(kind)}
        if not ids:
            continue
        profile, misconfigured = _notification_profile(coord.entry, notification)
        if misconfigured or profile is None:
            continue
        if not any(
            profiles.matches_filter(enriched[tid], profile["filter"], now=now)
            for tid in ids
            if tid in enriched
        ):
            continue
        await async_send_for_notification(hass, coord, notification, reason="auto")


async def async_run_notify(
    hass: HomeAssistant, coord: HomeKeeperCoordinator, data: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Resolve the ``home_keeper.notify`` call and send it.

    Accepts a saved ``notification`` (id/name → its profile + delivery), or a saved
    ``profile`` (id/name) to send with default delivery, either optionally with a
    ``target`` override. A bare/target-only call covers every due task.

    Two further overrides shape one call without editing anything saved. ``status``
    replaces the profile's due-state filter, so "everything this profile covers" needs
    no second profile; its ``none`` value selects nothing and exists only here, never in
    a stored profile (see ``profiles.STATUS_NONE``). ``when_empty`` says what a queue
    that matched nothing does — skip, as it always has, or deliver the "All caught up"
    card. Together they are what lets the panel's Test button always land something.

    That pairing also gives ``matched`` a second reading worth knowing before you
    depend on it. Under ``when_empty: all_clear`` something is always delivered, so
    ``matched`` says *which* card went out rather than whether one did: above zero is
    a task, zero is the all-clear. Under the default it keeps its plain meaning, where
    zero means nothing was sent.

    Returns
    ``(response, error)`` — on success ``response`` is ``{"matched", "sent"}``; when a
    named notification/profile can't be found ``error`` is a ``{"key", "placeholders"}``
    mapping the handler turns into a localized ``ServiceValidationError`` (keeping this
    module HA-exception-free). Custom filters/delivery come from saved Profiles and
    Notifications — the whole point of making them reusable — not inline on every call.
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
        base_profile, misconfigured = _notification_profile(coord.entry, base_notif)
        if misconfigured:
            # A saved notification that points at a deleted profile is a config error,
            # not a request to notify every overdue task — surface it.
            return {}, {
                "key": "notify_profile_not_found",
                "placeholders": {"profile": str(base_notif.get("profile_id"))},
            }
    if data.get("profile"):
        base_profile = profiles.resolve_profile(_profiles(coord.entry), data["profile"])
        if base_profile is None:
            return {}, {
                "key": "notify_profile_not_found",
                "placeholders": {"profile": str(data["profile"])},
            }

    # Filter = the saved profile, or the all-due default for a bare/target-only call,
    # then any per-call ``status`` the caller asked for. The override lands *after*
    # normalization on purpose: ``normalize_filter`` coerces anything outside STATUSES
    # to "overdue", so applying it first would silently turn ``none`` into ``overdue``.
    # Rebuilding the dict rather than mutating matters too — ``resolve_profile`` hands
    # back the live options entry, and a per-call override must not leak into it.
    profile = profiles.normalize_profile({"name": "ad-hoc", **(base_profile or {})})
    profile = {
        **profile,
        "filter": profiles.with_status(profile["filter"], data.get("status")),
    }

    # Delivery = the saved notification's, with an optional per-call target override.
    notif_raw: dict[str, Any] = {"name": "ad-hoc", **(base_notif or {})}
    if "target" in data:
        # An explicit override that names an unsupported service fails loudly rather
        # than being silently filtered: the caller asked for a specific destination,
        # and "sent: 0" would read as "nothing was due".
        _, rejected = notifications.split_targets(data["target"])
        if rejected:
            return {}, {
                "key": "notify_invalid_target",
                "placeholders": {
                    "target": ", ".join(rejected),
                    "prefix": notifications.TARGET_PREFIX,
                    "persistent": notifications.TARGET_PERSISTENT,
                },
            }
        notif_raw["targets"] = data["target"]
    notif_raw["profile_id"] = profile["id"]
    notification = notifications.normalize_notification(notif_raw)
    if not notification["targets"]:
        # A profile is only a filter — it carries no delivery target. Sending a bare
        # profile (or a saved notification with no 'Send to') would match tasks but push
        # nowhere, which reads as "the service did nothing". Fail loudly instead.
        return {}, {"key": "notify_no_targets", "placeholders": {}}

    matched, sent = await _send(
        hass,
        coord,
        notification,
        profile,
        reason="service",
        when_empty=data.get("when_empty", notifications.WHEN_EMPTY_SKIP),
    )
    return {"matched": matched, "sent": sent}, None


async def _async_live_coordinator(hass: HomeAssistant) -> Any:
    """The loaded coordinator, after a wait during a reload (lazy: no import cycle)."""
    from .coordinator import async_wait_for_coordinator

    return await async_wait_for_coordinator(hass)


def async_setup_notifications(hass: HomeAssistant) -> CALLBACK_TYPE:
    """Subscribe to mobile-app action events; returns the unsubscribe callback.

    ``async_setup`` calls this once for the Home Assistant run (X02-5). A listener
    of the config entry stopped at each unload, and a tap during the reload that
    followed reached no handler. Each tap now finds the loaded coordinator, and
    waits for it while the entry sets up.
    """

    async def _handle(
        coord: HomeKeeperCoordinator,
        verb: str,
        task_id: str,
        notification_id: str,
        due_token: str | None,
    ) -> None:
        entry = coord.entry
        notification = notifications.resolve_notification(
            _notifications(entry), notification_id
        )
        now = dt_util.now()
        if verb not in (
            notifications.ACTION_COMPLETE,
            notifications.ACTION_SNOOZE,
            notifications.ACTION_SKIP,
        ):
            return  # ACTION_OPEN — the URI deep-link is handled on the device
        try:
            # Gate every mutating tap on the button still reflecting the task's
            # current schedule, so a stale card — tapped after the task was
            # completed/snoozed/skipped elsewhere, or a second card for the same
            # task whose twin was already actioned — is a silent no-op. A stale
            # "Mark done" would advance next_due a full interval again, a stale
            # Snooze would bring a done task back early, and a stale Skip would drop
            # one more occurrence (B16-2). A missing task (deleted) is likewise a
            # no-op.
            #
            # NOTE: this check and the mutation it guards are atomic, and must stay
            # that way. Everything from get_task() through the store method's
            # ``self._tasks[task_id] = ...`` runs without a yield point (awaiting a
            # coroutine runs its body inline until *it* suspends, and the first
            # suspension of complete_task, snooze_task and skip_task is the later
            # ``await self._save()``), so two simultaneous taps — two phones on one
            # card, or two cards for one task — cannot both read the old next_due.
            # Introducing an await above that assignment would open that race.
            task = coord.store.get_task(task_id)
            if task is None:
                _LOGGER.debug(
                    "Home Keeper notification action %s on %s ignored: "
                    "task no longer exists",
                    verb,
                    task_id,
                )
                return
            # A legacy button carries no token. Mark done then needs the task to be
            # overdue. Snooze and Skip are also offered on a due-soon walk card, so a
            # legacy tap of those is accepted.
            tokenless_ok = (
                recurrence.is_overdue(task, now=now)
                if verb == notifications.ACTION_COMPLETE
                else True
            )
            if not notifications.is_current_action(
                task, due_token, tokenless_ok=tokenless_ok
            ):
                _LOGGER.debug(
                    "Home Keeper notification action %s on %s ignored: "
                    "stale tap (button carried next_due %s, task is now at %s)",
                    verb,
                    task_id,
                    due_token,
                    task.get("next_due"),
                )
                return
            if verb == notifications.ACTION_COMPLETE:
                await coord.store.complete_task(
                    task_id, origin=ORIGIN_NOTIFICATION_ACTION
                )
            elif verb == notifications.ACTION_SNOOZE:
                # A card already on someone's phone keeps whatever buttons it was
                # built with, so a verb switched off since then can still be tapped.
                # Ignore it the same way a stale completion tap is ignored, rather
                # than honouring a button the setting has withdrawn. A
                # completion-blocked task is the exception, as in ``actions_for``:
                # its card offers Snooze even with the switch off, because nothing
                # else can move the walk past it, so that tap must work (B16-3).
                if not _verb_allowed(
                    coord, notifications.ACTION_SNOOZE
                ) and not notifications.is_completion_blocked(task):
                    return
                # The task's own snooze length wins over the notification's.
                hours = notifications.snooze_hours_for(
                    coord.store.get_task(task_id), notification
                )
                await coord.store.snooze_task(
                    task_id,
                    now + timedelta(hours=hours),
                    origin=ORIGIN_NOTIFICATION_ACTION,
                )
            else:  # ACTION_SKIP
                if not _verb_allowed(coord, notifications.ACTION_SKIP):
                    return
                await coord.store.skip_task(task_id, origin=ORIGIN_NOTIFICATION_ACTION)
        except (KeyError, TaskValidationError) as err:
            _LOGGER.debug(
                "Home Keeper notification action %s on %s ignored: %s",
                verb,
                task_id,
                err,
            )
            return
        if verb == notifications.ACTION_COMPLETE:
            # Completing an auto-buy reminder restocks the part, so the reconciler
            # has to settle (and the shopping-list mirror with it) — a bare refresh
            # left the reminder standing until something else happened to settle
            # it. Falls back to a refresh when nothing changed, and its reload is
            # deferred, so the walk-advance below still runs.
            await coord.async_settle_buy_tasks()
        else:
            await coord.async_request_refresh()
        # Advance the walk: re-send the notification's next due task, which replaces
        # the card in place; an empty queue closes with an "all caught up" note. (Only
        # for a saved walk notification.) The task just acted on is kept out: under a
        # ``due_soon`` or ``all`` status it can still be due, and to send it again
        # with new buttons lets a second tap act on it again (B16-5).
        if notification is not None and (
            notification["style"] == notifications.STYLE_WALK
        ):
            matched, _ = await async_send_for_notification(
                hass,
                coord,
                notification,
                reason="walk-advance",
                exclude_task_id=task_id,
            )
            if matched == 0:
                all_clear = await hass.async_add_executor_job(
                    functools.partial(
                        notifications.build_all_clear,
                        notification,
                        lang=hass.config.language,
                    )
                )
                await _send_payload(hass, notification["targets"], all_clear)

    @callback
    def _on_action(event: Event) -> None:
        decoded = notifications.decode_action(event.data.get("action"))
        if decoded is None:
            return
        hass.async_create_task(_route(*decoded))

    async def _route(
        verb: str, task_id: str, notification_id: str, due_token: str | None
    ) -> None:
        coord = await _async_live_coordinator(hass)
        if coord is None:
            _LOGGER.debug(
                "Home Keeper notification action %s on %s ignored: not loaded",
                verb,
                task_id,
            )
            return
        await _handle(coord, verb, task_id, notification_id, due_token)

    return hass.bus.async_listen(EVENT_MOBILE_APP_ACTION, _on_action)
