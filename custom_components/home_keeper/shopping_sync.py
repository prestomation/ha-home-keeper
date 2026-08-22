"""Home-Assistant-aware half of the shopping-list mirror.

Reads the configured to-do list over ``todo.get_items``, asks the pure planner
in ``shopping.py`` what to do about it, applies the answer with
``todo.add_item`` / ``todo.update_item`` / ``todo.remove_item``, and feeds the
shopper's side of the loop — an item ticked off at the shop — back into the
store as a completion. Same split as ``problem_tasks.py`` / ``problem_sync.py``.

Three properties this module is responsible for:

* **It never breaks its caller.** A pass runs off the back of a completion or a
  stock adjustment; a shopping list that is unavailable, unloaded, or refuses
  new items must cost nothing more than a log line. Every outbound call is
  best-effort (the ``notifier`` precedent) and ``async_sync`` swallows whatever
  reaches it.
* **A failed call is retried, never compensated.** The planner hands back the
  bookkeeping as it will read once every operation has succeeded; anything that
  raised puts its entry back, so the next pass tries again. Dropping an entry
  for a remove that never happened would orphan that line on the list forever.
* **It reads a to-do list only when there is a reason to.** ``needs_pass``
  answers "has Home Keeper drifted from what it mirrored" from memory alone, so
  the many settles that change nothing cost no service calls. The surfaces that
  watch for the shopper's side — the list's own state changes, and a periodic
  sweep — ask for a full pass regardless, since that side is invisible from
  here.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.todo import TodoListEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from . import shopping
from .const import DOMAIN, OPTION_SHOPPING_LIST_ENTITY, ORIGIN_SHOPPING_LIST
from .models import TaskValidationError
from .options import current_options
from .shopping import TODO_DOMAIN

if TYPE_CHECKING:
    from .coordinator import HomeKeeperCoordinator

_LOGGER = logging.getLogger(__name__)

_TODO_SERVICE_DOMAIN = "todo"

# One pass can beget another: completing a reminder makes the reconciler retire
# it, which the list then has to be told about. Two passes cover that; the extra
# headroom absorbs our own writes echoing back through the list's state. The cap
# is what guarantees the loop ends whatever the lists do.
_MAX_PASSES = 4


def own_todo_entity_ids(hass: HomeAssistant) -> list[str]:
    """Home Keeper's own to-do entities — never a valid mirror target.

    Pointing the mirror at our own list would be a feedback loop, and our list
    declares only ``UPDATE_TODO_ITEM`` so it could not accept a new item anyway.
    Resolved from the registry rather than hard-coded, so a renamed entity is
    still recognised.
    """
    registry = er.async_get(hass)
    return sorted(
        entry.entity_id
        for entry in registry.entities.values()
        if entry.domain == TODO_DOMAIN and entry.platform == DOMAIN
    )


class ShoppingListSync:
    """Keeps an external to-do list in step with Home Keeper's buy reminders."""

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
        # target says its piece once instead of on every list edit.
        self._warned: set[str] = set()

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def async_initial_sync(self) -> None:
        """Bring the mirror in step once Home Assistant has finished starting.

        Deferred to the started event rather than run during setup: the list we
        mirror onto belongs to another integration, which may not have set up
        yet, and a target that reads as missing would have us do nothing.
        """
        await self.async_sync(force=True)

    @callback
    def async_start_listeners(self) -> None:
        """Watch the configured list so a tick-off at the shop reaches the store.

        Subscriptions go through ``entry.async_on_unload``, so unload/reload tears
        them down. There is no resubscribe path on purpose: the only thing that
        changes the target is an options save, and that reloads the entry.
        """
        self._entry.async_on_unload(self._async_stop)
        target = self._resolve_target()
        if target:
            self._entry.async_on_unload(
                async_track_state_change_event(
                    self._hass, [target], self._handle_state_change
                )
            )

    @callback
    def _async_stop(self) -> None:
        self._stopped = True

    @callback
    def _handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        # A to-do entity's state is its outstanding-item count, so a tick-off
        # always lands here. Our own writes echo back too; a settled pass emits
        # nothing, and the re-entrancy guard folds the burst into one run.
        self._hass.async_create_task(self.async_sync(force=True))

    @callback
    def async_schedule_sweep(self) -> None:
        """Ask for a full pass off the coordinator's periodic tick.

        A list whose outstanding count happens to land back where it started —
        one item ticked off while another was added — produces no state change at
        all, so the listener alone can miss a tick-off. Costs nothing until
        something is actually mirrored.
        """
        if self._stopped or not self._coordinator.store.get_shopping_items():
            return
        self._hass.async_create_task(self.async_sync(force=True))

    # ── the pass ─────────────────────────────────────────────────────────────
    async def async_sync(self, *, force: bool = False) -> None:
        """Bring the mirror in step. Never raises.

        *force* reads the lists even when Home Keeper's own state looks settled,
        which is the only way to notice the shopper's side of the loop.
        """
        if self._running:
            # Poked mid-pass — our own writes echoing back, or the reconciler
            # settling. Fold it into the run already in flight instead of nesting.
            self._pending = True
            return
        self._running = True
        self._pending = False
        try:
            for attempt in range(_MAX_PASSES):
                again = await self._sync_once(force=force or attempt > 0)
                if not (again or self._pending):
                    break
                self._pending = False
        except Exception:  # a broken list must never break a completion
            _LOGGER.exception(
                "Home Keeper shopping-list sync failed; it will retry on the next "
                "change"
            )
        finally:
            self._running = False
            self._pending = False

    async def _sync_once(self, *, force: bool) -> bool:
        """One plan-and-apply pass. Returns True when another pass is warranted."""
        if self._stopped:
            return False
        store = self._coordinator.store
        tracked = store.get_shopping_items()
        desired = shopping.buy_tasks_by_part(store.get_tasks())
        target = self._resolve_target()
        if not force and not shopping.needs_pass(
            tracked=tracked, desired=desired, target=target
        ):
            return False

        items_by_entity = await self._read_lists(
            shopping.lists_to_read(tracked, target=target), target=target
        )
        if self._stopped:
            return False
        plan = shopping.plan_sync(
            tracked=tracked,
            desired=desired,
            items_by_entity=items_by_entity,
            target=target,
        )
        settled = await self._apply(plan, before=tracked)
        if self._stopped:
            return False
        completed = await self._complete_reminders(plan, settled, before=tracked)
        # Persist before settling: the reconcile below re-enters this class, and
        # what it finds should be what this pass concluded.
        await store.async_set_shopping_items(settled)
        if not completed:
            return False
        # Completing a buy reminder restocks the part, which normally lifts it
        # back above its threshold — the reconciler then retires the reminder, and
        # the next pass tidies whatever that leaves on the list.
        await self._coordinator.async_settle_buy_tasks()
        return True

    async def _complete_reminders(
        self,
        plan: shopping.SyncPlan,
        settled: dict[str, dict[str, Any]],
        *,
        before: dict[str, dict[str, Any]],
    ) -> bool:
        """Complete the reminders whose items were ticked off at the shop."""
        store = self._coordinator.store
        completed = False
        for op in plan.complete:
            try:
                await store.complete_task(op.task_id, origin=ORIGIN_SHOPPING_LIST)
            except (KeyError, TaskValidationError) as err:
                _LOGGER.warning(
                    "Home Keeper could not complete buy reminder %s from the "
                    "shopping list: %s",
                    op.task_id,
                    err,
                )
                if op.key in before:
                    settled[op.key] = dict(before[op.key])
            else:
                completed = True
        return completed

    # ── reading ──────────────────────────────────────────────────────────────
    def _resolve_target(self) -> str:
        """The list to mirror onto, or ``""`` when there isn't a usable one."""
        target = shopping.normalize_target(
            current_options(self._entry).get(OPTION_SHOPPING_LIST_ENTITY, "")
        )
        if target and target in own_todo_entity_ids(self._hass):
            self._warn_once(
                f"own:{target}",
                "Home Keeper cannot mirror buy reminders onto its own to-do list "
                "(%s); pick a different list in Settings",
                target,
            )
            return ""
        return target

    async def _read_lists(
        self, entity_ids: list[str], *, target: str
    ) -> dict[str, list[dict[str, Any]]]:
        """Snapshot each list we care about, skipping any we cannot see.

        A list left out of the result is *unknown* to the planner, which then
        plans nothing for it. That is what stops an unavailable shopping list
        from reading as "the user emptied it".
        """
        snapshots: dict[str, list[dict[str, Any]]] = {}
        for entity_id in entity_ids:
            state = self._hass.states.get(entity_id)
            # The two ways a list can be unreadable are not the same, and are
            # deliberately logged differently. A target that does not exist is a
            # misconfiguration the user has to fix, so it says so once, by name.
            # A target that merely reads unavailable belongs to an integration
            # that is temporarily down: Home Assistant already logs that, the
            # next pass picks it up by itself, and warning here would fire on
            # every restart where a cloud-backed list comes up after we do.
            if state is None:
                if entity_id == target:
                    self._warn_once(
                        f"missing:{entity_id}",
                        "Home Keeper's shopping list %s does not exist; buy "
                        "reminders are not being mirrored",
                        entity_id,
                    )
                continue
            if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                _LOGGER.debug("Shopping list %s is not available yet", entity_id)
                continue
            try:
                response = await self._hass.services.async_call(
                    _TODO_SERVICE_DOMAIN,
                    "get_items",
                    {
                        "entity_id": entity_id,
                        "status": [
                            shopping.STATUS_NEEDS_ACTION,
                            shopping.STATUS_COMPLETED,
                        ],
                    },
                    blocking=True,
                    return_response=True,
                )
            except Exception as err:  # someone else's integration, someone else's bugs
                _LOGGER.debug("Could not read to-do list %s: %s", entity_id, err)
                continue
            items = shopping.normalize_items(response, entity_id)
            if items is None:
                _LOGGER.debug("To-do list %s returned nothing readable", entity_id)
                continue
            snapshots[entity_id] = items
        return snapshots

    # ── writing ──────────────────────────────────────────────────────────────
    async def _apply(
        self, plan: shopping.SyncPlan, *, before: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Run the plan and return the bookkeeping that actually holds.

        *before* is what was tracked going in: an operation that fails restores
        its entry from there, so the next pass retries rather than forgetting.
        """
        settled = {key: dict(entry) for key, entry in plan.tracked.items()}
        for remove in plan.remove:
            ok = await self._call(
                remove.entity_id,
                TodoListEntityFeature.DELETE_TODO_ITEM,
                "remove_item",
                {"entity_id": remove.entity_id, "item": [remove.item]},
            )
            if not ok and remove.key in before:
                settled[remove.key] = dict(before[remove.key])
        for update in plan.update:
            data: dict[str, Any] = {
                "entity_id": update.entity_id,
                "item": update.item,
            }
            if update.status is not None:
                data["status"] = update.status
            if update.rename is not None:
                data["rename"] = update.rename
            ok = await self._call(
                update.entity_id,
                TodoListEntityFeature.UPDATE_TODO_ITEM,
                "update_item",
                data,
            )
            if not ok and update.key in before:
                settled[update.key] = dict(before[update.key])
        for add in plan.add:
            ok = await self._call(
                add.entity_id,
                TodoListEntityFeature.CREATE_TODO_ITEM,
                "add_item",
                {"entity_id": add.entity_id, "item": add.summary},
            )
            if not ok:
                settled.pop(add.key, None)
        return settled

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
                "To-do list %s does not support %s, so Home Keeper cannot keep it "
                "fully in step with its buy reminders",
                entity_id,
                service,
            )
            return False
        try:
            await self._hass.services.async_call(
                _TODO_SERVICE_DOMAIN, service, data, blocking=True
            )
        except Exception as err:  # never break the completion that triggered us
            _LOGGER.debug("todo.%s on %s failed: %s", service, entity_id, err)
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
        _LOGGER.warning(message, *args)
