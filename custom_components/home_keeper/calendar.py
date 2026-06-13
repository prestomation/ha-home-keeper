"""Calendar entity for Home Keeper.

Surfaces upcoming task occurrences as calendar events so users can see "what's due
when" on HA's built-in Calendar card. Floating tasks contribute a single event at
their current ``next_due``; fixed tasks are expanded across the requested range by
the recurrence engine.
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
from .const import DOMAIN, REC_FIXED
from .coordinator import HomeKeeperCoordinator

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


class HomeKeeperCalendarEntity(
    CoordinatorEntity[HomeKeeperCoordinator], CalendarEntity
):
    """Calendar of upcoming maintenance/chore occurrences."""

    # Explicit name anchors entity_id -> calendar.home_keeper_upcoming_tasks.
    _attr_has_entity_name = False
    _attr_name = "Home Keeper Upcoming tasks"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: HomeKeeperCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_calendar"

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
        if task.get("recurrence_type") == REC_FIXED:
            anchor = dt_util.parse_datetime(task["anchor"])
            if anchor is None:
                return None
            return recurrence.next_fixed_occurrence(
                anchor, task["freq"], int(task["interval"]), after=now
            )
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
            if task.get("recurrence_type") == REC_FIXED:
                anchor = dt_util.parse_datetime(task["anchor"])
                if anchor is None:
                    continue
                for occ in recurrence.expand_fixed_occurrences(
                    anchor, task["freq"], int(task["interval"]), start_date, end_date
                ):
                    events.append(_event_for(task, occ))
            else:
                due_iso = task.get("next_due")
                due = dt_util.parse_datetime(due_iso) if due_iso else None
                if due and start_date <= due < end_date:
                    events.append(_event_for(task, due))
        return sorted(events, key=lambda e: e.start)
