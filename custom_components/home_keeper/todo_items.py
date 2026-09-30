"""Item matching shared by the two to-do list syncs.

``shopping.py`` and ``todo_list.py`` plan against the same thing — somebody
else's ``todo.*`` list, read back over ``todo.get_items`` as plain dicts — and
both have to answer the same questions about it before either state machine gets
a look in: how is this item addressed in a service call, has it been ticked off,
which live item is the one a bookkeeping entry points at, and is there already an
open item reading like this? Those are facts about a to-do list rather than about
either sync, so they live here once and the planners keep only what genuinely
differs between them — what a *vanished* line means, what a key is, when a line
is wanted at all.

Pure like the planners it serves: nothing here imports Home Assistant, so every
branch is unit-testable without an HA runtime (see
``tests/unit/test_todo_items.py``).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

__all__ = [
    "CAP_DESCRIPTION",
    "CAP_DUE_DATE",
    "STATUS_COMPLETED",
    "STATUS_NEEDS_ACTION",
    "UNCONFIRMED_GRACE",
    "add_unconfirmed",
    "added_stamp",
    "find_open",
    "item_identity",
    "item_is_open",
    "resolve_tracked",
]

# ``TodoItemStatus`` values, as the ``todo.get_items`` response spells them.
STATUS_NEEDS_ACTION = "needs_action"
STATUS_COMPLETED = "completed"

# Optional to-do item fields a list may or may not support, as capability tokens
# the sync drivers derive from the entity's ``supported_features``
# (``SET_DUE_DATE_ON_ITEM`` / ``SET_DESCRIPTION_ON_ITEM``). A planner only writes or
# compares these fields for entities whose capability set includes them: a list that
# drops a field would otherwise be rewritten on every pass, forever.
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
#
# What comes back to look once it expires is each sync's periodic sweep (every
# ``coordinator.SCAN_INTERVAL``), because a grace running out is neither a store
# mutation nor a list state change and so wakes nothing by itself. That sweep has to
# stay unconditional for this to repair at all; its docstring says so.
UNCONFIRMED_GRACE = timedelta(minutes=20)


def item_identity(item: dict[str, Any]) -> str:
    """How a to-do item is addressed in a service call.

    ``todo.update_item`` / ``todo.remove_item`` accept either the item's uid or
    its summary, so a list that does not hand out uids is still addressable.
    """
    uid = item.get("uid")
    if isinstance(uid, str) and uid:
        return uid
    return str(item.get("summary") or "")


def item_is_open(item: dict[str, Any]) -> bool:
    """True unless the item has been ticked off."""
    return item.get("status") != STATUS_COMPLETED


def resolve_tracked(
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
    time), and how a sync re-attaches to its own items if the bookkeeping is
    ever lost. An open item wins over a ticked-off one with the same text.

    When we captured a uid and no live item carries it, only an *open* item with
    the same text can take its place: the list recreated our line under a new uid.
    A ticked-off item with the same text is some earlier record, never ours, and
    reading it as our line turns a deleted item into a completed task (B09-1).
    """
    bound = isinstance(uid, str) and bool(uid)
    if bound:
        for item in items:
            claim = (entity_id, item_identity(item))
            if item.get("uid") == uid and claim not in claimed:
                return item
    by_summary = [
        item
        for item in items
        if item.get("summary") == summary
        and (entity_id, item_identity(item)) not in claimed
    ]
    for item in by_summary:
        if item_is_open(item):
            return item
    if bound:
        return None
    return by_summary[0] if by_summary else None


def find_open(
    items: list[dict[str, Any]],
    *,
    entity_id: str,
    summary: str,
    claimed: set[tuple[str, str]],
) -> dict[str, Any] | None:
    """An un-ticked item already reading *summary*, if the list has one."""
    for item in items:
        if (
            item_is_open(item)
            and item.get("summary") == summary
            and (entity_id, item_identity(item)) not in claimed
        ):
            return item
    return None


def added_stamp(entry: dict[str, Any], *, now: datetime) -> str:
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
        # ``str`` because the store holds these entries as opaque JSON and hands
        # back whatever is in the document: a number, or a value some other write
        # left behind, must read as "cannot be trusted" rather than raise.
        if stamped and datetime.fromisoformat(str(stamped)) <= now:
            return str(stamped)
    except (TypeError, ValueError):
        pass
    return now.isoformat()


def add_unconfirmed(
    entry: dict[str, Any],
    *,
    now: datetime,
    grace: timedelta = UNCONFIRMED_GRACE,
) -> bool:
    """Whether the hold on an add we could not confirm has run out.

    "I cannot see it" is not proof the add failed, so the answer is normally no,
    and both unreadable cases answer no as well: a missing stamp starts the clock
    this pass, and an unparsable one is not evidence of anything. The safe
    direction is always the one that cannot duplicate.
    """
    stamped = entry.get("added_at")
    if not stamped:
        return False
    try:
        return now - datetime.fromisoformat(str(stamped)) > grace
    except (TypeError, ValueError):
        return False
