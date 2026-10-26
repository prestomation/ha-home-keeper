"""Logbook rows for the task events.

Home Assistant loads this module when the logbook is set up. Each task event in
``events.LOGBOOK_EVENTS`` gets 1 row. The logbook matches the ``entity_id`` in the
event data, the Home Keeper to-do list, and the ``device_id``. So the row shows on
the to-do list and on the page of the task's device.

A completion row names the day of the completion when it is not the day the event
fired. The logbook gives the describe callback a row that holds the fire time.

The row does not name the entity. If it did, the logbook would show the name of the
to-do list in place of the name of the task.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_ICON,
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
)
from homeassistant.components.logbook.models import TIME_FIRED_TS_POS
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .events import LOGBOOK_EVENTS, LOGBOOK_ICONS, logbook_message


def _fired_ts(event: Any) -> float | None:
    """The time the event fired, from its logbook row, or None if there is no row."""
    try:
        return float(event.row[TIME_FIRED_TS_POS])
    except (AttributeError, IndexError, TypeError, ValueError):
        return None


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    """Describe the task events for the logbook."""

    @callback
    def async_describe_task_event(event: Event) -> dict[str, str]:
        event_type = str(event.event_type)
        return {
            LOGBOOK_ENTRY_NAME: event.data.get("name") or "Task",
            LOGBOOK_ENTRY_MESSAGE: logbook_message(
                event_type,
                event.data,
                fired_ts=_fired_ts(event),
                tz=dt_util.get_default_time_zone(),
            ),
            LOGBOOK_ENTRY_ICON: LOGBOOK_ICONS[event_type],
        }

    for event_type in LOGBOOK_EVENTS:
        async_describe_event(DOMAIN, event_type, async_describe_task_event)
