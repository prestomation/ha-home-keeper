"""Pure planning for the shopping-list mirror of auto-buy reminders.

An auto-buy reminder (``source = {"buy": {asset_id, part_id}}``, minted by
``reconcile.reconcile_buy_tasks`` while a part is low) can be mirrored onto an
existing Home Assistant to-do list — a shopping list — so it reaches voice
assistants and list widgets instead of living only on
``todo.home_keeper_tasks``. This module owns the whole decision: given what we
mirrored last time, what Home Keeper wants bought now, and what is actually on
the list, it returns the operations to apply. ``shopping_sync.py`` is the
Home-Assistant-aware half that reads the list, executes the plan, and feeds
tick-offs back into the store.

Like ``reconcile.py`` this imports nothing from Home Assistant: it is a pure
transformation over plain dicts, so every branch of the state machine is
unit-testable without an HA runtime (see ``tests/unit/test_shopping.py``).

Two rules shape the plan:

* **The list mirrors what Home Keeper currently wants bought.** An item we put
  there is removed once its reminder goes away unbought — the stock was topped
  up by hand, auto-buy was switched off, the part was deleted.
* **A completed item is never touched.** Whoever ticked it off — the shopper on
  their phone, or Home Keeper when the reminder was completed elsewhere — the
  entry stays as their record. Finding one ticked off while its reminder is
  still open is the *reverse* direction: Home Keeper completes the reminder,
  which restocks the part.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .reconcile import buy_source
from .recurrence import one_off_completed
from .todo_items import (
    STATUS_COMPLETED,
    STATUS_NEEDS_ACTION,
    find_open,
    item_identity,
    item_is_open,
    resolve_tracked,
)

__all__ = [
    "STATUS_COMPLETED",
    "STATUS_NEEDS_ACTION",
    "TODO_DOMAIN",
    "AddOp",
    "CompleteOp",
    "RemoveOp",
    "SyncPlan",
    "UpdateOp",
    "buy_tasks_by_part",
    "lists_to_read",
    "needs_pass",
    "normalize_items",
    "normalize_target",
    "part_key",
    "plan_sync",
    "source_key",
]

# The only entity domain a mirror target may live in.
TODO_DOMAIN = "todo"

# Separator for the ``asset_id``/``part_id`` pair that keys a mirrored item. The
# part — not the buy task — is the identity: a reminder is deleted and minted
# afresh for each low episode, and the mirror has to survive that.
_KEY_SEP = ":"


def part_key(asset_id: str, part_id: str) -> str:
    """The tracking key for one part's mirrored reminder."""
    return f"{asset_id}{_KEY_SEP}{part_id}"


def normalize_target(value: Any) -> str:
    """Coerce a configured mirror target to a ``todo.*`` entity id, or ``""``.

    ``""`` is the off switch, and it is also what anything unusable collapses to
    — a blank string, a non-string, an entity in some other domain, anything not
    shaped like an entity id at all. Keeping the rule here (rather than in
    ``options.py``) means the options flow, the ``set_options`` service and the
    panel all coerce identically, and the rule itself is covered by the unit
    suite.
    """
    if not isinstance(value, str):
        return ""
    entity_id = value.strip().lower()
    parts = entity_id.split(".")
    # An entity id is exactly ``domain.object_id`` — one dot, both halves filled.
    if len(parts) != 2 or parts[0] != TODO_DOMAIN or not parts[1]:
        return ""
    return entity_id


def buy_tasks_by_part(tasks: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index the auto-buy reminders in *tasks* by their part key.

    Each value is ``{"task_id", "name", "completed"}`` — everything the planner
    needs, so it never has to know the task schema. A reminder with no name is
    skipped: an empty summary is not something a to-do list can hold.
    """
    indexed: dict[str, dict[str, Any]] = {}
    for task_id, task in tasks.items():
        source = buy_source(task)
        if source is None:
            continue
        name = str(task.get("name") or "").strip()
        if not name:
            continue
        entry = {
            "task_id": str(task.get("id") or task_id),
            "name": name,
            "completed": one_off_completed(task),
        }
        key = source_key(source)
        # The reconciler keeps at most one buy task per part. If storage somehow
        # holds both a completed one and a fresh one, mirror the open one.
        current = indexed.get(key)
        if current is None or (current["completed"] and not entry["completed"]):
            indexed[key] = entry
    return indexed


def source_key(source: dict[str, Any]) -> str:
    """The tracking key for a ``buy_source`` mapping."""
    return part_key(str(source["asset_id"]), str(source["part_id"]))


def normalize_items(response: Any, entity_id: str) -> list[dict[str, Any]] | None:
    """Extract *entity_id*'s items from a ``todo.get_items`` response.

    Returns ``None`` when the response carries nothing for that entity, which the
    planner reads as *unknown* — a list we could not see is left strictly alone
    rather than guessed at. An entity that genuinely holds nothing answers with
    an empty list, which is a very different instruction.
    """
    if not isinstance(response, dict):
        return None
    payload = response.get(entity_id)
    if not isinstance(payload, dict):
        return None
    items = payload.get("items")
    if not isinstance(items, list):
        return None
    return [item for item in items if isinstance(item, dict)]


@dataclass(frozen=True)
class AddOp:
    """Put a new item on *entity_id* for the reminder tracked as *key*."""

    key: str
    entity_id: str
    summary: str


@dataclass(frozen=True)
class UpdateOp:
    """Tick *item* off, rename it, or both."""

    key: str
    entity_id: str
    item: str
    status: str | None = None
    rename: str | None = None


@dataclass(frozen=True)
class RemoveOp:
    """Take *item* off *entity_id* — it is not wanted any more."""

    key: str
    entity_id: str
    item: str


@dataclass(frozen=True)
class CompleteOp:
    """Complete a Home Keeper reminder because its item was ticked off."""

    key: str
    task_id: str


@dataclass(frozen=True)
class SyncPlan:
    """Everything one mirror pass wants done.

    ``tracked`` is the bookkeeping map as it will read **once every operation
    has succeeded**. Each op carries the ``key`` it belongs to so the driver can
    put an entry back when its call fails: a remove that did not happen must
    stay tracked, or the item it left behind is orphaned on the list forever
    with nothing left to remember it by. Failure is therefore always "try again
    next pass", never a compensating write.
    """

    add: list[AddOp] = field(default_factory=list)
    update: list[UpdateOp] = field(default_factory=list)
    remove: list[RemoveOp] = field(default_factory=list)
    complete: list[CompleteOp] = field(default_factory=list)
    tracked: dict[str, dict[str, Any]] = field(default_factory=dict)


def plan_sync(
    *,
    tracked: dict[str, dict[str, Any]],
    desired: dict[str, dict[str, Any]],
    items_by_entity: dict[str, list[dict[str, Any]]],
    target: str,
) -> SyncPlan:
    """Decide what to do about the mirror this pass.

    *tracked* is what we mirrored last time (``key -> {entity_id, summary,
    uid}``), *desired* is :func:`buy_tasks_by_part` over the current task map,
    *items_by_entity* holds the live contents of every list we could read, and
    *target* is the configured list (``""`` when the mirror is off).

    A list absent from *items_by_entity* could not be read — it is unavailable,
    or the integration behind it is not loaded — so nothing is planned for it and
    its bookkeeping is carried forward untouched. That is what keeps a broken
    shopping list from quietly deleting the mirror's memory of it.
    """
    plan = SyncPlan()
    # Item identities already spoken for this pass, so two parts whose reminders
    # happen to read the same can never fight over one list entry.
    claimed: set[tuple[str, str]] = set()
    # Keys pass one has finished with, which pass two must not re-add. Only the
    # reverse direction lands here: its reminder is still open (Home Keeper has
    # not completed it yet) but the shopper already ticked the item off, and
    # putting a second copy on the list would undo exactly what they just did.
    settled: set[str] = set()

    for key in sorted(set(tracked) | set(desired)):
        entry = tracked.get(key)
        if entry is None:
            continue
        entity_id = str(entry.get("entity_id") or "")
        summary = str(entry.get("summary") or "")
        want = desired.get(key)

        items = items_by_entity.get(entity_id)
        if items is None:
            plan.tracked[key] = dict(entry)
            continue

        item = resolve_tracked(
            items,
            entity_id=entity_id,
            uid=entry.get("uid"),
            summary=summary,
            claimed=claimed,
        )
        if item is None:
            # Someone deleted our item off the list. Take that as "not this one,
            # thanks" and leave it deleted — re-adding it every five minutes
            # would just be an argument. Keep the bookkeeping while the reminder
            # is open so the mirror stays quiet, and let it go when the reminder
            # does.
            if want is not None and not want["completed"]:
                plan.tracked[key] = dict(entry)
            continue

        identity = item_identity(item)
        claimed.add((entity_id, identity))

        if not item_is_open(item):
            # Ticked off. If the reminder is still open, that tick is the user
            # telling Home Keeper they bought it.
            if want is not None and not want["completed"]:
                plan.complete.append(CompleteOp(key, str(want["task_id"])))
                settled.add(key)
            continue

        if entity_id != target:
            # The target moved (or the mirror was switched off): clear the item
            # from the list it is on. Pass two puts it on the new list.
            plan.remove.append(RemoveOp(key, entity_id, identity))
            continue
        if want is None:
            # The reminder went away without anyone buying anything.
            plan.remove.append(RemoveOp(key, entity_id, identity))
            continue
        if want["completed"]:
            # Completed inside Home Keeper — tick the mirror off to match, so the
            # shopper sees it done rather than watching the line vanish.
            plan.update.append(
                UpdateOp(key, entity_id, identity, status=STATUS_COMPLETED)
            )
            continue

        name = str(want["name"])
        if item.get("summary") != name:
            # Generated reminder names are localized at write time, so the
            # household changing language renames them.
            plan.update.append(UpdateOp(key, entity_id, identity, rename=name))
        plan.tracked[key] = {
            "entity_id": entity_id,
            "summary": name,
            "uid": item.get("uid"),
        }

    if not target:
        return plan
    items = items_by_entity.get(target)
    if items is None:
        return plan
    for key in sorted(desired):
        if key in plan.tracked or key in settled:
            continue
        want = desired[key]
        if want["completed"]:
            # Never open a shopping entry for something already bought.
            continue
        name = str(want["name"])
        existing = find_open(items, entity_id=target, summary=name, claimed=claimed)
        if existing is not None:
            # Adopt a matching entry rather than stacking a duplicate on top of
            # it — the shopper may have written it themselves, or our own
            # bookkeeping may have been lost.
            claimed.add((target, item_identity(existing)))
            plan.tracked[key] = {
                "entity_id": target,
                "summary": name,
                "uid": existing.get("uid"),
            }
            continue
        plan.add.append(AddOp(key, target, name))
        # No uid: ``todo.add_item`` answers with nothing. The next pass binds one
        # by summary (see ``todo_items.resolve_tracked``), and until then the
        # summary is a perfectly good handle for ``update_item``/``remove_item``.
        plan.tracked[key] = {"entity_id": target, "summary": name, "uid": None}
    return plan


def lists_to_read(tracked: dict[str, dict[str, Any]], *, target: str) -> list[str]:
    """Every to-do list a pass must snapshot: the target plus any we still hold.

    A tracked entry names the list its item is on, so switching targets — even
    twice, even while Home Assistant was down — still leaves a trail back to
    whatever needs clearing.
    """
    entities = {
        str(entry.get("entity_id") or "")
        for entry in tracked.values()
        if entry.get("entity_id")
    }
    if target:
        entities.add(target)
    return sorted(entities)


def needs_pass(
    *,
    tracked: dict[str, dict[str, Any]],
    desired: dict[str, dict[str, Any]],
    target: str,
) -> bool:
    """Whether Home Keeper's own state has drifted from what it last mirrored.

    Reading a to-do list means a service call, and most reasons the mirror is
    poked — a completion somewhere else, a stock nudge on an unrelated part —
    change nothing it cares about. This answers "is there anything to do?" from
    the two maps alone, so a settled mirror costs nothing.

    It cannot see the shopper's side of the loop (an item ticked off on their
    phone is invisible here), so the surfaces that watch for *that* — the list's
    own state changes, and the periodic sweep — ask for a full pass regardless.
    """
    for key, entry in tracked.items():
        if str(entry.get("entity_id") or "") != target:
            return True
        want = desired.get(key)
        if want is None or want["completed"]:
            return True
        if str(want["name"]) != str(entry.get("summary") or ""):
            return True
    if target:
        for key, want in desired.items():
            if key not in tracked and not want["completed"]:
                return True
    return False
