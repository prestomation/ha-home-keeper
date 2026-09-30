"""The sensor watcher's passes, baseline and rename handling, against fakes.

``sensor_watcher`` imports Home Assistant, so this file needs a real one, the same
as ``test_template_error_log.py`` (see there for why the import is guarded by hand).
Home Assistant itself is not started: a fake ``hass`` holds the states, a fake store
has the replace-on-complete behaviour of ``store.py``, and the two ``async_track_*``
helpers are replaced. What is under test is the watcher's own bookkeeping: which
tasks a pass evaluates, how passes overlap, and what the baseline records. The
integration suite drives the same paths against a real Home Assistant.
"""

from __future__ import annotations

import asyncio
import types
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

try:
    from custom_components.home_keeper import sensor_watcher
except ImportError as err:  # pragma: no cover - the lane without a real HA
    pytest.skip(
        f"sensor_watcher needs a real Home Assistant: {err}", allow_module_level=True
    )

T0 = datetime(2026, 6, 1, 10, tzinfo=UTC)


def _state(value: str, *, stamp: datetime = T0, **attributes: Any):
    return types.SimpleNamespace(
        state=value, attributes=attributes, last_updated=stamp, last_reported=stamp
    )


class _Store:
    """The parts of ``HomeKeeperStore`` the watcher calls, with a slow save."""

    def __init__(self, tasks: dict[str, dict]) -> None:
        self.tasks = tasks
        self.completed: list[str] = []
        self.triggered: list[str] = []
        self.baselines: list[tuple[str, float]] = []
        self.repointed: list[tuple[str, str]] = []

    def get_tasks(self) -> dict[str, dict]:
        return self.tasks

    async def _save(self) -> None:
        # Home Assistant's Store awaits an executor write, so a pass suspends here.
        await asyncio.sleep(0.003)

    async def complete_task(self, tid: str, *, origin: str | None = None) -> dict:
        self.completed.append(tid)
        # store.py replaces the dict, so a dict read before this is now old.
        self.tasks[tid] = {**self.tasks[tid], "next_due": None}
        await self._save()
        return self.tasks[tid]

    async def trigger_task(self, tid: str) -> dict:
        self.triggered.append(tid)
        self.tasks[tid]["next_due"] = T0.isoformat()
        await self._save()
        return self.tasks[tid]

    async def set_sensor_baseline(self, tid: str, value: float) -> None:
        self.baselines.append((tid, value))
        self.tasks[tid]["sensor"] = {**self.tasks[tid]["sensor"], "baseline": value}
        await self._save()

    async def async_repoint_sensor_entity(self, old: str, new: str) -> list[str]:
        self.repointed.append((old, new))
        changed = []
        for tid, task in self.tasks.items():
            if task["sensor"].get("entity_id") == old:
                task["sensor"] = {**task["sensor"], "entity_id": new}
                changed.append(tid)
        return changed


class _Hass:
    def __init__(self, states: dict[str, Any]) -> None:
        self._states = states
        self.data: dict = {}
        self.pending: list[asyncio.Task] = []
        self.listeners: dict[str, Any] = {}
        self.states = types.SimpleNamespace(get=self._states.get)
        self.bus = types.SimpleNamespace(async_listen=self._listen)

    def _listen(self, event_type: str, handler):
        self.listeners[event_type] = handler
        return lambda: None

    def async_create_task(self, coro):
        task = asyncio.get_running_loop().create_task(coro)
        self.pending.append(task)
        return task

    async def settle(self) -> None:
        while self.pending:
            batch, self.pending = self.pending, []
            await asyncio.gather(*batch)


class _Coordinator:
    def __init__(self, store: _Store) -> None:
        self.store = store
        self.declarative_sync = None
        self.refreshes = 0

    async def async_request_refresh(self) -> None:
        self.refreshes += 1


def _task(tid: str, sensor: dict, *, armed: bool = False) -> dict:
    return {
        "id": tid,
        "name": tid,
        "recurrence_type": "sensor",
        "enabled": True,
        "sensor": sensor,
        "next_due": T0.isoformat() if armed else None,
    }


@pytest.fixture(autouse=True)
def _no_trackers(monkeypatch):
    tracked: list[list[str]] = []

    def _track_state(hass, entity_ids, handler):
        tracked.append(list(entity_ids))
        return lambda: None

    monkeypatch.setattr(sensor_watcher, "async_track_state_change_event", _track_state)
    monkeypatch.setattr(
        sensor_watcher, "async_track_point_in_time", lambda *a, **k: lambda: None
    )
    return tracked


def _watcher(tasks: dict[str, dict], states: dict[str, Any]):
    store = _Store(tasks)
    hass = _Hass(states)
    entry = types.SimpleNamespace(entry_id="e1", async_on_unload=lambda cb: None)
    watcher = sensor_watcher.SensorTaskWatcher(hass, entry, _Coordinator(store))
    return watcher, hass, store


def _run(coro_fn):
    """Run *coro_fn* on a loop that starts tasks eagerly, as Home Assistant does."""

    async def main():
        asyncio.get_running_loop().set_task_factory(asyncio.eager_task_factory)
        return await coro_fn()

    return asyncio.run(main())


def _changed(entity_id: str):
    return types.SimpleNamespace(data={"entity_id": entity_id})


# ── B14-2: one pass at a time ────────────────────────────────────────────────
def _six_armed_availability_tasks():
    tasks = {
        f"t{i}": _task(
            f"t{i}",
            {
                "entity_id": f"sensor.d{i}",
                "mode": "availability",
                "clear_on_recover": True,
            },
            armed=True,
        )
        for i in range(6)
    }
    states = {f"sensor.d{i}": _state("unavailable") for i in range(6)}
    return tasks, states


def test_b14_2_a_bridge_recovery_completes_each_task_once():
    # Six devices come back in one save window. Overlapping passes held the old
    # armed dicts and completed the later tasks again: 21 completions, not 6.
    tasks, states = _six_armed_availability_tasks()
    watcher, hass, store = _watcher(tasks, states)

    async def go():
        await watcher.async_baseline()
        for i in range(6):
            states[f"sensor.d{i}"] = _state("on")
            watcher._handle_state_change(_changed(f"sensor.d{i}"))
        await hass.settle()

    _run(go)
    assert sorted(store.completed) == [f"t{i}" for i in range(6)]


def test_b14_2_overlapping_full_passes_complete_each_task_once():
    # The same race through full passes: the periodic tick beside a hold timer.
    tasks, states = _six_armed_availability_tasks()
    watcher, hass, store = _watcher(tasks, states)

    async def go():
        await watcher.async_baseline()
        for i in range(6):
            states[f"sensor.d{i}"] = _state("on")
        for _ in range(4):
            hass.async_create_task(watcher.async_evaluate(refresh=False))
        await hass.settle()

    _run(go)
    assert sorted(store.completed) == [f"t{i}" for i in range(6)]
    assert watcher._running is False
    assert watcher._pending_all is False


def test_b14_2_a_folded_request_runs_after_the_pass_and_refreshes():
    tasks = {
        "tank": _task(
            "tank", {"entity_id": "binary_sensor.tank", "mode": "state", "state": "on"}
        ),
        "plug": _task(
            "plug",
            {
                "entity_id": "sensor.plug",
                "mode": "availability",
                "clear_on_recover": True,
            },
            armed=True,
        ),
    }
    states = {"binary_sensor.tank": _state("off"), "sensor.plug": _state("unavailable")}
    watcher, hass, store = _watcher(tasks, states)

    async def go():
        await watcher.async_baseline()
        states["sensor.plug"] = _state("on")
        # The periodic pass: it suspends in the save of the "plug" completion.
        tick = hass.async_create_task(watcher.async_evaluate(refresh=False))
        assert watcher._running is True
        states["binary_sensor.tank"] = _state("on")
        # This call does not wait for the running pass, so it returns at once.
        await watcher.async_evaluate(refresh=False, entity_ids=["binary_sensor.tank"])
        assert store.triggered == []
        await tick

    _run(go)
    assert store.completed == ["plug"]
    assert store.triggered == ["tank"]
    # The tick asked for no refresh, but the folded pass must: its caller already
    # returned, so nothing else shows the new arm before the next tick.
    assert watcher._coordinator.refreshes == 1


def test_b14_2_a_clear_skips_a_task_that_is_already_dormant():
    tasks, states = _six_armed_availability_tasks()
    watcher, _hass, store = _watcher(tasks, states)
    decision = {
        "action": "clear",
        "condition_met": False,
        "crossed_at": None,
        "hold_due_at": None,
    }

    async def go():
        store.tasks["t0"] = {**store.tasks["t0"], "next_due": None}
        # The old armed dict, as a pass that read it before an await still has it.
        return await watcher._apply_edge(
            "t0", tasks["t0"] | {"next_due": "x"}, decision
        )

    assert _run(go) is False
    assert store.completed == []


# ── B14-6: a state change evaluates only the tasks it can change ─────────────
def test_b14_6_a_state_change_evaluates_only_the_tasks_bound_to_the_entity():
    tasks = {
        "a": _task("a", {"entity_id": "sensor.a", "mode": "state", "state": "on"}),
        "b": _task("b", {"entity_id": "sensor.b", "mode": "state", "state": "on"}),
    }
    states = {"sensor.a": _state("off"), "sensor.b": _state("off")}
    watcher, hass, store = _watcher(tasks, states)

    async def go():
        await watcher.async_baseline()
        states["sensor.a"] = _state("on")
        states["sensor.b"] = _state("on")
        watcher._handle_state_change(_changed("sensor.a"))
        await hass.settle()
        first = list(store.triggered)
        await watcher.async_evaluate(refresh=False)
        return first

    first = _run(go)
    assert first == ["a"]
    # The periodic pass still evaluates every task.
    assert store.triggered == ["a", "b"]


def test_b14_6_a_template_that_names_the_entity_is_evaluated():
    cfg = {"entity_id": "sensor.x", "mode": "template", "template": "{{ 1 }}"}
    names = dict(cfg, template="{{ states('sensor.other') == 'on' }}")
    only = frozenset({"sensor.other"})
    assert sensor_watcher._bound_to_any(cfg, only) is False
    assert sensor_watcher._bound_to_any(names, only) is True
    assert sensor_watcher._bound_to_any(cfg, frozenset({"sensor.x"})) is True
    state_cfg = {"entity_id": "sensor.x", "mode": "state", "state": "sensor.other"}
    assert sensor_watcher._bound_to_any(state_cfg, only) is False


# ── B14-1 / B14-4: a baseline taken before the entity loaded ─────────────────
def test_b14_1_a_state_entity_that_loads_late_does_not_arm():
    # The vacuum still reports "water tank low" across a restart, but its integration
    # loads after Home Keeper. Its first state is not a new crossing.
    tasks = {
        "t": _task(
            "t", {"entity_id": "binary_sensor.tank", "mode": "state", "state": "on"}
        )
    }
    states: dict[str, Any] = {}
    watcher, hass, store = _watcher(tasks, states)

    async def go():
        await watcher.async_baseline()
        assert watcher._edge["t"]["condition_met"] is None
        states["binary_sensor.tank"] = _state("on")
        watcher._handle_state_change(_changed("binary_sensor.tank"))
        await hass.settle()
        # A real crossing after that still arms.
        states["binary_sensor.tank"] = _state("off")
        await watcher.async_evaluate(refresh=False)
        assert store.triggered == []
        states["binary_sensor.tank"] = _state("on")
        await watcher.async_evaluate(refresh=False)

    _run(go)
    assert store.triggered == ["t"]


def test_b14_1_a_threshold_entity_that_loads_late_does_not_arm():
    sensor = {
        "entity_id": "sensor.bat",
        "mode": "threshold",
        "comparison": "<",
        "value": 20,
    }
    watcher, hass, store = _watcher({"t": _task("t", sensor)}, {})

    async def go():
        await watcher.async_baseline()
        assert watcher._edge["t"]["condition_met"] is None
        hass._states["sensor.bat"] = _state("5")
        await watcher.async_evaluate(refresh=False)

    _run(go)
    assert store.triggered == []
    assert watcher._edge["t"]["condition_met"] is True


def test_b14_1_a_just_made_task_still_arms_on_a_standing_condition():
    tasks = {
        "t": _task(
            "t", {"entity_id": "binary_sensor.tank", "mode": "state", "state": "on"}
        )
    }
    watcher, _hass, store = _watcher(tasks, {"binary_sensor.tank": _state("on")})
    sensor_watcher.async_mark_tasks_new(watcher._hass, "e1", ["t"])

    async def go():
        await watcher.async_baseline()
        await watcher.async_evaluate(refresh=False)

    _run(go)
    assert store.triggered == ["t"]


def test_b14_4_the_restored_placeholder_is_not_an_outage():
    # Availability task, device online. At start-up Home Assistant writes a
    # "restored" unavailable placeholder, then the real state arrives.
    tasks = {
        "t": _task(
            "t",
            {
                "entity_id": "sensor.plug",
                "mode": "availability",
                "clear_on_recover": True,
            },
        )
    }
    states: dict[str, Any] = {}
    watcher, hass, store = _watcher(tasks, states)

    async def go():
        await watcher.async_baseline()
        states["sensor.plug"] = _state("unavailable", restored=True)
        watcher._handle_state_change(_changed("sensor.plug"))
        await hass.settle()
        assert store.triggered == []
        # An MQTT entity can report a real "unavailable" before its availability
        # message: with an unknown baseline, that is a baseline too.
        states["sensor.plug"] = _state("unavailable")
        await watcher.async_evaluate(refresh=False)
        states["sensor.plug"] = _state("on")
        await watcher.async_evaluate(refresh=False)

    _run(go)
    assert store.triggered == []
    assert store.completed == []


def test_b14_4_read_availability_status_reads_the_placeholder_as_missing():
    hass = _Hass({"sensor.p": _state("unavailable", restored=True)})
    cfg = {"entity_id": "sensor.p"}
    assert sensor_watcher.read_availability_status(hass, cfg) == "missing"
    hass._states["sensor.p"] = _state("unavailable")
    assert sensor_watcher.read_availability_status(hass, cfg) == "unavailable"
    assert sensor_watcher._entity_loaded(hass, "sensor.p") is True
    hass._states["sensor.p"] = _state("unavailable", restored=True)
    assert sensor_watcher._entity_loaded(hass, "sensor.p") is False
    assert sensor_watcher._entity_loaded(hass, "sensor.none") is False
    assert sensor_watcher._entity_loaded(hass, None) is False


def test_b14_4_an_unavailable_baseline_is_still_met_without_a_crossing():
    # A device that was offline before the restart must not open a new task.
    tasks = {"t": _task("t", {"entity_id": "sensor.plug", "mode": "availability"})}
    watcher, _hass, store = _watcher(tasks, {"sensor.plug": _state("unavailable")})

    async def go():
        await watcher.async_baseline()
        await watcher.async_evaluate(refresh=False)

    _run(go)
    assert watcher._edge["t"]["condition_met"] is True
    assert store.triggered == []


# ── B14-3: a meter reset needs two readings, not two passes ──────────────────
def test_b14_3_a_second_pass_over_the_same_dip_does_not_rebaseline():
    sensor = {
        "entity_id": "sensor.odo",
        "mode": "usage",
        "target": 10000,
        "baseline": 45000,
    }
    states = {"sensor.odo": _state("48000")}
    watcher, _hass, store = _watcher({"oil": _task("oil", sensor)}, states)

    async def go():
        await watcher.async_baseline()
        states["sensor.odo"] = _state("0", stamp=T0 + timedelta(minutes=1))
        await watcher.async_evaluate(refresh=False)  # the dip: a candidate
        await watcher.async_evaluate(refresh=False)  # an unrelated pass
        assert store.baselines == []
        # The odometer comes back: the dip was a glitch, nothing is re-anchored.
        states["sensor.odo"] = _state("48010", stamp=T0 + timedelta(minutes=2))
        await watcher.async_evaluate(refresh=False)

    _run(go)
    assert store.baselines == []
    assert store.triggered == []
    assert watcher._usage_reset["oil"] is None


def test_b14_3_a_second_report_below_the_baseline_rebaselines():
    sensor = {
        "entity_id": "sensor.odo",
        "mode": "usage",
        "target": 10000,
        "baseline": 45000,
    }
    states = {"sensor.odo": _state("0", stamp=T0)}
    watcher, _hass, store = _watcher({"oil": _task("oil", sensor)}, states)

    async def go():
        await watcher.async_evaluate(refresh=False)
        assert watcher._usage_reset["oil"] == (0.0, T0)
        # The same value, reported again (``last_reported`` moves).
        states["sensor.odo"] = _state("0", stamp=T0 + timedelta(minutes=1))
        await watcher.async_evaluate(refresh=False)

    _run(go)
    assert store.baselines == [("oil", 0.0)]
    assert watcher._usage_reset["oil"] is None


def test_b14_3_a_candidate_waits_through_a_missing_reading():
    sensor = {
        "entity_id": "sensor.odo",
        "mode": "usage",
        "target": 10000,
        "baseline": 45000,
        "also_every": {"interval": 1, "unit": "years"},
    }
    states: dict[str, Any] = {"sensor.odo": _state("0", stamp=T0)}
    watcher, _hass, store = _watcher({"oil": _task("oil", sensor)}, states)

    async def go():
        await watcher.async_evaluate(refresh=False)
        del states["sensor.odo"]
        await watcher.async_evaluate(refresh=False)
        assert watcher._usage_reset["oil"] == (0.0, T0)
        states["sensor.odo"] = _state("0", stamp=T0)
        await watcher.async_evaluate(refresh=False)
        assert store.baselines == []
        states["sensor.odo"] = _state("0", stamp=T0 + timedelta(minutes=1))
        await watcher.async_evaluate(refresh=False)

    _run(go)
    assert store.baselines == [("oil", 0.0)]


def test_b14_3_reading_stamp_prefers_last_reported():
    hass = _Hass({})
    assert sensor_watcher._reading_stamp(hass, {"entity_id": "sensor.none"}) is None
    assert sensor_watcher._reading_stamp(hass, None) is None
    later = T0 + timedelta(seconds=5)
    hass._states["sensor.o"] = types.SimpleNamespace(
        state="1", attributes={}, last_updated=T0, last_reported=later
    )
    assert sensor_watcher._reading_stamp(hass, {"entity_id": "sensor.o"}) == later
    hass._states["sensor.o"] = types.SimpleNamespace(
        state="1", attributes={}, last_updated=T0
    )
    assert sensor_watcher._reading_stamp(hass, {"entity_id": "sensor.o"}) == T0


# ── X10-1: a renamed entity keeps its tasks ──────────────────────────────────
def _registry_event(**data):
    return types.SimpleNamespace(data=data)


def test_x10_1_a_rename_rewrites_the_binding_and_keeps_the_edge(_no_trackers):
    sensor = {
        "entity_id": "sensor.car_battery",
        "mode": "threshold",
        "comparison": "<",
        "value": 20,
    }
    states = {"sensor.car_battery": _state("5")}
    watcher, hass, store = _watcher({"t": _task("t", sensor)}, states)

    async def go():
        await watcher.async_baseline()
        watcher.async_start_listeners()
        handler = hass.listeners[sensor_watcher.er.EVENT_ENTITY_REGISTRY_UPDATED]
        # Not a rename: nothing to do.
        handler(
            _registry_event(action="update", entity_id="sensor.car_battery", changes={})
        )
        handler(_registry_event(action="create", entity_id="sensor.new"))
        await hass.settle()
        assert store.repointed == []
        states["sensor.tesla_battery"] = states.pop("sensor.car_battery")
        handler(
            _registry_event(
                action="update",
                entity_id="sensor.tesla_battery",
                old_entity_id="sensor.car_battery",
                changes={"entity_id": "sensor.car_battery"},
            )
        )
        await hass.settle()
        await watcher.async_evaluate(refresh=False)

    _run(go)
    assert store.repointed == [("sensor.car_battery", "sensor.tesla_battery")]
    assert store.tasks["t"]["sensor"]["entity_id"] == "sensor.tesla_battery"
    # The battery was already low before the rename: it is the same condition, so
    # the task does not arm on it as if it were new.
    assert store.triggered == []
    assert watcher._edge["t"]["condition"][0] == "sensor.tesla_battery"
    assert _no_trackers[-1] == ["sensor.tesla_battery"]
