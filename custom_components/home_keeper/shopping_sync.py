"""Home-Assistant-aware half of the shopping-list mirror.

Reads the configured to-do list over ``todo.get_items``, asks the pure planner
in ``shopping.py`` what to do about it, applies the answer with
``todo.add_item`` / ``todo.update_item`` / ``todo.remove_item``, and feeds the
shopper's side of the loop — an item ticked off at the shop — back into the
store as a completion. Same split as ``problem_tasks.py`` / ``problem_sync.py``.

The parts of that both to-do syncs do identically — the re-entrancy guard and
pass budget in ``async_sync``, snapshotting lists, making a ``todo`` call that
may not be supported, warning once — live in ``TodoSyncDriver``
(``todo_sync_driver.py``), which also carries the three properties this module
owes its callers. What stays here is what is particular to mirroring buy
reminders: one configured target, a plan of add/tick-off/rename/remove, and a
line ticked off at the shop meaning "bought".
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from homeassistant.components.todo import TodoListEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from . import shopping
from .const import DOMAIN, OPTION_SHOPPING_LIST_ENTITY, ORIGIN_SHOPPING_LIST
from .models import TaskValidationError
from .options import current_options
from .shopping import TODO_DOMAIN
from .todo_sync_driver import TodoSyncDriver

_LOGGER = logging.getLogger(__name__)


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


class ShoppingListSync(TodoSyncDriver):
    """Keeps an external to-do list in step with Home Keeper's buy reminders."""

    _logger: ClassVar[logging.Logger] = _LOGGER
    _unsettled_warning: ClassVar[str] = (
        "Home Keeper's shopping-list sync did not settle in %d passes; the list "
        "may be out of step until the next change"
    )
    _failed_pass_message: ClassVar[str] = (
        "Home Keeper shopping-list sync failed; it will retry on the next change"
    )
    _missing_list_warning: ClassVar[str] = (
        "Home Keeper's shopping list %s does not exist; buy reminders are not "
        "being mirrored"
    )
    _unavailable_list_debug: ClassVar[str] = "Shopping list %s is not available yet"
    _unsupported_feature_warning: ClassVar[str] = (
        "To-do list %s does not support %s, so Home Keeper cannot keep it fully "
        "in step with its buy reminders"
    )

    # ── lifecycle ────────────────────────────────────────────────────────────
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
    async def _sync_once(self, *, force: bool) -> bool:
        """One plan-and-apply pass. Returns True when another pass is warranted."""
        if self._stopped:
            return False
        store = self._coordinator.store
        tracked = store.get_shopping_items()
        desired = shopping.buy_tasks_by_part(store.get_tasks(), store.get_assets())
        target = self._resolve_target()
        if not force and not shopping.needs_pass(
            tracked=tracked, desired=desired, target=target
        ):
            return False

        items_by_entity = await self._read_lists(
            shopping.lists_to_read(tracked, target=target),
            targets={target} if target else set(),
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
