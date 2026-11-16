"""Which actions a task accepts, for each recurrence type and phase.

A task is armed when it has a ``next_due`` and dormant when it has none. The phase is
always derived from the task and never stored. ``ALLOWED`` holds 1 row for each
recurrence type and phase. The store reads it before it changes a task, so each gate is
in 1 place. ``recurrence.py`` keeps the date math.

Pure: this module imports only ``const``, so the unit tests and mutmut run it without
Home Assistant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from .const import (
    REC_FIXED,
    REC_FLOATING,
    REC_SENSOR,
    REC_TRIGGERED,
    RECURRENCE_TYPES,
)

Phase = Literal["armed", "dormant"]
ARMED: Phase = "armed"
DORMANT: Phase = "dormant"

COMPLETE = "complete"
SKIP = "skip"
SNOOZE = "snooze"
DUE_TODAY = "due_today"
TRIGGER = "trigger"
MOVE_OCCURRENCE = "move_occurrence"

# Done and Skip are accepted in each phase. Done on a dormant task records a use or
# a late completion, and Skip on a dormant task only writes the log.
_ALWAYS = frozenset({COMPLETE, SKIP})
# Snooze and due today move a due date, so a dormant task has none to move.
_DEFER = frozenset({SNOOZE, DUE_TODAY})
# Only the owner or the watcher arms these types.
_TRIGGERED_TYPES = frozenset({REC_TRIGGERED, REC_SENSOR})


def _row(rec_type: str, phase: Phase) -> frozenset[str]:
    actions = set(_ALWAYS)
    if phase == ARMED:
        actions |= _DEFER
    if rec_type in _TRIGGERED_TYPES:
        actions.add(TRIGGER)
    if rec_type == REC_FIXED:
        actions.add(MOVE_OCCURRENCE)
    return frozenset(actions)


ALLOWED: dict[tuple[str, Phase], frozenset[str]] = {
    (rec_type, phase): _row(rec_type, phase)
    for rec_type in RECURRENCE_TYPES
    for phase in (ARMED, DORMANT)
}


def phase(task: dict[str, Any]) -> Phase:
    """Return the phase of *task*: armed with a ``next_due``, else dormant."""
    return ARMED if task.get("next_due") else DORMANT


def allows(task: dict[str, Any], action: str) -> bool:
    """Whether *task* accepts *action* in its type and phase now."""
    rec_type = task.get("recurrence_type") or REC_FLOATING
    return action in ALLOWED.get((rec_type, phase(task)), frozenset())


def arm(task: dict[str, Any], *, now: datetime) -> bool:
    """Make a dormant *task* due at *now*. Return whether ``next_due`` changed.

    An armed task keeps its due date. So a second trigger of an overdue task does not
    announce it as overdue again, and a snooze stays.
    """
    if phase(task) == ARMED:
        return False
    task["next_due"] = now.isoformat()
    return True
