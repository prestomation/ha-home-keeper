"""Home-Assistant-aware half of the task mirror.

Reads every configured to-do list over ``todo.get_items``, asks the pure planner in
``task_mirror.py`` what each mirror wants done about it, applies the answer with
``todo.add_item`` / ``todo.update_item`` / ``todo.remove_item``, and feeds the
household's side of the loop — a chore ticked off on somebody's phone — back into
the store as a completion. Same split as ``shopping.py`` / ``shopping_sync.py``,
and this module inherits that sibling's three properties:

* **It never breaks its caller.** A pass runs off the back of a task event, a
  list's own state change, or the coordinator's tick; a to-do list that is
  unavailable, unloaded, or refuses new items must cost nothing more than a log
  line. Every outbound call is best-effort and ``async_sync`` swallows whatever
  reaches it.
* **A failed call is retried, never compensated.** The planner hands back the
  bookkeeping as it will read once every operation has succeeded; anything that
  raised puts its entry back, so the next pass tries again. Dropping an entry for
  a remove that never happened would orphan that line on the list forever.
* **It reads a to-do list only when there is a reason to.** ``needs_pass``
  answers "has Home Keeper drifted from what it mirrored" from memory alone, so
  the great majority of task events — which concern tasks no mirror wants —
  cost no service calls. The surfaces that watch for the household's side (each
  list's own state changes, and the periodic sweep) ask for a full pass
  regardless, since that side is invisible from here.

Where the two mirrors diverge is what a *vanished* item means: the shopping mirror
leaves a deleted line deleted, while a task mirror may read it as "done" so that
providers which drop completed items (Todoist) can still tick a chore off. That
divergence lives entirely in the planner — see ``task_mirror.py`` — and this
driver only supplies the inputs it needs.
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
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from . import notifier, profiles, task_mirror
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
    ORIGIN_TODO_MIRROR,
)
from .models import TaskValidationError
from .options import current_options
from .shopping import STATUS_COMPLETED, STATUS_NEEDS_ACTION, normalize_items
from .shopping_sync import own_todo_entity_ids

if TYPE_CHECKING:
    from .coordinator import HomeKeeperCoordinator

_LOGGER = logging.getLogger(__name__)

_TODO_SERVICE_DOMAIN = "todo"

# One pass can beget another: an inbound tick completes a task, which reschedules
# it, which the lists then have to be told about. Two passes cover that; the extra
# headroom absorbs our own writes echoing back through each list's state. The cap
# is what guarantees the loop ends whatever the lists do.
_MAX_PASSES = 4

# Every store mutation that can change which tasks a profile surfaces, or what a
# mirrored item should say. A pass off one of these is *not* forced — ``needs_pass``
# decides whether any list is worth reading — so the churn from tasks no mirror
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


class TaskMirrorSync:
    """Keeps external to-do lists in step with the tasks each profile surfaces."""

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
        # mirror says its piece once instead of on every task event.
        self._warned: set[str] = set()

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def async_initial_sync(self) -> None:
        """Bring the mirrors in step once Home Assistant has finished starting.

        Deferred to the started event rather than run during setup: the lists we
        mirror onto belong to other integrations, which may not have set up yet,
        and a target that reads as missing would have us do nothing.
        """
        await self.async_sync(force=True)

    @callback
    def async_start_listeners(self) -> None:
        """Watch the mirrored lists, and the task changes that feed them.

        Subscriptions go through ``entry.async_on_unload``, so unload/reload tears
        them down. There is no resubscribe path on purpose: the only thing that
        changes which lists are mirrored is an options save, and that reloads the
        entry.
        """
        self._entry.async_on_unload(self._async_stop)
        targets = sorted(
            {
                str(mirror["sync"]["entity_id"])
                for mirror in profiles.synced_profiles(self._configured_mirrors())
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
    def _async_stop(self) -> None:
        self._stopped = True

    @callback
    def _handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        # A to-do entity's state is its outstanding-item count, so a tick-off
        # always lands here — and it is invisible to ``needs_pass``, which can only
        # see Home Keeper's own side. Hence the forced pass. Our own writes echo
        # back too; a settled pass emits nothing, and the re-entrancy guard folds
        # the burst into one run.
        self._hass.async_create_task(self.async_sync(force=True))

    @callback
    def _handle_task_event(self, event: Event[Any]) -> None:
        # Unforced: ``needs_pass`` gates the read, so a completion on a task no
        # mirror wants costs nothing. Our own inbound completions echo back through
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
        Costs nothing until something is configured or mirrored.
        """
        if self._stopped:
            return
        configured = profiles.synced_profiles(self._configured_mirrors())
        if not configured and not self._coordinator.store.get_task_mirror_items():
            return
        self._hass.async_create_task(self.async_sync(force=True))

    # ── the pass ─────────────────────────────────────────────────────────────
    async def async_sync(self, *, force: bool = False) -> None:
        """Bring the mirrors in step. Never raises.

        *force* reads the lists even when Home Keeper's own state looks settled,
        which is the only way to notice the household's side of the loop.
        """
        if self._running:
            # Poked mid-pass — our own writes echoing back, or the completion this
            # pass just made. Fold it into the run already in flight instead of
            # nesting.
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
            else:
                # The budget exists so the loop always ends, not because ending
                # this way is fine: a converging mirror settles in two passes.
                # Burning the whole budget means something is failing and
                # retrying — say so, rather than exiting quietly and leaving the
                # lists stale with no trace of why.
                _LOGGER.warning(
                    "Home Keeper's to-do list sync did not settle in %d passes; "
                    "the mirrored lists may be out of step until the next change",
                    _MAX_PASSES,
                )
        except Exception:  # a broken list must never break a task mutation
            _LOGGER.exception(
                "Home Keeper to-do list sync failed; it will retry on the next change"
            )
        finally:
            self._running = False
            self._pending = False

    async def _sync_once(self, *, force: bool) -> bool:
        """One plan-and-apply pass. Returns True when another pass is warranted."""
        if self._stopped:
            return False
        store = self._coordinator.store
        tracked = store.get_task_mirror_items()
        mirrors = self._resolve_mirrors()
        # Tasks are enriched with their **effective** labels/area — the ones they
        # inherit from a device or an area — by the same helper the notifier uses,
        # so a profile picks the same tasks for a mirrored list as it does for a
        # notification, the admin list and the card.
        enriched = notifier.effective_filter_tasks(
            self._hass, list(store.get_tasks().values())
        )
        desired = task_mirror.desired_by_mirror(mirrors, enriched, now=dt_util.now())
        if not force and not task_mirror.needs_pass(
            tracked=tracked, desired=desired, mirrors=mirrors
        ):
            return False

        targets = {
            str(mirror["sync"]["entity_id"])
            for mirror in profiles.synced_profiles(mirrors)
        }
        items_by_entity = await self._read_lists(
            task_mirror.lists_to_read(tracked, mirrors), targets=targets
        )
        if self._stopped:
            return False
        capabilities = {
            entity_id: self._capabilities(entity_id) for entity_id in items_by_entity
        }
        plan = task_mirror.plan_sync(
            mirrors=mirrors,
            tracked=tracked,
            desired=desired,
            items_by_entity=items_by_entity,
            capabilities=capabilities,
        )
        settled = await self._apply(plan, before=tracked)
        if self._stopped:
            return False
        completed = await self._complete_tasks(plan)
        # Persist before settling: the settle below reconciles and refreshes, and
        # everything that wakes off it — the task events it fires, the sweep on the
        # refresh — re-enters this class. What they find should be what this pass
        # concluded, not what the one before it did.
        await store.async_set_task_mirror_items(settled)
        if not completed:
            return False
        # An inbound completion has to behave like every other completion surface —
        # consumables spent, buy reminders reconciled, entities refreshed — so it
        # goes through the same single decision point rather than a bare refresh.
        await self._coordinator.async_settle_buy_tasks()
        return True

    async def _complete_tasks(self, plan: task_mirror.TaskMirrorPlan) -> bool:
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
                await store.complete_task(op.task_id, origin=ORIGIN_TODO_MIRROR)
            except KeyError:
                # Deleted while the pass was in flight; its item is somebody else's
                # record now and there is nothing left to mirror.
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
    def _configured_mirrors(self) -> list[dict[str, Any]]:
        """The stored profiles, normalized — a mirror is a profile's ``sync`` block.

        A profile whose ``sync.entity_id`` is ``""`` has its sync switched off, and
        stays in the list: the planner has to see it to take back off whatever it
        put on a list before.
        """
        return profiles.normalize_profiles(
            current_options(self._entry).get(OPTION_PROFILES, [])
        )

    def _resolve_mirrors(self) -> list[dict[str, Any]]:
        """The configured profiles, with any pointed at our own list switched off.

        Mirroring Home Keeper's tasks onto Home Keeper's own to-do list is a
        feedback loop, and that list declares only ``UPDATE_TODO_ITEM`` so it could
        not accept the items anyway. Blanking the target rather than dropping the
        profile keeps the planner's own rule intact: a mirror the user turned off
        clears what it wrote, so anything already on that list still comes back off
        it.
        """
        ours = set(own_todo_entity_ids(self._hass))
        resolved: list[dict[str, Any]] = []
        for mirror in self._configured_mirrors():
            entity_id = str(mirror["sync"]["entity_id"])
            if entity_id and entity_id in ours:
                self._warn_once(
                    f"own:{entity_id}",
                    "Home Keeper cannot mirror its tasks onto its own to-do list "
                    "(%s); pick a different list in Settings",
                    entity_id,
                )
                mirror = {**mirror, "sync": {**mirror["sync"], "entity_id": ""}}
            resolved.append(mirror)
        return resolved

    async def _read_lists(
        self, entity_ids: list[str], *, targets: set[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Snapshot each list we care about, skipping any we cannot see.

        A list left out of the result is *unknown* to the planner, which then plans
        nothing for it and carries its bookkeeping forward. That is what stops an
        unavailable to-do list from reading as "the household emptied it".
        """
        snapshots: dict[str, list[dict[str, Any]]] = {}
        for entity_id in entity_ids:
            state = self._hass.states.get(entity_id)
            # The two ways a list can be unreadable are not the same, and are
            # deliberately logged differently. A configured target that does not
            # exist is a misconfiguration the user has to fix, so it says so once,
            # by name. A target that merely reads unavailable belongs to an
            # integration that is temporarily down: Home Assistant already logs
            # that, the next pass picks it up by itself, and warning here would
            # fire on every restart where a cloud-backed list comes up after we do.
            if state is None:
                if entity_id in targets:
                    self._warn_once(
                        f"missing:{entity_id}",
                        "Home Keeper's mirrored to-do list %s does not exist; its "
                        "tasks are not being kept in step",
                        entity_id,
                    )
                continue
            if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                _LOGGER.debug("To-do list %s is not available yet", entity_id)
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
                _LOGGER.debug("Could not read to-do list %s: %s", entity_id, err)
                continue
            items = normalize_items(response, entity_id)
            if items is None:
                _LOGGER.debug("To-do list %s returned nothing readable", entity_id)
                continue
            snapshots[entity_id] = items
        return snapshots

    def _capabilities(self, entity_id: str) -> frozenset[str]:
        """Which optional item fields *entity_id* can actually hold.

        The planner neither writes nor diffs a field outside this set, so a list
        without due dates is never told one — otherwise every pass would "fix" the
        same item forever, because the value it wrote was dropped on arrival.
        """
        caps: set[str] = set()
        if self._supports(entity_id, TodoListEntityFeature.SET_DUE_DATE_ON_ITEM):
            caps.add(task_mirror.CAP_DUE_DATE)
        if self._supports(entity_id, TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM):
            caps.add(task_mirror.CAP_DESCRIPTION)
        return frozenset(caps)

    # ── writing ──────────────────────────────────────────────────────────────
    async def _apply(
        self, plan: task_mirror.TaskMirrorPlan, *, before: dict[str, dict[str, Any]]
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
                "fully in step with the tasks mirrored onto it",
                entity_id,
                service,
            )
            return False
        try:
            await self._hass.services.async_call(
                _TODO_SERVICE_DOMAIN, service, data, blocking=True
            )
        except Exception as err:  # never break the mutation that triggered us
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
