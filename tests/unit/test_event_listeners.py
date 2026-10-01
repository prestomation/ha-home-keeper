"""Notification taps and tag scans during an entry reload (X02-5).

The 2 bus listeners were scoped to the config entry. They stopped at each unload
and started again only at the end of setup, so a tap or a scan in that time
reached no handler, and Home Assistant does not send it again. They now listen for
the Home Assistant run, and each event waits for the loaded coordinator.

* ``coordinator.async_wait_for_coordinator`` is the wait.
* ``tag_listener`` loads here with a fake ``hk.coordinator``, put in
  ``sys.modules`` only while the listener starts.
* ``__init__.py`` starts both listeners in ``async_setup``, checked on the source.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import sys
import types
from pathlib import Path

from ha_stubs import install_ha_stubs
from notifier_harness import load_notifier
from test_coordinator_purge import coordinator

_COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "home_keeper"


# ── the wait ─────────────────────────────────────────────────────────────────
class _Entries:
    def __init__(self, entries) -> None:
        self.entries = entries

    def async_entries(self, domain):
        return self.entries


def _entry(*, loaded=None, disabled_by=None):
    state = coordinator.ConfigEntryState.LOADED if loaded else "setup_in_progress"
    return types.SimpleNamespace(
        state=state, runtime_data=loaded, disabled_by=disabled_by
    )


def _live() -> object:
    return object.__new__(coordinator.HomeKeeperCoordinator)


def test_x02_5_the_wait_gives_a_coordinator_that_loads_later():
    entry = _entry()
    hass = types.SimpleNamespace(config_entries=_Entries([entry]))
    coord = _live()

    async def _run():
        async def _load_soon():
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            entry.state = coordinator.ConfigEntryState.LOADED
            entry.runtime_data = coord

        loader = asyncio.ensure_future(_load_soon())
        found = await coordinator.async_wait_for_coordinator(hass, step=0)
        await loader
        return found

    assert asyncio.run(_run()) is coord


def test_x02_5_the_wait_gives_a_loaded_coordinator_at_once():
    coord = _live()
    hass = types.SimpleNamespace(config_entries=_Entries([_entry(loaded=coord)]))
    found = asyncio.run(
        coordinator.async_wait_for_coordinator(hass, timeout=0, step=1000)
    )
    assert found is coord


def test_x02_5_the_wait_stops_with_no_enabled_entry():
    hass = types.SimpleNamespace(config_entries=_Entries([_entry(disabled_by="user")]))
    # A step of 1000 s would hang the test if the wait slept once.
    assert asyncio.run(coordinator.async_wait_for_coordinator(hass, step=1000)) is None


def test_x02_5_the_wait_stops_with_no_entry():
    hass = types.SimpleNamespace(config_entries=_Entries([]))
    assert asyncio.run(coordinator.async_wait_for_coordinator(hass, step=1000)) is None


def test_x02_5_the_wait_stops_at_the_timeout():
    hass = types.SimpleNamespace(config_entries=_Entries([_entry()]))
    assert (
        asyncio.run(coordinator.async_wait_for_coordinator(hass, timeout=0, step=0))
        is None
    )


# ── the notification listener ────────────────────────────────────────────────
notifier = load_notifier()


class _Bus:
    def __init__(self) -> None:
        self.listeners: dict = {}

    def async_listen(self, event_type, listener):
        self.listeners[event_type] = listener
        return lambda: None


class _Hass:
    def __init__(self) -> None:
        self.bus = _Bus()
        self.pending: list = []

    def async_create_task(self, coro):
        self.pending.append(coro)

    def run_pending(self) -> None:
        async def _run():
            while self.pending:
                await self.pending.pop(0)

        asyncio.run(_run())


def test_x02_5_a_tap_with_no_coordinator_is_dropped_after_the_wait():
    hass = _Hass()
    asked: list = []

    async def _none(_hass):
        asked.append(_hass)
        return None

    original = notifier._async_live_coordinator
    notifier._async_live_coordinator = _none
    try:
        notifier.async_setup_notifications(hass)
        action = notifier.notifications.encode_action("complete", "t1", "n1", "tok")
        hass.bus.listeners[notifier.EVENT_MOBILE_APP_ACTION](
            types.SimpleNamespace(data={"action": action})
        )
        hass.run_pending()
    finally:
        notifier._async_live_coordinator = original
    assert asked == [hass]


# ── the tag listener ─────────────────────────────────────────────────────────
def _load_tag_listener():
    install_ha_stubs()
    spec = importlib.util.spec_from_file_location(
        "hk.tag_listener_under_test", str(_COMPONENT / "tag_listener.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tag_listener = _load_tag_listener()


class _TagStore:
    def __init__(self) -> None:
        self.completed: list[str] = []

    def list_tasks(self):
        return [{"id": "t1", "name": "Filter", "tag_id": "tag-1", "enabled": True}]

    async def complete_task(self, task_id, *, origin=None):
        self.completed.append(task_id)


class _TagCoord:
    def __init__(self) -> None:
        self.store = _TagStore()
        self.settled = 0

    async def async_settle_buy_tasks(self):
        self.settled += 1


def _start_tag_listener(hass, *, now, later):
    """Start the listener with a fake ``hk.coordinator``.

    *now* is what ``find_coordinator`` gives, *later* what the wait gives.
    """
    waited: list = []

    async def _wait(_hass):
        waited.append(_hass)
        return later

    fake = types.ModuleType("hk.coordinator")
    fake.find_coordinator = lambda _hass: now
    fake.async_wait_for_coordinator = _wait
    saved = sys.modules.get("hk.coordinator")
    sys.modules["hk.coordinator"] = fake
    try:
        tag_listener.async_setup_tag_listener(hass)
    finally:
        if saved is None:
            sys.modules.pop("hk.coordinator", None)
        else:
            sys.modules["hk.coordinator"] = saved
    return waited


def _scan(hass, tag_id="tag-1"):
    hass.bus.listeners[tag_listener.EVENT_HA_TAG_SCANNED](
        types.SimpleNamespace(data={"tag_id": tag_id})
    )
    hass.run_pending()


def test_x02_5_a_scan_during_a_reload_completes_after_setup(monkeypatch):
    hass = _Hass()
    coord = _TagCoord()
    monkeypatch.setattr(
        tag_listener.tags, "tasks_for_tag", lambda tasks, tag_id: list(tasks)
    )
    waited = _start_tag_listener(hass, now=None, later=coord)
    _scan(hass)
    assert waited == [hass]
    assert coord.store.completed == ["t1"]
    assert coord.settled == 1


def test_x02_5_a_scan_with_a_loaded_entry_does_not_wait(monkeypatch):
    hass = _Hass()
    coord = _TagCoord()
    monkeypatch.setattr(
        tag_listener.tags, "tasks_for_tag", lambda tasks, tag_id: list(tasks)
    )
    waited = _start_tag_listener(hass, now=coord, later=None)
    _scan(hass)
    assert waited == []
    assert coord.store.completed == ["t1"]


def test_x02_5_an_unbound_tag_makes_no_task(monkeypatch):
    hass = _Hass()
    coord = _TagCoord()
    monkeypatch.setattr(tag_listener.tags, "tasks_for_tag", lambda tasks, tag_id: [])
    _start_tag_listener(hass, now=coord, later=None)
    hass.bus.listeners[tag_listener.EVENT_HA_TAG_SCANNED](
        types.SimpleNamespace(data={"tag_id": "other"})
    )
    assert hass.pending == []


def test_x02_5_a_scan_that_waits_in_vain_does_nothing(monkeypatch):
    hass = _Hass()
    monkeypatch.setattr(
        tag_listener.tags, "tasks_for_tag", lambda tasks, tag_id: list(tasks)
    )
    waited = _start_tag_listener(hass, now=None, later=None)
    _scan(hass)
    assert waited == [hass]


# ── the registration ─────────────────────────────────────────────────────────
def _function_source(name: str) -> str:
    tree = ast.parse((_COMPONENT / "__init__.py").read_text())
    return ast.unparse(
        next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == name
        )
    )


def test_x02_5_the_listeners_start_once_for_the_run():
    setup = _function_source("async_setup")
    assert "notifier.async_setup_notifications(hass)" in setup
    assert "tag_listener.async_setup_tag_listener(hass)" in setup
    entry_setup = _function_source("async_setup_entry")
    assert "async_setup_notifications" not in entry_setup
    assert "async_setup_tag_listener" not in entry_setup
