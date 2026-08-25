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
``{"entity_id", "uid", "summary", "last_completed"}``. ``last_completed``
snapshots the task's own ``last_completed`` at bind time; a live value strictly
newer means "completed inside Home Keeper since mirrored", while an undone
completion moves the value backwards and therefore reads as plain content drift.
Per-mirror keying lets two mirrors hold the same task on two lists.

Content is capability-gated *here*, not in the driver: the driver passes each
entity's supported extras (:data:`CAP_DUE_DATE`, :data:`CAP_DESCRIPTION`), and the
planner neither emits nor diffs a field the list cannot hold — otherwise a list
without due dates would be told to update the same item forever.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from .shopping import STATUS_COMPLETED, STATUS_NEEDS_ACTION, normalize_target

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
    "mirror_key",
    "normalize_task_mirror",
    "normalize_task_mirrors",
]

# Optional to-do item fields a list may or may not support, as capability tokens
# the driver derives from the entity's ``supported_features``. The planner only
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
    default filter" (every enabled, scheduled task that is due now).
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
