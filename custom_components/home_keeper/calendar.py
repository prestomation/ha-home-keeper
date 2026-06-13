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
        """Return the next upcoming event across all tasks."""
        now = dt_util.now()
        upcoming: list[CalendarEvent] = []
        # Look ahead a generous window for the "next" event.
        events = self._collect_events(now, now + timedelta(days=370))
        upcoming = [e for e in events if e.end > now]
        if not upcoming:
            return None
        return min(upcoming, key=lambda e: e.start)

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
