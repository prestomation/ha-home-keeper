"""Calendar entity for Home Keeper.

Surfaces upcoming task occurrences as calendar events so users can see "what's due
when" on HA's built-in Calendar card. Floating tasks contribute a single event at
their current ``next_due``; fixed tasks are expanded across the requested range by
the recurrence engine, and their ``next_due`` replaces the grid occurrences before it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import recurrence
from .const import DOMAIN, REC_FIXED, REC_SENSOR, REC_TRIGGERED
from .coordinator import HomeKeeperCoordinator
from .devices import service_device_info

# Default duration shown for each task occurrence on the calendar.
EVENT_DURATION = timedelta(hours=1)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Home Keeper calendar."""
    coordinator: HomeKeeperCoordinator = entry.runtime_data
    async_add_entities([HomeKeeperCalendarEntity(coordinator)])


def _event_for(task: dict, start: datetime) -> CalendarEvent:
    return CalendarEvent(
        summary=task["name"],
        start=start,
        end=start + EVENT_DURATION,
        uid=f"{task['id']}_{start.isoformat()}",
        description=task.get("notes") or None,
    )


def _due(task: dict) -> datetime | None:
    """The task's ``next_due`` as a datetime, or None."""
    due_iso = task.get("next_due")
    return dt_util.parse_datetime(due_iso) if due_iso else None


def _follow_next_due(
    starts: list[datetime], due: datetime, start_date: datetime, end_date: datetime
) -> list[datetime]:
    """Grid occurrences of a fixed task, corrected by its ``next_due`` (B11-2).

    The grid occurrences from now up to ``next_due`` are done, skipped or deferred,
    so they are removed. ``next_due`` itself is added when it is off the grid (a
    snooze or a due-today) and in the window. A ``next_due`` in the past is an
    overdue occurrence, so nothing is removed for it.
    """
    cutoff = dt_util.now() - EVENT_DURATION
    if due > cutoff:
        starts = [occ for occ in starts if not cutoff <= occ < due]
    if due not in starts and due < end_date and due + EVENT_DURATION > start_date:
        starts = sorted([*starts, due])
    return starts


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
        best: tuple[datetime, dict] | None = None
        for task in self.coordinator.data.values():
            if not task.get("enabled", True):
                continue
            start = self._next_start(task, now)
            if start is None:
                continue
            if best is None or start < best[0]:
                best = (start, task)
        if best is None:
            return None
        return _event_for(best[1], best[0])

    def _next_start(self, task: dict, now: datetime) -> datetime | None:
        """Soonest upcoming occurrence start for a single task, or None."""
        # Triggered (condition-driven) and sensor-based tasks have no schedule to
        # project — they are "due now" while armed and invisible otherwise — so they
        # never belong on a forward-looking calendar.
        if task.get("recurrence_type") in (REC_TRIGGERED, REC_SENSOR):
            return None
        if task.get("recurrence_type") == REC_FIXED:
            due = _due(task)
            if due is not None and due + EVENT_DURATION > now:
                # ``next_due`` is what every other surface shows. A completion before
                # the time of day, a skip, a snooze and a due-today all move it off
                # the next grid occurrence, so the calendar follows it (B11-2).
                return due
            anchor = dt_util.parse_datetime(task["anchor"])
            if anchor is None:
                return None
            season = task.get("active_season")
            if season:
                # The first grid occurrence inside the season. ``_clamp_season`` uses
                # the same walk, so the calendar and ``next_due`` agree (B07-9). A
                # grid that can never land in one (every 12 months from January,
                # with a March season) exhausts the bound and leaves the task off
                # the calendar rather than inventing an out-of-season date for it —
                # it is still in the panel and on the to-do list, which is where an
                # impossible pairing gets noticed and corrected.
                return recurrence.next_in_season_occurrence(
                    anchor,
                    task["freq"],
                    int(task["interval"]),
                    season,
                    after=now - EVENT_DURATION,
                )
            occ = recurrence.next_fixed_occurrence(
                anchor,
                task["freq"],
                int(task["interval"]),
                after=now - EVENT_DURATION,
            )
            return occ
        due_iso = task.get("next_due")
        due = dt_util.parse_datetime(due_iso) if due_iso else None
        # Only treat a floating task as "upcoming" while its event hasn't ended.
        if due and due + EVENT_DURATION > now:
            return due
        return None

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
                continue  # no schedule to expand (see _next_start)
            if task.get("recurrence_type") == REC_FIXED:
                anchor = dt_util.parse_datetime(task["anchor"])
                if anchor is None:
                    continue
                season = task.get("active_season")
                # The expansion starts 1 event length early, to get an occurrence
                # that is in progress at the window start. An occurrence that ends
                # exactly at the window start is not in the window (B11-7).
                starts = [
                    occ
                    for occ in recurrence.expand_fixed_occurrences(
                        anchor,
                        task["freq"],
                        int(task["interval"]),
                        start_date - EVENT_DURATION,
                        end_date,
                    )
                    if occ + EVENT_DURATION > start_date
                    and (not season or recurrence.in_season(occ, season))
                ]
                due = _due(task)
                if due is not None:
                    starts = _follow_next_due(starts, due, start_date, end_date)
                events.extend(_event_for(task, occ) for occ in starts)
            else:
                due_iso = task.get("next_due")
                due = dt_util.parse_datetime(due_iso) if due_iso else None
                # Include a floating occurrence whose event overlaps the window
                # start, not only one that starts within it.
                if due and due < end_date and due + EVENT_DURATION > start_date:
                    events.append(_event_for(task, due))
        return sorted(events, key=lambda e: e.start)
