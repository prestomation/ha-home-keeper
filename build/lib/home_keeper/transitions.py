"""Pure edge-detection for Home Keeper's time-based task events.

The coordinator wakes periodically (and after every mutation) and holds the current
task map, but a due date passing is not itself a mutation — nothing *calls* anything
when ``now`` crosses a task's ``next_due``. This module turns "what the tasks look
like now" plus "what we already announced" into the set of `home_keeper_task_overdue`
/ `home_keeper_task_due_soon` events to fire, **edge-triggered** so each is announced
at most once per ``next_due`` value.

It imports nothing from Home Assistant (only the pure ``recurrence``/``events`` core
and ``const``), so the crossing logic — fire-once, reset-on-reschedule, skip
dormant/disabled — is unit-testable with an injected ``now``. The coordinator owns the
small state map and does the actual ``hass.bus`` firing; see
``coordinator._async_update_data``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from . import events, recurrence
from .const import EVENT_TASK_DUE_SOON, EVENT_TASK_OVERDUE

# How far ahead of ``next_due`` a task counts as "due soon". Matches the binary
# sensor's ``due_soon`` attribute window so the event and the entity agree.
DUE_SOON_WINDOW = timedelta(days=3)

# Per-task edge state carried between coordinator refreshes. Keyed by task id:
#   {"next_due": <iso|None>, "due_soon_fired": bool, "overdue_fired": bool}
# The two flags are independent because a task crosses *due-soon first, then overdue*
# against the **same** ``next_due`` — a bare next_due key couldn't fire both. The flags
# reset whenever ``next_due`` changes (a completion/reschedule/re-arm), which naturally
# re-arms the next announcement.
TaskEdgeState = dict[str, Any]
StateMap = dict[str, TaskEdgeState]


def detect_transitions(
    prev: StateMap,
    tasks: dict[str, dict[str, Any]],
    *,
    now: Any,
    window: timedelta = DUE_SOON_WINDOW,
) -> tuple[list[tuple[str, dict[str, Any]]], StateMap]:
    """Return ``(fired, next_state)`` for the current *tasks* against *prev* state.

    ``fired`` is a list of ``(event_name, payload)`` ready for the caller to put on the
    bus; ``next_state`` is the new per-task edge state to carry forward. A task fires
    ``due_soon`` once when it enters the window and ``overdue`` once when it reaches
    ``next_due`` — never again for the same ``next_due``. Dormant (``next_due is None``)
    and disabled tasks never fire (they're still tracked, so re-arming/re-enabling
    starts fresh). Tasks absent from *tasks* drop out of the state (deleted tasks can't
    leak stale flags).
    """
    fired: list[tuple[str, dict[str, Any]]] = []
    next_state: StateMap = {}

    for tid, task in tasks.items():
        next_due = task.get("next_due")
        prior = prev.get(tid)
        if prior is not None and prior.get("next_due") == next_due:
            due_soon_fired = bool(prior.get("due_soon_fired"))
            overdue_fired = bool(prior.get("overdue_fired"))
        else:
            # New task, or its schedule moved — re-arm both announcements.
            due_soon_fired = False
            overdue_fired = False

        if task.get("enabled", True) and next_due is not None:
            parsed = recurrence._parse(next_due)
            if not due_soon_fired and recurrence.is_due_soon(task, window, now=now):
                due_in_hours = round((parsed - now).total_seconds() / 3600, 1)
                fired.append(
                    (
                        EVENT_TASK_DUE_SOON,
                        events.task_event_data(
                            task, extra={"due_in_hours": due_in_hours}
                        ),
                    )
                )
                due_soon_fired = True
            if not overdue_fired and recurrence.is_overdue(task, now=now):
                days_overdue = (now - parsed).days
                fired.append(
                    (
                        EVENT_TASK_OVERDUE,
                        events.task_event_data(
                            task, extra={"days_overdue": days_overdue}
                        ),
                    )
                )
                overdue_fired = True

        next_state[tid] = {
            "next_due": next_due,
            "due_soon_fired": due_soon_fired,
            "overdue_fired": overdue_fired,
        }

    return fired, next_state
