"""Unit tests for the todo-list-sync driver (``todo_list_sync.py``).

The driver is what stands between a pure plan and somebody else's to-do list, so
what is pinned here is its behaviour when that list — or the task behind it —
misbehaves: a failed call must leave the bookkeeping able to retry, an unreadable
list must plan nothing at all, a tick that Home Keeper refuses must say so rather
than vanish, and none of it may ever raise into the task mutation that triggered
the pass.

Like ``test_shopping_sync.py`` this stubs the HA symbols the module imports, hands
it doubles for its HA-aware siblings, and loads the **real** file under the
synthetic ``hk`` package so the shipped code is what runs. The real end-to-end
wiring against a live ``todo`` entity lives in the integration suite.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import importlib.util
import sys
import types
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import hk_todo_list as tm
import pytest

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)

LIST = "todo.family"
OTHER = "todo.chores"
OURS = "todo.home_keeper_tasks"

M1 = "m1"
M2 = "m2"
T1 = "t1"
KEY = tm.sync_key(M1, T1)

NAME = "Change the filter"
NOTES = "Behind the grille"
DUE = "2026-06-14"

# 09:00 on the 15th, in the household's own offset — so a task due on the 14th is
# overdue, which is what the default profile filter selects.
NOW = datetime(2026, 6, 15, 9, 0, tzinfo=timezone(timedelta(hours=-4)))
OVERDUE_ISO = "2026-06-14T09:00:00-04:00"
DONE_ISO = "2026-06-15T08:00:00-04:00"

# ``TodoListEntityFeature`` bits, as Home Assistant numbers them.
CREATE, DELETE, UPDATE, MOVE = 1, 2, 4, 8
SET_DUE_DATE, SET_DUE_DATETIME, SET_DESCRIPTION = 16, 32, 64
# What a list must have before the sync can work at all…
BASIC = CREATE | DELETE | UPDATE
# …and everything a well-equipped one offers.
ALL_FEATURES = BASIC | MOVE | SET_DUE_DATE | SET_DUE_DATETIME | SET_DESCRIPTION


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
    """Additively register the HA symbols the modules under test import.

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
    feature = getattr(comp_todo, "TodoListEntityFeature", None)
    if feature is None or not hasattr(feature, "SET_DUE_DATE_ON_ITEM"):
        # A strict superset of the four-bit stub ``test_shopping_sync.py`` installs,
        # carrying Home Assistant's real values — so whichever suite gets here first,
        # the other still finds every member it needs.
        class TodoListEntityFeature(enum.IntFlag):
            CREATE_TODO_ITEM = CREATE
            DELETE_TODO_ITEM = DELETE
            UPDATE_TODO_ITEM = UPDATE
            MOVE_TODO_ITEM = MOVE
            SET_DUE_DATE_ON_ITEM = SET_DUE_DATE
            SET_DUE_DATETIME_ON_ITEM = SET_DUE_DATETIME
            SET_DESCRIPTION_ON_ITEM = SET_DESCRIPTION

        comp_todo.TodoListEntityFeature = TodoListEntityFeature

    config_entries = _mod("homeassistant.config_entries")
    if not hasattr(config_entries, "ConfigEntry"):

        class ConfigEntry:
            pass

        config_entries.ConfigEntry = ConfigEntry
    if not hasattr(config_entries, "ConfigEntryState"):

        class ConfigEntryState(enum.Enum):
            LOADED = "loaded"

        config_entries.ConfigEntryState = ConfigEntryState

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
    # Only needs to *exist* so the import resolves. What the driver actually calls
    # is injected per test by the ``registry`` fixture below — the shared stub tree
    # is written by several suites, so reaching for it here would make this suite
    # depend on load order.
    entity_registry = _mod("homeassistant.helpers.entity_registry")
    if not hasattr(entity_registry, "async_get"):
        entity_registry.async_get = lambda hass: types.SimpleNamespace(entities={})
    helpers.entity_registry = entity_registry
    event_mod = _mod("homeassistant.helpers.event")
    if not hasattr(event_mod, "async_track_state_change_event"):
        event_mod.async_track_state_change_event = lambda hass, ids, cb: lambda: None
    helpers.event = event_mod
    storage = _mod("homeassistant.helpers.storage")
    if not hasattr(storage, "Store"):

        class Store:  # replaced per-test anyway; this only satisfies the import
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

        storage.Store = Store
    helpers.storage = storage

    util = _mod("homeassistant.util")
    dt_mod = _mod("homeassistant.util.dt")
    if not hasattr(dt_mod, "now"):
        dt_mod.now = lambda: NOW
    util.dt = dt_mod


class _Enricher:
    """Stands in for ``notifier.effective_filter_tasks``.

    The real one resolves each task's **effective** labels and area from the
    device/area registries. Here it records what it was handed and applies a
    canned inheritance map, so a test can show the driver plans from the
    *enriched* tasks rather than the raw ones without needing real registries.
    """

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []
        self.inherited: dict[str, list[str]] = {}

    def reset(self) -> None:
        self.calls = []
        self.inherited = {}

    def __call__(self, hass: object, tasks: list[dict]) -> list[dict]:
        self.calls.append([dict(task) for task in tasks])
        return [
            {
                **task,
                "labels": sorted(
                    set(task.get("labels") or [])
                    | set(self.inherited.get(str(task["id"]), ()))
                ),
            }
            for task in tasks
        ]


ENRICH = _Enricher()


@contextlib.contextmanager
def _borrowed(modules: dict[str, types.ModuleType]) -> Iterator[None]:
    """Register *modules* for the duration, then put back what was there before.

    Several suites hand the same ``hk.*`` names different doubles, and the loads
    below need siblings only while the module body executes — after that the
    bindings are resolved. Restoring leaves no trace for the next suite to trip
    over, whatever order pytest imports them in.
    """
    saved = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        yield
    finally:
        for name, prior in saved.items():
            if prior is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior


def _load_module() -> types.ModuleType:
    """Load ``todo_list_sync.py`` as ``hk.todo_list_sync`` with doubles."""
    existing = sys.modules.get("hk.todo_list_sync")
    if existing is not None:
        return existing
    _install_ha_stubs()
    # ``hk.notifier`` may already be the real module (``test_notifier_blocking.py``
    # loads it), a bare fake (``test_coordinator_purge.py``), or absent. Only the
    # last case needs a placeholder so the relative import resolves; either way the
    # binding is replaced below, so the real registry-reading helper never runs.
    placeholder = types.ModuleType("hk.notifier")
    placeholder.effective_filter_tasks = ENRICH
    borrow = {} if "hk.notifier" in sys.modules else {"hk.notifier": placeholder}

    spec = importlib.util.spec_from_file_location(
        "hk.todo_list_sync", str(_COMPONENT_DIR / "todo_list_sync.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hk.todo_list_sync"] = module
    with _borrowed(borrow):
        spec.loader.exec_module(module)
    module.notifier = types.SimpleNamespace(effective_filter_tasks=ENRICH)
    # Pin the clock so "overdue" is a fact about the fixtures, not about today.
    module.dt_util = types.SimpleNamespace(now=lambda: NOW)
    return module


def _load_store() -> types.ModuleType:
    """Load the real ``store.py`` for the bookkeeping trio, leaving no footprint.

    ``store.py`` is HA-coupled, but the four methods under test here touch nothing
    beyond the storage document, so a fake ``Store`` is the whole harness. Its one
    HA-aware sibling (``sensor_watcher``, used only when reading a meter) is
    borrowed for the load and handed straight back.
    """
    watcher = types.ModuleType("hk.sensor_watcher")
    watcher.read_sensor_value = lambda *args, **kwargs: None
    spec = importlib.util.spec_from_file_location(
        "hk.store", str(_COMPONENT_DIR / "store.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    with _borrowed({"hk.sensor_watcher": watcher, "hk.store": module}):
        spec.loader.exec_module(module)
    module.Store = _FakeHAStore
    return module


class _FakeHAStore:
    """Stands in for Home Assistant's ``Store`` helper: one in-memory document."""

    def __init__(self, hass: object, version: int, key: str) -> None:
        self.data: dict | None = None
        self.saves: list[dict] = []
        self.removed = False

    async def async_load(self) -> dict | None:
        return self.data

    async def async_save(self, data: dict) -> None:
        self.saves.append(data)
        self.data = data

    async def async_remove(self) -> None:
        self.removed = True
        self.data = None


todo_list_sync = _load_module()
store_mod = _load_store()
ORIGIN = sys.modules["hk.const"].ORIGIN_TODO_SYNC
TaskValidationError = sys.modules["hk.models"].TaskValidationError
profiles = sys.modules["hk.profiles"]


@pytest.fixture(autouse=True)
def registry():
    """Give ``own_todo_entity_ids`` an entity registry of our own.

    That helper lives in ``shopping_sync`` (the driver imports it, as the rest of
    the integration does), so the patch goes on that module's ``er`` binding and is
    restored afterwards rather than on the shared HA stub other suites write to.
    """
    entries: dict[str, object] = {}
    sibling = sys.modules["hk.shopping_sync"]
    original = sibling.er
    sibling.er = types.SimpleNamespace(
        async_get=lambda _hass: types.SimpleNamespace(entities=entries)
    )
    try:
        yield entries
    finally:
        sibling.er = original


@pytest.fixture(autouse=True)
def enricher():
    """A clean effective-labels double per test."""
    ENRICH.reset()
    return ENRICH


# ── fakes ─────────────────────────────────────────────────────────────────────


def _synced_profile(mid=M1, entity_id=LIST, filt=None, **sync):
    """A profile syncing onto *entity_id* — a sync is a profile's sync block."""
    return profiles.normalize_profile(
        {
            "id": mid,
            "name": mid,
            "filter": filt or {},
            "sync": {"entity_id": entity_id, **sync},
        }
    )


def _task(tid=T1, name=NAME, due=OVERDUE_ISO, notes="", **extra):
    """An ordinary, enabled, overdue task as the store holds it."""
    return {
        "id": tid,
        "name": name,
        "next_due": due,
        "last_completed": None,
        "enabled": True,
        "notes": notes,
        **extra,
    }


def _item(
    summary=NAME, uid="i1", status=tm.STATUS_NEEDS_ACTION, due=DUE, description=""
):
    return {
        "uid": uid,
        "summary": summary,
        "status": status,
        "due": due,
        "description": description,
    }


def _entry(entity_id=LIST, uid="i1", summary=NAME, due=DUE, last_completed=None):
    return {
        "entity_id": entity_id,
        "uid": uid,
        "summary": summary,
        "due": due,
        "last_completed": last_completed,
    }


def _tracked(entry=None, key=KEY):
    return {key: _entry() if entry is None else entry}


class _FakeStore:
    """The slice of ``store.py`` the driver touches."""

    def __init__(self, tasks=None, items=None):
        self._tasks = tasks or {}
        self._todo_list_items = items or {}
        self.completed: list[tuple[str, str | None]] = []
        self.complete_error: Exception | None = None
        self.writes = 0
        # Ordered trace of the two things that must not swap places: persisting
        # the bookkeeping, and the settle that re-enters the driver.
        self.log: list[str] = []

    def get_tasks(self):
        return self._tasks

    def get_todo_list_items(self):
        return self._todo_list_items

    async def async_set_todo_list_items(self, items):
        self.log.append("persist")
        if items == self._todo_list_items:
            return False
        self._todo_list_items = items
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
        self.store.log.append("settle")


class _FakeServices:
    """Records ``todo.*`` calls and answers ``get_items`` from canned lists."""

    def __init__(self, lists):
        self._lists = lists
        self.calls: list[tuple[str, dict]] = []
        # Reads are counted separately from writes: "did this pass touch a to-do
        # list at all" is its own claim, and a test that only watched writes would
        # pass whether or not the read gate worked.
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


class _FakeBus:
    def __init__(self):
        self.listeners: list[tuple[str, object]] = []

    def async_listen(self, event_type, handler):
        self.listeners.append((event_type, handler))
        return lambda: None


class _FakeHass:
    def __init__(self, lists=None, features=ALL_FEATURES, missing=(), unavailable=()):
        lists = lists if lists is not None else {LIST: []}
        by_entity = (
            features if isinstance(features, dict) else dict.fromkeys(lists, features)
        )
        self.services = _FakeServices(lists)
        self.bus = _FakeBus()
        self._states = {
            entity_id: types.SimpleNamespace(
                state="unavailable" if entity_id in unavailable else "0",
                attributes={
                    "supported_features": by_entity.get(entity_id, ALL_FEATURES)
                },
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


def _config_entry(synced=None):
    return types.SimpleNamespace(
        options={"profiles": [_synced_profile()] if synced is None else synced},
        async_on_unload=lambda _cb: None,
    )


def _build(hass, store, *, synced=None):
    """A driver over the fakes, plus the coordinator it will settle through."""
    coordinator = _FakeCoordinator(store)
    return (
        todo_list_sync.TodoListSync(hass, _config_entry(synced), coordinator),
        coordinator,
    )


def _sync(hass, store, *, synced=None, force=True):
    """Build a driver and run one full ``async_sync``."""
    sync, coordinator = _build(hass, store, synced=synced)
    asyncio.run(sync.async_sync(force=force))
    return sync, coordinator


def _once(sync):
    """One ``_sync_once``, so "does this warrant another pass" is observable."""
    return asyncio.run(sync._sync_once(force=True))


def _services(hass, service):
    return [data for name, data in hass.services.calls if name == service]


# ── the happy path ────────────────────────────────────────────────────────────


def test_a_due_task_lands_on_the_list_with_its_date_and_notes():
    hass = _FakeHass({LIST: []})
    store = _FakeStore(tasks={T1: _task(notes=NOTES)})
    _sync(hass, store)
    assert _services(hass, "add_item") == [
        {"entity_id": LIST, "item": NAME, "due_date": DUE, "description": NOTES}
    ]
    # No uid: ``todo.add_item`` answers with nothing, and the next pass binds one.
    assert store.get_todo_list_items() == {
        KEY: {
            "entity_id": LIST,
            "uid": None,
            "summary": NAME,
            "due": DUE,
            "last_completed": None,
        }
    }


def test_a_list_without_the_optional_fields_gets_a_bare_add():
    # The planner gates the optional fields on what the list can hold, so a list
    # with neither feature bit must be told a summary and nothing else — otherwise
    # every pass would "fix" a due date the list silently dropped.
    hass = _FakeHass({LIST: []}, features=BASIC)
    store = _FakeStore(tasks={T1: _task(notes=NOTES)})
    _sync(hass, store)
    assert _services(hass, "add_item") == [{"entity_id": LIST, "item": NAME}]


def test_the_capability_map_is_derived_per_list_from_supported_features():
    hass = _FakeHass(
        {LIST: [], OTHER: []},
        features={LIST: BASIC | SET_DUE_DATE, OTHER: BASIC | SET_DESCRIPTION},
    )
    store = _FakeStore(tasks={T1: _task(notes=NOTES)})
    _sync(hass, store, synced=[_synced_profile(), _synced_profile(M2, entity_id=OTHER)])
    assert _services(hass, "add_item") == [
        {"entity_id": LIST, "item": NAME, "due_date": DUE},
        {"entity_id": OTHER, "item": NAME, "description": NOTES},
    ]


def test_a_renamed_rescheduled_task_updates_the_item_it_is_bound_to():
    stale = _item(summary="Old name", due="2026-06-10", description="Old note")
    hass = _FakeHass({LIST: [stale]})
    store = _FakeStore(
        tasks={T1: _task(notes="New note")},
        items=_tracked(_entry(summary="Old name", due="2026-06-10")),
    )
    _sync(hass, store)
    assert _services(hass, "update_item") == [
        {
            "entity_id": LIST,
            "item": "i1",
            "rename": NAME,
            "due_date": DUE,
            "description": "New note",
        }
    ]
    assert store.get_todo_list_items() == _tracked()


def test_completing_in_home_keeper_ticks_the_item_off_and_relists_the_next_one():
    # A recurring chore done inside Home Keeper: the household should see the line
    # ticked off — not vanish — and the next occurrence arrives beside it.
    hass = _FakeHass({LIST: [_item()]})
    store = _FakeStore(
        tasks={T1: _task(last_completed=DONE_ISO)},
        items=_tracked(),
    )
    _sync(hass, store)
    assert _services(hass, "update_item") == [
        {"entity_id": LIST, "item": "i1", "status": tm.STATUS_COMPLETED}
    ]
    assert _services(hass, "add_item") == [
        {"entity_id": LIST, "item": NAME, "due_date": DUE}
    ]


def test_a_profile_selects_the_tasks_it_would_select_in_a_notification(enricher):
    # The sync plans from tasks enriched with their **effective** labels, so a
    # profile filtering on a label the task only inherits from its device still
    # picks it up — the same tasks a notification on that profile would carry.
    hass = _FakeHass({LIST: []})
    store = _FakeStore(tasks={T1: _task(device_id="dev1")})
    enricher.inherited[T1] = ["dog"]
    _sync(hass, store, synced=[_synced_profile(filt={"labels": ["dog"]})])
    assert enricher.calls == [[_task(device_id="dev1")]]  # handed the raw task…
    assert _services(hass, "add_item") == [
        {"entity_id": LIST, "item": NAME, "due_date": DUE}
    ]  # …and planned from the enriched one


# ── when the list misbehaves ──────────────────────────────────────────────────


@pytest.mark.parametrize("how", ["missing", "unavailable", "unreadable"])
def test_an_unreadable_list_plans_nothing_and_forgets_nothing(how):
    hass = _FakeHass(
        {LIST: [_item()]},
        missing=(LIST,) if how == "missing" else (),
        unavailable=(LIST,) if how == "unavailable" else (),
    )
    if how == "unreadable":
        hass.services.get_items_error = RuntimeError("boom")
    before = _tracked()
    # No tasks at all, so a *readable* list would have this item removed.
    store = _FakeStore(items=dict(before))
    _sync(hass, store)
    assert hass.services.calls == []
    assert store.get_todo_list_items() == before


def test_a_failed_remove_keeps_the_entry_so_the_next_pass_retries():
    # Forgetting the entry would strand that line on the list with nothing left to
    # remember it by.
    hass = _FakeHass({LIST: [_item()]})
    hass.services.fail.add("remove_item")
    before = _tracked()
    store = _FakeStore(items=dict(before))
    _sync(hass, store)
    assert _services(hass, "remove_item") == [{"entity_id": LIST, "item": ["i1"]}]
    assert store.get_todo_list_items() == before


def test_a_failed_update_keeps_the_entry_it_was_going_to_replace():
    hass = _FakeHass({LIST: [_item(summary="Old name")]})
    hass.services.fail.add("update_item")
    before = _tracked(_entry(summary="Old name"))
    store = _FakeStore(tasks={T1: _task()}, items=dict(before))
    _sync(hass, store)
    assert _services(hass, "update_item")  # it was attempted
    assert store.get_todo_list_items() == before  # …and not believed


def test_a_failed_add_is_not_recorded_as_synced():
    hass = _FakeHass({LIST: []})
    hass.services.fail.add("add_item")
    store = _FakeStore(tasks={T1: _task()})
    _sync(hass, store)
    assert _services(hass, "add_item")
    assert store.get_todo_list_items() == {}


@pytest.mark.parametrize(
    ("features", "service"),
    [(BASIC & ~DELETE, "remove_item"), (BASIC & ~CREATE, "add_item")],
)
def test_a_list_missing_a_base_feature_is_not_asked_to_use_it(features, service):
    adding = service == "add_item"
    # Adding: a task nothing on the list holds yet. Removing: a tracked line whose
    # task is gone.
    hass = _FakeHass({LIST: [] if adding else [_item()]}, features=features)
    items = {} if adding else _tracked()
    store = _FakeStore(tasks={T1: _task()} if adding else {}, items=dict(items))
    _sync(hass, store)
    assert hass.services.calls == []
    assert store.get_todo_list_items() == items


def test_a_pass_never_raises_into_the_mutation_that_triggered_it(caplog):
    # A task completion awaits this; it must not be the thing that fails.
    hass = _FakeHass({LIST: []})
    store = _FakeStore(tasks={T1: _task()})

    def _explode():
        raise RuntimeError("storage is on fire")

    store.get_todo_list_items = _explode
    with caplog.at_level("ERROR"):
        _sync(hass, store)  # no exception escapes
    assert "to-do list sync failed" in caplog.text


def test_a_list_that_refuses_every_call_costs_only_a_log_line():
    hass = _FakeHass({LIST: []})

    async def _explode(*args, **kwargs):
        raise RuntimeError("the family list is on fire")

    hass.services.async_call = _explode
    store = _FakeStore(tasks={T1: _task()})
    _sync(hass, store)
    assert store.get_todo_list_items() == {}


# ── the inbound direction ─────────────────────────────────────────────────────


def test_a_ticked_item_completes_the_task_and_settles():
    hass = _FakeHass({LIST: [_item(status=tm.STATUS_COMPLETED)]})
    store = _FakeStore(tasks={T1: _task()}, items=_tracked())
    sync, coordinator = _build(hass, store)
    again = _once(sync)
    assert store.completed == [(T1, ORIGIN)]
    assert coordinator.settles == 1
    assert again is True  # the completion reschedules the task; look again
    # The item they ticked off is theirs — we neither delete nor re-add it.
    assert hass.services.calls == []
    assert store.get_todo_list_items() == {}


def test_the_bookkeeping_is_persisted_before_the_settle_re_enters_us():
    # ``async_settle_buy_tasks`` runs this class again; what it finds must be what
    # this pass concluded, not what the pass before it did.
    hass = _FakeHass({LIST: [_item(status=tm.STATUS_COMPLETED)]})
    store = _FakeStore(tasks={T1: _task()}, items=_tracked())
    sync, _ = _build(hass, store)
    _once(sync)
    assert store.log == ["persist", "settle"]


def test_a_task_that_refuses_remote_completion_says_so_and_reappears(caplog):
    # ``require_tag_scan`` tasks refuse completion from anywhere but a real scan.
    # Restoring the entry would quietly re-bind the task to a line already ticked
    # off; dropping it puts a fresh open item back, which is honest feedback.
    hass = _FakeHass({LIST: [_item(status=tm.STATUS_COMPLETED)]})
    store = _FakeStore(tasks={T1: _task()}, items=_tracked())
    store.complete_error = TaskValidationError("scan its tag to complete it")
    sync, coordinator = _build(hass, store)
    with caplog.at_level("WARNING"):
        again = _once(sync)
    assert store.completed == []
    assert coordinator.settles == 0
    assert again is False
    assert store.get_todo_list_items() == {}
    assert caplog.text.count("did not take") == 1

    caplog.clear()
    with caplog.at_level("WARNING"):
        _once(sync)
    assert "did not take" not in caplog.text  # said once, not on every pass
    assert _services(hass, "add_item") == [
        {"entity_id": LIST, "item": NAME, "due_date": DUE}
    ]


def test_a_task_deleted_mid_pass_drops_its_entry_without_a_word(caplog):
    hass = _FakeHass({LIST: [_item(status=tm.STATUS_COMPLETED)]})
    store = _FakeStore(tasks={T1: _task()}, items=_tracked())
    store.complete_error = KeyError(T1)
    sync, coordinator = _build(hass, store)
    with caplog.at_level("WARNING"):
        again = _once(sync)
    assert again is False
    assert coordinator.settles == 0
    assert store.get_todo_list_items() == {}
    assert caplog.records == []  # nothing to tell anyone about


# ── guards ────────────────────────────────────────────────────────────────────


def test_a_sync_pointed_at_our_own_list_is_refused_once(registry, caplog):
    # Syncing our own tasks onto our own list is a loop, and ours accepts no new
    # items anyway — so the pass must not even read it.
    hass = _FakeHass({OURS: []})
    registry[OURS] = types.SimpleNamespace(
        entity_id=OURS, domain="todo", platform="home_keeper"
    )
    store = _FakeStore(tasks={T1: _task()})
    with caplog.at_level("WARNING"):
        sync, _ = _sync(hass, store, synced=[_synced_profile(entity_id=OURS)])
    assert hass.services.reads == []
    assert hass.services.calls == []
    assert store.get_todo_list_items() == {}
    assert caplog.text.count("its own to-do list") == 1

    caplog.clear()
    with caplog.at_level("WARNING"):
        asyncio.run(sync.async_sync(force=True))
    assert "its own to-do list" not in caplog.text


def test_a_foreign_todo_list_is_not_mistaken_for_ours(registry):
    registry[LIST] = types.SimpleNamespace(
        entity_id=LIST, domain="todo", platform="local_todo"
    )
    hass = _FakeHass({LIST: []})
    store = _FakeStore(tasks={T1: _task()})
    _sync(hass, store)
    assert _services(hass, "add_item")


def test_clearing_a_profiles_picker_takes_its_chores_back_off_the_list():
    # Clearing the picker is the delete: with the sync living inside the profile
    # there is no separate record to remove, so the off switch has to tidy up.
    hass = _FakeHass({LIST: [_item()]})
    store = _FakeStore(tasks={T1: _task()}, items=_tracked())
    _sync(hass, store, synced=[_synced_profile(entity_id="")])
    assert _services(hass, "remove_item") == [{"entity_id": LIST, "item": ["i1"]}]
    assert store.get_todo_list_items() == {}


def test_a_profile_that_is_not_syncing_costs_no_reads():
    # Most households have profiles for the panel and the card and sync none of
    # them; those must not make a pass read a single list.
    hass = _FakeHass({LIST: [_item()]})
    store = _FakeStore(tasks={T1: _task()})
    _sync(hass, store, synced=[_synced_profile(entity_id="")])
    assert hass.services.reads == []
    assert store.get_todo_list_items() == {}


def test_an_event_driven_pass_with_no_drift_reads_no_lists():
    # Every task mutation pokes this; almost none of them concern a sync, and
    # none of those should cost a service call.
    hass = _FakeHass({LIST: [_item()]})
    store = _FakeStore(tasks={T1: _task()}, items=_tracked())
    _sync(hass, store, force=False)
    assert hass.services.reads == []
    assert hass.services.calls == []
    assert store.writes == 0


def test_a_forced_pass_reads_the_lists_even_when_nothing_drifted():
    # The household's side is invisible to ``needs_pass``, so the surfaces that
    # watch for it force a read.
    hass = _FakeHass({LIST: [_item()]})
    store = _FakeStore(tasks={T1: _task()}, items=_tracked())
    _sync(hass, store, force=True)
    assert hass.services.reads == [LIST]
    assert hass.services.calls == []
    assert store.writes == 0


def test_a_pass_running_already_is_folded_in_rather_than_nested():
    hass = _FakeHass({LIST: []})
    store = _FakeStore(tasks={T1: _task()})
    sync, _ = _build(hass, store)
    sync._running = True
    asyncio.run(sync.async_sync(force=True))
    assert hass.services.calls == []
    assert sync._pending is True


def test_a_sync_that_cannot_settle_says_so(caplog):
    """The pass budget guarantees termination; it should not hide a failure.

    Driven through ``_sync_once`` directly: every real path converges, which is the
    point of the design, so the only way to reach the budget is a pass that keeps
    asking for another one. The loop must still end — that is the budget's job —
    but exiting quietly would leave the lists stale with nothing in the log to
    explain it.
    """
    hass = _FakeHass({LIST: []})
    sync, _ = _build(hass, _FakeStore())
    passes = []

    async def _never_settles(*, force):
        passes.append(force)
        return True

    sync._sync_once = _never_settles
    with caplog.at_level("WARNING"):
        asyncio.run(sync.async_sync(force=True))
    assert len(passes) == sync._MAX_PASSES
    assert "did not settle" in caplog.text
    # The guard is released either way, so the next change is not locked out.
    assert sync._running is False and sync._pending is False


def test_a_settling_sync_stays_quiet(caplog):
    hass = _FakeHass({LIST: []})
    store = _FakeStore(tasks={T1: _task()})
    with caplog.at_level("WARNING"):
        _sync(hass, store)
    assert "did not settle" not in caplog.text


# ── the sweep and the listeners ───────────────────────────────────────────────


def test_the_sweep_costs_nothing_until_something_is_configured_or_synced():
    hass = _FakeHass({LIST: []})
    idle, _ = _build(hass, _FakeStore(), synced=[])
    idle.async_schedule_sweep()
    assert hass.tasks == []

    # A configured sync alone is reason enough: a task falling due mutates
    # nothing, so this tick is the only thing that notices it.
    configured, _ = _build(hass, _FakeStore(), synced=[_synced_profile()])
    configured.async_schedule_sweep()
    assert len(hass.tasks) == 1

    # …and so is bookkeeping left by a sync since switched off, which still has
    # items to take back off a list.
    leftover, _ = _build(hass, _FakeStore(items=_tracked()), synced=[])
    leftover.async_schedule_sweep()
    assert len(hass.tasks) == 2


def test_an_unloaded_entry_ends_the_sweep_and_the_pass():
    hass = _FakeHass({LIST: [_item()]})
    store = _FakeStore(tasks={T1: _task()}, items=_tracked())
    sync, _ = _build(hass, store)
    sync._async_stop()
    sync.async_schedule_sweep()
    assert hass.tasks == []
    assert _once(sync) is False
    assert hass.services.reads == []


def _watched_lists(monkeypatch) -> list[list[str]]:
    """Capture what ``async_track_state_change_event`` is asked to watch."""
    watched: list[list[str]] = []

    def _track(_hass, entity_ids, _handler):
        watched.append(list(entity_ids))
        return lambda: None

    monkeypatch.setattr(todo_list_sync, "async_track_state_change_event", _track)
    return watched


def test_start_listeners_watches_every_list_and_every_task_event(monkeypatch):
    hass = _FakeHass({LIST: [], OTHER: []})
    watched = _watched_lists(monkeypatch)
    unloads: list[object] = []
    entry = _config_entry(
        synced=[
            _synced_profile(),
            _synced_profile(M2, entity_id=OTHER),
            _synced_profile("m3", entity_id=LIST),  # a second sync on one list
            _synced_profile("m4", entity_id=""),  # switched off
        ]
    )
    entry.async_on_unload = unloads.append
    sync = todo_list_sync.TodoListSync(hass, entry, _FakeCoordinator(_FakeStore()))
    sync.async_start_listeners()

    assert watched == [[OTHER, LIST]]  # sorted, distinct, the off switch skipped
    assert [name for name, _ in hass.bus.listeners] == list(todo_list_sync._TASK_EVENTS)
    # Everything the entry has to tear down: the stop flag, the state listener, and
    # one subscription per task event.
    assert len(unloads) == 2 + len(todo_list_sync._TASK_EVENTS)


def test_no_configured_list_means_no_state_listener(monkeypatch):
    hass = _FakeHass({LIST: []})
    watched = _watched_lists(monkeypatch)
    entry = _config_entry(synced=[])
    sync = todo_list_sync.TodoListSync(hass, entry, _FakeCoordinator(_FakeStore()))
    sync.async_start_listeners()
    assert watched == []


def test_a_list_edit_forces_a_pass_while_a_task_event_does_not():
    # ``needs_pass`` can see a task change but never a tick-off on somebody's
    # phone, so only the list's own state change has to force the read.
    hass = _FakeHass({LIST: []})
    sync, _ = _build(hass, _FakeStore())
    forced: list[bool] = []

    async def _record(*, force=False):
        forced.append(force)

    sync.async_sync = _record
    hass.async_create_task = asyncio.run
    sync._handle_state_change(None)
    sync._handle_task_event(None)
    assert forced == [True, False]


# ── the store's bookkeeping trio ──────────────────────────────────────────────


def _fresh_store():
    return store_mod.HomeKeeperStore(types.SimpleNamespace())


def test_the_todo_list_bookkeeping_round_trips_through_the_store():
    store = _fresh_store()
    assert store.get_todo_list_items() == {}
    assert asyncio.run(store.async_set_todo_list_items(_tracked())) is True
    assert store.get_todo_list_items() == _tracked()
    assert store._store.saves[-1]["todo_list_items"] == _tracked()


def test_writing_the_same_bookkeeping_again_does_not_touch_the_disk():
    # A pass runs on every task mutation and every edit to a synced list, and
    # most settle to exactly what was already stored.
    store = _fresh_store()
    asyncio.run(store.async_set_todo_list_items(_tracked()))
    saves = len(store._store.saves)
    assert asyncio.run(store.async_set_todo_list_items(_tracked())) is False
    assert len(store._store.saves) == saves


def test_a_document_written_before_todo_lists_existed_loads_clean():
    store = _fresh_store()
    store._store.data = {"tasks": {}, "assets": {}, "problem_notes": {}}
    asyncio.run(store.load())
    assert store.get_todo_list_items() == {}


def test_stored_todo_list_bookkeeping_survives_a_reload():
    store = _fresh_store()
    store._store.data = {"tasks": {}, "todo_list_items": _tracked()}
    asyncio.run(store.load())
    assert store.get_todo_list_items() == _tracked()


def test_removing_the_integration_clears_the_todo_list_bookkeeping():
    store = _fresh_store()
    asyncio.run(store.async_set_todo_list_items(_tracked()))
    asyncio.run(store.async_remove())
    assert store.get_todo_list_items() == {}
    assert store._store.removed is True
