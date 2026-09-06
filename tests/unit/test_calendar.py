"""Unit tests for the calendar entity's window semantics (``calendar.py``).

The calendar entity is a thin projection over the pure ``recurrence`` engine, but
it imports Home Assistant (``CalendarEntity``/``CoordinatorEntity``/``dt_util``).
Rather than pull in the full HA test harness, we load ``calendar.py`` under the
same synthetic ``hk`` package used by the other pure unit tests (see
``tests/conftest.py``), over the shared stub tree in ``ha_stubs.py``. This keeps
the high-value window-overlap logic (N6) under fast, deterministic unit
coverage; the store/entity wiring is exercised by the integration suite.

The clock comes from that tree's ``dt_util.now``, which raises until a test
patches it — so an occurrence test that forgot to say *when* it is fails loudly
rather than drifting with today's date.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ha_stubs import install_ha_stubs

TZ = timezone(timedelta(hours=-4))


def _dt(y, mo, d, h=0, mi=0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=TZ)


def _load_calendar() -> types.ModuleType:
    """Load ``calendar.py`` as ``hk.calendar`` so its relative imports resolve."""
    if "hk.calendar" in sys.modules:
        return sys.modules["hk.calendar"]
    install_ha_stubs()
    # ``from .coordinator import HomeKeeperCoordinator`` — the real module pulls in
    # HA/store; the entity only needs the name for typing, so stub it.
    if "hk.coordinator" not in sys.modules:
        coord = types.ModuleType("hk.coordinator")
        coord.HomeKeeperCoordinator = type("HomeKeeperCoordinator", (), {})
        sys.modules["hk.coordinator"] = coord
    component_dir = (
        Path(__file__).resolve().parent.parent.parent
        / "custom_components"
        / "home_keeper"
    )
    spec = importlib.util.spec_from_file_location(
        "hk.calendar", str(component_dir / "calendar.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hk.calendar"] = module
    spec.loader.exec_module(module)
    return module


cal = _load_calendar()


def _entity(tasks: dict) -> object:
    """Build a calendar entity backed by an in-memory coordinator (no __init__)."""
    entity = object.__new__(cal.HomeKeeperCalendarEntity)
    entity.coordinator = types.SimpleNamespace(data=tasks)
    return entity


def _fixed_task(anchor: datetime, freq="DAILY", interval=1, **over) -> dict:
    task = {
        "id": "t_fixed",
        "name": "Fixed chore",
        "recurrence_type": "fixed",
        "freq": freq,
        "interval": interval,
        "anchor": anchor.isoformat(),
        "enabled": True,
    }
    task.update(over)
    return task


def _floating_task(next_due: datetime, **over) -> dict:
    task = {
        "id": "t_float",
        "name": "Floating chore",
        "recurrence_type": "floating",
        "next_due": next_due.isoformat(),
        "enabled": True,
    }
    task.update(over)
    return task


# EVENT_DURATION is 1 hour in calendar.py.
DUR = cal.EVENT_DURATION
assert timedelta(hours=1) == DUR


# --- (a) event property: occurrence active during its window ----------------


def test_event_returns_in_progress_fixed_occurrence(monkeypatch):
    """A fixed occurrence that started 30 min ago is still the active event."""
    anchor = _dt(2026, 6, 1, 9)  # 09:00 daily
    now = _dt(2026, 6, 15, 9, 30)  # 30 min into the 09:00 occurrence
    monkeypatch.setattr(cal.dt_util, "now", lambda: now)

    entity = _entity({"t_fixed": _fixed_task(anchor)})
    event = entity.event

    assert event is not None
    # The active (in-progress) occurrence is 09:00 today, not tomorrow's 09:00.
    assert event.start == _dt(2026, 6, 15, 9)
    assert event.end == _dt(2026, 6, 15, 10)


def test_event_returns_in_progress_floating_occurrence(monkeypatch):
    """The floating branch keeps an in-progress occurrence active (baseline)."""
    now = _dt(2026, 6, 15, 9, 30)
    monkeypatch.setattr(cal.dt_util, "now", lambda: now)

    entity = _entity({"t_float": _floating_task(_dt(2026, 6, 15, 9))})
    event = entity.event

    assert event is not None
    assert event.start == _dt(2026, 6, 15, 9)


def test_event_skips_fixed_occurrence_after_window_ends(monkeypatch):
    """Once the window has fully passed, the next occurrence is returned."""
    anchor = _dt(2026, 6, 1, 9)
    now = _dt(2026, 6, 15, 10, 30)  # 90 min past the 09:00 start → window over
    monkeypatch.setattr(cal.dt_util, "now", lambda: now)

    entity = _entity({"t_fixed": _fixed_task(anchor)})
    event = entity.event

    assert event is not None
    # 09:00 today has ended (10:00); the soonest live occurrence is tomorrow 09:00.
    assert event.start == _dt(2026, 6, 16, 9)


# --- (b) get_events: window start falling inside an occurrence's window ------


def test_collect_events_includes_fixed_occurrence_overlapping_window_start():
    anchor = _dt(2026, 6, 1, 9)
    entity = _entity({"t_fixed": _fixed_task(anchor)})

    # Window starts at 09:30, i.e. inside the 09:00 occurrence's [09:00,10:00) window.
    start = _dt(2026, 6, 15, 9, 30)
    end = _dt(2026, 6, 15, 23)
    starts = [e.start for e in entity._collect_events(start, end)]

    assert _dt(2026, 6, 15, 9) in starts  # overlapping-start occurrence included


def test_collect_events_includes_floating_occurrence_overlapping_window_start():
    entity = _entity({"t_float": _floating_task(_dt(2026, 6, 15, 9))})

    start = _dt(2026, 6, 15, 9, 30)  # inside the [09:00,10:00) window
    end = _dt(2026, 6, 16, 0)
    starts = [e.start for e in entity._collect_events(start, end)]

    assert _dt(2026, 6, 15, 9) in starts


def test_collect_events_excludes_occurrence_ended_before_window():
    """A non-overlapping past occurrence stays excluded (no double-count/leak)."""
    anchor = _dt(2026, 6, 1, 9)
    entity = _entity({"t_fixed": _fixed_task(anchor)})

    # Window starts at 10:30 — after the 09:00 occurrence's window fully ended.
    start = _dt(2026, 6, 15, 10, 30)
    end = _dt(2026, 6, 16, 23)
    starts = [e.start for e in entity._collect_events(start, end)]

    assert _dt(2026, 6, 15, 9) not in starts  # ended (10:00) before window start
    assert _dt(2026, 6, 16, 9) in starts  # tomorrow's occurrence is inside window


def test_collect_events_normal_window_returns_each_occurrence_once():
    """A plain multi-day window lists each daily occurrence exactly once."""
    anchor = _dt(2026, 6, 1, 9)
    entity = _entity({"t_fixed": _fixed_task(anchor)})

    start = _dt(2026, 6, 15, 0)
    end = _dt(2026, 6, 18, 0)  # covers 15th, 16th, 17th 09:00 occurrences
    starts = [e.start for e in entity._collect_events(start, end)]

    assert starts == [
        _dt(2026, 6, 15, 9),
        _dt(2026, 6, 16, 9),
        _dt(2026, 6, 17, 9),
    ]


# --- (c) active season: the calendar shows only in-season occurrences --------


def test_event_skips_ahead_to_the_first_in_season_occurrence(monkeypatch):
    """A daily task in December, restricted to a single day in April."""
    anchor = _dt(2026, 6, 1, 9)
    now = _dt(2026, 12, 15, 8)
    monkeypatch.setattr(cal.dt_util, "now", lambda: now)

    task = _fixed_task(anchor, active_season=[{"start": "04-10", "end": "04-10"}])
    event = _entity({"t_fixed": task}).event

    assert event is not None
    assert event.start == _dt(2027, 4, 10, 9)


def test_event_is_none_when_the_grid_never_lands_in_the_season(monkeypatch):
    """A grid that cannot intersect its season leaves the task off the calendar.

    Every 12 months from a January anchor, in a March-only season: the grid only
    ever lands in January, so the search exhausts its iteration bound. Nothing is
    shown rather than a date outside the season being invented — the task is still
    in the panel and on the to-do list, which is where it is acted on.
    """
    anchor = _dt(2026, 1, 15, 9)
    now = _dt(2026, 6, 15, 8)
    monkeypatch.setattr(cal.dt_util, "now", lambda: now)

    task = _fixed_task(
        anchor,
        freq="MONTHLY",
        interval=12,
        active_season=[{"start": "03-01", "end": "03-31"}],
    )

    assert _entity({"t_fixed": task}).event is None


def test_collect_events_drops_occurrences_outside_every_season_window():
    """Two windows, and a stretch of the year covered by neither."""
    anchor = _dt(2026, 1, 1, 9)  # daily at 09:00
    task = _fixed_task(
        anchor,
        active_season=[
            {"start": "04-01", "end": "04-03"},
            {"start": "04-06", "end": "04-07"},
        ],
    )
    entity = _entity({"t_fixed": task})

    starts = [e.start for e in entity._collect_events(_dt(2026, 4, 1), _dt(2026, 4, 9))]

    assert starts == [
        _dt(2026, 4, 1, 9),
        _dt(2026, 4, 2, 9),
        _dt(2026, 4, 3, 9),
        _dt(2026, 4, 6, 9),
        _dt(2026, 4, 7, 9),
    ]


def test_collect_events_keeps_a_wrapping_season_across_the_new_year():
    """November through March includes both sides of the year boundary."""
    anchor = _dt(2026, 1, 1, 9)
    task = _fixed_task(anchor, active_season=[{"start": "11-01", "end": "03-31"}])
    entity = _entity({"t_fixed": task})

    starts = [
        e.start for e in entity._collect_events(_dt(2026, 12, 30), _dt(2027, 1, 3))
    ]

    assert starts == [
        _dt(2026, 12, 30, 9),
        _dt(2026, 12, 31, 9),
        _dt(2027, 1, 1, 9),
        _dt(2027, 1, 2, 9),
    ]


def test_the_season_search_stops_at_its_iteration_bound(monkeypatch):
    """The walk toward an in-season occurrence is bounded, not open-ended.

    The pathological case above proves `None` comes back; this proves *why*. A grid
    that never lands in its season would otherwise walk forever, and a calendar read
    that never returns is worse than a task that isn't on the calendar. Shrinking the
    bound makes the count observable: the walk takes exactly that many steps and
    stops.
    """
    steps = 0
    real_next = cal.recurrence.next_fixed_occurrence

    def counted(*args, **kwargs):
        nonlocal steps
        steps += 1
        return real_next(*args, **kwargs)

    monkeypatch.setattr(cal.recurrence, "next_fixed_occurrence", counted)
    monkeypatch.setattr(cal.recurrence, "MAX_EXPAND_ITERATIONS", 5)
    monkeypatch.setattr(cal.dt_util, "now", lambda: _dt(2026, 6, 15, 8))

    task = _fixed_task(
        _dt(2026, 1, 15, 9),
        freq="MONTHLY",
        interval=12,
        active_season=[{"start": "03-01", "end": "03-31"}],
    )

    assert _entity({"t_fixed": task}).event is None
    # One call to find the first occurrence, then one per bounded step.
    assert steps == 6
