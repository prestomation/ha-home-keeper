"""Recurrence engine for Home Keeper.

These are deliberately *pure* functions: they take and return timezone-aware
``datetime`` objects and plain task dicts, and import nothing from Home Assistant.
That keeps the product's core logic trivially unit-testable in isolation (the
caller is responsible for passing an aware ``now`` from ``homeassistant.util.dt``).

Two recurrence models are supported:

* **floating** — the next due date is measured from the last completion (or the
  task's anchor if never completed): ``next_due = last_completed + interval·unit``.
  Completing the task resets the clock. A missed task simply stays overdue; the
  due date does not march forward on its own.

* **fixed** — the next due date follows a calendar schedule anchored at a fixed
  datetime (``FREQ=DAILY|WEEKLY|MONTHLY`` every ``interval`` steps). Completing an
  occurrence records history but the schedule advances independently of when the
  task was actually completed.
"""

from __future__ import annotations

import calendar as _calendar
from datetime import datetime, timedelta

from .const import (
    FREQ_DAILY,
    FREQ_MONTHLY,
    FREQ_WEEKLY,
    MAX_COMPLETION_HISTORY,
    MAX_EXPAND_ITERATIONS,
    REC_FIXED,
    REC_FLOATING,
    UNIT_DAYS,
    UNIT_MONTHS,
    UNIT_WEEKS,
)


def add_months(dt: datetime, months: int) -> datetime:
    """Return *dt* shifted by *months*, clamping the day to the month's length.

    e.g. ``add_months(Jan 31, 1) -> Feb 28`` (or Feb 29 in a leap year). The
    time-of-day and tzinfo are preserved.
    """
    if months == 0:
        return dt
    # Convert to a zero-based month index for clean arithmetic. Python's floor
    # division and non-negative modulo make this correct for negative months too
    # (e.g. Jan + (-2) months -> month_index -2 -> year-1, month 11 = November),
    # though in practice this integration only ever advances by positive months.
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    last_day = _calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def add_interval(dt: datetime, interval: int, unit: str) -> datetime:
    """Return *dt* advanced by ``interval`` of ``unit`` (days/weeks/months)."""
    if interval < 1:
        raise ValueError(f"interval must be >= 1, got {interval}")
    if unit == UNIT_DAYS:
        return dt + timedelta(days=interval)
    if unit == UNIT_WEEKS:
        return dt + timedelta(weeks=interval)
    if unit == UNIT_MONTHS:
        return add_months(dt, interval)
    raise ValueError(f"unknown unit: {unit!r}")


def compute_floating_next_due(
    last_completed: datetime | None,
    interval: int,
    unit: str,
    *,
    now: datetime,
) -> datetime:
    """Next due date for a floating task, measured from last completion or *now*."""
    base = last_completed if last_completed is not None else now
    return add_interval(base, interval, unit)


def _step(dt: datetime, freq: str, interval: int) -> datetime:
    """Advance *dt* by one schedule step of *freq*·*interval*."""
    if freq == FREQ_DAILY:
        return dt + timedelta(days=interval)
    if freq == FREQ_WEEKLY:
        return dt + timedelta(weeks=interval)
    if freq == FREQ_MONTHLY:
        return add_months(dt, interval)
    raise ValueError(f"unknown freq: {freq!r}")


def next_fixed_occurrence(
    anchor: datetime,
    freq: str,
    interval: int,
    *,
    after: datetime,
) -> datetime:
    """Smallest occurrence strictly greater than *after* for a fixed schedule.

    Occurrences start at *anchor* and repeat every *interval* of *freq*,
    preserving the anchor's time-of-day. If *after* precedes the anchor, the
    anchor itself is returned.
    """
    if interval < 1:
        raise ValueError(f"interval must be >= 1, got {interval}")
    if anchor > after:
        return anchor
    occ = anchor
    iterations = 0
    while occ <= after:
        occ = _step(occ, freq, interval)
        iterations += 1
        if iterations > MAX_EXPAND_ITERATIONS:
            # Anchor is far in the past relative to *after*; jump ahead in bulk
            # for the common DAILY case rather than looping forever.
            raise RuntimeError(
                "next_fixed_occurrence exceeded iteration cap; "
                f"anchor={anchor.isoformat()} after={after.isoformat()}"
            )
    return occ


def expand_fixed_occurrences(
    anchor: datetime,
    freq: str,
    interval: int,
    start: datetime,
    end: datetime,
) -> list[datetime]:
    """All fixed occurrences within the half-open range ``[start, end)``.

    Bounded by ``MAX_EXPAND_ITERATIONS`` to guard against runaway loops.
    """
    if start >= end:
        return []
    occurrences: list[datetime] = []
    # Find the first occurrence at or after *start*.
    occ = anchor
    iterations = 0
    while occ < start:
        occ = _step(occ, freq, interval)
        iterations += 1
        if iterations > MAX_EXPAND_ITERATIONS:
            return occurrences
    while occ < end and iterations <= MAX_EXPAND_ITERATIONS:
        occurrences.append(occ)
        occ = _step(occ, freq, interval)
        iterations += 1
    return occurrences


def _parse(value: str | datetime | None) -> datetime | None:
    """Parse an ISO string into an aware datetime (pass-through for datetimes)."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def compute_next_due(task: dict, *, now: datetime) -> datetime:
    """Compute next_due for *task* from its current state (no mutation)."""
    rec_type = task.get("recurrence_type", REC_FLOATING)
    if rec_type == REC_FLOATING:
        return compute_floating_next_due(
            _parse(task.get("last_completed")),
            int(task["interval"]),
            task["unit"],
            now=now,
        )
    if rec_type == REC_FIXED:
        anchor = _parse(task["anchor"])
        assert anchor is not None
        return next_fixed_occurrence(
            anchor, task["freq"], int(task["interval"]), after=now
        )
    raise ValueError(f"unknown recurrence_type: {rec_type!r}")


def apply_completion(task: dict, completed_at: datetime, *, now: datetime) -> dict:
    """Return *task* mutated to reflect a completion at *completed_at*.

    Records the completion in history (capped) and recomputes ``next_due``:

    * floating -> measured from ``completed_at`` (the clock resets)
    * fixed    -> the next scheduled occurrence after ``now`` (schedule-driven;
      completion only marks the occurrence done)
    """
    history = list(task.get("completions", []))
    history.append({"ts": completed_at.isoformat()})
    if len(history) > MAX_COMPLETION_HISTORY:
        history = history[-MAX_COMPLETION_HISTORY:]
    task["completions"] = history
    task["last_completed"] = completed_at.isoformat()

    rec_type = task.get("recurrence_type", REC_FLOATING)
    if rec_type == REC_FLOATING:
        task["next_due"] = compute_floating_next_due(
            completed_at, int(task["interval"]), task["unit"], now=now
        ).isoformat()
    elif rec_type == REC_FIXED:
        anchor = _parse(task["anchor"])
        assert anchor is not None
        task["next_due"] = next_fixed_occurrence(
            anchor, task["freq"], int(task["interval"]), after=now
        ).isoformat()
    else:
        raise ValueError(f"unknown recurrence_type: {rec_type!r}")
    return task


def is_overdue(task: dict, *, now: datetime) -> bool:
    """True when the task's next due date is at or before *now*."""
    next_due = _parse(task.get("next_due"))
    if next_due is None:
        return False
    return now >= next_due


def is_due_soon(task: dict, window: timedelta, *, now: datetime) -> bool:
    """True when the task becomes due within *window* (and is not yet overdue)."""
    next_due = _parse(task.get("next_due"))
    if next_due is None:
        return False
    return now < next_due <= now + window
