"""Pure planning for task mirrors — profile-filtered tasks on external to-do lists.

A *task mirror* keeps an existing Home Assistant to-do list (a ``todo.*`` entity —
a Todoist project, Google Tasks, a local family list) in step with the Home Keeper
tasks a profile selects, so chores show up where the household already looks. The
mirror is two-way: completing the task in Home Keeper ticks the item off, and
ticking the item off completes the task. Several mirrors can run at once, each
pairing one profile (or the default filter) with one list.

Like ``shopping.py`` this module imports nothing from Home Assistant: it is a pure
transformation over plain dicts, so every branch of the state machine is
unit-testable without an HA runtime (see ``tests/unit/test_task_mirror.py``).
``task_mirror_sync.py`` is the Home-Assistant-aware half that reads the lists,
executes the plan, and feeds tick-offs back into the store.

The rules that shape a plan:

* **A list mirrors what its profile surfaces right now.** The profile's ``status``
  is also the mirror's timing — ``overdue`` puts a task on the list when it falls
  due, ``due_soon`` three days ahead, ``all`` as soon as it is scheduled. A task
  that stops matching (completed, rescheduled, disabled, filtered out) has its
  open item removed. Auto-buy reminders are skipped entirely: the shopping-list
  mirror owns those, and two mirrors fighting over one line helps nobody.
* **A completed item is never touched.** Whoever ticked it off, the entry stays as
  their record. When the task recurs and falls due again, a *fresh* item is added
  alongside the old one — that is the history Todoist users expect.
* **A vanished item may mean "done".** Unlike the shopping mirror, which leaves a
  deleted line deleted, a mirror whose ``vanish_as_completed`` toggle is on treats
  a tracked open item that disappeared as completed — required for providers like
  Todoist whose ``todo`` entity drops completed items instead of reporting them.
  The completion is **uid-gated**: an entry that never captured a uid has no proof
  its add ever landed, so it is re-added, never completed. With the toggle off (or
  two-way sync off) a vanished item is treated as deleted and recreated — the
  strict self-healing reading.
* **Two-way is per mirror.** With ``two_way`` off the inbound direction is inert:
  ticks and vanishes never complete tasks; a ticked item freezes its bookkeeping
  entry so the mirror does not argue with the user by re-adding the task.

Bookkeeping (persisted by the store, silently) is a flat map
``mirror_key(mirror_id, task_id) -> entry`` with entries shaped
``{"entity_id", "uid", "summary", "due", "last_completed"}``. ``last_completed``
snapshots the task's own ``last_completed`` at bind time; a live value strictly
newer means "completed inside Home Keeper since mirrored", while an undone
completion moves the value backwards and therefore reads as plain content drift.
``due`` snapshots the date we last wrote, so :func:`needs_pass` can spot a
rescheduled task without reading a single list — the content *diff* still
compares against the live item, because the list is what the household sees.
Per-mirror keying lets two mirrors hold the same task on two lists.

Content is capability-gated *here*, not in the driver: the driver passes each
entity's supported extras (:data:`CAP_DUE_DATE`, :data:`CAP_DESCRIPTION`), and the
planner neither emits nor diffs a field the list cannot hold — otherwise a list
without due dates would be told to update the same item forever.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from . import profiles
from .reconcile import buy_source
from .shopping import STATUS_COMPLETED, STATUS_NEEDS_ACTION, normalize_target
from .transitions import DUE_SOON_WINDOW

__all__ = [
    "CAP_DESCRIPTION",
    "CAP_DUE_DATE",
    "STATUS_COMPLETED",
    "STATUS_NEEDS_ACTION",
    "AddOp",
    "CompleteOp",
    "RemoveOp",
    "TaskMirrorPlan",
    "UpdateOp",
    "completed_since",
    "desired_by_mirror",
    "lists_to_read",
    "mirror_key",
    "needs_pass",
    "normalize_task_mirror",
    "normalize_task_mirrors",
    "plan_sync",
]

# Optional to-do item fields a list may or may not support, as capability tokens
# ``task_mirror_sync`` derives from the entity's ``supported_features``
# (``SET_DUE_DATE_ON_ITEM`` / ``SET_DESCRIPTION_ON_ITEM``). The planner only
# writes or compares these fields for entities whose capability set includes them.
CAP_DUE_DATE = "due"
CAP_DESCRIPTION = "description"

# Separator joining a mirror id to a task id in a bookkeeping key. Mirror ids are
# uuid hex and task ids are opaque, so the first ``:`` is unambiguous.
_KEY_SEP = ":"


def mirror_key(mirror_id: str, task_id: str) -> str:
    """The bookkeeping key for one task's item on one mirror."""
    return f"{mirror_id}{_KEY_SEP}{task_id}"


def normalize_task_mirror(raw: Any) -> dict[str, Any]:
    """Coerce one raw mirror config to its stored, fully-defaulted shape.

    Generates a stable ``id`` when absent (bookkeeping keys reference it across
    edits) and defaults every field, so forms and consumers never special-case a
    missing key. ``entity_id`` goes through :func:`shopping.normalize_target` so
    anything unusable collapses to ``""`` — the off switch — and a typo disables
    the mirror rather than half-working. ``profile_id`` is ``None`` for "the
    default filter" (every enabled, scheduled task that is due now); an empty
    string — the panel form's "cleared" value — coerces to ``None`` too.
    """
    raw = raw if isinstance(raw, dict) else {}
    profile_id = raw.get("profile_id")
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex),
        "entity_id": normalize_target(raw.get("entity_id")),
        "profile_id": str(profile_id) if profile_id not in (None, "") else None,
        "two_way": bool(raw.get("two_way", True)),
        "vanish_as_completed": bool(raw.get("vanish_as_completed", True)),
    }


def normalize_task_mirrors(raw: Any) -> list[dict[str, Any]]:
    """Coerce the stored mirror list, dropping non-dict entries."""
    if not isinstance(raw, (list, tuple)):
        return []
    return [normalize_task_mirror(m) for m in raw if isinstance(m, dict)]


@dataclass(frozen=True)
class AddOp:
    """Put a new item on *entity_id* for the task tracked as *key*.

    ``due`` and ``description`` are ``None`` when the list does not support them
    (or there is nothing to say); the driver omits absent fields from the call.
    """

    key: str
    entity_id: str
    summary: str
    due: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class UpdateOp:
    """Tick *item* off, rename it, or move its due date/description.

    ``None`` means "leave that field alone"; an empty-string ``description``
    clears one the task no longer carries.
    """

    key: str
    entity_id: str
    item: str
    status: str | None = None
    rename: str | None = None
    due: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class RemoveOp:
    """Take *item* off *entity_id* — its task is no longer mirrored there."""

    key: str
    entity_id: str
    item: str


@dataclass(frozen=True)
class CompleteOp:
    """Complete a Home Keeper task because its item was ticked off (or vanished)."""

    key: str
    task_id: str


@dataclass(frozen=True)
class TaskMirrorPlan:
    """Everything one mirror pass wants done.

    ``tracked`` is the bookkeeping map as it will read **once every operation has
    succeeded**. Each op carries the ``key`` it belongs to so the driver can put
    an entry back when its call fails: a remove that did not happen must stay
    tracked, or the item it left behind is orphaned on the list forever. Failure
    is therefore always "try again next pass", never a compensating write.
    """

    add: list[AddOp] = field(default_factory=list)
    update: list[UpdateOp] = field(default_factory=list)
    remove: list[RemoveOp] = field(default_factory=list)
    complete: list[CompleteOp] = field(default_factory=list)
    tracked: dict[str, dict[str, Any]] = field(default_factory=dict)


def completed_since(snapshot: str | None, last_completed: str | None) -> bool:
    """Whether *last_completed* records a completion made since *snapshot* was taken.

    The two are compared as instants rather than as text: the same moment can be
    written several ways (a ``Z`` suffix, a different offset, a trailing
    microsecond), and ordering the strings would read a change of spelling as a
    completion. A missing snapshot is older than any completion — that is a task
    bound to a mirror before it had ever been done.

    Undoing a completion moves ``last_completed`` backwards, or clears it
    entirely, and that is deliberately *not* a completion: the item stays open
    and the task simply reads as content drift on the next pass. Anything
    unparsable answers "no" for the same reason — inventing a completion ticks
    off an item nobody finished, while missing one costs only an update.
    """
    if last_completed is None:
        return False
    try:
        current = datetime.fromisoformat(last_completed)
        if not snapshot:
            return True
        return current > datetime.fromisoformat(snapshot)
    except (TypeError, ValueError):
        return False


def desired_by_mirror(
    mirrors: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    profiles_list: list[dict[str, Any]],
    *,
    now: datetime,
    window: timedelta = DUE_SOON_WINDOW,
) -> dict[str, dict[str, dict[str, Any]]]:
    """What every mirror wants on its list: ``mirror_id -> task_id -> want``.

    *tasks* arrive **already enriched**: the driver resolves each task's
    effective labels, area and device (the ones it inherits from its device or
    area) before calling, so the profile matcher here selects exactly the tasks
    the panel and the card show for that same profile.

    A mirror with no list configured is off, so it is skipped. A mirror naming a
    profile that no longer exists is *misconfigured* rather than empty, and is
    left out of the result entirely — an empty selection would read as "clear
    this list", and deleting a profile must not wipe the list it was feeding.
    Without a profile a mirror gets the default filter, which is every enabled,
    scheduled task that is due now.

    Auto-buy reminders are skipped whatever a profile says: the shopping-list
    mirror owns those, and two mirrors fighting over one line helps nobody. A
    nameless task is skipped too — an empty summary is not something a to-do list
    can hold. The ``due`` a want carries is date-only, because that is the
    granularity a to-do list works in and a time would leave the item drifting.
    """
    wanted: dict[str, dict[str, dict[str, Any]]] = {}
    for mirror in mirrors:
        if not str(mirror["entity_id"]):
            continue
        profile_id = mirror.get("profile_id")
        if profile_id is None:
            filt = profiles.normalize_filter({})
        else:
            profile = profiles.resolve_profile(profiles_list, str(profile_id))
            if profile is None:
                continue
            filt = profiles.normalize_filter(profile.get("filter"))
        wants: dict[str, dict[str, Any]] = {}
        for task in tasks:
            if not profiles.matches_filter(task, filt, now=now, window=window):
                continue
            if buy_source(task) is not None:
                continue
            name = str(task.get("name") or "").strip()
            if not name:
                continue
            # matches_filter has already guaranteed a next_due.
            due = datetime.fromisoformat(task["next_due"]).date().isoformat()
            wants[str(task["id"])] = {
                "task_id": str(task["id"]),
                "name": name,
                "due": due,
                "notes": str(task.get("notes") or ""),
                "last_completed": task.get("last_completed"),
            }
        wanted[str(mirror["id"])] = wants
    return wanted


# The four resolution helpers below read like ``shopping.py``'s, and are kept
# separate on purpose: the two planners ask a list different questions — the
# shopping mirror holds one line per part and leaves a deleted one deleted, a
# task mirror holds one per task *per mirror* and may read a vanished line as
# done — so sharing them would tie one state machine to the other's.
def _identity(item: dict[str, Any]) -> str:
    """How a to-do item is addressed in a service call.

    ``todo.update_item`` / ``todo.remove_item`` accept either the item's uid or
    its summary, so a list that does not hand out uids is still addressable.
    """
    uid = item.get("uid")
    if isinstance(uid, str) and uid:
        return uid
    return str(item.get("summary") or "")


def _is_open(item: dict[str, Any]) -> bool:
    """True unless the item has been ticked off."""
    return item.get("status") != STATUS_COMPLETED


def _resolve(
    items: list[dict[str, Any]],
    *,
    entity_id: str,
    uid: Any,
    summary: str,
    claimed: set[tuple[str, str]],
) -> dict[str, Any] | None:
    """Find the live item a tracked entry points at.

    The uid is authoritative when we captured one. Otherwise we fall back to the
    summary — that is how a freshly added item is picked up on the next pass
    (``todo.add_item`` returns nothing, so there is no uid to record at the
    time), and how a mirror re-attaches to its own items if the bookkeeping is
    ever lost. An open item wins over a ticked-off one with the same text.
    """
    if isinstance(uid, str) and uid:
        for item in items:
            if item.get("uid") == uid and (entity_id, _identity(item)) not in claimed:
                return item
    by_summary = [
        item
        for item in items
        if item.get("summary") == summary
        and (entity_id, _identity(item)) not in claimed
    ]
    for item in by_summary:
        if _is_open(item):
            return item
    return by_summary[0] if by_summary else None


def _find_open(
    items: list[dict[str, Any]],
    *,
    entity_id: str,
    summary: str,
    claimed: set[tuple[str, str]],
) -> dict[str, Any] | None:
    """An un-ticked item already reading *summary*, if the list has one."""
    for item in items:
        if (
            _is_open(item)
            and item.get("summary") == summary
            and (entity_id, _identity(item)) not in claimed
        ):
            return item
    return None


def _entry(entity_id: str, item_uid: Any, want: dict[str, Any]) -> dict[str, Any]:
    """The bookkeeping entry binding *want* to the item now holding it."""
    return {
        "entity_id": entity_id,
        "uid": item_uid,
        "summary": str(want["name"]),
        "due": str(want["due"]),
        "last_completed": want["last_completed"],
    }


def plan_sync(
    *,
    mirrors: list[dict[str, Any]],
    tracked: dict[str, dict[str, Any]],
    desired: dict[str, dict[str, dict[str, Any]]],
    items_by_entity: dict[str, list[dict[str, Any]]],
    capabilities: dict[str, frozenset[str]],
) -> TaskMirrorPlan:
    """Decide what every mirror wants done this pass.

    *tracked* is what we mirrored last time, *desired* is
    :func:`desired_by_mirror` over the current tasks, *items_by_entity* holds the
    live contents of every list we could read, and *capabilities* says which
    optional fields each list can actually hold.

    A list absent from *items_by_entity* could not be read — it is unavailable,
    or the integration behind it is not loaded — so nothing is planned for it and
    its bookkeeping is carried forward untouched. An unreadable list is not an
    empty one, and that distinction is what stops a broken to-do integration from
    quietly deleting a mirror's memory of what it put there.

    A mirror whose id is missing from *desired* is misconfigured (its profile was
    deleted), and is treated the same way: bookkeeping forward, hands off. Only a
    mirror the user actually turned off gets its items cleared.

    The claim set and the settled set span the **whole** plan rather than one
    mirror, because two mirrors can point at one list: without that, both would
    resolve to the same line and each would undo the other's work.
    """
    plan = TaskMirrorPlan()
    by_id = {str(mirror["id"]): mirror for mirror in mirrors}
    # Item identities already spoken for this pass, so two tasks that read the
    # same — or two mirrors on one list — can never fight over one line.
    claimed: set[tuple[str, str]] = set()
    # Keys pass one has finished with, which pass two must not put back on the
    # list. Only inbound completions land here: the household ticked the item off
    # and a second copy would undo exactly what they just did.
    settled: set[str] = set()

    for key in sorted(tracked):
        entry = tracked[key]
        mirror_id, _, task_id = key.partition(_KEY_SEP)
        entity_id = str(entry.get("entity_id") or "")
        summary = str(entry.get("summary") or "")
        mirror = by_id.get(mirror_id)
        items = items_by_entity.get(entity_id)

        if mirror is None or not str(mirror["entity_id"]):
            # The mirror was deleted, or its list was cleared. Turning a mirror
            # off clears what it wrote — leaving the chores behind would strand
            # them somewhere nothing updates them any more.
            if items is None:
                plan.tracked[key] = dict(entry)
                continue
            item = _resolve(
                items,
                entity_id=entity_id,
                uid=entry.get("uid"),
                summary=summary,
                claimed=claimed,
            )
            if item is not None:
                claimed.add((entity_id, _identity(item)))
                if _is_open(item):
                    plan.remove.append(RemoveOp(key, entity_id, _identity(item)))
            continue

        wants = desired.get(mirror_id)
        if wants is None:
            # Misconfigured: the profile it names is gone. Hold everything until
            # someone points it at a profile that exists.
            plan.tracked[key] = dict(entry)
            continue

        target = str(mirror["entity_id"])
        want = wants.get(task_id)
        if items is None:
            plan.tracked[key] = dict(entry)
            continue

        item = _resolve(
            items,
            entity_id=entity_id,
            uid=entry.get("uid"),
            summary=summary,
            claimed=claimed,
        )
        if item is None:
            # The item is not on the list any more. Providers like Todoist drop a
            # completed item rather than reporting it, so for a mirror that opted
            # in this is how a tick reaches Home Keeper at all. It is uid-gated:
            # an entry that never captured one has no proof its add ever landed,
            # and completing a task on the strength of a write we cannot confirm
            # is the one mistake there is no undo for.
            if want is None:
                continue
            if entry.get("uid") and mirror["two_way"] and mirror["vanish_as_completed"]:
                plan.complete.append(CompleteOp(key, task_id))
                settled.add(key)
            continue

        identity = _identity(item)
        claimed.add((entity_id, identity))

        if not _is_open(item):
            # Ticked off on the list. If Home Keeper has not recorded that
            # completion itself, the tick is the household telling it so.
            if want is not None and not completed_since(
                entry.get("last_completed"), want["last_completed"]
            ):
                if mirror["two_way"]:
                    plan.complete.append(CompleteOp(key, task_id))
                    settled.add(key)
                else:
                    # Inbound is inert, so the tick means nothing to Home Keeper —
                    # but freezing the entry keeps pass two from putting the chore
                    # straight back and arguing with whoever ticked it.
                    plan.tracked[key] = dict(entry)
            continue

        if want is None:
            plan.remove.append(RemoveOp(key, entity_id, identity))
            continue
        if completed_since(entry.get("last_completed"), want["last_completed"]):
            # Completed inside Home Keeper since we bound this item: tick it off
            # so the household sees it done rather than watching the line vanish.
            # The key is not settled — a recurring task that is due again gets a
            # *fresh* item in this same pass, alongside the one just ticked off,
            # which is the history a to-do list is for.
            plan.update.append(
                UpdateOp(key, entity_id, identity, status=STATUS_COMPLETED)
            )
            continue
        if entity_id != target:
            # The mirror was pointed at a different list. Clear the old line;
            # pass two puts the chore on the new one.
            plan.remove.append(RemoveOp(key, entity_id, identity))
            continue

        caps = capabilities.get(entity_id, frozenset())
        name = str(want["name"])
        rename = name if item.get("summary") != name else None
        due = None
        if CAP_DUE_DATE in caps and str(item.get("due") or "")[:10] != str(want["due"]):
            # A list that cannot hold a due date is never told one: comparing a
            # field it drops would rewrite the same item on every pass forever.
            due = str(want["due"])
        notes = str(want["notes"])
        description = None
        if CAP_DESCRIPTION in caps and str(item.get("description") or "") != notes:
            # "" clears a description the task no longer carries.
            description = notes
        if rename is not None or due is not None or description is not None:
            plan.update.append(
                UpdateOp(
                    key,
                    entity_id,
                    identity,
                    rename=rename,
                    due=due,
                    description=description,
                )
            )
        plan.tracked[key] = _entry(entity_id, item.get("uid") or entry.get("uid"), want)

    for mirror_id in sorted(desired):
        mirror = by_id.get(mirror_id)
        if mirror is None:
            continue
        target = str(mirror["entity_id"])
        items = items_by_entity.get(target)
        if not target or items is None:
            continue
        caps = capabilities.get(target, frozenset())
        wants = desired[mirror_id]
        for task_id in sorted(wants):
            key = mirror_key(mirror_id, task_id)
            if key in plan.tracked or key in settled:
                continue
            want = wants[task_id]
            name = str(want["name"])
            existing = _find_open(
                items, entity_id=target, summary=name, claimed=claimed
            )
            if existing is not None:
                # Adopt a matching line rather than stacking a duplicate on top
                # of it — someone may have written it themselves, or our own
                # bookkeeping may have been lost.
                claimed.add((target, _identity(existing)))
                plan.tracked[key] = _entry(target, existing.get("uid"), want)
                continue
            notes = str(want["notes"])
            plan.add.append(
                AddOp(
                    key,
                    target,
                    name,
                    due=str(want["due"]) if CAP_DUE_DATE in caps else None,
                    description=notes if CAP_DESCRIPTION in caps and notes else None,
                )
            )
            # No uid: ``todo.add_item`` answers with nothing. The next pass binds
            # one by summary (see :func:`_resolve`), and until then the summary is
            # a perfectly good handle for ``update_item``/``remove_item``.
            plan.tracked[key] = _entry(target, None, want)
    return plan


def lists_to_read(
    tracked: dict[str, dict[str, Any]], mirrors: list[dict[str, Any]]
) -> list[str]:
    """Every to-do list a pass must snapshot: each mirror's, plus any we hold.

    A tracked entry names the list its item is on, so switching a mirror's target
    — even twice, even while Home Assistant was down — still leaves a trail back
    to whatever needs clearing.
    """
    entities = {str(mirror["entity_id"]) for mirror in mirrors}
    entities |= {str(entry.get("entity_id") or "") for entry in tracked.values()}
    entities.discard("")
    return sorted(entities)


def needs_pass(
    *,
    tracked: dict[str, dict[str, Any]],
    desired: dict[str, dict[str, dict[str, Any]]],
    mirrors: list[dict[str, Any]],
) -> bool:
    """Whether Home Keeper's own state has drifted from what it last mirrored.

    Reading a to-do list means a service call per list, and most of what pokes
    the mirrors — a completion on an unrelated task, an options save that touched
    something else — changes nothing they care about. This answers "is there
    anything to do?" from the bookkeeping and the wanted map alone, so settled
    mirrors cost nothing.

    It cannot see the household's side of the loop (an item ticked off on someone's
    phone is invisible here), so the surfaces that watch for *that* — the lists'
    own state changes, and the periodic sweep — ask for a full pass regardless.
    """
    by_id = {str(mirror["id"]): mirror for mirror in mirrors}
    for key, entry in tracked.items():
        mirror_id, _, task_id = key.partition(_KEY_SEP)
        mirror = by_id.get(mirror_id)
        if mirror is None or not str(mirror["entity_id"]):
            return True
        wants = desired.get(mirror_id)
        if wants is None:
            # Misconfigured mirrors are held, not planned, so they never drift.
            continue
        want = wants.get(task_id)
        if want is None:
            return True
        if str(entry.get("entity_id") or "") != str(mirror["entity_id"]):
            return True
        if str(want["name"]) != str(entry.get("summary") or ""):
            return True
        if str(want["due"]) != str(entry.get("due") or ""):
            return True
        if completed_since(entry.get("last_completed"), want["last_completed"]):
            return True
    for mirror_id, wants in desired.items():
        for task_id in wants:
            if mirror_key(mirror_id, task_id) not in tracked:
                return True
    return False
