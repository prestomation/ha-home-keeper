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
    REC_ONE_OFF,
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
    """An occurrence at or just before *target*, jumped to in O(1) where possible.

    A long-dormant fixed schedule can be thousands of steps past its anchor;
    stepping one occurrence at a time would be slow (and historically raised once
    it blew an iteration cap). We deliberately *under*-shoot (``- 1`` step) so the
    caller's short loop finishes on the exact occurrence using wall-clock stepping
    — correct across DST and month-length clamping. Day/week deltas are exact, so
    the bulk jump is too.

    MONTHLY is trickier: progressive day-clamping makes the grid path-dependent, so
    we can't jump directly from the anchor for a day > 28 (``add_months(Jan 31, 2)``
    is Mar 31, but stepping is Jan 31 -> Feb 28 -> Mar 28). We exploit the fact that
    the clamped day is monotonically non-increasing toward 28 — once it bottoms out
    at 28 (the global floor: every month has >= 28 days) it never changes again, so
    from that occurrence we *can* jump in O(1). We therefore step until the day hits
    28 (typically a handful of steps — interval-1 monthly reaches a non-leap
    February within a few years) and then bulk-jump the remainder. Schedules whose
    reachable months never include a short-enough month (e.g. an even interval that
    skips February) keep a day > 28 forever; for those we simply step to the target,
    bounded by the (finite) span between anchor and target — slower, but never the
    old iteration-cap crash.
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
    # MONTHLY
    occ = anchor
    while occ.day > 28:
        nxt = add_months(occ, interval)
        if nxt > target:
            # Reached the target before the day stabilized: hand the (exact) grid
            # occurrence to the caller's loop. Bounded by the anchor→target span.
            return occ
        occ = nxt
    # The day has bottomed out at 28 and is now stable for every further step, so
    # the remaining whole steps can be jumped at once (under-shooting by one).
    remaining = (target.year - occ.year) * 12 + (target.month - occ.month)
    jump = max(0, remaining // interval - 1)
    return add_months(occ, jump * interval)


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
    if rec_type == REC_ONE_OFF:
        # A do-once task is due at its stored ``due`` date. Going dormant on
        # completion is ``apply_completion``'s job (next_due -> None); this function
        # only ever (re)arms it back to ``due`` (e.g. when a completion is undone).
        due = _parse(task["due"])
        assert due is not None
        return due
    raise ValueError(f"unknown recurrence_type: {rec_type!r}")


def apply_completion(
    task: dict,
    completed_at: datetime,
    *,
    now: datetime,
    metadata: dict | None = None,
) -> dict:
    """Return *task* mutated to reflect a completion at *completed_at*.

    *metadata* is an optional, pre-cleaned mapping of per-completion context
    (``note``/``cost``/``photo``/``who`` — see
    ``models.normalize_completion_metadata``). Its keys are merged into the new
    history entry alongside the mandatory ``ts``; an empty/None mapping records just
    the timestamp (the historical behaviour). This function stays agnostic about
    *which* keys are valid — cleaning/validation is the caller's job — so the pure
    recurrence math is unaffected by the metadata feature.

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
    entry: dict = {"ts": completed_at.isoformat()}
    if metadata:
        entry.update(metadata)
    history.append(entry)
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
    elif rec_type in (REC_TRIGGERED, REC_ONE_OFF):
        # A one-off is permanently complete; a triggered task clears its condition.
        # Both go dormant (every time surface drops them). Undoing the completion
        # re-arms a one-off (see ``remove_completion``); a triggered task is
        # re-armed only by its owning integration.
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
    rec_type = task.get("recurrence_type")
    if rec_type == REC_ONE_OFF:
        # Undoing the (final) completion of a do-once task re-arms it to its ``due``
        # date so it returns to every time surface; if any completion remains it
        # stays dormant. Unlike a triggered task, a one-off's armed/dormant state is
        # history-driven, so editing the log *does* re-arm it.
        task["next_due"] = (
            compute_next_due(task, now=now).isoformat() if not history else None
        )
    elif rec_type != REC_TRIGGERED:
        task["next_due"] = compute_next_due(task, now=now).isoformat()
    return task


def update_completion(
    task: dict, ts: str, metadata: dict, *, fields: tuple[str, ...]
) -> tuple[dict, str | None]:
    """Edit the metadata of the completion at ISO timestamp *ts* in place.

    Used to amend a past completion (fix a note, add a forgotten cost/photo). For
    each key in *fields* (the recognised metadata keys), a non-empty value in
    *metadata* is set on the entry and an absent/empty value clears it — so an edit
    that blanks the note removes the key rather than storing ``""``. ``ts``,
    schedule, and ``last_completed``/``next_due`` are never touched: amending a log
    entry must not rewind or re-arm a task. Raises :class:`KeyError`-free — instead a
    ``ValueError`` is raised when no entry matches *ts* so the caller can surface a
    clear error.

    Returns ``(task, replaced_photo)`` where *replaced_photo* is the previous
    ``photo`` id when the edit changed or cleared it (so the HA layer can delete the
    now-orphaned image), else ``None``.
    """
    history = list(task.get("completions", []))
    target: dict | None = None
    for entry in history:
        if entry.get("ts") == ts:
            target = entry
            break
    if target is None:
        raise ValueError(f"no completion at {ts!r}")
    old_photo = target.get("photo")
    for key in fields:
        value = metadata.get(key)
        if value in (None, ""):
            target.pop(key, None)
        else:
            target[key] = value
    task["completions"] = history
    new_photo = target.get("photo")
    replaced_photo = old_photo if old_photo and old_photo != new_photo else None
    return task, replaced_photo


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


def one_off_expired(task: dict, retention_days: int, *, now: datetime) -> bool:
    """True when a completed one-off task is past its auto-delete retention window.

    A do-once task goes dormant on completion (``next_due is None`` with a
    ``last_completed`` stamp). With a positive *retention_days* it is eligible for
    auto-deletion once ``last_completed + retention_days`` has passed. Returns
    ``False`` for any other task kind, an uncompleted/re-armed one-off, or a
    non-positive retention (the "keep forever" default). Pure — no HA imports.
    """
    if retention_days <= 0:
        return False
    if task.get("recurrence_type") != REC_ONE_OFF:
        return False
    if task.get("next_due") is not None:
        return False
    completed = _parse(task.get("last_completed"))
    if completed is None:
        return False
    return now >= completed + timedelta(days=retention_days)
