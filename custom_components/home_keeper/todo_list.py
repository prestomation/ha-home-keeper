"""Pure planning for to-do list sync — profile-filtered tasks on external to-do lists.

A *to-do list sync* keeps an existing Home Assistant to-do list (a ``todo.*`` entity —
a Todoist project, Google Tasks, a local family list) in step with the Home Keeper
tasks a profile selects, so chores show up where the household already looks. The
sync is two-way: completing the task in Home Keeper ticks the item off, and
ticking the item off completes the task.

**A sync is a profile.** There is no separate sync record: a profile carries a
``sync`` block (``profiles.normalize_sync``) naming the one list it syncs onto,
and clearing that ``entity_id`` is both the off switch and the delete. One list per
profile, at most — a household that wants two lists writes two profiles, which it
needed anyway to say what goes on each. So every sync has a real filter behind it
and none can name a profile that is gone.

Like ``shopping.py`` this module imports nothing from Home Assistant: it is a pure
transformation over plain dicts, so every branch of the state machine is
unit-testable without an HA runtime (see ``tests/unit/test_todo_list.py``).
``todo_list_sync.py`` is the Home-Assistant-aware half that reads the lists,
executes the plan, and feeds tick-offs back into the store.

The rules that shape a plan:

* **A list carries what its profile surfaces right now.** The profile's ``status``
  is also the sync's timing — ``overdue`` puts a task on the list when it falls
  due, ``due_soon`` three days ahead, ``all`` as soon as it is scheduled. A task
  that stops matching (completed, rescheduled, disabled, filtered out) has its
  open item removed. Two kinds are skipped whatever the profile says, because a
  sync is a *delivery* surface and decides for itself what belongs on a to-do
  list (the split ``profiles.matches_filter`` documents): auto-buy reminders,
  which the shopping-list sync owns and would otherwise fight over one line,
  and **completion-blocked** tasks — today a synced ``problem`` sensor, which
  belongs in a Profile but not on a list, since only the integration that owns
  the sensor can decide it is fixed. An item nobody can ever tick off is worse
  than no item, the same call ``notifications.actions_for`` makes about buttons.
* **A completed item is never touched.** Whoever ticked it off, the entry stays as
  their record. When the task recurs and falls due again, a *fresh* item is added
  alongside the old one — that is the history Todoist users expect.
* **A vanished item may mean "done".** Unlike the shopping-list sync, which leaves a
  deleted line deleted, a sync whose ``vanish_as_completed`` toggle is on treats
  a tracked open item that disappeared as completed — required for providers like
  Todoist whose ``todo`` entity drops completed items instead of reporting them.
  The completion is **uid-gated**: an entry that never captured a uid has no proof
  its add ever landed, so it is held (see below) and eventually re-added, never
  completed. With the toggle off (or two-way sync off) a vanished item is treated
  as deleted and recreated — the strict self-healing reading.
* **A write's own outcome outranks a later read of the list.** ``todo.add_item``
  answers with nothing, so a fresh entry carries no uid and is matched by summary on
  a later pass. Some lists do not make an added item readable straight away — Home
  Assistant's CalDAV entity refreshes its cached items in a fire-and-forget task,
  where ``local_todo`` and Todoist both await theirs — so "I cannot see it" is *not*
  proof the add failed. Reading it that way added the item a second time, and the
  duplicate was permanent: the bookkeeping points at one copy, so every later edit
  moved only that one and deleting the task orphaned the other. An unconfirmed entry
  is therefore **held** rather than re-added, for :data:`UNCONFIRMED_GRACE` — long
  enough to clear the slowest provider's visibility lag, after which a genuinely lost
  add is repaired rather than leaving the task with no item for good.
* **Two-way is per profile.** With ``two_way`` off the inbound direction is inert:
  ticks and vanishes never complete tasks; a ticked item freezes its bookkeeping
  entry so the sync does not argue with the user by re-adding the task.

Bookkeeping (persisted by the store, silently) is a flat map
``sync_key(profile_id, task_id) -> entry`` with entries shaped
``{"entity_id", "uid", "summary", "due", "last_completed", "added_at"}``.
``added_at`` stamps when an item was added but not yet seen on the list, and is
dropped the moment one is resolved; it is what bounds the hold described above.
``last_completed``
snapshots the task's own ``last_completed`` at bind time; a live value strictly
newer means "completed inside Home Keeper since it was synced", while an undone
completion moves the value backwards and therefore reads as plain content drift.
``due`` snapshots the date we last wrote, so :func:`needs_pass` can spot a
rescheduled task without reading a single list — the content *diff* still
compares against the live item, because the list is what the household sees.
Per-profile keying lets two profiles hold the same task on two lists.

Content is capability-gated *here*, not in the driver: the driver passes each
entity's supported extras (:data:`CAP_DUE_DATE`, :data:`CAP_DESCRIPTION`), and the
planner neither emits nor diffs a field the list cannot hold — otherwise a list
without due dates would be told to update the same item forever.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from . import profiles
from .notifications import is_completion_blocked
from .reconcile import buy_source
from .todo_items import (
    STATUS_COMPLETED,
    STATUS_NEEDS_ACTION,
    find_open,
    item_identity,
    item_is_open,
    resolve_tracked,
)
from .transitions import DUE_SOON_WINDOW

__all__ = [
    "CAP_DESCRIPTION",
    "CAP_DUE_DATE",
    "STATUS_COMPLETED",
    "STATUS_NEEDS_ACTION",
    "AddOp",
    "CompleteOp",
    "RemoveOp",
    "TodoListPlan",
    "UpdateOp",
    "completed_since",
    "desired_by_sync",
    "lists_to_read",
    "needs_pass",
    "plan_sync",
    "sync_key",
]

# Optional to-do item fields a list may or may not support, as capability tokens
# ``todo_list_sync`` derives from the entity's ``supported_features``
# (``SET_DUE_DATE_ON_ITEM`` / ``SET_DESCRIPTION_ON_ITEM``). The planner only
# writes or compares these fields for entities whose capability set includes them.
CAP_DUE_DATE = "due"
CAP_DESCRIPTION = "description"

# How long an entry whose add we could not confirm is held before it is re-added.
# It is a *staleness budget*, not a formula: it has to comfortably clear the slowest
# provider's visibility lag, and the slowest known is Home Assistant's CalDAV entity,
# which polls every 15 minutes. A grace below that could fire before the provider had
# any chance to show the item, recreating the duplicate this exists to prevent.
#
# Wall clock rather than a count of passes, deliberately: ``TodoSyncDriver`` runs up
# to four passes back to back with no delay between them, so "unseen for two passes"
# can elapse in milliseconds — entirely inside the window we are waiting out.
UNCONFIRMED_GRACE = timedelta(minutes=20)

# Separator joining a profile id to a task id in a bookkeeping key. Profile ids are
# uuid hex and task ids are opaque, so the first ``:`` is unambiguous.
_KEY_SEP = ":"


def sync_key(profile_id: str, task_id: str) -> str:
    """The bookkeeping key for one task's item on one profile's list."""
    return f"{profile_id}{_KEY_SEP}{task_id}"


def _target(profile: dict[str, Any]) -> str:
    """The list *profile* syncs to — ``""`` when its sync is switched off."""
    return str(profile["sync"]["entity_id"])


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
    """Take *item* off *entity_id* — its task is no longer synced there."""

    key: str
    entity_id: str
    item: str


@dataclass(frozen=True)
class CompleteOp:
    """Complete a Home Keeper task because its item was ticked off (or vanished)."""

    key: str
    task_id: str


@dataclass(frozen=True)
class TodoListPlan:
    """Everything one sync pass wants done.

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
    bound to a sync before it had ever been done.

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


def desired_by_sync(
    synced: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    *,
    now: datetime,
    window: timedelta = DUE_SOON_WINDOW,
) -> dict[str, dict[str, dict[str, Any]]]:
    """What every sync wants on its list: ``profile_id -> task_id -> want``.

    *synced* are the profiles themselves, each carrying the ``sync`` block that
    says which list it syncs onto; one with no list is switched off and is
    skipped, so the result names exactly the profiles that are syncing.

    *tasks* arrive **already enriched**: the driver resolves each task's
    effective labels, area and device (the ones it inherits from its device or
    area) before calling, so the profile matcher here selects exactly the tasks
    the panel and the card show for that same profile.

    Auto-buy reminders are skipped whatever a profile says: the shopping-list
    sync owns those, and two syncs fighting over one line helps nobody. A
    nameless task is skipped too — an empty summary is not something a to-do list
    can hold. The ``due`` a want carries is date-only, because that is the
    granularity a to-do list works in and a time would leave the item drifting.
    """
    wanted: dict[str, dict[str, dict[str, Any]]] = {}
    for profile in synced:
        if not _target(profile):
            continue
        filt = profiles.normalize_filter(profile.get("filter"))
        wants: dict[str, dict[str, Any]] = {}
        for task in tasks:
            if not profiles.matches_filter(task, filt, now=now, window=window):
                continue
            if buy_source(task) is not None:
                continue
            if is_completion_blocked(task):
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
        wanted[str(profile["id"])] = wants
    return wanted


def _entry(
    entity_id: str,
    item_uid: Any,
    want: dict[str, Any],
    *,
    added_at: str | None = None,
) -> dict[str, Any]:
    """The bookkeeping entry binding *want* to the item now holding it.

    *added_at* is set only where we have added an item we have not seen back yet, so
    resolving one against the live list clears it by simply not passing it on.
    """
    return {
        "entity_id": entity_id,
        "uid": item_uid,
        "summary": str(want["name"]),
        "due": str(want["due"]),
        "last_completed": want["last_completed"],
        "added_at": added_at,
    }


def _added_stamp(entry: dict[str, Any], *, now: datetime) -> str:
    """The stamp to hold *entry* under, replacing one that cannot be trusted.

    Re-stamping rather than keeping whatever is there matters because the hold is
    open-ended until the stamp ages out: a value that is unparsable, or in the
    future because the clock jumped backwards before NTP corrected it, would never
    age out at all. That turns "hold, never duplicate" into "hold, never deliver" —
    a silent, permanent absence, which is the failure this whole path exists to
    avoid, only pointing the other way.
    """
    stamped = entry.get("added_at")
    try:
        if stamped and datetime.fromisoformat(str(stamped)) <= now:
            return str(stamped)
    except (TypeError, ValueError):
        pass
    return now.isoformat()


def _add_unconfirmed(
    entry: dict[str, Any],
    *,
    now: datetime,
    grace: timedelta = UNCONFIRMED_GRACE,
) -> bool:
    """Whether a uid-less entry we cannot resolve should be added again.

    "I cannot see it" is not proof the add failed — see the module docstring — so
    the answer is normally no, and both unreadable cases answer no as well: a
    missing stamp starts the clock this pass, and an unparsable one is not evidence
    of anything. The safe direction is always the one that cannot duplicate, which
    is the same call :func:`completed_since` makes about an unparsable timestamp.
    """
    stamped = entry.get("added_at")
    if not stamped:
        return False
    try:
        return now - datetime.fromisoformat(str(stamped)) > grace
    except (TypeError, ValueError):
        return False


def plan_sync(
    *,
    synced: list[dict[str, Any]],
    tracked: dict[str, dict[str, Any]],
    desired: dict[str, dict[str, dict[str, Any]]],
    items_by_entity: dict[str, list[dict[str, Any]]],
    capabilities: dict[str, frozenset[str]],
    now: datetime,
) -> TodoListPlan:
    """Decide what every sync wants done this pass.

    *synced* are the profiles, *tracked* is what we wrote last time, *desired*
    is :func:`desired_by_sync` over the current tasks, *items_by_entity* holds
    the live contents of every list we could read, and *capabilities* says which
    optional fields each list can actually hold.

    A list absent from *items_by_entity* could not be read — it is unavailable,
    or the integration behind it is not loaded — so nothing is planned for it and
    its bookkeeping is carried forward untouched. An unreadable list is not an
    empty one, and that distinction is what stops a broken to-do integration from
    quietly deleting a sync's memory of what it put there.

    A profile that was deleted, or whose list was cleared, does get its items
    taken back off: with the sync living inside the profile those are the same
    gesture, and either way nothing would keep those lines in step again.

    The claim set and the settled set span the **whole** plan rather than one
    profile, because two profiles can point at one list: without that, both would
    resolve to the same line and each would undo the other's work.
    """
    plan = TodoListPlan()
    by_id = {str(profile["id"]): profile for profile in synced}
    # Item identities already spoken for this pass, so two tasks that read the
    # same — or two syncs on one list — can never fight over one line.
    claimed: set[tuple[str, str]] = set()
    # Keys pass one has finished with, which pass two must not put back on the
    # list. Only inbound completions land here: the household ticked the item off
    # and a second copy would undo exactly what they just did.
    settled: set[str] = set()

    for key in sorted(tracked):
        entry = tracked[key]
        profile_id, _, task_id = key.partition(_KEY_SEP)
        entity_id = str(entry.get("entity_id") or "")
        summary = str(entry.get("summary") or "")
        profile = by_id.get(profile_id)
        items = items_by_entity.get(entity_id)

        if profile is None or not _target(profile):
            # The profile was deleted, or its list was cleared. Turning a sync
            # off clears what it wrote — leaving the chores behind would strand
            # them somewhere nothing updates them any more.
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
            if item is not None:
                claimed.add((entity_id, item_identity(item)))
                if item_is_open(item):
                    plan.remove.append(RemoveOp(key, entity_id, item_identity(item)))
            continue

        target = _target(profile)
        # A profile still syncing is always in *desired* — it is its own filter,
        # so there is nothing left for it to fail to resolve.
        want = desired[profile_id].get(task_id)
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
            # The item is not on the list any more. Providers like Todoist drop a
            # completed item rather than reporting it, so for a sync that opted
            # in this is how a tick reaches Home Keeper at all. It is uid-gated:
            # an entry that never captured one has no proof its add ever landed,
            # and completing a task on the strength of a write we cannot confirm
            # is the one mistake there is no undo for.
            if want is None:
                continue
            if entry.get("uid"):
                sync = profile["sync"]
                if sync["two_way"] and sync["vanish_as_completed"]:
                    plan.complete.append(CompleteOp(key, task_id))
                    settled.add(key)
                continue
            if _add_unconfirmed(entry, now=now):
                # The hold is up. Whatever happened to that add, waiting longer
                # will not tell us, and a task with no item is worse than a
                # second one — fall through so pass two puts a fresh line on.
                continue
            # Added, not seen back yet. The add call already answered whether it
            # landed; a list that cannot show it yet does not overrule that.
            # Holding the key here is the whole mechanism — pass two skips a key
            # already in ``tracked`` — and the entry is carried over *verbatim*
            # because for a uid-less entry the summary is the handle: it has to
            # keep saying what we wrote, not what we now want, or a task renamed
            # while its item was invisible would never match it again.
            held = dict(entry)
            held["added_at"] = _added_stamp(entry, now=now)
            plan.tracked[key] = held
            continue

        identity = item_identity(item)
        claimed.add((entity_id, identity))

        if not item_is_open(item):
            # Ticked off on the list. If Home Keeper has not recorded that
            # completion itself, the tick is the household telling it so.
            if want is not None and not completed_since(
                entry.get("last_completed"), want["last_completed"]
            ):
                if entry.get("added_at") and not _add_unconfirmed(entry, now=now):
                    # An add we have not confirmed, resolving to a *ticked-off*
                    # line: on a list that keeps completed items this is the
                    # predecessor we ticked off ourselves last cycle, matched by
                    # summary because our new item is not readable yet. Reading it
                    # as the household's tick completes the task a second time and
                    # strands the new item for good. Wait for a list that can show
                    # it — an open item wins over a ticked one the moment it can.
                    plan.tracked[key] = dict(entry)
                    continue
                if profile["sync"]["two_way"]:
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
            # The sync was pointed at a different list. Clear the old line;
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

    for profile_id in sorted(desired):
        profile = by_id.get(profile_id)
        if profile is None:
            continue
        target = _target(profile)
        items = items_by_entity.get(target)
        if items is None:
            continue
        caps = capabilities.get(target, frozenset())
        wants = desired[profile_id]
        for task_id in sorted(wants):
            key = sync_key(profile_id, task_id)
            if key in plan.tracked or key in settled:
                continue
            want = wants[task_id]
            name = str(want["name"])
            existing = find_open(items, entity_id=target, summary=name, claimed=claimed)
            if existing is not None:
                # Adopt a matching line rather than stacking a duplicate on top
                # of it — someone may have written it themselves, or our own
                # bookkeeping may have been lost.
                claimed.add((target, item_identity(existing)))
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
            # one by summary (see ``todo_items.resolve_tracked``), and until then
            # the summary is a perfectly good handle for
            # ``update_item``/``remove_item``. The stamp starts the hold that keeps
            # a list too slow to show the new item from earning a second one.
            plan.tracked[key] = _entry(target, None, want, added_at=now.isoformat())
    return plan


def lists_to_read(
    tracked: dict[str, dict[str, Any]], synced: list[dict[str, Any]]
) -> list[str]:
    """Every to-do list a pass must snapshot: each sync's, plus any we hold.

    A tracked entry names the list its item is on, so switching a profile's target
    — even twice, even while Home Assistant was down — still leaves a trail back
    to whatever needs clearing.
    """
    entities = {_target(profile) for profile in synced}
    entities |= {str(entry.get("entity_id") or "") for entry in tracked.values()}
    entities.discard("")
    return sorted(entities)


def needs_pass(
    *,
    tracked: dict[str, dict[str, Any]],
    desired: dict[str, dict[str, dict[str, Any]]],
    synced: list[dict[str, Any]],
) -> bool:
    """Whether Home Keeper's own state has drifted from what it last synced.

    Reading a to-do list means a service call per list, and most of what pokes
    the syncs — a completion on an unrelated task, an options save that touched
    something else — changes nothing they care about. This answers "is there
    anything to do?" from the bookkeeping and the wanted map alone, so settled
    syncs cost nothing.

    It cannot see the household's side of the loop (an item ticked off on someone's
    phone is invisible here), so the surfaces that watch for *that* — the lists'
    own state changes, and the periodic sweep — ask for a full pass regardless.
    """
    by_id = {str(profile["id"]): profile for profile in synced}
    for key, entry in tracked.items():
        profile_id, _, task_id = key.partition(_KEY_SEP)
        profile = by_id.get(profile_id)
        if profile is None or not _target(profile):
            return True
        want = desired[profile_id].get(task_id)
        if want is None:
            return True
        if str(entry.get("entity_id") or "") != _target(profile):
            return True
        if str(want["name"]) != str(entry.get("summary") or ""):
            return True
        if str(want["due"]) != str(entry.get("due") or ""):
            return True
        if completed_since(entry.get("last_completed"), want["last_completed"]):
            return True
    for profile_id, wants in desired.items():
        for task_id in wants:
            if sync_key(profile_id, task_id) not in tracked:
                return True
    return False
