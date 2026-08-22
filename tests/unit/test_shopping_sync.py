"""Unit tests for the shopping-list mirror driver (``shopping_sync.py``).

The driver is what stands between a pure plan and someone else's to-do list, so
what is pinned here is its behaviour when that list misbehaves: a failed call
must leave the bookkeeping able to retry, an unreadable list must plan nothing
at all, and none of it may ever raise into the completion or stock adjustment
that triggered the pass.

Like ``test_coordinator_purge.py`` this stubs the HA symbols the module imports,
registers fakes for its HA-aware siblings, and loads the **real** file under the
synthetic ``hk`` package so the shipped code is what runs. The real end-to-end
wiring against ``todo.shopping_list`` lives in the integration suite.
"""

from __future__ import annotations

import asyncio
import enum
import importlib.util
import sys
import types
from pathlib import Path

import hk_shopping as sh
import pytest

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)

TARGET = "todo.shopping_list"
OURS = "todo.home_keeper_tasks"
KEY = "asset1:part1"

# Everything the built-in shopping list supports.
_ALL_FEATURES = 1 | 2 | 4 | 8


def _real_ha_present() -> bool:
    """True only when the *real* Home Assistant package is installed."""
    mod = sys.modules.get("homeassistant")
    if mod is None:
        try:  # pragma: no cover - depends on environment
            import homeassistant as mod  # type: ignore[no-redef]
        except ImportError:
            return False
    return getattr(mod, "__file__", None) is not None


def _install_ha_stubs() -> None:
    """Additively register the HA symbols ``shopping_sync.py`` imports.

    Idempotent and non-clobbering, like its siblings: the other pure-unit suites
    install their own partial ``homeassistant`` trees, so this only fills gaps.
    """
    if _real_ha_present():  # pragma: no cover - real HA env
        return

    def _mod(name: str) -> types.ModuleType:
        existing = sys.modules.get(name)
        if existing is not None:
            return existing
        m = types.ModuleType(name)
        sys.modules[name] = m
        return m

    ha = _mod("homeassistant")
    components = _mod("homeassistant.components")
    ha.components = components

    comp_todo = _mod("homeassistant.components.todo")
    if not hasattr(comp_todo, "TodoListEntityFeature"):

        class TodoListEntityFeature(enum.IntFlag):
            CREATE_TODO_ITEM = 1
            DELETE_TODO_ITEM = 2
            UPDATE_TODO_ITEM = 4
            MOVE_TODO_ITEM = 8

        comp_todo.TodoListEntityFeature = TodoListEntityFeature

    config_entries = _mod("homeassistant.config_entries")
    if not hasattr(config_entries, "ConfigEntry"):

        class ConfigEntry:
            pass

        config_entries.ConfigEntry = ConfigEntry

    const = _mod("homeassistant.const")
    if not hasattr(const, "STATE_UNAVAILABLE"):
        const.STATE_UNAVAILABLE = "unavailable"
    if not hasattr(const, "STATE_UNKNOWN"):
        const.STATE_UNKNOWN = "unknown"

    core = _mod("homeassistant.core")
    for name in ("HomeAssistant", "Event", "EventStateChangedData"):
        if not hasattr(core, name):
            setattr(
                core,
                name,
                type(
                    name, (), {"__class_getitem__": classmethod(lambda cls, item: cls)}
                ),
            )
    if not hasattr(core, "callback"):
        core.callback = lambda func: func

    helpers = _mod("homeassistant.helpers")
    # Only needs to *exist* so the import resolves. What the driver actually
    # calls is injected per test by the ``registry`` fixture below — the shared
    # stub tree is written by several suites (``test_device_heal.py`` registers
    # an ``async_get`` that takes no arguments), so reaching for it here would
    # make this suite depend on load order.
    entity_registry = _mod("homeassistant.helpers.entity_registry")
    if not hasattr(entity_registry, "async_get"):
        entity_registry.async_get = lambda hass: types.SimpleNamespace(entities={})
    helpers.entity_registry = entity_registry
    event_mod = _mod("homeassistant.helpers.event")
    if not hasattr(event_mod, "async_track_state_change_event"):
        event_mod.async_track_state_change_event = lambda hass, ids, cb: lambda: None
    helpers.event = event_mod


def _load_module() -> types.ModuleType:
    """Load ``shopping_sync.py`` as ``hk.shopping_sync`` with fake siblings."""
    existing = sys.modules.get("hk.shopping_sync")
    if existing is not None:
        return existing
    _install_ha_stubs()
    # ``hk.options`` is the real module (conftest loads it — it imports Home
    # Assistant only under ``TYPE_CHECKING``), so ``_resolve_target`` runs the real
    # ``current_options`` here rather than a fake that hands back raw entry options.

    spec = importlib.util.spec_from_file_location(
        "hk.shopping_sync", str(_COMPONENT_DIR / "shopping_sync.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hk.shopping_sync"] = module
    spec.loader.exec_module(module)
    return module


shopping_sync = _load_module()
ORIGIN = sys.modules["hk.const"].ORIGIN_SHOPPING_LIST
TaskValidationError = sys.modules["hk.models"].TaskValidationError


@pytest.fixture(autouse=True)
def registry():
    """Give the driver an entity registry of our own, restored afterwards.

    Patches the binding on the loaded module rather than the shared
    ``homeassistant.helpers.entity_registry`` stub, which other suites also
    write to.
    """
    entries: dict[str, object] = {}
    original = shopping_sync.er
    shopping_sync.er = types.SimpleNamespace(
        async_get=lambda _hass: types.SimpleNamespace(entities=entries)
    )
    try:
        yield entries
    finally:
        shopping_sync.er = original


# ── fakes ─────────────────────────────────────────────────────────────────────


def _buy_task(tid="t1", name="Buy Anode rod", completed=False):
    return {
        "id": tid,
        "name": name,
        "recurrence_type": "one-off",
        "next_due": None if completed else "2026-06-13T10:00:00-04:00",
        "last_completed": "2026-06-14T09:00:00-04:00" if completed else None,
        "source": {"buy": {"asset_id": "asset1", "part_id": "part1"}},
    }


def _item(summary="Buy Anode rod", uid="i1", status=sh.STATUS_NEEDS_ACTION):
    return {"uid": uid, "summary": summary, "status": status}


class _FakeStore:
    """The slice of ``store.py`` the driver touches."""

    def __init__(self, tasks=None, items=None):
        self._tasks = tasks or {}
        self._shopping = items or {}
        self.completed: list[tuple[str, str | None]] = []
        self.complete_error: Exception | None = None
        self.writes = 0

    def get_tasks(self):
        return self._tasks

    def get_shopping_items(self):
        return self._shopping

    async def async_set_shopping_items(self, items):
        if items == self._shopping:
            return False
        self._shopping = items
        self.writes += 1
        return True

    async def complete_task(self, task_id, *, origin=None):
        if self.complete_error is not None:
            raise self.complete_error
        self.completed.append((task_id, origin))
        self._tasks.pop(task_id, None)
        return {}


class _FakeCoordinator:
    def __init__(self, store):
        self.store = store
        self.settles = 0

    async def async_settle_buy_tasks(self):
        self.settles += 1


class _FakeServices:
    """Records ``todo.*`` calls and answers ``get_items`` from canned lists."""

    def __init__(self, lists):
        self._lists = lists
        self.calls: list[tuple[str, dict]] = []
        # Reads are counted separately from writes: "did this pass touch a to-do
        # list at all" is its own claim, and a test that only watched writes
        # would pass whether or not the read gate worked.
        self.reads: list[str] = []
        self.fail: set[str] = set()
        self.get_items_error: Exception | None = None

    async def async_call(self, domain, service, data, blocking=False, **kwargs):
        assert domain == "todo"
        if service == "get_items":
            self.reads.append(data["entity_id"])
            if self.get_items_error is not None:
                raise self.get_items_error
            entity_id = data["entity_id"]
            return {entity_id: {"items": list(self._lists.get(entity_id, []))}}
        self.calls.append((service, data))
        if service in self.fail:
            raise RuntimeError(f"{service} refused")
        return None


class _FakeHass:
    def __init__(self, lists=None, features=_ALL_FEATURES, missing=()):
        lists = lists if lists is not None else {TARGET: []}
        self.services = _FakeServices(lists)
        self._states = {
            entity_id: types.SimpleNamespace(
                state="0", attributes={"supported_features": features}
            )
            for entity_id in lists
            if entity_id not in missing
        }
        self.tasks: list = []

    @property
    def states(self):
        return types.SimpleNamespace(get=self._states.get)

    def async_create_task(self, coro):
        self.tasks.append(coro)
        coro.close()


def _sync(hass, store, *, target=TARGET, force=True):
    """Build a driver over the fakes and run one full ``async_sync``."""
    entry = types.SimpleNamespace(
        options={"shopping_list_entity": target},
        async_on_unload=lambda _cb: None,
    )
    coordinator = _FakeCoordinator(store)
    sync = shopping_sync.ShoppingListSync(hass, entry, coordinator)
    asyncio.run(sync.async_sync(force=force))
    return sync, coordinator


def _services(hass, service):
    return [data for name, data in hass.services.calls if name == service]


# ── the happy path ────────────────────────────────────────────────────────────


def test_a_low_part_puts_an_item_on_the_list_and_is_remembered():
    hass = _FakeHass({TARGET: []})
    store = _FakeStore(tasks={"t1": _buy_task()})
    _sync(hass, store)
    assert _services(hass, "add_item") == [
        {"entity_id": TARGET, "item": "Buy Anode rod"}
    ]
    assert store.get_shopping_items() == {
        KEY: {"entity_id": TARGET, "summary": "Buy Anode rod", "uid": None}
    }


def test_a_settled_mirror_reads_no_lists_at_all():
    # The chokepoint fires on every completion and stock nudge; almost none of
    # them concern the mirror, and none of those should cost a service call.
    hass = _FakeHass({TARGET: [_item()]})
    store = _FakeStore(
        tasks={"t1": _buy_task()},
        items={KEY: {"entity_id": TARGET, "summary": "Buy Anode rod", "uid": "i1"}},
    )
    _sync(hass, store, force=False)
    assert hass.services.reads == []
    assert hass.services.calls == []
    assert store.writes == 0


def test_ticking_the_item_off_completes_the_reminder_and_settles():
    hass = _FakeHass({TARGET: [_item(status=sh.STATUS_COMPLETED)]})
    store = _FakeStore(
        tasks={"t1": _buy_task()},
        items={KEY: {"entity_id": TARGET, "summary": "Buy Anode rod", "uid": "i1"}},
    )
    _, coordinator = _sync(hass, store)
    assert store.completed == [("t1", ORIGIN)]
    assert coordinator.settles == 1
    # The item they ticked off is theirs — we do not delete or re-add it.
    assert _services(hass, "remove_item") == []
    assert _services(hass, "add_item") == []
    assert store.get_shopping_items() == {}


def test_a_retired_reminder_takes_its_item_off_the_list():
    hass = _FakeHass({TARGET: [_item()]})
    store = _FakeStore(
        items={KEY: {"entity_id": TARGET, "summary": "Buy Anode rod", "uid": "i1"}}
    )
    _sync(hass, store)
    assert _services(hass, "remove_item") == [{"entity_id": TARGET, "item": ["i1"]}]
    assert store.get_shopping_items() == {}


# ── when the list misbehaves ──────────────────────────────────────────────────


def test_an_unreadable_list_plans_nothing_and_forgets_nothing():
    hass = _FakeHass({TARGET: [_item()]})
    hass.services.get_items_error = RuntimeError("boom")
    before = {KEY: {"entity_id": TARGET, "summary": "Buy Anode rod", "uid": "i1"}}
    store = _FakeStore(items=dict(before))
    _sync(hass, store)
    assert hass.services.calls == []
    assert store.get_shopping_items() == before


def test_a_missing_list_plans_nothing():
    hass = _FakeHass({TARGET: []}, missing=(TARGET,))
    store = _FakeStore(tasks={"t1": _buy_task()})
    _sync(hass, store)
    assert hass.services.reads == []
    assert hass.services.calls == []
    assert store.get_shopping_items() == {}


def test_a_failed_add_is_not_recorded_as_mirrored():
    hass = _FakeHass({TARGET: []})
    hass.services.fail.add("add_item")
    store = _FakeStore(tasks={"t1": _buy_task()})
    _sync(hass, store)
    assert _services(hass, "add_item")  # it was attempted
    assert store.get_shopping_items() == {}  # …and not believed


def test_a_failed_remove_keeps_the_entry_so_the_next_pass_retries():
    # Forgetting the entry would strand that line on the list with nothing left
    # to remember it by.
    hass = _FakeHass({TARGET: [_item()]})
    hass.services.fail.add("remove_item")
    before = {KEY: {"entity_id": TARGET, "summary": "Buy Anode rod", "uid": "i1"}}
    store = _FakeStore(items=dict(before))
    _sync(hass, store)
    assert store.get_shopping_items() == before


def test_a_list_that_cannot_delete_is_not_asked_to():
    create_only = 1 | 4
    hass = _FakeHass({TARGET: [_item()]}, features=create_only)
    before = {KEY: {"entity_id": TARGET, "summary": "Buy Anode rod", "uid": "i1"}}
    store = _FakeStore(items=dict(before))
    _sync(hass, store)
    assert hass.services.calls == []
    assert store.get_shopping_items() == before


def test_a_list_that_cannot_create_is_not_asked_to():
    hass = _FakeHass({TARGET: []}, features=2 | 4)
    store = _FakeStore(tasks={"t1": _buy_task()})
    _sync(hass, store)
    assert hass.services.calls == []
    assert store.get_shopping_items() == {}


def test_a_failed_completion_keeps_the_entry_and_does_not_settle():
    hass = _FakeHass({TARGET: [_item(status=sh.STATUS_COMPLETED)]})
    before = {KEY: {"entity_id": TARGET, "summary": "Buy Anode rod", "uid": "i1"}}
    store = _FakeStore(tasks={"t1": _buy_task()}, items=dict(before))
    store.complete_error = TaskValidationError("nope")
    _, coordinator = _sync(hass, store)
    assert store.completed == []
    assert coordinator.settles == 0
    assert store.get_shopping_items() == before


def test_a_pass_never_raises_into_whatever_triggered_it():
    # A completion or a stock adjustment awaits this; it must not be the thing
    # that fails.
    hass = _FakeHass({TARGET: []})

    async def _explode(*args, **kwargs):
        raise RuntimeError("the shopping list is on fire")

    hass.services.async_call = _explode
    store = _FakeStore(tasks={"t1": _buy_task()})
    _sync(hass, store)  # no exception escapes
    assert store.get_shopping_items() == {}


# ── guards ────────────────────────────────────────────────────────────────────


def test_home_keepers_own_list_is_refused(registry):
    # Mirroring our own list onto itself is a loop, and ours accepts no new
    # items anyway — so the pass must not even read it.
    hass = _FakeHass({OURS: []})
    registry[OURS] = types.SimpleNamespace(
        entity_id=OURS, domain="todo", platform="home_keeper"
    )
    store = _FakeStore(tasks={"t1": _buy_task()})
    _sync(hass, store, target=OURS)
    assert hass.services.reads == []
    assert hass.services.calls == []
    assert store.get_shopping_items() == {}


def test_a_foreign_todo_list_is_not_mistaken_for_ours(registry):
    registry[TARGET] = types.SimpleNamespace(
        entity_id=TARGET, domain="todo", platform="shopping_list"
    )
    hass = _FakeHass({TARGET: []})
    store = _FakeStore(tasks={"t1": _buy_task()})
    _sync(hass, store)
    assert _services(hass, "add_item")


def test_a_pass_running_already_is_folded_in_rather_than_nested():
    hass = _FakeHass({TARGET: []})
    store = _FakeStore(tasks={"t1": _buy_task()})
    entry = types.SimpleNamespace(
        options={"shopping_list_entity": TARGET}, async_on_unload=lambda _cb: None
    )
    sync = shopping_sync.ShoppingListSync(hass, entry, _FakeCoordinator(store))
    sync._running = True
    asyncio.run(sync.async_sync(force=True))
    assert hass.services.calls == []
    assert sync._pending is True


@pytest.mark.parametrize("target", ["", "sensor.not_a_list"])
def test_no_usable_target_means_no_mirroring(target):
    hass = _FakeHass({TARGET: []})
    store = _FakeStore(tasks={"t1": _buy_task()})
    _sync(hass, store, target=target)
    assert hass.services.reads == []
    assert hass.services.calls == []
    assert store.get_shopping_items() == {}


def test_the_periodic_sweep_costs_nothing_until_something_is_mirrored():
    hass = _FakeHass({TARGET: []})
    entry = types.SimpleNamespace(
        options={"shopping_list_entity": TARGET}, async_on_unload=lambda _cb: None
    )
    sync = shopping_sync.ShoppingListSync(hass, entry, _FakeCoordinator(_FakeStore()))
    sync.async_schedule_sweep()
    assert hass.tasks == []

    mirrored = _FakeStore(
        items={KEY: {"entity_id": TARGET, "summary": "Buy Anode rod", "uid": "i1"}}
    )
    sync2 = shopping_sync.ShoppingListSync(hass, entry, _FakeCoordinator(mirrored))
    sync2.async_schedule_sweep()
    assert len(hass.tasks) == 1


def test_a_mirror_that_cannot_settle_says_so(caplog):
    """The pass budget guarantees termination; it should not hide a failure.

    Driven through ``_sync_once`` directly: every real path converges, which is
    the point of the design, so the only way to reach the budget is a pass that
    keeps asking for another one. The loop must still end — that is the budget's
    job — but exiting quietly would leave the list stale with nothing in the log
    to explain it.
    """
    hass = _FakeHass({TARGET: []})
    entry = types.SimpleNamespace(
        options={"shopping_list_entity": TARGET}, async_on_unload=lambda _cb: None
    )
    sync = shopping_sync.ShoppingListSync(hass, entry, _FakeCoordinator(_FakeStore()))
    passes = []

    async def _never_settles(*, force):
        passes.append(force)
        return True

    sync._sync_once = _never_settles
    with caplog.at_level("WARNING"):
        asyncio.run(sync.async_sync(force=True))
    assert len(passes) == shopping_sync._MAX_PASSES
    assert "did not settle" in caplog.text
    # The guard is released either way, so the next change is not locked out.
    assert sync._running is False and sync._pending is False


def test_a_settling_mirror_stays_quiet(caplog):
    hass = _FakeHass({TARGET: []})
    store = _FakeStore(tasks={"t1": _buy_task()})
    with caplog.at_level("WARNING"):
        _sync(hass, store)
    assert "did not settle" not in caplog.text


def test_a_reminder_still_open_after_a_tick_off_gets_a_fresh_line(caplog):
    """The shopper ticked it off, but the reminder outlived the restock.

    That happens when the restock quantity does not lift the part above its
    threshold: the reminder stays open, so the mirror puts a new line on the
    list rather than adopting the one already ticked off. Convergence here is
    what keeps the pass budget out of it.
    """
    hass = _FakeHass({TARGET: [_item(status=sh.STATUS_COMPLETED)]})
    store = _FakeStore(
        tasks={"t1": _buy_task()},
        items={KEY: {"entity_id": TARGET, "summary": "Buy Anode rod", "uid": "i1"}},
    )

    async def _complete(task_id, *, origin=None):
        store.completed.append((task_id, origin))  # reminder stays low, so stays open

    store.complete_task = _complete
    with caplog.at_level("WARNING"):
        _sync(hass, store)
    assert store.completed == [("t1", ORIGIN)]
    assert _services(hass, "add_item") == [
        {"entity_id": TARGET, "item": "Buy Anode rod"}
    ]
    # The line they ticked off is left exactly as it is.
    assert _services(hass, "remove_item") == []
    assert "did not settle" not in caplog.text
