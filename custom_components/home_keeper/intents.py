"""Conversation / voice intents for Home Keeper (Assist).

Registers intent handlers so tasks can be **completed** and **queried** by voice or
text through Home Assistant's Assist. The handlers delegate to the same store
methods every other surface uses — ``store.complete_task`` is the single completion
chokepoint — so a voice completion stays fully observable (it fires
``home_keeper_task_completed`` with ``origin=ORIGIN_INTENT``) and obeys the same
guards (a problem-sensor-synced task is rejected with a spoken explanation).

Resolving a spoken task name to a stored task is pure logic and lives in
``task_match.py`` (unit-tested in isolation); this module only does the HA-specific
work: registry lookups (area/device names -> ids), building the spoken response, and
mapping store errors to speech. The natural-language sentences that route here ship
in ``custom_sentences/en/home_keeper.yaml`` (see README "Voice control").
"""

from __future__ import annotations

from typing import ClassVar

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import intent
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    INTENT_COMPLETE_TASK,
    INTENT_LIST_DUE_TASKS,
    ORIGIN_INTENT,
)
from .coordinator import HomeKeeperCoordinator
from .models import TaskValidationError
from .task_match import match_task, select_due_tasks


def _coordinator(hass: HomeAssistant) -> HomeKeeperCoordinator | None:
    """Return the active Home Keeper coordinator, or None if not set up.

    Resolved per-call (not captured at registration) so the global, idempotently
    registered handlers always see the current coordinator across entry reloads.
    """
    for entry in hass.config_entries.async_entries(DOMAIN):
        coord = getattr(entry, "runtime_data", None)
        if isinstance(coord, HomeKeeperCoordinator):
            return coord
    return None


def _resolve_area_id(hass: HomeAssistant, name: str) -> str | None:
    """Map a spoken area name (or alias) to its area id, case-insensitively."""
    target = name.strip().casefold()
    for area in ar.async_get(hass).async_list_areas():
        if area.name.casefold() == target:
            return area.id
        for alias in area.aliases or ():
            if alias.casefold() == target:
                return area.id
    return None


def _resolve_device_id(hass: HomeAssistant, name: str) -> str | None:
    """Map a spoken device name to its device id, case-insensitively."""
    target = name.strip().casefold()
    for device in dr.async_get(hass).devices.values():
        label = device.name_by_user or device.name
        if label and label.casefold() == target:
            return device.id
    return None


def _join_names(names: list[str]) -> str:
    """Join task names into a natural spoken list ("A, B, and C")."""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


class CompleteTaskIntentHandler(intent.IntentHandler):
    """Complete a Home Keeper task named in the utterance."""

    intent_type = INTENT_COMPLETE_TASK
    description = "Mark a Home Keeper maintenance task or chore as done."
    slot_schema: ClassVar[dict] = {
        vol.Required("name"): cv.string,
        vol.Optional("area"): cv.string,
        vol.Optional("device"): cv.string,
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        name = slots["name"]["value"]
        response = intent_obj.create_response()

        coord = _coordinator(hass)
        if coord is None:
            response.async_set_speech("Home Keeper isn't set up yet.")
            return response

        area_id = None
        if "area" in slots:
            area_name = slots["area"]["value"]
            area_id = _resolve_area_id(hass, area_name)
            if area_id is None:
                response.async_set_speech(f"I don't know an area called {area_name}.")
                return response

        device_id = None
        if "device" in slots:
            device_name = slots["device"]["value"]
            device_id = _resolve_device_id(hass, device_name)
            if device_id is None:
                response.async_set_speech(
                    f"I don't know a device called {device_name}."
                )
                return response

        tasks = [t for t in coord.store.list_tasks() if t.get("enabled", True)]
        result = match_task(tasks, name, area_id=area_id, device_id=device_id)

        if result.not_found:
            response.async_set_speech(f"I couldn't find a task matching {name}.")
            return response
        if result.ambiguous:
            names = _join_names([t["name"] for t in result.candidates])
            response.async_set_speech(
                f"I found more than one task matching {name}: {names}. "
                "Which one should I complete?"
            )
            return response

        task = result.task
        try:
            await coord.store.complete_task(task["id"], origin=ORIGIN_INTENT)
        except TaskValidationError as err:
            # e.g. a problem-sensor-synced task can't be cleared here — speak why.
            response.async_set_speech(str(err))
            return response
        await coord.async_request_refresh()
        response.async_set_speech(f"Done. I've completed {task['name']}.")
        return response


class ListDueTasksIntentHandler(intent.IntentHandler):
    """Report which Home Keeper tasks are currently due or overdue."""

    intent_type = INTENT_LIST_DUE_TASKS
    description = "List Home Keeper tasks that are currently due or overdue."
    # No slots: inherit the base handler's "accept no slots" default.

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        response = intent_obj.create_response()

        coord = _coordinator(hass)
        if coord is None:
            response.async_set_speech("Home Keeper isn't set up yet.")
            return response

        due = select_due_tasks(coord.store.list_tasks(), dt_util.now())
        if not due:
            response.async_set_speech("You have no tasks due right now.")
            return response

        names = _join_names([t["name"] for t in due])
        count = len(due)
        noun = "task" if count == 1 else "tasks"
        response.async_set_speech(f"You have {count} {noun} due: {names}.")
        return response


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Register Home Keeper conversation intents.

    Idempotent across entry reloads: ``intent.async_register`` keys handlers by
    ``intent_type``, so re-registering simply replaces the previous instance.
    """
    intent.async_register(hass, CompleteTaskIntentHandler())
    intent.async_register(hass, ListDueTasksIntentHandler())
