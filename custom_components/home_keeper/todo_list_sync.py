"""Home-Assistant-aware half of the to-do list sync.

Reads every configured to-do list over ``todo.get_items``, asks the pure planner in
``todo_list.py`` what each sync wants done about it, applies the answer with
``todo.add_item`` / ``todo.update_item`` / ``todo.remove_item``, and feeds the
household's side of the loop — a chore ticked off on somebody's phone — back into
the store as a completion. Same split as ``shopping.py`` / ``shopping_sync.py``,
and the same HA-facing driver base: ``TodoSyncDriver``
(``todo_sync_driver.py``) carries the re-entrancy guard and pass budget, the
defensive list snapshotting, the capability-checked ``todo`` calls and the
warn-once ledger, along with the three properties both syncs owe their callers.
What stays here is what is particular to syncing profile-filtered chores: many
targets rather than one, task events feeding the pass, due dates and
descriptions on the items, and an inbound tick meaning a task is done.

Where the two syncs diverge is what a *vanished* item means: the shopping-list sync
leaves a deleted line deleted, while a to-do list sync may read it as "done" so that
providers which drop completed items (Todoist) can still tick a chore off. That
divergence lives entirely in the planner — see ``todo_list.py`` — and this
driver only supplies the inputs it needs.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from homeassistant.components.todo import TodoListEntityFeature
from homeassistant.core import Event, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from . import notifier, profiles, todo_list
from .const import (
    EVENT_TASK_COMPLETED,
    EVENT_TASK_CREATED,
    EVENT_TASK_DELETED,
    EVENT_TASK_SKIPPED,
    EVENT_TASK_SNOOZED,
    EVENT_TASK_TRIGGERED,
    EVENT_TASK_UNCOMPLETED,
    EVENT_TASK_UPDATED,
    OPTION_PROFILES,
    ORIGIN_TODO_SYNC,
)
from .models import TaskValidationError
from .options import current_options
from .shopping_sync import own_todo_entity_ids
from .todo_sync_driver import TodoSyncDriver

_LOGGER = logging.getLogger(__name__)

# Every store mutation that can change which tasks a profile surfaces, or what a
# synced item should say. A pass off one of these is *not* forced — ``needs_pass``
# decides whether any list is worth reading — so the churn from tasks no sync
# wants costs nothing, and our own inbound completion echoing back through here
# settles for free.
_TASK_EVENTS = (
    EVENT_TASK_CREATED,
    EVENT_TASK_UPDATED,
    EVENT_TASK_DELETED,
    EVENT_TASK_COMPLETED,
    EVENT_TASK_UNCOMPLETED,
    EVENT_TASK_SNOOZED,
    EVENT_TASK_SKIPPED,
    EVENT_TASK_TRIGGERED,
)


class TodoListSync(TodoSyncDriver):
    """Keeps external to-do lists in step with the tasks each profile surfaces."""

    _logger: ClassVar[logging.Logger] = _LOGGER
    _unsettled_warning: ClassVar[str] = (
        "Home Keeper's to-do list sync did not settle in %d passes; the synced "
        "lists may be out of step until the next change"
    )
    _failed_pass_message: ClassVar[str] = (
        "Home Keeper to-do list sync failed; it will retry on the next change"
    )
    _missing_list_warning: ClassVar[str] = (
        "Home Keeper's synced to-do list %s does not exist; its tasks are not "
        "being kept in step"
    )
    _unavailable_list_debug: ClassVar[str] = "To-do list %s is not available yet"
    _unsupported_feature_warning: ClassVar[str] = (
        "To-do list %s does not support %s, so Home Keeper cannot keep it fully "
        "in step with the tasks synced onto it"
    )

    # ── lifecycle ────────────────────────────────────────────────────────────
    @callback
    def async_start_listeners(self) -> None:
        """Watch the synced lists, and the task changes that feed them.

        Subscriptions go through ``entry.async_on_unload``, so unload/reload tears
        them down. There is no resubscribe path on purpose: the only thing that
        changes which lists are synced is an options save, and that reloads the
        entry.
        """
        self._entry.async_on_unload(self._async_stop)
        targets = sorted(
            {
                str(profile["sync"]["entity_id"])
                for profile in profiles.synced_profiles(self._configured_syncs())
            }
        )
        if targets:
            self._entry.async_on_unload(
                async_track_state_change_event(
                    self._hass, targets, self._handle_state_change
                )
            )
        for event_name in _TASK_EVENTS:
            self._entry.async_on_unload(
                self._hass.bus.async_listen(event_name, self._handle_task_event)
            )

    @callback
    def _handle_task_event(self, event: Event[Any]) -> None:
        # Unforced: ``needs_pass`` gates the read, so a completion on a task no
        # sync wants costs nothing. Our own inbound completions echo back through
        # here as well, and settle for free.
        self._hass.async_create_task(self.async_sync())

    @callback
    def async_schedule_sweep(self) -> None:
        """Ask for a full pass off the coordinator's periodic tick.

        Two things only this notices. A list whose outstanding count happens to
        land back where it started — one item ticked off while another was added —
        produces no state change at all, so the listener alone can miss a tick-off.
        And a task *falling due* is not a store mutation, so no task event fires
        for it: the periodic pass is what puts a newly-overdue chore on the list.
        Costs nothing until something is configured or synced.
        """
        if self._stopped:
            return
        configured = profiles.synced_profiles(self._configured_syncs())
        if not configured and not self._coordinator.store.get_todo_list_items():
            return
        self._hass.async_create_task(self.async_sync(force=True))

    # ── the pass ─────────────────────────────────────────────────────────────
    async def _sync_once(self, *, force: bool) -> bool:
        """One plan-and-apply pass. Returns True when another pass is warranted."""
        if self._stopped:
            return False
        store = self._coordinator.store
        tracked = store.get_todo_list_items()
        synced = self._resolve_syncs()
        # Tasks are enriched with their **effective** labels/area — the ones they
        # inherit from a device or an area — by the same helper the notifier uses,
        # so a profile picks the same tasks for a synced list as it does for a
        # notification, the admin list and the card.
        enriched = notifier.effective_filter_tasks(
            self._hass, list(store.get_tasks().values())
        )
        # One instant for the whole pass: what a profile surfaces and how long an
        # unconfirmed add has been waiting are two readings of the same "now", and
        # taking the clock twice would let them disagree across the reads between.
        now = dt_util.now()
        desired = todo_list.desired_by_sync(synced, enriched, now=now)
        if not force and not todo_list.needs_pass(
            tracked=tracked, desired=desired, synced=synced
        ):
            return False

        targets = {
            str(profile["sync"]["entity_id"])
            for profile in profiles.synced_profiles(synced)
        }
        items_by_entity = await self._read_lists(
            todo_list.lists_to_read(tracked, synced), targets=targets
        )
        if self._stopped:
            return False
        capabilities = {
            entity_id: self._capabilities(entity_id) for entity_id in items_by_entity
        }
        plan = todo_list.plan_sync(
            synced=synced,
            tracked=tracked,
            desired=desired,
            items_by_entity=items_by_entity,
            capabilities=capabilities,
            now=now,
        )
        settled = await self._apply(plan, before=tracked)
        if self._stopped:
            return False
        completed = await self._complete_tasks(plan)
        # Persist before settling: the settle below reconciles and refreshes, and
        # everything that wakes off it — the task events it fires, the sweep on the
        # refresh — re-enters this class. What they find should be what this pass
        # concluded, not what the one before it did.
        await store.async_set_todo_list_items(settled)
        if not completed:
            return False
        # An inbound completion has to behave like every other completion surface —
        # consumables spent, buy reminders reconciled, entities refreshed — so it
        # goes through the same single decision point rather than a bare refresh.
        await self._coordinator.async_settle_buy_tasks()
        return True

    async def _complete_tasks(self, plan: todo_list.TodoListPlan) -> bool:
        """Complete the tasks whose items the household ticked off.

        Nothing is restored to the bookkeeping here, and both failure paths mean
        it. A task deleted between plan and apply is gone, and the item somebody
        ticked off is their record of it now. A task that *refuses* remote
        completion — ``require_tag_scan``, by design — must not be quietly re-bound
        to a line already ticked off either: leaving the entry dropped puts a fresh
        open item back on the list next pass, which is honest feedback that the
        tick did not take.
        """
        store = self._coordinator.store
        completed = False
        for op in plan.complete:
            try:
                await store.complete_task(op.task_id, origin=ORIGIN_TODO_SYNC)
            except KeyError:
                # Deleted while the pass was in flight; its item is somebody else's
                # record now and there is nothing left to sync.
                _LOGGER.debug(
                    "Task %s was gone before the to-do list tick reached it",
                    op.task_id,
                )
            except TaskValidationError as err:
                self._warn_once(
                    f"complete:{op.task_id}",
                    "Home Keeper could not complete task %s from a to-do list (%s), "
                    "so the tick did not take and the task will reappear on the list",
                    op.task_id,
                    err,
                )
            else:
                completed = True
        return completed

    # ── reading ──────────────────────────────────────────────────────────────
    def _configured_syncs(self) -> list[dict[str, Any]]:
        """The stored profiles, normalized — a sync is a profile's ``sync`` block.

        A profile whose ``sync.entity_id`` is ``""`` has its sync switched off, and
        stays in the list: the planner has to see it to take back off whatever it
        put on a list before.
        """
        return profiles.normalize_profiles(
            current_options(self._entry).get(OPTION_PROFILES, [])
        )

    def _resolve_syncs(self) -> list[dict[str, Any]]:
        """The configured profiles, with any pointed at our own list switched off.

        Syncing Home Keeper's tasks onto Home Keeper's own to-do list is a
        feedback loop, and that list declares only ``UPDATE_TODO_ITEM`` so it could
        not accept the items anyway. Blanking the target rather than dropping the
        profile keeps the planner's own rule intact: a sync the user turned off
        clears what it wrote, so anything already on that list still comes back off
        it.
        """
        ours = set(own_todo_entity_ids(self._hass))
        resolved: list[dict[str, Any]] = []
        for profile in self._configured_syncs():
            entity_id = str(profile["sync"]["entity_id"])
            if entity_id and entity_id in ours:
                self._warn_once(
                    f"own:{entity_id}",
                    "Home Keeper cannot sync its tasks onto its own to-do list "
                    "(%s); pick a different list in Settings",
                    entity_id,
                )
                profile = {**profile, "sync": {**profile["sync"], "entity_id": ""}}
            resolved.append(profile)
        return resolved

    def _capabilities(self, entity_id: str) -> frozenset[str]:
        """Which optional item fields *entity_id* can actually hold.

        The planner neither writes nor diffs a field outside this set, so a list
        without due dates is never told one — otherwise every pass would "fix" the
        same item forever, because the value it wrote was dropped on arrival.
        """
        caps: set[str] = set()
        if self._supports(entity_id, TodoListEntityFeature.SET_DUE_DATE_ON_ITEM):
            caps.add(todo_list.CAP_DUE_DATE)
        if self._supports(entity_id, TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM):
            caps.add(todo_list.CAP_DESCRIPTION)
        return frozenset(caps)

    # ── writing ──────────────────────────────────────────────────────────────
    async def _apply(
        self, plan: todo_list.TodoListPlan, *, before: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Run the plan and return the bookkeeping that actually holds.

        *before* is what was tracked going in: an operation that fails restores its
        entry from there, so the next pass retries rather than forgetting.
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
            # Each field is present only when the planner asked for it, and the
            # optional two are already capability-gated there — so there is nothing
            # left to strip here.
            if update.status is not None:
                data["status"] = update.status
            if update.rename is not None:
                data["rename"] = update.rename
            if update.due is not None:
                data["due_date"] = update.due
            if update.description is not None:
                data["description"] = update.description
            ok = await self._call(
                update.entity_id,
                TodoListEntityFeature.UPDATE_TODO_ITEM,
                "update_item",
                data,
            )
            if not ok and update.key in before:
                settled[update.key] = dict(before[update.key])
        for add in plan.add:
            payload: dict[str, Any] = {"entity_id": add.entity_id, "item": add.summary}
            if add.due is not None:
                payload["due_date"] = add.due
            if add.description is not None:
                payload["description"] = add.description
            ok = await self._call(
                add.entity_id,
                TodoListEntityFeature.CREATE_TODO_ITEM,
                "add_item",
                payload,
            )
            if not ok:
                settled.pop(add.key, None)
        return settled
