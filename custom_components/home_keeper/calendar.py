"""Calendar entity for Home Keeper.

Surfaces upcoming task occurrences as calendar events so users can see "what's due
when" on HA's built-in Calendar card. Floating tasks contribute a single event at
their current ``next_due``; fixed tasks are expanded across the requested range by
the recurrence engine. A fixed task's ``next_due`` replaces the schedule dates before
it.

A fixed task's events carry the task's RRULE and a ``recurrence_id``, the same shape
Home Assistant's own local calendar uses. That is what makes Home Assistant's event
dialog offer "Only this event": saving a new time there moves that one date
(``home_keeper.move_occurrence``). A change to the whole series is an edit of the
task, so it is refused with a message that points at the panel. Editing the event of
any other task moves its due date, the same as a snooze.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import recurrence
from .const import DOMAIN, ORIGIN_CALENDAR, REC_FIXED, REC_SENSOR, REC_TRIGGERED
from .coordinator import HomeKeeperCoordinator
from .models import TaskValidationError
from .service_device import service_device_info

# Default duration shown for each task occurrence on the calendar.
EVENT_DURATION = timedelta(hours=1)
# ``recurrence_id`` format: a floating local date-time, as Home Assistant's local
# calendar writes it (RFC 5545 "form #1").
RECURRENCE_ID_FORMAT = "%Y%m%dT%H%M%S"
# The separator in the uid of a one-date event (floating, one-off, or a fixed task's
# snoozed date): ``<task id>@<ISO start>``. A fixed task's schedule events use the
# bare task id, so the two can never be confused.
_UID_SEPARATOR = "@"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Home Keeper calendar."""
    coordinator: HomeKeeperCoordinator = entry.runtime_data
    async_add_entities([HomeKeeperCalendarEntity(coordinator)])


def recurrence_id_for(occurrence: datetime) -> str:
    """The ``recurrence_id`` of a schedule date: its local wall time."""
    return dt_util.as_local(occurrence).strftime(RECURRENCE_ID_FORMAT)


def parse_recurrence_id(value: str) -> datetime:
    """The schedule date a ``recurrence_id`` names, in Home Assistant's zone."""
    naive = datetime.strptime(value, RECURRENCE_ID_FORMAT)
    return naive.replace(tzinfo=dt_util.get_default_time_zone())


def _schedule_event(task: dict, start: datetime, original: datetime) -> CalendarEvent:
    """An event of a fixed task's schedule. *original* is the date on the rule."""
    anchor = dt_util.parse_datetime(task["anchor"])
    assert anchor is not None
    local_anchor = dt_util.as_local(anchor).replace(tzinfo=None)
    return CalendarEvent(
        summary=task["name"],
        start=start,
        end=start + EVENT_DURATION,
        uid=task["id"],
        description=task.get("notes") or None,
        rrule=recurrence.effective_rule(recurrence.task_rule(task), local_anchor),
        recurrence_id=recurrence_id_for(original),
    )


def _single_event(task: dict, start: datetime) -> CalendarEvent:
    """A one-date event: a floating or one-off task, or a snoozed fixed task."""
    return CalendarEvent(
        summary=task["name"],
        start=start,
        end=start + EVENT_DURATION,
        uid=f"{task['id']}{_UID_SEPARATOR}{start.isoformat()}",
        description=task.get("notes") or None,
    )


def _due_ahead(
    task: dict, now: datetime | None = None
) -> tuple[datetime, datetime] | None:
    """``(next_due, now)`` while a fixed task's next event has not ended, else ``None``.

    ``next_due`` is what every other surface shows. A completion before the time of
    day, a skip, a snooze and a due-today all move it off the next schedule date, so
    the calendar follows it (B11-2). A ``next_due`` in the past is an overdue date,
    and the schedule shows from now on. The clock is read only when there is a
    ``next_due`` to judge, so a plain schedule never depends on it.
    """
    due = dt_util.parse_datetime(task.get("next_due") or "")
    if due is None:
        return None
    now = now or dt_util.now()
    if due + EVENT_DURATION <= now:
        return None
    return due, now


def _off_schedule(task: dict, due: datetime) -> bool:
    """Whether *due* is a snoozed or due-today date, not a date of the schedule."""
    # ``next_due`` comes off storage with a bare offset; judge it in Home Assistant's
    # zone, or a summer anchor makes every winter date look like a snooze.
    return not recurrence.is_task_occurrence(
        task, due, tz=dt_util.get_default_time_zone()
    )


def _fixed_events(
    task: dict, start_date: datetime, end_date: datetime
) -> list[CalendarEvent]:
    """The events of a fixed task in ``[start_date, end_date)``.

    Moves are applied by the engine. The schedule dates from now up to ``next_due``
    are done, skipped or deferred, so they are left out. A ``next_due`` that is off
    the schedule (a snooze or a due-today) shows as its own event.
    """
    season = task.get("active_season")
    moved_to = {dst.timestamp(): src for src, dst in recurrence.task_moves(task)}
    ahead = _due_ahead(task)
    events: list[CalendarEvent] = []
    # The expansion starts 1 event length early, to get a date that is in progress at
    # the window start. A date that ends exactly at the window start is not in the
    # window (B11-7).
    for occ in recurrence.expand_task_occurrences(
        task, start_date - EVENT_DURATION, end_date
    ):
        if occ + EVENT_DURATION <= start_date:
            continue
        if season and not recurrence.in_season(occ, season):
            continue
        if ahead is not None and ahead[1] - EVENT_DURATION <= occ < ahead[0]:
            continue
        original = moved_to.get(occ.timestamp(), occ)
        events.append(_schedule_event(task, occ, original))
    if ahead is not None:
        due = ahead[0]
        if (
            due < end_date
            and due + EVENT_DURATION > start_date
            and _off_schedule(task, due)
        ):
            events.append(_single_event(task, due))
    return events


class HomeKeeperCalendarEntity(
    CoordinatorEntity[HomeKeeperCoordinator], CalendarEntity
):
    """Calendar of upcoming maintenance/chore occurrences."""

    # The entity is on the "Home Keeper" service device, so the translated name
    # composes to "Home Keeper Upcoming tasks" and the entity_id is
    # calendar.home_keeper_upcoming_tasks (X13-4).
    _attr_has_entity_name = True
    _attr_translation_key = "upcoming_tasks"
    _attr_icon = "mdi:calendar-clock"
    _attr_supported_features = CalendarEntityFeature.UPDATE_EVENT

    def __init__(self, coordinator: HomeKeeperCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_calendar"
        self._attr_device_info = service_device_info()

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event across all tasks.

        Computed directly (one occurrence per task) rather than by expanding a
        large window, so a daily fixed task doesn't generate hundreds of events
        just to find the soonest one.
        """
        now = dt_util.now()
        best: CalendarEvent | None = None
        for task in self.coordinator.data.values():
            if not task.get("enabled", True):
                continue
            candidate = self._next_event(task, now)
            if candidate is None:
                continue
            start = candidate.start_datetime_local
            if best is None or start < best.start_datetime_local:
                best = candidate
        return best

    def _next_event(self, task: dict, now: datetime) -> CalendarEvent | None:
        """Soonest upcoming event for a single task, or None."""
        # Triggered (condition-driven) and sensor-based tasks have no schedule to
        # project — they are "due now" while armed and invisible otherwise — so they
        # never belong on a forward-looking calendar.
        if task.get("recurrence_type") in (REC_TRIGGERED, REC_SENSOR):
            return None
        if task.get("recurrence_type") == REC_FIXED:
            if dt_util.parse_datetime(task["anchor"]) is None:
                return None
            if (ahead := _due_ahead(task, now)) is not None:
                shown = ahead[0]
                if _off_schedule(task, shown):
                    return _single_event(task, shown)
                moved_to = {
                    dst.timestamp(): src for src, dst in recurrence.task_moves(task)
                }
                original = moved_to.get(shown.timestamp(), shown)
                return _schedule_event(task, shown, original)
            return self._next_fixed_event(task, now)
        due_iso = task.get("next_due")
        due = dt_util.parse_datetime(due_iso) if due_iso else None
        # Only treat a floating task as "upcoming" while its event hasn't ended.
        if due and due + EVENT_DURATION > now:
            return _single_event(task, due)
        return None

    @staticmethod
    def _next_fixed_event(task: dict, now: datetime) -> CalendarEvent | None:
        season = task.get("active_season")
        moved_to = {dst.timestamp(): src for src, dst in recurrence.task_moves(task)}
        after = now - EVENT_DURATION
        try:
            if season:
                # The first occurrence inside the season. ``_clamp_season`` uses the
                # same walk, so the calendar and ``next_due`` agree (B07-9). A
                # schedule that can never land in one (every 12 months from January,
                # with a March season) exhausts the bound and leaves the task off the
                # calendar rather than inventing an out-of-season date for it — it is
                # still in the panel and on the to-do list, which is where an
                # impossible pairing gets noticed and corrected.
                found = recurrence.next_in_season_occurrence(task, season, after=after)
                if found is None:
                    return None
                occ = found
            else:
                occ = recurrence.next_task_occurrence(task, after=after)
        except ValueError:
            return None
        return _schedule_event(task, occ, moved_to.get(occ.timestamp(), occ))

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return self._collect_events(start_date, end_date)

    def _collect_events(
        self, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        for task in self.coordinator.data.values():
            if not task.get("enabled", True):
                continue
            if task.get("recurrence_type") in (REC_TRIGGERED, REC_SENSOR):
                continue  # no schedule to expand (see _next_event)
            if task.get("recurrence_type") == REC_FIXED:
                if dt_util.parse_datetime(task["anchor"]) is None:
                    continue
                try:
                    events += _fixed_events(task, start_date, end_date)
                except ValueError:
                    continue
            else:
                due_iso = task.get("next_due")
                due = dt_util.parse_datetime(due_iso) if due_iso else None
                # Include a floating occurrence whose event overlaps the window
                # start, not only one that starts within it.
                if due and due < end_date and due + EVENT_DURATION > start_date:
                    events.append(_single_event(task, due))
        return sorted(events, key=lambda e: e.start_datetime_local)

    async def async_update_event(
        self,
        uid: str,
        event: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Move one date from Home Assistant's event dialog.

        * A fixed task's event with a ``recurrence_id`` and no range is "Only this
          event": the date moves, the rest of the schedule does not.
        * Any other task's event moves its due date, the same as a snooze.
        * A change to a whole series, or to anything but the start time, is an edit of
          the task itself, which is the panel's job.
        """
        store = self.coordinator.store
        task_id, _, _ = uid.partition(_UID_SEPARATOR)
        task = self.coordinator.data.get(task_id)
        if task is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="task_not_found",
                translation_placeholders={"task_id": task_id},
            )
        start = event.get("dtstart")
        if not isinstance(start, datetime):
            raise self._series_error()
        if start.tzinfo is None:
            start = start.replace(tzinfo=dt_util.get_default_time_zone())
        is_fixed = task.get("recurrence_type") == REC_FIXED
        # Only the start time may change here. A new name is an edit of the task. For
        # a repeating event, Home Assistant's dialog sends the series rule back with
        # an "Only this event" edit, and may rewrite it on the way (drop
        # ``INTERVAL=1``, reorder a list), so a fixed task ignores it. An event that
        # does not repeat must not gain a rule.
        summary = event.get("summary")
        changed_other = summary not in (None, "", task["name"]) or (
            not is_fixed and event.get("rrule") not in (None, "")
        )
        try:
            if is_fixed and _UID_SEPARATOR not in uid:
                if recurrence_id is None or recurrence_range or changed_other:
                    raise self._series_error()
                await store.move_occurrence(
                    task_id,
                    parse_recurrence_id(recurrence_id),
                    start,
                    origin=ORIGIN_CALENDAR,
                )
            else:
                if recurrence_range or changed_other:
                    raise self._series_error()
                if start <= dt_util.now():
                    raise TaskValidationError(
                        "a date can only move to a time in the future"
                    )
                await store.snooze_task(task_id, start, origin=ORIGIN_CALENDAR)
        except TaskValidationError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="invalid_task",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()

    @staticmethod
    def _series_error() -> HomeAssistantError:
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="calendar_edit_in_panel",
        )
