"""Unit tests for the calendar entity's window semantics (``calendar.py``).

The calendar entity is a thin projection over the pure ``recurrence`` engine, but
it imports Home Assistant (``CalendarEntity``/``CoordinatorEntity``/``dt_util``).
Rather than pull in the full HA test harness, we load ``calendar.py`` under the
same synthetic ``hk`` package used by the other pure unit tests (see
``tests/conftest.py``), stubbing only the handful of HA symbols it references.
This keeps the high-value window-overlap logic (N6) under fast, deterministic
unit coverage; the store/entity wiring is exercised by the integration suite.
"""

from __future__ import annotations

import importlib.util
import sys
import types
import typing
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=-4))


def _dt(y, mo, d, h=0, mi=0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=TZ)


def _install_ha_stubs() -> None:
    """Register minimal stand-ins for the HA symbols ``calendar.py`` imports.

    Only installed when Home Assistant isn't importable (the pure-unit
    environment). When real HA is present these modules already exist and are
    left untouched.
    """
    try:  # pragma: no cover - depends on environment
        import homeassistant  # noqa: F401

        return
    except ImportError:
        pass

    def _mod(name: str) -> types.ModuleType:
        m = types.ModuleType(name)
        sys.modules[name] = m
        return m

    ha = _mod("homeassistant")
    _mod("homeassistant.components")
    ha.components = sys.modules["homeassistant.components"]

    comp_cal = _mod("homeassistant.components.calendar")

    class CalendarEntity:
        pass

    class CalendarEvent:
        def __init__(self, summary, start, end, uid, description=None):
            self.summary = summary
            self.start = start
            self.end = end
            self.uid = uid
            self.description = description

    comp_cal.CalendarEntity = CalendarEntity
    comp_cal.CalendarEvent = CalendarEvent

    config_entries = _mod("homeassistant.config_entries")
    config_entries.ConfigEntry = type("ConfigEntry", (), {})

    core = _mod("homeassistant.core")
    core.HomeAssistant = type("HomeAssistant", (), {})

    _mod("homeassistant.helpers")
    entity_platform = _mod("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = object

    update_coordinator = _mod("homeassistant.helpers.update_coordinator")
    _T = typing.TypeVar("_T")

    class CoordinatorEntity(typing.Generic[_T]):
        def __init__(self, coordinator):
            self.coordinator = coordinator

    update_coordinator.CoordinatorEntity = CoordinatorEntity

    util = _mod("homeassistant.util")
    dt = _mod("homeassistant.util.dt")

    def parse_datetime(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    def now():  # overridden per-test via monkeypatch
        raise AssertionError("dt_util.now() must be patched in tests")

    dt.parse_datetime = parse_datetime
    dt.now = now
    util.dt = dt


def _load_calendar() -> types.ModuleType:
    """Load ``calendar.py`` as ``hk.calendar`` so its relative imports resolve."""
    if "hk.calendar" in sys.modules:
        return sys.modules["hk.calendar"]
    _install_ha_stubs()
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
