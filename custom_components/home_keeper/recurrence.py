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

* **fixed** — the next due date follows a calendar schedule: an RFC 5545 RRULE
  (``rrule``, e.g. ``FREQ=WEEKLY;BYDAY=TU,FR``) anchored at a fixed datetime, plus
  any single dates the user moved (``moved_occurrences``). Completing an occurrence
  records history but the schedule advances independently of when the task was
  actually completed.
"""

from __future__ import annotations

import calendar as _calendar
from collections.abc import Iterable
from datetime import datetime, timedelta, tzinfo

from dateutil import rrule as _dateutil_rrule

from .const import (
    FREQ_DAILY,
    FREQ_MONTHLY,
    FREQ_WEEKLY,
    FREQ_YEARLY,
    MAX_COMPLETION_HISTORY,
    MAX_EXPAND_ITERATIONS,
    MAX_INTERVAL,
    MAX_MOVED_OCCURRENCES,
    MAX_RULE_LENGTH,
    REC_FIXED,
    REC_FLOATING,
    REC_ONE_OFF,
    REC_SENSOR,
    REC_TRIGGERED,
    REC_USE,
    RULE_FORBIDDEN_PARTS,
    RULE_FREQS,
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


def _parse_mmdd(mmdd: str) -> tuple[int, int]:
    """Parse ``"MM-DD"`` to ``(month, day)``."""
    parts = mmdd.split("-")
    return int(parts[0]), int(parts[1])


def _normalize_season(season: dict | list) -> list[dict]:
    """Coerce *season* to a list of ``{"start": ..., "end": ...}`` windows."""
    if isinstance(season, dict):
        return [season]
    return list(season)


def in_season(dt_val: datetime, season: dict | list) -> bool:
    """True when *dt_val*'s month-day falls inside any active-season window.

    Non-wrapping (e.g. Apr-Sep): ``start <= md <= end``.
    Wrapping (e.g. Nov-Mar): ``md >= start or md <= end``.
    """
    md = (dt_val.month, dt_val.day)
    for window in _normalize_season(season):
        s_m, s_d = _parse_mmdd(window["start"])
        e_m, e_d = _parse_mmdd(window["end"])
        start = (s_m, s_d)
        end = (e_m, e_d)
        if start <= end:
            if start <= md <= end:
                return True
        elif md >= start or md <= end:
            return True
    return False


def _next_season_start(dt_val: datetime, season: dict | list) -> datetime:
    """Earliest datetime at any window's start on or after *dt_val*.

    Clamps the day via ``calendar.monthrange`` so a season start like ``"01-31"``
    landing in February becomes Feb 28/29.
    """
    candidates: list[datetime] = []
    for window in _normalize_season(season):
        s_m, s_d = _parse_mmdd(window["start"])
        year = dt_val.year
        last_day = _calendar.monthrange(year, s_m)[1]
        day = min(s_d, last_day)
        candidate = dt_val.replace(
            month=s_m, day=day, hour=0, minute=0, second=0, microsecond=0
        )
        if candidate < dt_val:
            year += 1
            last_day = _calendar.monthrange(year, s_m)[1]
            day = min(s_d, last_day)
            candidate = dt_val.replace(
                year=year,
                month=s_m,
                day=day,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        candidates.append(candidate)
    return min(candidates)


def _clamp_season(next_due: datetime, task: dict) -> datetime:
    """Push *next_due* to the next season start if it falls outside the season.

    For fixed tasks the result stays grid-aligned: the first fixed occurrence
    on or after the season start is returned instead of the bare start date.
    """
    season = task.get("active_season")
    if not season:
        return next_due
    if in_season(next_due, season):
        return next_due
    season_start = _next_season_start(next_due, season)
    rec_type = task.get("recurrence_type", REC_FLOATING)
    if rec_type == REC_FIXED:
        after = season_start - timedelta(seconds=1)
        return next_task_occurrence(task, after=after)
    return season_start


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


def _regrid(anchor: datetime, probe: datetime) -> datetime:
    """*anchor* re-homed into *probe*'s timezone, so stepping keeps local wall time.

    A schedule promises a wall clock: "every day at 10:00" means 10:00 on the kitchen
    clock, on both sides of a daylight-saving transition. :func:`_step` delivers that
    — but only while the anchor carries a real zone, because ``dt + timedelta`` holds
    the *tzinfo it is given*. A fixed UTC offset is a tzinfo too, and holding one of
    those across a transition is what makes a 10:00 task read 09:00 every autumn.

    Storage is what strips the zone. An ISO string carries an offset and not a zone
    identity, so ``ZoneInfo("America/Los_Angeles")`` is written as ``-07:00`` and
    reloads as ``timezone(timedelta(hours=-7))``. Every anchor therefore comes back
    from the store offset-only, no matter how it was written — which is why writing it
    differently cannot fix this and re-homing on the way in has to.

    *probe* is the caller's clock (``after`` here, ``start`` in
    :func:`expand_fixed_occurrences`), which in this integration is always derived
    from ``dt_util.now()`` and so carries Home Assistant's configured zone. Re-homing
    keeps the instant and swaps the tzinfo, so an anchor stored as ``17:00+00:00``,
    ``10:00-07:00`` or naive-turned-``10:00-07:00`` all resolve to the same 10:00
    local and all hold it through the transition.
    """
    return anchor.astimezone(probe.tzinfo)


# ── Fixed schedules: an RRULE anchored at a datetime ─────────────────────────
#
# A fixed task stores an RFC 5545 RRULE body (``FREQ=WEEKLY;BYDAY=TU,FR``) and an
# ``anchor``. The anchor is the rule's DTSTART: it gives the time of day and the
# earliest date. ``dateutil.rrule`` expands the rule. Home Keeper adds 3 things on top:
#
# * **Wall time.** The rule is expanded on *naive local* times and each result is
#   given the caller's zone, so "every Tuesday at 07:00" stays at 07:00 on both sides
#   of a daylight-saving change (see :func:`_regrid`).
# * **Month end.** A plain ``FREQ=MONTHLY`` anchored on the 31st means "the 31st, or
#   the last day of a shorter month". RFC 5545 skips the months that have no 31st, and
#   nobody who asks for "monthly" wants that. See :func:`effective_rule`.
# * **Moves.** ``moved_occurrences`` moves single dates of the schedule and leaves the
#   rest alone. See :func:`task_moves` and :func:`move_occurrence`.

_WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
# The BY-parts that choose *which days* a rule lands on. When a rule names none of
# them, dateutil takes the day from DTSTART; :func:`effective_rule` makes that choice
# explicit so the start can be moved forward without changing the answer.
_DAY_PARTS = ("BYDAY", "BYMONTHDAY", "BYYEARDAY", "BYWEEKNO")
# How far past a probe the expansion looks before it gives up. A rule is validated to
# have an occurrence within this window of its anchor, so for a valid rule this never
# drops a real date; it only bounds a rule whose next date is centuries away.
_HORIZON = timedelta(days=366 * 20)
_FORBIDDEN_PARTS = frozenset(RULE_FORBIDDEN_PARTS)
# The length of one rule period, in days, rounded up. A rule with a long INTERVAL
# (every 30 years) needs a horizon longer than 20 years to reach its next date.
_PERIOD_DAYS = {FREQ_DAILY: 1, FREQ_WEEKLY: 7, FREQ_MONTHLY: 31, FREQ_YEARLY: 366}


def _horizon(rule: str) -> timedelta:
    """How far past a probe to look: 20 years, or 2 whole periods if that is longer."""
    parts = rule_parts(rule)
    period = _PERIOD_DAYS.get(parts.get("FREQ", ""), 366)
    interval = int(parts.get("INTERVAL", "1"))
    return max(_HORIZON, timedelta(days=period * interval * 2))


class RuleError(ValueError):
    """A fixed-schedule RRULE that Home Keeper cannot store.

    ``reason`` is a short stable key (``syntax``, ``freq``, ``forbidden``, ``empty``,
    ``length``) so the HA layer can pick a translated message.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"invalid rule ({reason}): {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def rule_parts(rule: str) -> dict[str, str]:
    """Split an RRULE body into ``{PART: value}``, upper-cased.

    Only the shape is checked here: ``KEY=VALUE`` pairs split by ``;``. Whether the
    values mean anything is :func:`normalize_rule`'s job.
    """
    parts: dict[str, str] = {}
    for chunk in rule.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, sep, value = chunk.partition("=")
        if not sep or not key.strip() or not value.strip():
            raise RuleError("syntax", chunk)
        parts[key.strip().upper()] = value.strip().upper()
    return parts


def _join_parts(parts: dict[str, str]) -> str:
    """The inverse of :func:`rule_parts`, with FREQ first as RFC 5545 writes it."""
    ordered = [f"FREQ={parts['FREQ']}"] if "FREQ" in parts else []
    ordered += [f"{k}={v}" for k, v in parts.items() if k != "FREQ"]
    return ";".join(ordered)


def normalize_rule(rule: object) -> str:
    """Validate a user-supplied RRULE body and return its canonical text.

    Accepts an optional ``RRULE:`` prefix (a rule copied from another calendar has
    one), strips blanks and upper-cases. Refuses a rule that:

    * does not parse (``syntax``), or has no FREQ or a sub-daily one (``freq``);
    * carries COUNT, UNTIL, DTSTART or a sub-daily BY-part (``forbidden``);
    * has no occurrence within 20 years of any start (``empty``) — for example the
      30th of February. This is what lets every later expansion stop at a horizon.
    """
    if not isinstance(rule, str):
        raise RuleError("syntax", repr(rule))
    text = rule.strip()
    if text.upper().startswith("RRULE:"):
        text = text[len("RRULE:") :]
    if len(text) > MAX_RULE_LENGTH:
        raise RuleError("length", str(len(text)))
    if not text:
        raise RuleError("syntax", "")
    parts = rule_parts(text)
    freq = parts.get("FREQ")
    if freq not in RULE_FREQS:
        raise RuleError("freq", str(freq))
    forbidden = sorted(_FORBIDDEN_PARTS.intersection(parts))
    if forbidden:
        raise RuleError("forbidden", ",".join(forbidden))
    interval = parts.get("INTERVAL", "1")
    if not interval.isdigit() or not 1 <= int(interval) <= MAX_INTERVAL:
        raise RuleError("syntax", f"INTERVAL={interval}")
    canonical = _join_parts(parts)
    # A fixed probe start. A rule that yields nothing in 20 years from here yields
    # nothing from any start: every part is periodic within a 400-year Gregorian cycle
    # except the leap day, and a leap day comes round every 4 or 8 years.
    probe = datetime(2000, 1, 1)
    try:
        expanded = _rrulestr(effective_rule(canonical, probe), dtstart=probe).replace(
            until=probe + _HORIZON
        )
        first = expanded.after(probe, inc=True)
    except (ValueError, TypeError, KeyError, OverflowError) as err:
        raise RuleError("syntax", str(err)) from err
    if first is None:
        raise RuleError("empty", canonical)
    return canonical


def legacy_rule(freq: str, interval: int) -> str:
    """The RRULE a legacy ``freq``/``interval`` pair means.

    Month-end handling is not written into the text: :func:`effective_rule` applies it
    to any plain monthly rule, so a migrated task and one made in the new form read the
    same, and the day buttons can show both.
    """
    if freq not in (FREQ_DAILY, FREQ_WEEKLY, FREQ_MONTHLY):
        raise RuleError("freq", str(freq))
    if interval < 1:
        raise RuleError("syntax", f"INTERVAL={interval}")
    return f"FREQ={freq};INTERVAL={int(interval)}"


def task_rule(task: dict) -> str:
    """The RRULE of a fixed *task*.

    A stored task always has ``rrule`` once the store has loaded. A dict built by hand
    (a test, an import of an old export) may still carry the legacy pair, so fall back
    to it rather than fail.
    """
    rule = task.get("rrule")
    if rule:
        return str(rule)
    return legacy_rule(task["freq"], int(task.get("interval") or 1))


def effective_rule(rule: str, start: datetime) -> str:
    """*rule* with every choice dateutil would take from DTSTART written out.

    dateutil fills an absent BYDAY / BYMONTHDAY / BYMONTH from the start date. That is
    fine until the start moves, and :func:`_fast_forward_start` moves it, so the
    choices are fixed here from the *real* anchor first.

    It is also where month end is decided. A plain monthly rule on the 29th, 30th or
    31st becomes "that day, or the last day of a shorter month"
    (``BYMONTHDAY=28,...,D;BYSETPOS=-1`` picks the latest of those days the month has).
    A plain yearly rule on February 29 becomes "February 29, or February 28".
    """
    parts = rule_parts(rule)
    freq = parts["FREQ"]
    if any(p in parts for p in _DAY_PARTS):
        return _join_parts(parts)
    if freq == FREQ_WEEKLY:
        parts["BYDAY"] = _WEEKDAYS[start.weekday()]
    elif freq == FREQ_MONTHLY:
        if start.day > 28 and "BYSETPOS" not in parts:
            parts["BYMONTHDAY"] = ",".join(str(d) for d in range(28, start.day + 1))
            parts["BYSETPOS"] = "-1"
        else:
            parts["BYMONTHDAY"] = str(start.day)
    elif freq == FREQ_YEARLY:
        parts.setdefault("BYMONTH", str(start.month))
        if (start.month, start.day) == (2, 29) and "BYSETPOS" not in parts:
            parts["BYMONTHDAY"] = "28,29"
            parts["BYSETPOS"] = "-1"
        else:
            parts["BYMONTHDAY"] = str(start.day)
    return _join_parts(parts)


def _rrulestr(text: str, *, dtstart: datetime) -> _dateutil_rrule.rrule:
    """Parse an RRULE body. A body never yields a set, so narrow the type."""
    parsed = _dateutil_rrule.rrulestr(text, dtstart=dtstart)
    assert isinstance(parsed, _dateutil_rrule.rrule)
    return parsed


def _fast_forward_start(
    start: datetime, freq: str, interval: int, target: datetime
) -> datetime:
    """A start whole periods after *start* and at or before *target*.

    dateutil walks from DTSTART, so a daily task anchored in 2019 would take thousands
    of steps on every call. Moving the start by a whole number of rule periods keeps
    every later occurrence the same, because :func:`effective_rule` has already fixed
    the days that the start used to decide. One period of margin is kept, so the moved
    start is always on the safe side of *target*.

    Daily and weekly periods are exact on naive wall times. A month or year period moves
    to the first day of its month, which is still inside the same rule period.
    """
    if target <= start:
        return start
    if freq == FREQ_DAILY:
        steps = max(0, (target - start).days // interval - 1)
        return start + timedelta(days=steps * interval)
    if freq == FREQ_WEEKLY:
        steps = max(0, (target - start).days // (7 * interval) - 1)
        return start + timedelta(weeks=steps * interval)
    if freq == FREQ_MONTHLY:
        months = (target.year - start.year) * 12 + (target.month - start.month)
        steps = max(0, months // interval - 1)
        if steps == 0:
            return start
        index = start.month - 1 + steps * interval
        return start.replace(year=start.year + index // 12, month=index % 12 + 1, day=1)
    # YEARLY
    steps = max(0, (target.year - start.year) // interval - 1)
    if steps == 0:
        return start
    return start.replace(year=start.year + steps * interval, month=1, day=1)


def _localize(naive: datetime, tz: tzinfo | None) -> datetime:
    """Give a naive local wall time the probe's zone, keeping the wall time."""
    return naive.replace(tzinfo=tz)


def _expansion(
    anchor: datetime, rule: str, probe: datetime, until: datetime | None
) -> tuple[_dateutil_rrule.rrule, tzinfo | None]:
    """The dateutil rule for *anchor*/*rule*, started near *probe*, ending at *until*.

    Returns the rule and the zone its naive results belong to. With no *until*, the
    rule ends one :func:`_horizon` after *probe*, clamped to the last representable
    year so a far horizon cannot overflow.
    """
    tz = probe.tzinfo
    start = _regrid(anchor, probe).replace(tzinfo=None)
    effective = effective_rule(rule, start)
    parts = rule_parts(effective)
    naive_probe = probe.astimezone(tz).replace(tzinfo=None)
    moved = _fast_forward_start(
        start, parts["FREQ"], int(parts.get("INTERVAL", "1")), naive_probe
    )
    if until is None:
        try:
            naive_until = naive_probe + _horizon(effective)
        except OverflowError:
            naive_until = datetime(9999, 12, 31)
    else:
        naive_until = until.astimezone(tz).replace(tzinfo=None)
    expanded = _rrulestr(effective, dtstart=moved).replace(until=naive_until)
    return expanded, tz


def _instant(value: datetime) -> float:
    """A key that compares datetimes by instant, whatever their tzinfo."""
    return value.timestamp()


def _parse_move(move: object) -> tuple[datetime, datetime] | None:
    """One ``moved_occurrences`` row as ``(from, to)``, or ``None`` when it is bad."""
    if not isinstance(move, dict):
        return None
    try:
        src = datetime.fromisoformat(move["from"])
        dst = datetime.fromisoformat(move["to"])
    except (KeyError, TypeError, ValueError):
        return None
    if src.tzinfo is None or dst.tzinfo is None:
        return None
    return src, dst


def _parsed_moves(moves: Iterable[dict] | None) -> list[tuple[datetime, datetime]]:
    """``moved_occurrences`` as ``(from, to)`` datetimes. Bad rows are ignored."""
    return [pair for pair in map(_parse_move, moves or ()) if pair is not None]


def next_fixed_occurrence(
    anchor: datetime,
    rule: str,
    *,
    after: datetime,
    moves: Iterable[dict] | None = None,
) -> datetime:
    """Smallest occurrence strictly greater than *after* for a fixed schedule.

    Occurrences come from *rule* anchored at *anchor*, read at the anchor's
    time-of-day **in *after*'s timezone** (see :func:`_regrid`). *moves* takes the
    ``from`` dates off the schedule and puts the ``to`` dates on it.

    Raises ``ValueError`` when the rule has no occurrence within 20 years of *after*,
    which :func:`normalize_rule` makes unreachable for a stored rule.
    """
    parsed = _parsed_moves(moves)
    moved_from = {_instant(src) for src, _ in parsed}
    expanded, tz = _expansion(anchor, rule, after, None)
    probe = after.astimezone(tz).replace(tzinfo=None)
    candidate: datetime | None = None
    # A moved-away date is skipped, so look past at most that many rule dates.
    for _ in range(len(moved_from) + 1):
        found = expanded.after(probe)
        if found is None:
            break
        local = _localize(found, tz)
        if _instant(local) not in moved_from:
            candidate = local
            break
        probe = found
    targets = [dst.astimezone(tz) for _, dst in parsed if dst > after]
    options = [c for c in (candidate, *targets) if c is not None]
    if not options:
        raise ValueError(
            f"fixed schedule has no occurrence after {after.isoformat()}: {rule}"
        )
    return min(options, key=_instant)


def expand_fixed_occurrences(
    anchor: datetime,
    rule: str,
    start: datetime,
    end: datetime,
    *,
    moves: Iterable[dict] | None = None,
) -> list[datetime]:
    """All fixed occurrences within the half-open range ``[start, end)``, in order.

    Occurrences read at the anchor's time-of-day in *start*'s timezone, the same rule
    :func:`next_fixed_occurrence` follows (see :func:`_regrid`). *moves* applies the
    same way. Capped at ``MAX_EXPAND_ITERATIONS`` results.
    """
    if start >= end:
        return []
    parsed = _parsed_moves(moves)
    moved_from = {_instant(src) for src, _ in parsed}
    expanded, tz = _expansion(anchor, rule, start, end)
    naive_start = start.astimezone(tz).replace(tzinfo=None)
    occurrences: list[datetime] = []
    for found in expanded.xafter(naive_start, count=MAX_EXPAND_ITERATIONS, inc=True):
        local = _localize(found, tz)
        if local >= end:
            break
        if local >= start and _instant(local) not in moved_from:
            occurrences.append(local)
    occurrences += [dst.astimezone(tz) for _, dst in parsed if start <= dst < end]
    # A move onto a date the rule already has is refused by ``move_occurrence``, but
    # an imported list is not checked that deeply. One date shows once, whatever put
    # it there twice.
    unique = {_instant(o): o for o in occurrences}
    return sorted(unique.values(), key=_instant)[:MAX_EXPAND_ITERATIONS]


def is_rule_occurrence(
    anchor: datetime, rule: str, moment: datetime, *, tz: tzinfo | None = None
) -> bool:
    """Whether *moment* is a date of the bare rule, with no moves applied.

    The rule is expanded in the probe's zone (see :func:`_regrid`), so *tz* must be
    Home Assistant's zone whenever *moment* came off a stored ISO string: such a
    string carries a bare offset, and an anchor from July read at a July offset in
    November lands an hour away from every November date.
    """
    if tz is not None:
        moment = moment.astimezone(tz)
    probe = moment - timedelta(microseconds=1)
    try:
        return next_fixed_occurrence(anchor, rule, after=probe) == moment
    except ValueError:
        return False


def task_moves(task: dict) -> list[tuple[datetime, datetime]]:
    """A fixed *task*'s moves as ``(from, to)`` datetimes."""
    return _parsed_moves(task.get("moved_occurrences"))


def is_task_occurrence(
    task: dict, moment: datetime, *, tz: tzinfo | None = None
) -> bool:
    """Whether *moment* is a date of a fixed *task*'s schedule, moves included.

    A snooze or due-today puts ``next_due`` off the schedule; this is how the
    calendar and the engine tell the two apart. Pass Home Assistant's zone as *tz*
    for a *moment* read from storage (see :func:`is_rule_occurrence`).
    """
    anchor = _parse(task["anchor"])
    assert anchor is not None
    if tz is not None:
        moment = moment.astimezone(tz)
    return _is_occurrence(task, anchor, moment)


def next_task_occurrence(task: dict, *, after: datetime) -> datetime:
    """:func:`next_fixed_occurrence` for a fixed *task*, moves included."""
    anchor = _parse(task["anchor"])
    assert anchor is not None
    return next_fixed_occurrence(
        anchor, task_rule(task), after=after, moves=task.get("moved_occurrences")
    )


def expand_task_occurrences(
    task: dict, start: datetime, end: datetime
) -> list[datetime]:
    """:func:`expand_fixed_occurrences` for a fixed *task*, moves included."""
    anchor = _parse(task["anchor"])
    assert anchor is not None
    return expand_fixed_occurrences(
        anchor, task_rule(task), start, end, moves=task.get("moved_occurrences")
    )


def upcoming_occurrences(
    task: dict, *, now: datetime, count: int
) -> list[dict[str, str | None]]:
    """The next *count* dates of a fixed *task*, as ``{start, moved_from}`` rows.

    ``start`` is the date as the schedule now holds it; ``moved_from`` is the original
    date when that row is a move, else ``None``. The panel's Upcoming block and the
    card's "A later date" list read this, so both say exactly what the calendar says.
    A season is applied the same way :func:`compute_next_due` applies it.
    """
    moved_to = {
        _instant(dst): src for src, dst in _parsed_moves(task.get("moved_occurrences"))
    }
    rows: list[dict[str, str | None]] = []
    probe = now
    for _ in range(count * 4):
        if len(rows) >= count:
            break
        try:
            occ = _clamp_season(next_task_occurrence(task, after=probe), task)
        except ValueError:
            break
        src = moved_to.get(_instant(occ))
        rows.append(
            {"start": occ.isoformat(), "moved_from": src.isoformat() if src else None}
        )
        probe = occ
    return rows


def move_occurrence(
    task: dict, occurrence: datetime, to: datetime, *, now: datetime
) -> tuple[dict, datetime, datetime | None]:
    """Move one date of *task*'s fixed schedule to *to*.

    Returns ``(task, original, previous_to)``: the mutated task, the date on the rule
    that moved, and where that date was before this call (``None`` when it had not
    moved).

    *occurrence* names the date on the **rule** (the original date). Moving a date that
    is already moved changes where it goes, so the badge keeps saying where it came
    from; moving it back to its own date removes the move. *occurrence* may also be
    the *current* date of a move, which is what a calendar shows and hands back.

    ``next_due`` is recomputed when the date the task is showing is the one that moved
    (or the new date comes before it). A snooze or due-today is off the schedule, so it
    is left alone.

    Raises ``ValueError`` when *occurrence* is not a date of the schedule, when *to* is
    in the past, or when *to* is already a date of the schedule.
    """
    if task.get("recurrence_type") != REC_FIXED:
        raise ValueError("only a fixed task has dates to move")
    anchor = _parse(task["anchor"])
    assert anchor is not None
    rule = task_rule(task)
    # Every instant here is judged in Home Assistant's zone (the zone of *now*). A
    # date handed in as an offset string — the panel, the card and the service all
    # send one — would otherwise be expanded at its own offset, which is an hour off
    # for half the year (see :func:`is_rule_occurrence`).
    zone = now.tzinfo
    occurrence = (
        occurrence.replace(tzinfo=zone) if occurrence.tzinfo is None else occurrence
    ).astimezone(zone)
    to = (to.replace(tzinfo=zone) if to.tzinfo is None else to).astimezone(zone)
    rows = [
        (dict(m), pair)
        for m in task.get("moved_occurrences") or []
        if (pair := _parse_move(m)) is not None
    ]
    # A calendar hands back the date it showed, which for a moved date is the ``to``.
    for _, (src, dst) in rows:
        if _instant(dst) == _instant(occurrence):
            occurrence = src.astimezone(zone)
            break
    previous_to = next(
        (
            dst.astimezone(zone)
            for _, (src, dst) in rows
            if _instant(src) == _instant(occurrence)
        ),
        None,
    )
    if not is_rule_occurrence(anchor, rule, occurrence):
        raise ValueError(f"{occurrence.isoformat()} is not a date of this schedule")
    others = [
        (m, pair) for m, pair in rows if _instant(pair[0]) != _instant(occurrence)
    ]
    keep = [m for m, _ in others]
    if _instant(to) == _instant(occurrence) and previous_to is not None and to <= now:
        # Putting a date back on its own day when that day has passed would take it
        # off every surface at once: it is behind now, and no longer moved ahead.
        raise ValueError("the original date has passed, so the move cannot be undone")
    if _instant(to) != _instant(occurrence):
        if to <= now:
            raise ValueError("a date can only move to a time in the future")
        taken = is_rule_occurrence(anchor, rule, to) or any(
            _instant(dst) == _instant(to) for _, (_, dst) in others
        )
        if taken:
            raise ValueError(f"{to.isoformat()} is already a date of this schedule")
        if len(keep) >= MAX_MOVED_OCCURRENCES:
            raise ValueError("too many moved dates on this task")
        keep.append({"from": occurrence.isoformat(), "to": to.isoformat()})
    shown = _parse(task.get("next_due"))
    if shown is not None:
        shown = shown.astimezone(zone)
    # Which date the task shows now, judged against the moves *before* this one.
    on_schedule = shown is not None and _is_occurrence(task, anchor, shown)
    task["moved_occurrences"] = keep
    if shown is None:
        task["next_due"] = compute_next_due(task, now=now).isoformat()
    elif on_schedule and (
        _instant(shown) == _instant(occurrence)
        or any(
            _instant(shown) == _instant(dst)
            for _, (src, dst) in rows
            if _instant(src) == _instant(occurrence)
        )
        or (now < to < shown)
    ):
        # The shown date is the one that moved, or the new date comes first. A
        # snooze or due-today is not on the schedule, so it keeps its date.
        task["next_due"] = compute_next_due(task, now=now).isoformat()
    return task, occurrence, previous_to


def prune_moves(task: dict, *, before: datetime) -> dict:
    """Drop the moves whose original and new dates are both before *before*.

    A move that is fully in the past changes nothing any more, and keeping it would let
    the list grow without end.
    """
    moves = task.get("moved_occurrences")
    if not moves:
        return task
    kept = []
    for move in moves:
        pair = _parse_move(move)
        if pair is not None and (pair[0] >= before or pair[1] >= before):
            kept.append(move)
    task["moved_occurrences"] = kept
    return task


def _parse(value: str | datetime | None) -> datetime | None:
    """Parse an ISO string into an aware datetime (pass-through for datetimes)."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def compute_next_due(task: dict, *, now: datetime) -> datetime:
    """Compute next_due for *task* from its current state (no mutation)."""
    rec_type = task.get("recurrence_type", REC_FLOATING)
    if rec_type == REC_FLOATING:
        return _clamp_season(
            compute_floating_next_due(
                _parse(task.get("last_completed")),
                int(task["interval"]),
                task["unit"],
                now=now,
            ),
            task,
        )
    if rec_type == REC_FIXED:
        return _clamp_season(next_task_occurrence(task, after=now), task)
    if rec_type in (REC_TRIGGERED, REC_SENSOR):
        # A condition/sensor-driven task has no schedule: computing a due date means
        # *arming* it (the condition is true), so it reads as due-now. Going
        # dormant is the asymmetric job of ``apply_completion`` (next_due -> None);
        # this function is only ever called to (re)arm. A sensor task is armed by the
        # watcher (``store.trigger_task``); ``build_task`` starts it dormant.
        return now
    if rec_type == REC_ONE_OFF:
        # A do-once task is due at its stored ``due`` date. Going dormant on
        # completion is ``apply_completion``'s job (next_due -> None); this function
        # only ever (re)arms it back to ``due`` (e.g. when a completion is undone).
        due = _parse(task["due"])
        assert due is not None
        return due
    if rec_type == REC_USE:
        # Every other type answers "when is this due?" with a date. A use task answers
        # it with "never": nothing arms it, so there is no correct datetime to return
        # and returning ``now`` (the triggered/sensor answer) would strand a counting
        # task as permanently overdue on every time surface. Each of the 5 callers
        # below skips a use task before reaching here, so this is a regression guard
        # rather than a live path — loud on purpose, because the silent alternative
        # ships a wrong due date.
        raise ValueError("a use task is never due; nothing arms it")
    raise ValueError(f"unknown recurrence_type: {rec_type!r}")


def _record_entry(history: Iterable[dict], entry: dict) -> list[dict]:
    """Return *history* with *entry* recorded, deduped on ``ts`` and capped.

    Shared by the completion log and the skip log: both are ``ts``-keyed lists of
    dated entries with the same identity rule, so they get the same insert. A second
    entry at the exact same instant (a double-tapped notification action, a duplicated
    automation) would otherwise create an ambiguous twin that undo/edit can't tell
    apart, so it *replaces* the entry already at that ``ts`` rather than appending.
    """
    entries = list(history)
    ts_iso = entry["ts"]
    dup = next((i for i, e in enumerate(entries) if e.get("ts") == ts_iso), None)
    if dup is not None:
        entries[dup] = entry
    else:
        entries.append(entry)
    # `>=` here would be equivalent, not a bug: at exactly the cap the slice returns
    # the same entries, so only the strict form is observable.
    if len(entries) > MAX_COMPLETION_HISTORY:  # pragma: no mutate
        entries = entries[-MAX_COMPLETION_HISTORY:]
    return entries


def _is_occurrence(task: dict, anchor: datetime, moment: datetime) -> bool:
    """Whether *moment* is one of the schedule's own occurrences.

    Asked for exactly one instant per call, so it is answered by asking the grid for
    the occurrence after the moment before *moment*: a date on the grid is its own
    answer. An off-grid date belongs to a snooze or a due-today rather than to the
    schedule, and :func:`_advance_fixed_schedule` must not move the schedule past it.

    A season is not consulted. ``_clamp_season`` only ever returns a grid occurrence,
    so a clamped ``next_due`` passes here, and a raw grid date that the season would
    reject is still a date the schedule owns.
    """
    probe = moment - timedelta(microseconds=1)
    try:
        return next_task_occurrence(task, after=probe) == moment
    except ValueError:
        return False


def _advance_fixed_schedule(task: dict, *, now: datetime) -> str:
    """The ``next_due`` a fixed task moves to once its occurrence is dealt with.

    Shared by :func:`apply_completion` and :func:`skip_occurrence`, because completing
    an occurrence and skipping it move the schedule in exactly the same way — only the
    log each one writes is different.

    The schedule advances past ``max(now, next_due)``, and both halves earn their keep:

    * **Past ``next_due``**, because the occurrence the task is *showing* is the one
      the user just dealt with. Advancing past ``now`` alone hands that occurrence
      straight back whenever the task is completed before its time of day: a task
      anchored at 10:00 and marked done at 09:00 stayed due at 10:00 today, so the
      completion read as though it had done nothing (#331). An anchor late in the
      evening was unusable that way for nearly the whole day.
    * **Past ``now``**, because an overdue task must not crawl the grid one missed
      occurrence per press. A daily task last due a fortnight ago lands on the next
      occurrence after today, collapsing the fortnight into a single step.

    A task with no ``next_due`` has no occurrence on the board, so *now* is the whole
    answer. ``models.build_task`` reaches this state on purpose: a ``last_completed``
    seed is recorded as a completion *before* the schedule is ever computed.

    This is deliberately not what :func:`compute_next_due` does. That function derives
    a due date from a task's own state with no memory of where the schedule already
    stood, which is what makes it the right tool for *rewinding* one (see
    :func:`remove_completion`) and the wrong tool for advancing it.
    """
    anchor = _parse(task["anchor"])
    assert anchor is not None
    current = _parse(task.get("next_due"))
    # ``current`` comes off a stored ISO string, so it carries a bare offset; re-home
    # it before ``max`` so the winner always hands ``next_fixed_occurrence`` a probe in
    # Home Assistant's zone (see ``_regrid``). Comparison itself is instant-based and
    # would be correct either way — it is the *tzinfo of the winner* that matters.
    if current is not None:
        current = current.astimezone(now.tzinfo)
        # ...and only when it really is an occurrence. ``next_due`` holds a *deferred*
        # instant after a snooze or a due-today, and neither of those is a date the
        # user dealt with — advancing past a snooze target threw away every occurrence
        # between the task's own one and the target, so snoozing a Monday task a week
        # and then doing it anyway lost the Monday in between. A deferred date reads as
        # "no occurrence on the board", which is the ``now``-only branch below.
        if not _is_occurrence(task, anchor, current):
            current = None
    after = max(now, current) if current is not None else now
    # Moves fully before the date being dealt with change nothing any more.
    prune_moves(task, before=min(after, now) - timedelta(days=1))
    return _clamp_season(next_task_occurrence(task, after=after), task).isoformat()


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
    * fixed     -> the next scheduled occurrence after the one the task was showing
      (schedule-driven; the completion marks that occurrence done rather than
      restarting a clock — see :func:`_advance_fixed_schedule`)
    * triggered -> ``next_due = None`` (dormant): completing a condition-driven
      task *clears* the condition rather than rescheduling it, so it leaves every
      time surface until the owner re-arms it. History is still recorded, so the
      replacement cadence accumulates on the task.
    """
    # A caller-supplied ``completed_at`` may be naive (HA's ``cv.datetime`` parses
    # offset-less strings naively). Qualify it with *now*'s zone before it is
    # persisted anywhere: a naive ``last_completed``/``ts``/``next_due`` poisons the
    # store — every later aware-vs-naive comparison (``is_overdue``, history ``max``)
    # raises ``TypeError`` until the storage file is hand-edited.
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=now.tzinfo)
    ts_iso = completed_at.isoformat()
    entry: dict = {"ts": ts_iso}
    if metadata:
        entry.update(metadata)
    task["completions"] = _record_entry(task.get("completions", []), entry)
    task["last_completed"] = completed_at.isoformat()

    rec_type = task.get("recurrence_type", REC_FLOATING)
    if rec_type == REC_FLOATING:
        task["next_due"] = _clamp_season(
            compute_floating_next_due(
                completed_at, int(task["interval"]), task["unit"], now=now
            ),
            task,
        ).isoformat()
    elif rec_type == REC_FIXED:
        task["next_due"] = _advance_fixed_schedule(task, now=now)
    elif rec_type in (REC_TRIGGERED, REC_ONE_OFF, REC_SENSOR, REC_USE):
        # A one-off is permanently complete; a triggered task clears its condition; a
        # sensor task's crossing has been actioned (and its meter reset by the store,
        # which has the live reading). All go dormant (every time surface drops them).
        # Undoing the completion re-arms a one-off (see ``remove_completion``); a
        # triggered task is re-armed only by its owning integration, and a sensor task
        # only by the watcher on a fresh crossing.
        #
        # A use task is the odd one here: it was already dormant and stays dormant, so
        # this assignment changes nothing. Completing it is not "done with the thing" —
        # it is the *record of 1 use*, and the entry this call just appended to
        # ``completions`` is the whole point. The replacement task beside it is what
        # comes due, armed by ``coordinator.async_settle_use_tasks`` once enough
        # entries accumulate.
        task["next_due"] = None
    else:
        raise ValueError(f"unknown recurrence_type: {rec_type!r}")
    return task


def skip_occurrence(task: dict, *, now: datetime, metadata: dict | None = None) -> dict:
    """Return *task* advanced past its current occurrence with **no** completion.

    "Skip this one" — move the task forward off every time surface without recording
    that it was *done*. The maintenance log (``completions``) and ``last_completed``
    stay untouched, so a floating task's clock is not reset and every completion count,
    cadence average and "last done" reading is unaffected: a skip is the record of
    deliberately *not* doing the thing.

    The skip is still logged, in its own ``skips`` list — same ``ts``-keyed entry shape
    as a completion, carrying the same optional *metadata* (``note``/``who``, plus
    ``reading`` for a meter task) — so the panel can show it in history and the user
    can amend or undo it. Keeping the two lists apart is what makes "a skip is not a
    completion" true by construction rather than by filtering at eighteen call sites.

    ``next_due`` moves; because it does, the coordinator's edge detection re-arms the
    overdue/due-soon announcements for the new date.

    * floating  -> ``now + interval·unit`` (a fresh interval from now; the next
      completion still measures from *its* ``completed_at``).
    * fixed     -> the next scheduled occurrence strictly after ``max(now, next_due)``,
      exactly as a completion advances it (:func:`_advance_fixed_schedule`). An
      upcoming task advances exactly one occurrence; an overdue task jumps to the next
      occurrence after *now*, collapsing any already-missed occurrences rather than
      taking one skip per missed period.
    * one-off / triggered / sensor -> dormant (``next_due = None``): there is no "next"
      occurrence to advance to, so skipping clears it from every time surface (a
      triggered/sensor task is re-armed only by its owner/the watcher; a one-off stays
      done unless its completion is undone).
    """
    entry: dict = {"ts": now.isoformat()}
    if metadata:
        entry.update(metadata)
    task["skips"] = _record_entry(task.get("skips", []), entry)

    rec_type = task.get("recurrence_type", REC_FLOATING)
    if rec_type == REC_FLOATING:
        task["next_due"] = _clamp_season(
            add_interval(now, int(task["interval"]), task["unit"]), task
        ).isoformat()
    elif rec_type == REC_FIXED:
        task["next_due"] = _advance_fixed_schedule(task, now=now)
    elif rec_type in (REC_TRIGGERED, REC_ONE_OFF, REC_SENSOR, REC_USE):
        # A use task is already dormant, so this is a no-op on ``next_due``. The skip
        # is still logged: "I deliberately did not use it today" is a legitimate thing
        # to record, and it stays out of ``completions``, so it never counts as a use.
        task["next_due"] = None
    else:
        raise ValueError(f"unknown recurrence_type: {rec_type!r}")
    return task


def record_skip(
    task: dict, skipped_at: datetime, *, metadata: dict | None = None
) -> dict:
    """Return *task* with a skip **logged** at *skipped_at*, leaving ``next_due`` alone.

    The back-dated half of :func:`skip_occurrence`, for replaying a history that
    already happened (see ``transfer.py``). A skip recorded for 2019 says an
    occurrence was passed over then; running the live schedule math for it against
    today's clock would invent a due date nobody ever saw. Whatever the task does
    next is decided by the events after it, or — when it is the last one — by the
    schedule ``build_task`` already computed.

    Shares :func:`_record_entry` with the live path, so a backfilled skip gets the
    same ``ts`` dedupe and the same history cap as one taken today.
    """
    if skipped_at.tzinfo is None:
        raise ValueError("skipped_at must be timezone-aware")
    entry: dict = {"ts": skipped_at.isoformat()}
    if metadata:
        entry.update(metadata)
    task["skips"] = _record_entry(task.get("skips", []), entry)
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
    elif rec_type not in (REC_TRIGGERED, REC_SENSOR, REC_USE):
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


def move_completion(task: dict, old_ts: str, new_ts: str, *, now: datetime) -> dict:
    """Return *task* with the completion at *old_ts* re-timestamped to *new_ts*.

    Back-dates (or corrects) an already-recorded completion — distinct from
    ``update_completion`` (which edits metadata but never ``ts``) and from deleting
    and re-adding (which would lose the entry's metadata and re-stamp it at "now").
    A caller-supplied *new_ts* may be naive (the ``move_completion`` service's
    ``new_completed_at`` field is ``cv.datetime``, which — like ``complete_task``'s
    ``completed_at`` — accepts an offset-less value); it is qualified with *now*'s
    zone the same way ``apply_completion`` does.

    Removes the entry at *old_ts* (raising ``ValueError`` if none matches — mirrors
    ``update_completion``'s missing-``ts`` behaviour) and re-inserts it at *new_ts*,
    preserving its metadata. Colliding with an existing entry already at *new_ts*
    replaces it (the same same-instant dedup ``apply_completion`` does); the moved
    entry's metadata wins and the entry it collided with is discarded.

    Triggered/sensor tasks' ``next_due`` is left untouched, and so is a **fixed**
    task's: its due date is schedule state that completing or skipping already moved
    on (:func:`_advance_fixed_schedule`), not a value derived from the log, so
    recomputing it from the anchor here would rewind the task onto an occurrence it
    has already dealt with. Only :func:`remove_completion` rewinds, because an undo is
    meant to.

    Both the removal and the re-insertion happen *before* ``last_completed``/
    ``next_due`` are re-derived — re-deriving in between (as if this were
    ``remove_completion`` followed by a separate insert) would misfire for a one-off
    task: removing its only completion looks like "history now empty" and re-arms
    ``next_due`` to ``due``, which would be wrong once the moved entry lands back in
    history. Deriving once from the final, post-move history avoids that: a one-off
    with its only completion moved stays dormant (``next_due = None``), exactly as it
    was before the move. Triggered/sensor tasks' ``next_due`` is left untouched, same
    as ``remove_completion`` — their armed/dormant state is condition-driven, not
    history-driven, and this function does not validate the new timestamp against it
    (a manual history edit is not schedule-validated, same as ``update_completion``/
    ``remove_completion`` today).
    """
    history = list(task.get("completions", []))
    index = next((i for i, e in enumerate(history) if e.get("ts") == old_ts), None)
    if index is None:
        raise ValueError(f"no completion at {old_ts!r}")
    entry = dict(history[index])
    del history[index]

    new_dt = _parse(new_ts)
    assert new_dt is not None
    if new_dt.tzinfo is None:
        new_dt = new_dt.replace(tzinfo=now.tzinfo)
    new_ts_iso = new_dt.isoformat()
    entry["ts"] = new_ts_iso
    dup = next((i for i, e in enumerate(history) if e.get("ts") == new_ts_iso), None)
    if dup is not None:
        history[dup] = entry
    else:
        history.append(entry)
    task["completions"] = history

    # Unlike remove_completion, history can never be empty here: removing old_ts
    # always re-inserts (or collapses) exactly one entry, so there's always a
    # latest to derive last_completed from.
    latest = max(history, key=lambda e: datetime.fromisoformat(e["ts"]))
    task["last_completed"] = latest["ts"]

    rec_type = task.get("recurrence_type")
    if rec_type == REC_ONE_OFF:
        # A moved completion is still a completion: history is never empty here
        # (see above), so a one-off always stays dormant post-move — it only
        # re-arms via remove_completion, which can genuinely empty history.
        task["next_due"] = None
    elif rec_type not in (REC_TRIGGERED, REC_SENSOR, REC_FIXED, REC_USE):
        task["next_due"] = compute_next_due(task, now=now).isoformat()
    return task


def update_skip(
    task: dict, ts: str, metadata: dict, *, fields: tuple[str, ...]
) -> dict:
    """Edit the metadata of the skip at ISO timestamp *ts* in place.

    The skip twin of :func:`update_completion`, with the same clear-on-empty rule: a
    non-empty value in *metadata* is set, an absent or empty one removes the key, so
    blanking a note deletes it rather than storing ``""``. ``ts`` and the schedule are
    never touched — amending the log must not re-time or re-arm anything.

    Unlike the completion twin it returns just the task: a skip carries no ``photo``,
    so there is never an orphaned upload for the caller to clean up. Raises
    ``ValueError`` when no skip matches *ts*, mirroring ``update_completion``.
    """
    skips = list(task.get("skips", []))
    target = next((e for e in skips if e.get("ts") == ts), None)
    if target is None:
        raise ValueError(f"no skip at {ts!r}")
    for key in fields:
        value = metadata.get(key)
        if value in (None, ""):
            target.pop(key, None)
        else:
            target[key] = value
    task["skips"] = skips
    return task


def remove_skip(task: dict, ts: str) -> dict:
    """Return *task* with the skip at ISO timestamp *ts* removed.

    Undoes a skip. Unlike :func:`remove_completion` there is nothing to re-derive:
    skips never set ``last_completed``, and ``next_due`` was advanced by the skip at
    the time rather than computed from the log, so re-deriving it here would be
    guesswork about a schedule the user may have since moved on from. Restoring a
    usage meter's baseline *is* real state and is the store's job (it holds the
    ``meter_start`` the skip recorded). A no-op when *ts* is not present.
    """
    task["skips"] = [e for e in task.get("skips", []) if e.get("ts") != ts]
    return task


def move_skip(task: dict, old_ts: str, new_ts: str, *, now: datetime) -> dict:
    """Return *task* with the skip at *old_ts* re-timestamped to *new_ts*.

    The skip twin of :func:`move_completion`, minus the re-derivation: see
    :func:`remove_skip` for why a skip's timestamp does not drive the schedule.
    A naive *new_ts* is qualified with *now*'s zone the same way, and colliding with
    an existing skip at *new_ts* replaces it (the moved entry's metadata wins).
    Raises ``ValueError`` when no skip matches *old_ts*.
    """
    skips = list(task.get("skips", []))
    index = next((i for i, e in enumerate(skips) if e.get("ts") == old_ts), None)
    if index is None:
        raise ValueError(f"no skip at {old_ts!r}")
    entry = dict(skips[index])
    del skips[index]

    new_dt = _parse(new_ts)
    assert new_dt is not None
    if new_dt.tzinfo is None:
        new_dt = new_dt.replace(tzinfo=now.tzinfo)
    entry["ts"] = new_dt.isoformat()
    task["skips"] = _record_entry(skips, entry)
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


def one_off_completed(task: dict) -> bool:
    """True for a do-once task that is already done (dormant, not re-armed).

    Completing a one-off clears ``next_due`` permanently and stamps
    ``last_completed``; undoing that completion re-arms ``next_due``. Several
    surfaces need exactly this shape — the to-do list drops a finished one-off
    (#221), the shopping-list mirror checks a bought reminder off, and
    :func:`one_off_expired` layers a retention window on top — so it lives here
    once rather than being re-derived at each call site.
    """
    return (
        task.get("recurrence_type") == REC_ONE_OFF
        and not task.get("next_due")
        and bool(task.get("last_completed"))
    )


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
    if not one_off_completed(task):
        return False
    completed = _parse(task.get("last_completed"))
    if completed is None:  # pragma: no mutate - unreachable: one_off_completed
        return False  # pragma: no mutate - already required a truthy stamp
    return now >= completed + timedelta(days=retention_days)
