"""One Home Assistant stub tree for the unit suites that load HA-coupled modules.

Seven suites here (``test_calendar``, ``test_coordinator_purge``,
``test_device_heal``, ``test_notifier_blocking``, ``test_shopping_sync``,
``test_todo``, ``test_todo_list_sync``) load a **real** module out of
``custom_components/home_keeper`` under the synthetic ``hk`` package (see
``tests/conftest.py``) rather than standing up the full Home Assistant test
harness. Each of them needs a handful of ``homeassistant`` symbols to exist so
the imports resolve; they all used to hand-roll their own partial tree, which is
what this module replaces.

The contract every caller depends on:

* **Additive, never clobbering.** Every symbol is written behind a
  ``if not hasattr(...)`` guard, so a real Home Assistant submodule — or a
  richer stub another suite installed first — is filled in around, never
  overwritten.
* **Idempotent, and load-order-free.** Because it only fills gaps, it does not
  matter which suite gets here first, or how many times it is called.
* **A superset.** It registers the union of what all seven suites import, so a
  suite may find symbols present that it does not itself need. That is
  deliberate: one tree with everything in it beats seven that disagree.
* **It does not pin the clock.** ``homeassistant.util.dt.now`` *raises*, because
  a shared "now" that silently answers the wrong instant is worse than one that
  says it was never set up. Every suite that needs a fixed clock pins
  ``module.dt_util`` on the module it loaded, after loading it — which is also
  what keeps those suites independent of each other.

Nothing here imports Home Assistant for real: ``install_ha_stubs`` builds plain
``types.ModuleType`` objects, and ``real_ha_present`` only probes. That matters
because ``tests/conftest.py`` loads the pure core eagerly at import time.
"""

from __future__ import annotations

import enum
import sys
import types
import typing
from datetime import UTC, datetime

__all__ = ["install_ha_stubs", "real_ha_present"]


def real_ha_present() -> bool:
    """True only when the *real* Home Assistant package is installed.

    A hand-built stub ``homeassistant`` module has no ``__file__``; the real
    package does. This distinguishes them so we fill gaps over a stub tree but
    never shadow real submodules.
    """
    mod = sys.modules.get("homeassistant")
    if mod is None:
        try:  # pragma: no cover - depends on environment
            import homeassistant as mod  # type: ignore[no-redef]
        except ImportError:
            return False
    return getattr(mod, "__file__", None) is not None


def _mod(name: str) -> types.ModuleType:
    """Return ``name`` from ``sys.modules``, registering an empty one if absent."""
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m


def install_ha_stubs() -> None:
    """Additively register the HA symbols the HA-coupled unit suites import.

    See the module docstring for the contract. A no-op when the real package is
    installed, which is the shape the CI lane with
    ``pytest-homeassistant-custom-component`` runs in.
    """
    if real_ha_present():  # pragma: no cover - real HA env
        return

    ha = _mod("homeassistant")
    _install_components(ha)
    _install_config_entries()
    _install_const()
    _install_core()
    _install_exceptions()
    _install_helpers()
    _install_util()


def _install_components(ha: types.ModuleType) -> None:
    """``homeassistant.components.{calendar,todo}`` — the two entity platforms."""
    components = _mod("homeassistant.components")
    ha.components = components

    comp_cal = _mod("homeassistant.components.calendar")
    if not hasattr(comp_cal, "CalendarEntity"):

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
    components.calendar = comp_cal

    comp_todo = _mod("homeassistant.components.todo")
    if not hasattr(comp_todo, "TodoItem"):

        class TodoItem:
            def __init__(
                self,
                *,
                uid=None,
                summary=None,
                status=None,
                due=None,
                description=None,
            ) -> None:
                self.uid = uid
                self.summary = summary
                self.status = status
                self.due = due
                self.description = description

        class TodoItemStatus(enum.Enum):
            NEEDS_ACTION = "needs_action"
            COMPLETED = "completed"

        class TodoListEntity:
            pass

        comp_todo.TodoItem = TodoItem
        comp_todo.TodoItemStatus = TodoItemStatus
        comp_todo.TodoListEntity = TodoListEntity

    # Guarded on a *member* rather than on the name, so that a four-bit flag left
    # by an older stub is upgraded rather than kept: the to-do list sync gates its
    # optional fields on ``SET_DUE_DATE_ON_ITEM``/``SET_DESCRIPTION_ON_ITEM``,
    # which the entity and the shopping mirror never ask for. These are Home
    # Assistant's own values, and a strict superset of the bits any one suite
    # needs, so whoever gets here first leaves every member the others look for.
    feature = getattr(comp_todo, "TodoListEntityFeature", None)
    if feature is None or not hasattr(feature, "SET_DUE_DATE_ON_ITEM"):

        class TodoListEntityFeature(enum.IntFlag):
            CREATE_TODO_ITEM = 1
            DELETE_TODO_ITEM = 2
            UPDATE_TODO_ITEM = 4
            MOVE_TODO_ITEM = 8
            SET_DUE_DATE_ON_ITEM = 16
            SET_DUE_DATETIME_ON_ITEM = 32
            SET_DESCRIPTION_ON_ITEM = 64

        comp_todo.TodoListEntityFeature = TodoListEntityFeature
    components.todo = comp_todo


def _install_config_entries() -> None:
    """``homeassistant.config_entries`` — names only; nothing calls into them."""
    config_entries = _mod("homeassistant.config_entries")
    if not hasattr(config_entries, "ConfigEntry"):

        class ConfigEntry:
            pass

        config_entries.ConfigEntry = ConfigEntry
    if not hasattr(config_entries, "ConfigEntryState"):

        class ConfigEntryState(enum.Enum):
            LOADED = "loaded"

        config_entries.ConfigEntryState = ConfigEntryState


def _install_const() -> None:
    """``homeassistant.const`` — the two state strings the sync drivers compare."""
    const = _mod("homeassistant.const")
    if not hasattr(const, "STATE_UNAVAILABLE"):
        const.STATE_UNAVAILABLE = "unavailable"
    if not hasattr(const, "STATE_UNKNOWN"):
        const.STATE_UNKNOWN = "unknown"


def _install_core() -> None:
    """``homeassistant.core`` — annotation stand-ins plus the ``callback`` no-op."""
    core = _mod("homeassistant.core")
    # Subscriptable on purpose: ``todo_sync_driver.py`` annotates with
    # ``Event[EventStateChangedData]``, which a bare ``type`` cannot carry.
    for name in ("HomeAssistant", "Event", "EventStateChangedData"):
        if not hasattr(core, name):
            setattr(
                core,
                name,
                type(
                    name, (), {"__class_getitem__": classmethod(lambda cls, item: cls)}
                ),
            )
    if not hasattr(core, "CALLBACK_TYPE"):
        core.CALLBACK_TYPE = object
    if not hasattr(core, "callback"):
        core.callback = lambda func: func


def _install_exceptions() -> None:
    """``homeassistant.exceptions`` — with the translation kwargs HA carries."""
    exceptions = _mod("homeassistant.exceptions")
    if not hasattr(exceptions, "HomeAssistantError"):

        class HomeAssistantError(Exception):
            def __init__(
                self,
                *args,
                translation_domain=None,
                translation_key=None,
                translation_placeholders=None,
            ) -> None:
                super().__init__(*args)
                self.translation_domain = translation_domain
                self.translation_key = translation_key
                self.translation_placeholders = translation_placeholders

        exceptions.HomeAssistantError = HomeAssistantError


def _install_helpers() -> None:
    """``homeassistant.helpers.*`` — the registries, the event helper, storage."""
    helpers = _mod("homeassistant.helpers")

    area_registry = _mod("homeassistant.helpers.area_registry")
    if not hasattr(area_registry, "async_get"):
        area_registry.async_get = lambda hass: None
    helpers.area_registry = area_registry

    device_registry = _mod("homeassistant.helpers.device_registry")
    if not hasattr(device_registry, "DeviceInfo"):

        class DeviceInfo(dict):
            pass

        device_registry.DeviceInfo = DeviceInfo
    # A callable rather than a placeholder class: this is the one registry getter
    # a suite might reach through without replacing it first, and answering
    # ``None`` is the honest "there is no registry here".
    if not hasattr(device_registry, "async_get"):
        device_registry.async_get = lambda hass: None
    for name in ("async_entries_for_config_entry", "DeviceRegistry", "DeviceEntry"):
        if not hasattr(device_registry, name):
            setattr(device_registry, name, type(name, (), {}))
    helpers.device_registry = device_registry

    entity_platform = _mod("homeassistant.helpers.entity_platform")
    if not hasattr(entity_platform, "AddEntitiesCallback"):
        entity_platform.AddEntitiesCallback = object
    helpers.entity_platform = entity_platform

    entity_registry = _mod("homeassistant.helpers.entity_registry")
    # This only needs to *exist* so the imports resolve. Every suite that reads a
    # registry for real injects its own on the loaded module's ``er`` binding,
    # precisely because this tree is shared and reaching for it would make one
    # suite depend on another's load order.
    if not hasattr(entity_registry, "async_get"):
        entity_registry.async_get = lambda hass: types.SimpleNamespace(entities={})
    if not hasattr(entity_registry, "async_entries_for_device"):
        entity_registry.async_entries_for_device = type(
            "async_entries_for_device", (), {}
        )
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

    update_coordinator = _mod("homeassistant.helpers.update_coordinator")
    if not hasattr(update_coordinator, "CoordinatorEntity"):
        _T = typing.TypeVar("_T")

        class CoordinatorEntity(typing.Generic[_T]):
            def __init__(self, coordinator) -> None:
                self.coordinator = coordinator

        update_coordinator.CoordinatorEntity = CoordinatorEntity
    if not hasattr(update_coordinator, "DataUpdateCoordinator"):

        class DataUpdateCoordinator:
            def __class_getitem__(cls, item):  # allow ``DataUpdateCoordinator[...]``
                return cls

            def __init__(self, *args, **kwargs) -> None:  # unused (bypass __init__)
                pass

        update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator


def _install_util() -> None:
    """``homeassistant.util.dt`` — everything but a working ``now()``."""
    util = _mod("homeassistant.util")
    dt = _mod("homeassistant.util.dt")
    if not hasattr(dt, "parse_datetime"):

        def parse_datetime(value):
            if not value:
                return None
            try:
                return datetime.fromisoformat(value)
            except (TypeError, ValueError):
                return None

        dt.parse_datetime = parse_datetime
    if not hasattr(dt, "now"):

        def now():  # pinned per-suite on the loaded module's ``dt_util`` binding
            raise AssertionError("dt_util.now() must be patched in tests")

        dt.now = now
    if not hasattr(dt, "DEFAULT_TIME_ZONE"):
        dt.DEFAULT_TIME_ZONE = UTC
    if not hasattr(dt, "as_local"):

        def as_local(value):
            # Reads the module global at call time, like HA's own implementation.
            # Nothing here patches it — a suite that needs a different "local"
            # swaps the loaded module's ``dt_util`` wholesale — so this only ever
            # resolves to UTC. It exists so the tests that don't care about the
            # zone can still call through.
            return value.astimezone(dt.DEFAULT_TIME_ZONE)

        dt.as_local = as_local
    util.dt = dt
