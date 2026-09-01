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

from typing import Any

__all__ = [
    "STATUS_COMPLETED",
    "STATUS_NEEDS_ACTION",
    "find_open",
    "item_identity",
    "item_is_open",
    "resolve_tracked",
]

# ``TodoItemStatus`` values, as the ``todo.get_items`` response spells them.
STATUS_NEEDS_ACTION = "needs_action"
STATUS_COMPLETED = "completed"


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
    """
    if isinstance(uid, str) and uid:
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
