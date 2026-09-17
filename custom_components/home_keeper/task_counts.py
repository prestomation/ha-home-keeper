"""Pure aggregation for the task **count sensors** (no HA imports).

A count sensor answers "how many tasks does this profile surface right now?" in one
number a dashboard badge can show, with the neighbouring counts and the next task up
as attributes. :func:`count_tasks` does the whole computation over plain dicts and an
injected ``now``, so every branch is unit-testable without a Home Assistant runtime —
the ``recurrence.py`` / ``sensor_tasks.py`` contract. ``sensor.py`` is a thin
publisher over it.

Nothing here re-implements the profile status ladder. The state runs through
``profiles.matches_filter`` and the scope through ``profiles.due_queue``, so a count
can never disagree with the panel, the card, a notification or a to-do list sync
about what the same profile means.

Two definitions this module pins, because a user watches the numbers and an automation
depends on them:

* **``due_soon`` is the strict band** — due inside the window and *not yet* overdue,
  exactly ``recurrence.is_due_soon`` and the ``binary_sensor`` attribute of the same
  name. So a profile whose status is ``due_soon`` has a state of ``overdue +
  due_soon``, not ``due_soon``.
* **``due_today`` is a calendar date**, not a 24-hour window: the task falls due on
  *today* in ``now``'s own timezone. That is what ``home_keeper.set_due_today``
  means, and a badge reading "3 due today" that counted 01:00 tomorrow would be wrong
  to the person reading it.

``now`` must therefore be timezone-aware **local** time — ``dt_util.now()``, never
``dt_util.utcnow()``. A UTC ``now`` shifts ``due_today`` by the offset with no error
to signal it. ``tests/unit/test_task_counts.py`` pins that with a non-UTC zone.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from . import profiles, recurrence
from .transitions import DUE_SOON_WINDOW

__all__ = ["COUNT_KEYS", "count_tasks"]

#: Every key :func:`count_tasks` returns. ``state`` becomes the sensor's state and the
#: rest become its attributes verbatim, so this tuple is the published contract.
COUNT_KEYS = (
    "state",
    "total",
    "overdue",
    "due_soon",
    "due_today",
    "next_due",
    "next_task_name",
    "next_task_id",
    "most_overdue_days",
)

#: Seconds in a day, for the ``most_overdue_days`` conversion.
_DAY_SECONDS = 86400.0


def _due_date(task: dict[str, Any], now: datetime) -> date:
    """The calendar date *task* falls due on, read in ``now``'s timezone.

    ``next_due`` is guaranteed non-None by ``matches_filter``, which every task in
    the scope has passed — the same invariant ``profiles._due_key`` reads on.
    """
    return datetime.fromisoformat(task["next_due"]).astimezone(now.tzinfo).date()


def _days_overdue(task: dict[str, Any], now: datetime) -> float:
    """How many days *task* is past its due instant, to one decimal place."""
    due = datetime.fromisoformat(task["next_due"])
    return round((now - due).total_seconds() / _DAY_SECONDS, 1)


def count_tasks(
    tasks: list[dict[str, Any]],
    filt: dict[str, Any],
    *,
    now: datetime,
    window: timedelta = DUE_SOON_WINDOW,
) -> dict[str, Any]:
    """Count the tasks *filt* scopes to, and name the next one up.

    *tasks* must already carry effective label and area ids — the HA-aware caller
    resolves those with ``notifier.effective_filter_tasks`` before calling, the same
    enrichment the notifier does, or a profile filtering on an inherited label counts
    a different set here than the panel shows.

    ``state`` honours *filt*'s own status, so it is the number that profile surfaces.
    Every other count is taken over the profile's **scope** — the same filter with the
    status widened to ``all`` — so ``total`` stays the size of the profile's world
    however its status tier is set, and the pointers name a task even when the state
    is 0.
    """
    scope_filt = profiles.with_status(filt, profiles.STATUS_ALL)
    # due_queue sorts earliest next_due first, so scope[0] is the next task up and the
    # first overdue entry is the most overdue. No second sort. The window is left at
    # its default deliberately: the scope status is "all", which admits every enabled
    # scheduled task whatever the window says, so passing one here would read as if it
    # mattered.
    scope = profiles.due_queue(tasks, scope_filt, now=now)
    overdue = [task for task in scope if recurrence.is_overdue(task, now=now)]
    today = now.date()
    upcoming = scope[0] if scope else None
    return {
        "state": sum(
            1
            for task in scope
            if profiles.matches_filter(task, filt, now=now, window=window)
        ),
        "total": len(scope),
        "overdue": len(overdue),
        "due_soon": sum(
            1 for task in scope if recurrence.is_due_soon(task, window, now=now)
        ),
        "due_today": sum(1 for task in scope if _due_date(task, now) == today),
        "next_due": upcoming.get("next_due") if upcoming else None,
        "next_task_name": upcoming.get("name") if upcoming else None,
        "next_task_id": upcoming.get("id") if upcoming else None,
        "most_overdue_days": _days_overdue(overdue[0], now) if overdue else None,
    }
