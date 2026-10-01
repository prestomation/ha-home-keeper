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
    from .coordinator import HomeKeeperCoordinator

_LOGGER = logging.getLogger(__name__)


def async_setup_tag_listener(hass: HomeAssistant) -> CALLBACK_TYPE:
    """Subscribe to ``tag_scanned``; returns the unsubscribe callback.

    ``async_setup`` calls this once for the Home Assistant run (X02-5). A listener
    of the config entry stopped at each unload, and a scan during the reload that
    followed was lost. That matters most for a ``require_tag_scan`` task, which
    has no other way to be completed. Each scan now finds the loaded coordinator,
    and waits for it while the entry sets up.
    """
    from .coordinator import async_wait_for_coordinator, find_coordinator

    async def _complete(
        coord: HomeKeeperCoordinator, matched: list[dict[str, Any]]
    ) -> None:
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

    def _match(coord: HomeKeeperCoordinator, tag_id: str) -> list[dict[str, Any]]:
        # Tags are shared with the rest of Home Assistant, so most scans are for
        # somebody else's automation — an unbound tag is a silent no-op.
        return tags.tasks_for_tag(coord.store.list_tasks(), tag_id)

    async def _after_setup(tag_id: str) -> None:
        coord = await async_wait_for_coordinator(hass)
        if coord is not None and (matched := _match(coord, tag_id)):
            await _complete(coord, matched)

    @callback
    def _on_tag_scanned(event: Event) -> None:
        tag_id = event.data.get("tag_id")
        if not tag_id or not isinstance(tag_id, str):
            return
        coord = find_coordinator(hass)
        if coord is None:
            # The entry reloads: wait for it, so the scan is not lost.
            hass.async_create_task(_after_setup(tag_id))
            return
        if matched := _match(coord, tag_id):
            hass.async_create_task(_complete(coord, matched))

    return hass.bus.async_listen(EVENT_HA_TAG_SCANNED, _on_tag_scanned)
