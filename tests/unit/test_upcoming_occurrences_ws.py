"""The ``home_keeper/upcoming_occurrences`` websocket command (``websocket_api.py``).

The command expands a fixed schedule. A season walk is bounded, but it is still CPU
work, so the command runs it in the executor and keeps the event loop free. These
tests load the real ``websocket_api.py`` under the synthetic ``hk`` package, with
fakes for its siblings that import Home Assistant, and call the command's handler.
The fake executor records each job, so the tests prove where the work runs.
"""

from __future__ import annotations

import asyncio
import functools
import importlib.util
import sys
import threading
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("voluptuous")

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)
TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 11, 18, 10, tzinfo=TZ)
# The siblings of ``websocket_api`` that import Home Assistant at run time.
_FAKED = (
    "companions",
    "cost_summary",
    "declarative_companion_sync",
    "devices",
    "manuals",
    "notifier",
    "coordinator",
    "shopping_sync",
    "transfer_runner",
)


def _fake(name: str) -> types.ModuleType:
    module = types.ModuleType(name)

    def _any(attr: str) -> Any:
        if attr.startswith("__"):
            raise AttributeError(attr)
        return types.SimpleNamespace()

    module.__getattr__ = _any  # type: ignore[method-assign]
    return module


def _load() -> types.ModuleType:
    fakes = {f"hk.{name}": _fake(f"hk.{name}") for name in _FAKED}
    package = sys.modules["hk"]
    saved = {name: sys.modules.get(name) for name in fakes}
    saved_attrs = {name: getattr(package, name, None) for name in _FAKED}
    sys.modules.update(fakes)
    for name in _FAKED:
        setattr(package, name, fakes[f"hk.{name}"])
    try:
        spec = importlib.util.spec_from_file_location(
            "hk.websocket_api", str(_COMPONENT_DIR / "websocket_api.py")
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        for name, previous in saved_attrs.items():
            if previous is None:
                if hasattr(package, name):
                    delattr(package, name)
            else:
                setattr(package, name, previous)
    module.recurrence = sys.modules["hk_recurrence"]
    module.models = sys.modules["hk_models"]
    module.TaskValidationError = sys.modules["hk_models"].TaskValidationError
    module.dt_util = types.SimpleNamespace(
        now=lambda: NOW,
        parse_datetime=lambda value: datetime.fromisoformat(value),
    )
    return module


ws = _load()
# Read the error text tables now, off the loop, as ``backend_i18n.preload`` does.
ws.resolve_exception("en", "invalid_task")
# The decorators wrap the coroutine. ``__wrapped__`` is the handler itself.
handler = ws.ws_upcoming_occurrences.__wrapped__


class _Hass:
    def __init__(self) -> None:
        self.jobs: list[tuple[Any, int]] = []
        self.data: dict[str, Any] = {}
        self.config = types.SimpleNamespace(language="en")

    async def async_add_executor_job(self, func, *args):
        def run():
            self.jobs.append((func, threading.get_ident()))
            return func(*args)

        return await asyncio.get_running_loop().run_in_executor(None, run)


class _Connection:
    def __init__(self) -> None:
        self.results: list[Any] = []
        self.errors: list[tuple[str, str]] = []

    def send_result(self, msg_id: int, result: Any) -> None:
        self.results.append(result)

    def send_error(self, msg_id: int, code: str, message: str) -> None:
        self.errors.append((code, message))


def _call(hass: _Hass, msg: dict[str, Any]) -> tuple[_Connection, int]:
    connection = _Connection()
    loop_thread: list[int] = []

    async def run() -> None:
        loop_thread.append(threading.get_ident())
        await handler(hass, connection, {"id": 1, "count": 4, **msg})

    asyncio.run(run())
    return connection, loop_thread[0]


def _jobs_of(hass: _Hass, func: Any) -> list[tuple[Any, int]]:
    return [
        (job, thread)
        for job, thread in hass.jobs
        if isinstance(job, functools.partial) and job.func is func
    ]


def test_a_draft_rule_expands_in_the_executor():
    hass = _Hass()
    connection, loop_thread = _call(
        hass,
        {
            "rrule": "FREQ=WEEKLY;BYDAY=FR",
            "anchor": "2026-01-02T09:00:00-04:00",
            "active_season": {"start": "06-01", "end": "06-30"},
        },
    )
    ((job, thread),) = _jobs_of(hass, ws.recurrence.upcoming_occurrences)
    assert thread != loop_thread
    assert job.keywords == {"now": NOW, "count": 4}
    (result,) = connection.results
    assert [row["start"] for row in result["occurrences"]] == [
        "2027-06-04T09:00:00-04:00",
        "2027-06-11T09:00:00-04:00",
        "2027-06-18T09:00:00-04:00",
        "2027-06-25T09:00:00-04:00",
    ]


def test_a_stored_task_expands_in_the_executor():
    task = {
        "id": "t1",
        "recurrence_type": "fixed",
        "rrule": "FREQ=DAILY",
        "anchor": "2026-01-01T09:00:00-04:00",
        "moved_occurrences": [],
    }
    hass = _Hass()
    coord = types.SimpleNamespace(data={"t1": task})
    ws._coordinator = lambda hass_: coord
    connection, loop_thread = _call(hass, {"task_id": "t1", "count": 2})
    ((job, thread),) = _jobs_of(hass, ws.recurrence.upcoming_occurrences)
    assert thread != loop_thread
    # The executor gets a copy, so a write on the loop cannot change it mid-walk.
    assert job.args[0] == task
    assert job.args[0] is not task
    (result,) = connection.results
    assert [row["start"] for row in result["occurrences"]] == [
        "2026-11-19T09:00:00-04:00",
        "2026-11-20T09:00:00-04:00",
    ]


def test_a_draft_with_no_date_in_its_season_answers_invalid_rule():
    hass = _Hass()
    connection, _loop = _call(
        hass,
        {
            "rrule": "FREQ=DAILY;BYYEARDAY=366",
            "anchor": "2026-01-01T09:00:00-04:00",
            "active_season": {"start": "06-01", "end": "06-02"},
        },
    )
    assert connection.results == []
    ((code, message),) = connection.errors
    assert code == "invalid_rule"
    assert "no date in the active season" in message
