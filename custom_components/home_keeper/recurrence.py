"""Recurrence engine for Home Keeper.

These are deliberately *pure* functions: they take and return timezone-aware
``datetime`` objects and plain task dicts, and import nothing from Home Assistant.
That keeps the product's core logic trivially unit-testable in isolation (the
caller is responsible for passing an aware ``now`` from ``homeassistant.util.dt``).

Two recurrence models are supported:

* **floating** — the next due date is measured from the last completion:
  ``next_due = last_completed + interval·unit``. A task that has *never* been
  completed has no clock to measure from, so it is due immediately (``now``) rather
  than a full interval into the future — a brand-new chore you haven't done yet is
  due now, not "in N days". Completing the task (or seeding an initial completion at
  creation) starts the clock. A missed task simply stays overdue; the due date does
  not march forward on its own.

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
    REC_TRIGGERED,
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
    """Next due date for a floating task, measured from the last completion.

    A task that has never been completed (``last_completed is None``) is due
    immediately (``now``): there is no completion to measure an interval from, and a
    chore you have not yet done should read as due now rather than a full interval
    into the future. Seeding an initial completion opts into the measured behaviour.
    """
    if last_completed is None:
        return now
    return add_interval(last_completed, interval, unit)


def _step(dt: datetime, freq: str, interval: int) -> datetime:
    """Advance *dt* by one schedule step of *freq*·*interval*."""
    if freq == FREQ_DAILY:
        return dt + timedelta(days=interval)
    if freq == FREQ_WEEKLY:
        return dt + timedelta(weeks=interval)
    if freq == FREQ_MONTHLY:
        return add_months(dt, interval)
    raise ValueError(f"unknown freq: {freq!r}")


def _fast_forward(
    anchor: datetime, freq: str, interval: int, target: datetime
) -> datetime:
    """An occurrence at or just before *target*, jumped to in O(1).

    A long-dormant fixed schedule can be thousands of steps past its anchor;
    stepping one occurrence at a time would be slow (and historically raised once
    it blew an iteration cap). We deliberately *under*-shoot (``- 1`` step) so the
    caller's short loop finishes on the exact occurrence using wall-clock stepping
    — correct across DST and month-length clamping. Day/week deltas are exact, so
    the bulk jump is too; MONTHLY is left to the loop (it would need ~830 years to
    approach the cap) to preserve its progressive day-clamping behavior.
    """
    elapsed = (target - anchor).total_seconds()
    if elapsed <= 0:
        return anchor
    if freq == FREQ_DAILY:
        steps = max(0, int(elapsed // (86_400 * interval)) - 1)
        return anchor + timedelta(days=interval * steps)
    if freq == FREQ_WEEKLY:
        steps = max(0, int(elapsed // (604_800 * interval)) - 1)
        return anchor + timedelta(weeks=interval * steps)
    return anchor


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
    occ = _fast_forward(anchor, freq, interval, after)
    iterations = 0
    while occ <= after:
        occ = _step(occ, freq, interval)
        iterations += 1
        if iterations > MAX_EXPAND_ITERATIONS:
            # Unreachable for realistic inputs now that we fast-forward; kept as a
            # last-resort guard against a pathological freq/interval.
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
    # Find the first occurrence at or after *start* — fast-forward close first so a
    # far-past anchor doesn't exhaust the iteration cap before reaching the window.
    occ = _fast_forward(anchor, freq, interval, start)
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
    if rec_type == REC_TRIGGERED:
        # A condition-driven task has no schedule: computing a due date means
        # *arming* it (the condition is true), so it reads as due-now. Going
        # dormant is the asymmetric job of ``apply_completion`` (next_due -> None);
        # this function is only ever called to (re)arm.
        return now
    raise ValueError(f"unknown recurrence_type: {rec_type!r}")


def apply_completion(task: dict, completed_at: datetime, *, now: datetime) -> dict:
    """Return *task* mutated to reflect a completion at *completed_at*.

    Records the completion in history (capped) and recomputes ``next_due``:

    * floating  -> measured from ``completed_at`` (the clock resets)
    * fixed     -> the next scheduled occurrence after ``now`` (schedule-driven;
      completion only marks the occurrence done)
    * triggered -> ``next_due = None`` (dormant): completing a condition-driven
      task *clears* the condition rather than rescheduling it, so it leaves every
      time surface until the owner re-arms it. History is still recorded, so the
      replacement cadence accumulates on the task.
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
    elif rec_type == REC_TRIGGERED:
        task["next_due"] = None
    else:
        raise ValueError(f"unknown recurrence_type: {rec_type!r}")
    return task


def remove_completion(task: dict, ts: str, *, now: datetime) -> dict:
    """Return *task* with the completion at ISO timestamp *ts* removed.

    Undoes an accidental completion: drops the first matching history entry,
    re-derives ``last_completed`` from the remaining history (the latest, or None),
    and recomputes ``next_due`` from that state. For a floating task this rewinds
    the clock to the prior completion; for a fixed task ``next_due`` stays
    schedule-driven; for a triggered task ``next_due`` is left untouched (its
    armed/dormant state is condition-driven, not history-driven — editing the
    replacement log must not arm a dormant task). A no-op when *ts* is not present.
    """
    history = list(task.get("completions", []))
    for index, entry in enumerate(history):
        if entry.get("ts") == ts:
            del history[index]
            break
    task["completions"] = history
    if history:
        latest = max(history, key=lambda entry: datetime.fromisoformat(entry["ts"]))
        task["last_completed"] = latest["ts"]
    else:
        task["last_completed"] = None
    if task.get("recurrence_type") != REC_TRIGGERED:
        task["next_due"] = compute_next_due(task, now=now).isoformat()
    return task


def is_overdue(task: dict, *, now: datetime) -> bool:
    """True when the task's next due date is at or before *now*.

    Convention: the due instant itself counts as overdue (``>=``). This pairs with
    :func:`is_due_soon`'s strict ``now < next_due`` lower bound so the two states
    partition cleanly at the boundary (no gap, no overlap). This is intentionally
    *not* the strict ``>`` used by :func:`next_fixed_occurrence`, which serves a
    different purpose (advancing to the next occurrence); a completion always sets
    ``next_due`` strictly in the future, so a just-completed task is never overdue.
    """
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
