"""Logbook rows for the task events.

Home Assistant loads this module when the logbook is set up. Each task event in
``events.LOGBOOK_EVENTS`` gets 1 row. The logbook matches the ``entity_id`` in the
event data, the Home Keeper to-do list, and the ``device_id``. So the row shows on
the to-do list and on the page of the task's device.

The row does not name the entity. If it did, the logbook would show the name of the
to-do list in place of the name of the task.
"""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_ICON,
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
)
from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN
from .events import LOGBOOK_EVENTS, LOGBOOK_ICONS, logbook_message


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
            LOGBOOK_ENTRY_MESSAGE: logbook_message(event_type, event.data),
            LOGBOOK_ENTRY_ICON: LOGBOOK_ICONS[event_type],
        }

    for event_type in LOGBOOK_EVENTS:
        async_describe_event(DOMAIN, event_type, async_describe_task_event)
