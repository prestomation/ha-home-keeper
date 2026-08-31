"""What the two to-do list drivers do the same way, in one place.

``shopping_sync.py`` (auto-buy reminders mirrored onto a shopping list) and
``todo_list_sync.py`` (profile-filtered chores kept in step with household
lists) are two different state machines driving one API: somebody else's
``todo.*`` entity, read over ``todo.get_items`` and written with
``todo.add_item`` / ``update_item`` / ``remove_item``. Snapshotting lists
defensively, refusing to call a service the entity does not support, holding the
re-entrancy guard and the pass budget around a plan-and-apply loop, saying a
thing once rather than on every event — none of that is specific to either sync,
so it lives here, and each driver supplies only what genuinely differs: how it
resolves its targets, what it plans, how it applies that plan, and what an
inbound tick means.

The three properties both drivers owe their callers are properties of this base:

* **It never breaks its caller.** A pass runs off the back of a completion, a
  stock adjustment or a task event; a list that is unavailable, unloaded, or
  refuses new items must cost nothing more than a log line. Every outbound call
  is best-effort (the ``notifier`` precedent) and :meth:`async_sync` swallows
  whatever reaches it.
* **A failed call is retried, never compensated.** The planners hand back the
  bookkeeping as it will read once every operation has succeeded; anything that
  raised puts its entry back, so the next pass tries again. That restoration is
  each subclass's ``_apply``, because the ops it walks differ.
* **It reads a to-do list only when there is a reason to.** Each planner's
  ``needs_pass`` answers "has Home Keeper drifted from what it last wrote" from
  memory alone; only the surfaces watching the *other* side of the loop — a
  list's own state changes, the periodic sweep — force a read.

Everything the log says is a class-level knob rather than a shared string: a
household reading its log should see "shopping list" or "synced to-do list",
whichever actually happened, and each driver keeps logging under its own module
name.

``problem_sync.py`` is deliberately not a subclass. It mirrors ``binary_sensor``
entities into tasks off the entity registry and a state listener, and never
reads or writes a to-do list at all — what it shares with these two is the pure
planner/HA-driver split, not a mechanism.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.components.todo import TodoListEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)

from .shopping import normalize_items
from .todo_items import STATUS_COMPLETED, STATUS_NEEDS_ACTION

if TYPE_CHECKING:
    from .coordinator import HomeKeeperCoordinator

_TODO_SERVICE_DOMAIN = "todo"


class TodoSyncDriver(ABC):
    """The Home-Assistant-facing half of a to-do list sync.

    A subclass owns its own targets, planner and plan application; it implements
    :meth:`_sync_once` and sets the class-level strings below, which are the
    only things the shared paths say out loud.
    """

    # Where the shared paths log, so a message still reads as coming from the
    # driver that produced it rather than from this base.
    _logger: ClassVar[logging.Logger]
    # Burning the whole pass budget (``async_sync``), with the count.
    _unsettled_warning: ClassVar[str]
    # A pass that raised (``async_sync``), logged with the traceback.
    _failed_pass_message: ClassVar[str]
    # A configured target that does not exist (``_read_lists``), by entity id.
    _missing_list_warning: ClassVar[str]
    # A list that exists but is not readable yet (``_read_lists``), by entity id.
    _unavailable_list_debug: ClassVar[str]
    # An entity missing the feature a call needs (``_call``): entity id, service.
    _unsupported_feature_warning: ClassVar[str]

    # One pass can beget another: an inbound tick completes a task, which the
    # lists then have to be told about. Two passes cover that; the extra headroom
    # absorbs our own writes echoing back through each list's state. The cap is
    # what guarantees the loop ends whatever the lists do.
    _MAX_PASSES: ClassVar[int] = 4

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: HomeKeeperCoordinator,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._running = False
        self._pending = False
        self._stopped = False
        # Reasons already logged at warning level, so a permanently misconfigured
        # target says its piece once instead of on every event that pokes a pass.
        self._warned: set[str] = set()

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def async_initial_sync(self) -> None:
        """Bring the lists in step once Home Assistant has finished starting.

        Deferred to the started event rather than run during setup: the lists we
        write to belong to other integrations, which may not have set up yet, and
        a target that reads as missing would have us do nothing.
        """
        await self.async_sync(force=True)

    @callback
    def _async_stop(self) -> None:
        self._stopped = True

    @callback
    def _handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        # A to-do entity's state is its outstanding-item count, so a tick-off
        # always lands here — and it is invisible to ``needs_pass``, which can
        # only see Home Keeper's own side. Hence the forced pass. Our own writes
        # echo back too; a settled pass emits nothing, and the re-entrancy guard
        # folds the burst into one run.
        self._hass.async_create_task(self.async_sync(force=True))

    # ── the pass ─────────────────────────────────────────────────────────────
    async def async_sync(self, *, force: bool = False) -> None:
        """Bring the lists in step. Never raises.

        *force* reads the lists even when Home Keeper's own state looks settled,
        which is the only way to notice the other side of the loop — an item
        ticked off on somebody's phone.
        """
        if self._running:
            # Poked mid-pass — our own writes echoing back, or the completion
            # this pass just made. Fold it into the run already in flight instead
            # of nesting.
            self._pending = True
            return
        self._running = True
        self._pending = False
        try:
            for attempt in range(self._MAX_PASSES):
                again = await self._sync_once(force=force or attempt > 0)
                if not (again or self._pending):
                    break
                self._pending = False
            else:
                # The budget exists so the loop always ends, not because ending
                # this way is fine: a converging sync settles in two passes.
                # Burning the whole budget means something is failing and
                # retrying — say so, rather than exiting quietly and leaving the
                # lists stale with no trace of why.
                self._logger.warning(self._unsettled_warning, self._MAX_PASSES)
        except Exception:  # a broken list must never break what triggered us
            self._logger.exception(self._failed_pass_message)
        finally:
            self._running = False
            self._pending = False

    @abstractmethod
    async def _sync_once(self, *, force: bool) -> bool:
        """One plan-and-apply pass. Returns True when another pass is warranted."""

    # ── reading ──────────────────────────────────────────────────────────────
    async def _read_lists(
        self, entity_ids: list[str], *, targets: set[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Snapshot each list we care about, skipping any we cannot see.

        A list left out of the result is *unknown* to the planner, which then
        plans nothing for it and carries its bookkeeping forward. That is what
        stops an unavailable list from reading as "somebody emptied it".

        *targets* is what is configured right now, as opposed to the lists we
        merely still hold items on: only a configured one that has gone missing
        is worth telling the user about.
        """
        snapshots: dict[str, list[dict[str, Any]]] = {}
        for entity_id in entity_ids:
            state = self._hass.states.get(entity_id)
            # The two ways a list can be unreadable are not the same, and are
            # deliberately logged differently. A configured target that does not
            # exist is a misconfiguration the user has to fix, so it says so
            # once, by name. A target that merely reads unavailable belongs to an
            # integration that is temporarily down: Home Assistant already logs
            # that, the next pass picks it up by itself, and warning here would
            # fire on every restart where a cloud-backed list comes up after we
            # do.
            if state is None:
                if entity_id in targets:
                    self._warn_once(
                        f"missing:{entity_id}",
                        self._missing_list_warning,
                        entity_id,
                    )
                continue
            if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                self._logger.debug(self._unavailable_list_debug, entity_id)
                continue
            try:
                response = await self._hass.services.async_call(
                    _TODO_SERVICE_DOMAIN,
                    "get_items",
                    {
                        "entity_id": entity_id,
                        "status": [STATUS_NEEDS_ACTION, STATUS_COMPLETED],
                    },
                    blocking=True,
                    return_response=True,
                )
            except Exception as err:  # someone else's integration, someone else's bugs
                self._logger.debug("Could not read to-do list %s: %s", entity_id, err)
                continue
            items = normalize_items(response, entity_id)
            if items is None:
                self._logger.debug("To-do list %s returned nothing readable", entity_id)
                continue
            snapshots[entity_id] = items
        return snapshots

    # ── writing ──────────────────────────────────────────────────────────────
    async def _call(
        self,
        entity_id: str,
        feature: TodoListEntityFeature,
        service: str,
        data: dict[str, Any],
    ) -> bool:
        """Make one ``todo`` service call. Returns whether it landed."""
        if not self._supports(entity_id, feature):
            self._warn_once(
                f"feature:{entity_id}:{service}",
                self._unsupported_feature_warning,
                entity_id,
                service,
            )
            return False
        try:
            await self._hass.services.async_call(
                _TODO_SERVICE_DOMAIN, service, data, blocking=True
            )
        except Exception as err:  # never break the mutation that triggered us
            self._logger.debug("todo.%s on %s failed: %s", service, entity_id, err)
            return False
        return True

    def _supports(self, entity_id: str, feature: TodoListEntityFeature) -> bool:
        state = self._hass.states.get(entity_id)
        if state is None:
            return False
        return bool(int(state.attributes.get("supported_features") or 0) & feature)

    def _warn_once(self, reason: str, message: str, *args: Any) -> None:
        if reason in self._warned:
            return
        self._warned.add(reason)
        self._logger.warning(message, *args)
