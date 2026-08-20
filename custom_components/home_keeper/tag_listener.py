"""Home-Assistant-aware driver for NFC/RFID tag completion.

Home Assistant core's ``tag`` integration fires ``tag_scanned`` whenever a tag is
read — by the companion app, an ESPHome reader, or any integration that scans one.
This module listens for that event, routes the scanned id through the pure
:mod:`tags` module to the tasks bound to it, and completes each through the store's
completion chokepoint marked :data:`~.const.ORIGIN_TAG_SCAN` (the marker that also
authorizes a ``require_tag_scan`` task). Home Keeper never registers or reads tags
itself: the user creates the tag in Home Assistant and picks it on the task.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback

from . import models, tags
from .const import EVENT_HA_TAG_SCANNED, ORIGIN_TAG_SCAN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .coordinator import HomeKeeperCoordinator

_LOGGER = logging.getLogger(__name__)


def async_setup_tag_listener(
    hass: HomeAssistant, entry: ConfigEntry, coord: HomeKeeperCoordinator
) -> CALLBACK_TYPE:
    """Subscribe to ``tag_scanned``; returns the unsubscribe callback."""

    async def _complete(matched: list[dict[str, Any]]) -> None:
        completed = False
        for task in matched:
            try:
                await coord.store.complete_task(task["id"], origin=ORIGIN_TAG_SCAN)
            except (KeyError, models.TaskValidationError) as err:
                # A scan is a physical gesture with no error surface to raise into, and
                # one unhappy task must not swallow the rest of the scan. Tasks that
                # legitimately refuse a scan-driven completion land here — a
                # problem-sensor-synced task someone stuck a tag on, or one deleted
                # between the routing pass and this one.
                _LOGGER.debug(
                    "Home Keeper tag completion of %s ignored: %s", task["id"], err
                )
                continue
            completed = True
        if completed:
            # Completing an auto-buy task bumps stock (restocked) → its reminder is
            # removed; settle so those device entities are (un)registered (else a
            # plain refresh).
            await coord.async_settle_buy_tasks()

    @callback
    def _on_tag_scanned(event: Event) -> None:
        tag_id = event.data.get("tag_id")
        if not tag_id or not isinstance(tag_id, str):
            return
        matched = tags.tasks_for_tag(coord.store.list_tasks(), tag_id)
        if not matched:
            # Tags are shared with the rest of Home Assistant, so most scans are for
            # somebody else's automation — an unbound tag is a silent no-op.
            return
        hass.async_create_task(_complete(matched))

    return hass.bus.async_listen(EVENT_HA_TAG_SCANNED, _on_tag_scanned)
