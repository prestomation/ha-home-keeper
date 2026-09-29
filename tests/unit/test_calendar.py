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


def test_collect_events_keeps_the_local_hour_across_a_dst_transition():
    """The calendar projects the anchor grid itself, so it drifts wherever the engine
    does. A stored anchor is offset-only (an ISO string has no zone identity), and
    Home Assistant hands ``async_get_events`` a window already through
    ``dt_util.as_local`` — so the window is what tells the grid which zone to hold.
    Without that, a 09:00 task would list at 08:00 for half the year and disagree with
    its own to-do entity.
    """
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/New_York")
    stored = datetime(2026, 6, 1, 9, tzinfo=zone).isoformat()
    entity = _entity({"t_fixed": _fixed_task(datetime.fromisoformat(stored))})

    # A window on the far side of the autumn transition, in the zone HA would pass.
    start = datetime(2026, 11, 5, 0, tzinfo=zone)
    end = datetime(2026, 11, 7, 0, tzinfo=zone)
    hours = {e.start.astimezone(zone).hour for e in entity._collect_events(start, end)}

    assert hours == {9}, f"occurrences drifted off 09:00 local: {sorted(hours)}"


# --- RRULE events, moved dates and the "Only this event" edit ---------------

import asyncio  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

import pytest  # noqa: E402

_HA_EXC = sys.modules["homeassistant.exceptions"]


def _rule_task(**over) -> dict:
    task = {
        "id": "t_bins",
        "name": "Take trash out",
        "recurrence_type": "fixed",
        "rrule": "FREQ=WEEKLY;BYDAY=TU,FR",
        "anchor": _dt(2026, 9, 29, 7).isoformat(),
        "moved_occurrences": [],
        "next_due": _dt(2026, 10, 2, 7).isoformat(),
        "enabled": True,
    }
    task.update(over)
    return task


class _Store:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.error: Exception | None = None

    async def move_occurrence(self, task_id, occurrence, to, *, origin=None):
        self.calls.append(("move", task_id, occurrence, to, origin))
        if self.error:
            raise self.error

    async def snooze_task(self, task_id, until, *, origin=None):
        self.calls.append(("snooze", task_id, until, origin))
        if self.error:
            raise self.error


def _editable(tasks: dict) -> tuple[object, _Store]:
    entity = _entity(tasks)
    store = _Store()
    refreshed: list[bool] = []

    async def refresh() -> None:
        refreshed.append(True)

    entity.coordinator.store = store
    entity.coordinator.async_request_refresh = refresh
    entity.coordinator.refreshed = refreshed
    return entity, store


@pytest.fixture
def local_tz(monkeypatch):
    """Make HA's local zone the suite's fixed offset for recurrence_id text."""
    monkeypatch.setattr(cal.dt_util, "as_local", lambda value: value.astimezone(TZ))
    monkeypatch.setattr(cal.dt_util, "get_default_time_zone", lambda: TZ)


def test_a_schedule_event_carries_its_rule_and_recurrence_id(local_tz):
    entity = _entity({"t_bins": _rule_task()})
    events = entity._collect_events(_dt(2026, 10, 1), _dt(2026, 10, 7))
    assert [e.start for e in events] == [_dt(2026, 10, 2, 7), _dt(2026, 10, 6, 7)]
    first = events[0]
    assert first.uid == "t_bins"
    assert first.rrule == "FREQ=WEEKLY;BYDAY=TU,FR"
    assert first.recurrence_id == "20261002T070000"


def test_a_plain_weekly_event_names_its_day_in_the_rule(local_tz):
    task = _rule_task(
        rrule="FREQ=WEEKLY;INTERVAL=1", next_due=_dt(2026, 10, 6, 7).isoformat()
    )
    events = _entity({"t_bins": task})._collect_events(
        _dt(2026, 10, 5), _dt(2026, 10, 7)
    )
    assert events[0].rrule == "FREQ=WEEKLY;INTERVAL=1;BYDAY=TU"


def test_a_moved_date_shows_on_its_new_day_with_its_original_id(local_tz):
    task = _rule_task(
        moved_occurrences=[
            {
                "from": _dt(2026, 10, 9, 7).isoformat(),
                "to": _dt(2026, 10, 10, 7).isoformat(),
            }
        ]
    )
    events = _entity({"t_bins": task})._collect_events(
        _dt(2026, 10, 8), _dt(2026, 10, 12)
    )
    assert [e.start for e in events] == [_dt(2026, 10, 10, 7)]
    assert events[0].recurrence_id == "20261009T070000"


def test_a_snoozed_fixed_task_shows_its_snoozed_date(local_tz, monkeypatch):
    now = _dt(2026, 10, 1, 12)
    monkeypatch.setattr(cal.dt_util, "now", lambda: now)
    snoozed = _dt(2026, 10, 3, 18)
    task = _rule_task(next_due=snoozed.isoformat())
    events = _entity({"t_bins": task})._collect_events(
        _dt(2026, 9, 28), _dt(2026, 10, 8)
    )
    # Tue 29 is before now and stays; Fri 2 is dealt with by the snooze; Tue 6 stays.
    assert [e.start for e in events] == [
        _dt(2026, 9, 29, 7),
        snoozed,
        _dt(2026, 10, 6, 7),
    ]
    snooze_event = events[1]
    assert snooze_event.uid.startswith("t_bins@")
    assert snooze_event.rrule is None
    assert entity_event(task, now).start == snoozed


def entity_event(task, now):
    return _entity({task["id"]: task}).event


def test_a_passed_snooze_does_not_hide_the_schedule(local_tz, monkeypatch):
    now = _dt(2026, 10, 5, 12)
    monkeypatch.setattr(cal.dt_util, "now", lambda: now)
    task = _rule_task(next_due=_dt(2026, 10, 3, 18).isoformat())
    events = _entity({"t_bins": task})._collect_events(
        _dt(2026, 10, 5), _dt(2026, 10, 8)
    )
    assert [e.start for e in events] == [_dt(2026, 10, 6, 7)]


def test_the_next_event_is_a_schedule_event(local_tz, monkeypatch):
    monkeypatch.setattr(cal.dt_util, "now", lambda: _dt(2026, 10, 1, 12))
    event = _entity({"t_bins": _rule_task()}).event
    assert event.start == _dt(2026, 10, 2, 7)
    assert event.recurrence_id == "20261002T070000"


def test_a_rule_with_no_dates_leaves_the_calendar_quiet(local_tz, monkeypatch):
    monkeypatch.setattr(cal.dt_util, "now", lambda: _dt(2026, 10, 1, 12))
    task = _rule_task(rrule="FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30", next_due=None)
    entity = _entity({"t_bins": task})
    assert entity.event is None
    assert entity._collect_events(_dt(2026, 10, 1), _dt(2027, 10, 1)) == []


def test_the_calendar_offers_editing():
    # Read through an instance: Home Assistant wraps ``_attr_*`` class attributes in
    # a property on the class itself.
    assert _entity({})._attr_supported_features == (
        cal.CalendarEntityFeature.UPDATE_EVENT
    )


def test_recurrence_ids_round_trip(local_tz):
    moment = _dt(2026, 10, 9, 7)
    assert cal.parse_recurrence_id(cal.recurrence_id_for(moment)) == moment


def _update(entity, uid, event, **kw):
    asyncio.run(entity.async_update_event(uid, event, **kw))


def test_only_this_event_moves_that_date(local_tz):
    entity, store = _editable({"t_bins": _rule_task()})
    new = _dt(2026, 10, 10, 7)
    _update(
        entity,
        "t_bins",
        {
            "dtstart": new,
            "dtend": new,
            "summary": "Take trash out",
            "rrule": "RRULE:BYDAY=TU,FR;FREQ=WEEKLY",
        },
        recurrence_id="20261009T070000",
    )
    assert store.calls == [
        ("move", "t_bins", _dt(2026, 10, 9, 7), new, cal.ORIGIN_CALENDAR)
    ]
    assert entity.coordinator.refreshed == [True]


@pytest.mark.parametrize("rule", ["FREQ=WEEKLY;BYDAY=FR,TU", "FREQ=DAILY", "garbage"])
def test_only_this_event_ignores_the_rule_the_dialog_sends_back(local_tz, rule):
    # Home Assistant's dialog sends the series rule back, and may rewrite it. The
    # rule of one date cannot change, so whatever comes back is ignored.
    entity, store = _editable({"t_bins": _rule_task()})
    _update(
        entity,
        "t_bins",
        {"dtstart": _dt(2026, 10, 10, 7), "rrule": rule},
        recurrence_id="20261009T070000",
    )
    assert [c[0] for c in store.calls] == ["move"]


def test_a_floating_event_cannot_move_into_the_past(local_tz, monkeypatch):
    monkeypatch.setattr(cal.dt_util, "now", lambda: _dt(2026, 10, 3, 12))
    task = _floating_task(_dt(2026, 10, 4, 9))
    entity, store = _editable({"t_float": task})
    with pytest.raises(_HA_EXC.HomeAssistantError) as err:
        _update(entity, f"t_float@{task['next_due']}", {"dtstart": _dt(2026, 10, 2, 9)})
    assert err.value.translation_key == "invalid_task"
    assert store.calls == []


def test_a_summer_anchor_is_not_a_snooze_in_winter(monkeypatch):
    # The anchor is stored at a summer offset and next_due at a winter one. Judged
    # at their own offsets the two are an hour apart, and the task read as snoozed.
    la = ZoneInfo("America/Los_Angeles")
    monkeypatch.setattr(cal.dt_util, "get_default_time_zone", lambda: la)
    monkeypatch.setattr(cal.dt_util, "as_local", lambda value: value.astimezone(la))
    task = _rule_task(
        rrule="FREQ=WEEKLY;BYDAY=TU",
        anchor="2026-07-07T10:00:00-07:00",
        next_due="2026-11-24T10:00:00-08:00",
    )
    events = _entity({"t_bins": task})._collect_events(
        datetime(2026, 11, 23, tzinfo=la), datetime(2026, 11, 26, tzinfo=la)
    )
    assert [e.uid for e in events] == ["t_bins"]


def test_a_naive_start_is_read_in_home_assistant_zone(local_tz):
    entity, store = _editable({"t_bins": _rule_task()})
    _update(
        entity,
        "t_bins",
        {"dtstart": datetime(2026, 10, 10, 7)},
        recurrence_id="20261009T070000",
    )
    assert store.calls[0][3] == _dt(2026, 10, 10, 7)


@pytest.mark.parametrize(
    ("event", "kw"),
    [
        ({"dtstart": _dt(2026, 10, 10, 7)}, {}),  # the whole series
        (
            {"dtstart": _dt(2026, 10, 10, 7)},
            {"recurrence_id": "20261009T070000", "recurrence_range": "THISANDFUTURE"},
        ),
        (
            {"dtstart": _dt(2026, 10, 10, 7), "summary": "Recycling"},
            {"recurrence_id": "20261009T070000"},
        ),
        ({"dtstart": _dt(2026, 10, 10).date()}, {"recurrence_id": "20261009T070000"}),
    ],
)
def test_anything_but_one_new_time_points_at_the_panel(local_tz, event, kw):
    entity, store = _editable({"t_bins": _rule_task()})
    with pytest.raises(_HA_EXC.HomeAssistantError) as err:
        _update(entity, "t_bins", event, **kw)
    assert err.value.translation_key == "calendar_edit_in_panel"
    assert store.calls == []


def test_editing_a_floating_event_snoozes_it(local_tz, monkeypatch):
    monkeypatch.setattr(cal.dt_util, "now", lambda: _dt(2026, 10, 1, 12))
    task = _floating_task(_dt(2026, 10, 2, 9))
    entity, store = _editable({"t_float": task})
    new = _dt(2026, 10, 4, 9)
    _update(entity, f"t_float@{task['next_due']}", {"dtstart": new})
    assert store.calls == [("snooze", "t_float", new, cal.ORIGIN_CALENDAR)]


def test_a_floating_event_cannot_be_given_a_rule(local_tz):
    task = _floating_task(_dt(2026, 10, 2, 9))
    entity, store = _editable({"t_float": task})
    with pytest.raises(_HA_EXC.HomeAssistantError):
        _update(
            entity,
            f"t_float@{task['next_due']}",
            {"dtstart": _dt(2026, 10, 4, 9), "rrule": "FREQ=DAILY"},
        )
    assert store.calls == []


def test_editing_a_snoozed_fixed_date_snoozes_again(local_tz, monkeypatch):
    monkeypatch.setattr(cal.dt_util, "now", lambda: _dt(2026, 10, 1, 12))
    task = _rule_task(next_due=_dt(2026, 10, 3, 18).isoformat())
    entity, store = _editable({"t_bins": task})
    new = _dt(2026, 10, 3, 20)
    _update(entity, f"t_bins@{task['next_due']}", {"dtstart": new})
    assert store.calls == [("snooze", "t_bins", new, cal.ORIGIN_CALENDAR)]


def test_an_unknown_task_is_reported(local_tz):
    entity, _ = _editable({})
    with pytest.raises(_HA_EXC.HomeAssistantError) as err:
        _update(entity, "gone", {"dtstart": _dt(2026, 10, 10, 7)})
    assert err.value.translation_key == "task_not_found"


def test_a_refused_move_is_reported_in_words(local_tz):
    entity, store = _editable({"t_bins": _rule_task()})
    store.error = cal.TaskValidationError("a date can only move to the future")
    with pytest.raises(_HA_EXC.HomeAssistantError) as err:
        _update(
            entity,
            "t_bins",
            {"dtstart": _dt(2026, 10, 10, 7)},
            recurrence_id="20261009T070000",
        )
    assert err.value.translation_key == "invalid_task"
    assert err.value.translation_placeholders == {
        "error": "a date can only move to the future"
    }
    assert entity.coordinator.refreshed == []
