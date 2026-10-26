"""Unit tests for ``logbook.py``, the logbook rows of the task events (#467)."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

from ha_stubs import install_ha_stubs

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)


def _load_logbook() -> types.ModuleType:
    """Load ``logbook.py`` as ``hk.logbook`` so its relative imports resolve."""
    if "hk.logbook" in sys.modules:
        return sys.modules["hk.logbook"]
    install_ha_stubs()
    spec = importlib.util.spec_from_file_location(
        "hk.logbook", str(_COMPONENT_DIR / "logbook.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hk.logbook"] = module
    spec.loader.exec_module(module)
    return module


logbook = _load_logbook()
_LB = sys.modules["homeassistant.components.logbook"]


def _describers() -> dict[str, object]:
    found: dict[str, object] = {}

    def describe_event(domain: str, event_type: str, describe: object) -> None:
        assert domain == "home_keeper"
        found[event_type] = describe

    logbook.async_describe_events(object(), describe_event)
    return found


def test_each_logbook_event_is_described() -> None:
    events = sys.modules["hk.events"]
    assert set(_describers()) == set(events.LOGBOOK_EVENTS)


def test_the_row_names_the_task_and_not_the_entity() -> None:
    describe = _describers()["home_keeper_task_completed"]
    event = types.SimpleNamespace(
        event_type="home_keeper_task_completed",
        data={
            "name": "Replace furnace filter",
            "who": "Ben",
            "entity_id": "todo.home_keeper_tasks",
        },
    )
    assert describe(event) == {
        _LB.LOGBOOK_ENTRY_NAME: "Replace furnace filter",
        _LB.LOGBOOK_ENTRY_MESSAGE: "was completed by Ben",
        _LB.LOGBOOK_ENTRY_ICON: "mdi:check-circle-outline",
    }


def test_a_task_with_no_name_gets_a_generic_name() -> None:
    describe = _describers()["home_keeper_task_overdue"]
    event = types.SimpleNamespace(event_type="home_keeper_task_overdue", data={})
    row = describe(event)
    assert row[_LB.LOGBOOK_ENTRY_NAME] == "Task"
    assert row[_LB.LOGBOOK_ENTRY_MESSAGE] == "became overdue"
    assert row[_LB.LOGBOOK_ENTRY_ICON] == "mdi:alert-circle-outline"


def _row(fired: datetime) -> tuple[object, ...]:
    """A logbook row with only the fire time set, at the position the logbook reads."""
    row: list[object] = [None] * 12
    row[sys.modules["homeassistant.components.logbook.models"].TIME_FIRED_TS_POS] = (
        fired.timestamp()
    )
    return tuple(row)


def test_a_backdated_completion_names_its_day() -> None:
    """The row fires on 2026-10-26 (UTC); the completion is on 2026-10-20."""
    describe = _describers()["home_keeper_task_completed"]
    event = types.SimpleNamespace(
        event_type="home_keeper_task_completed",
        data={"name": "Filter", "completed_at": "2026-10-20T08:00:00+00:00"},
        row=_row(datetime(2026, 10, 26, 9, tzinfo=UTC)),
    )
    assert describe(event)[_LB.LOGBOOK_ENTRY_MESSAGE] == "was completed on 2026-10-20"


def test_a_completion_on_the_day_it_fires_names_no_day() -> None:
    describe = _describers()["home_keeper_task_uncompleted"]
    event = types.SimpleNamespace(
        event_type="home_keeper_task_uncompleted",
        data={"name": "Filter", "ts": "2026-10-26T08:00:00+00:00"},
        row=_row(datetime(2026, 10, 26, 9, tzinfo=UTC)),
    )
    assert describe(event)[_LB.LOGBOOK_ENTRY_MESSAGE] == "had a completion removed"
