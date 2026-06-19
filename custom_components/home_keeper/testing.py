"""Test helpers for integrations that contribute tasks to Home Keeper.

Import this from *your* integration's test suite (it needs a real Home Assistant
test environment, e.g. ``pytest-homeassistant-custom-component``) to exercise the
cross-integration contract — creating tasks, completing them, and receiving the
``home_keeper_task_completed`` event — **without** standing up Home Keeper's panel,
storage, or entities.

The fake is built on Home Keeper's own model/recurrence code and the shared event
payload builder (:mod:`home_keeper.events`), so it stays in lockstep with the real
integration: if the contract changes, this fake changes with it. See
``docs/INTEGRATING.md``.

Example
-------
    from home_keeper.testing import async_setup_fake_home_keeper

    async def test_my_integration_syncs(hass):
        hk = await async_setup_fake_home_keeper(hass)

        # ... set up your integration; it calls home_keeper.add_task ...
        task = hk.get_task_by_source("my_integration", thing_id="abc")

        # Simulate the user checking the task off in Home Keeper (origin=None):
        hk.fire_user_completion(task["id"])
        await hass.async_block_till_done()
        # ... assert your integration mirrored the completion ...
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.util import dt as dt_util

from . import events, models, recurrence
from .const import (
    DOMAIN,
    EVENT_TASK_COMPLETED,
    EVENT_TASK_CREATED,
    EVENT_TASK_DELETED,
    EVENT_TASK_TRIGGERED,
    EVENT_TASK_UPDATED,
)

# Permissive schema: the fake mirrors behaviour, not validation. Your integration's
# real calls still flow through Home Keeper's strict schemas in production.
_ANY = vol.Schema({}, extra=vol.ALLOW_EXTRA)


class FakeHomeKeeper:
    """In-memory stand-in for Home Keeper's services + completion event.

    Registers the real service names (``add_task``/``update_task``/``delete_task``/
    ``complete_task``/``list_tasks``) on the test ``hass`` and fires the genuine
    ``home_keeper_task_completed`` event on completion.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.tasks: dict[str, dict[str, Any]] = {}

    # -- service handlers (names + shapes match the real integration) ---------

    async def _add_task(self, call: ServiceCall) -> dict[str, Any]:
        task = models.build_task(dict(call.data), now=dt_util.now())
        self.tasks[task["id"]] = task
        self.hass.bus.async_fire(EVENT_TASK_CREATED, events.task_event_data(task))
        return {"task_id": task["id"]}

    async def _update_task(self, call: ServiceCall) -> None:
        data = dict(call.data)
        task_id = data.pop("task_id")
        merged = models.merge_update(self.tasks[task_id], data, now=dt_util.now())
        self.tasks[task_id] = merged
        changed = sorted(k for k in data if k != "task_id")
        if changed:
            self.hass.bus.async_fire(
                EVENT_TASK_UPDATED,
                events.task_event_data(merged, extra={"changed_fields": changed}),
            )

    async def _delete_task(self, call: ServiceCall) -> None:
        task = self.tasks.pop(call.data["task_id"], None)
        if task is not None:
            self.hass.bus.async_fire(EVENT_TASK_DELETED, events.task_event_data(task))

    async def _complete_task(self, call: ServiceCall) -> None:
        self._complete(
            call.data["task_id"],
            call.data.get("completed_at"),
            call.data.get("origin"),
        )

    async def _trigger_task(self, call: ServiceCall) -> None:
        # Arm a triggered (condition-driven) task: next_due -> now (due). Mirrors the
        # real store.trigger_task — including rejecting non-triggered tasks — so glue
        # tests catch a caller that arms a floating/fixed task by mistake.
        task = self.tasks.get(call.data["task_id"])
        if task is None:
            return
        if task.get("recurrence_type") != "triggered":
            raise models.TaskValidationError(
                "trigger_task is only valid for triggered (condition-driven) tasks"
            )
        task["next_due"] = dt_util.now().isoformat()
        self.hass.bus.async_fire(EVENT_TASK_TRIGGERED, events.task_event_data(task))

    async def _list_tasks(self, call: ServiceCall) -> dict[str, Any]:
        return {"tasks": [dict(t) for t in self.tasks.values()]}

    # -- test helpers ---------------------------------------------------------

    def _complete(
        self, task_id: str, completed_at: Any | None, origin: str | None
    ) -> dict[str, Any]:
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        now = dt_util.now()
        when = completed_at or now
        # The real complete_task service coerces completed_at via cv.datetime before
        # the store sees it; mirror that so callers can pass an ISO string (as a
        # contributing integration naturally would).
        if isinstance(when, str):
            when = dt_util.parse_datetime(when) or now
        updated = recurrence.apply_completion(dict(task), when, now=now)
        self.tasks[task_id] = updated
        self.hass.bus.async_fire(
            EVENT_TASK_COMPLETED, events.completion_event_data(updated, when, origin)
        )
        return updated

    def fire_user_completion(
        self, task_id: str, completed_at: Any | None = None
    ) -> dict[str, Any]:
        """Simulate a user checking the task off in the UI (``origin`` None)."""
        return self._complete(task_id, completed_at, None)

    def get_task_by_source(self, namespace: str, **match: Any) -> dict[str, Any] | None:
        """Return the first task whose ``source[namespace]`` matches all kwargs."""
        for task in self.tasks.values():
            src = (task.get("source") or {}).get(namespace)
            if isinstance(src, dict) and all(src.get(k) == v for k, v in match.items()):
                return task
        return None

    # -- lifecycle ------------------------------------------------------------

    def register(self) -> None:
        reg = self.hass.services.async_register
        reg(
            DOMAIN,
            "add_task",
            self._add_task,
            _ANY,
            supports_response=SupportsResponse.OPTIONAL,
        )
        reg(DOMAIN, "update_task", self._update_task, _ANY)
        reg(DOMAIN, "delete_task", self._delete_task, _ANY)
        reg(DOMAIN, "complete_task", self._complete_task, _ANY)
        reg(DOMAIN, "trigger_task", self._trigger_task, _ANY)
        reg(
            DOMAIN,
            "list_tasks",
            self._list_tasks,
            _ANY,
            supports_response=SupportsResponse.ONLY,
        )

    def remove(self) -> None:
        for name in (
            "add_task",
            "update_task",
            "delete_task",
            "complete_task",
            "trigger_task",
            "list_tasks",
        ):
            self.hass.services.async_remove(DOMAIN, name)


async def async_setup_fake_home_keeper(hass: HomeAssistant) -> FakeHomeKeeper:
    """Register the fake Home Keeper services on *hass* and return the handle."""
    fake = FakeHomeKeeper(hass)
    fake.register()
    return fake
