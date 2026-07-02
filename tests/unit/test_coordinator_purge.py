"""Unit tests for the coordinator's one-off purge → deferred reload (N5).

``HomeKeeperCoordinator._purge_expired_one_offs`` auto-deletes completed one-off
tasks past the retention window. ``store.delete_task`` only mutates the store — the
entity registry is cleaned by reloading the config entry. So when a purged task owned
per-task entities (device-attached + enabled) the coordinator must trigger an entry
reload; and because the purge runs inside ``_async_update_data`` (the coordinator's
own refresh), that reload must be **deferred** via ``hass.async_create_task`` rather
than awaited inline (awaiting inline would tear down this coordinator mid-refresh).

The coordinator imports Home Assistant heavily, so — like ``test_calendar.py`` — we
stub the handful of HA symbols it references and register fakes for its HA-aware
sibling modules, then load ``coordinator.py`` under the synthetic ``hk`` package and
drive ``_purge_expired_one_offs`` against a fake store/hass. The real store/entity
wiring is exercised by the integration suite.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 1, tzinfo=TZ)


def _real_ha_present() -> bool:
    """True only when the *real* Home Assistant package is installed.

    A hand-built stub ``homeassistant`` module (e.g. from ``test_calendar.py``) has
    no ``__file__``; the real package does. This distinguishes them so we fill gaps
    over a stub tree but never shadow real submodules.
    """
    mod = sys.modules.get("homeassistant")
    if mod is None:
        try:  # pragma: no cover - depends on environment
            import homeassistant as mod  # type: ignore[no-redef]
        except ImportError:
            return False
    return getattr(mod, "__file__", None) is not None


def _install_ha_stubs() -> None:
    """Additively register the HA symbols ``coordinator.py`` imports.

    Idempotent and non-clobbering: another pure-unit test (``test_calendar.py``)
    installs its own partial ``homeassistant`` stub tree, so we only *fill gaps*
    (create missing modules, set missing attributes) rather than early-return or
    overwrite — otherwise load order between the two suites would matter.
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

    _mod("homeassistant")
    config_entries = _mod("homeassistant.config_entries")
    if not hasattr(config_entries, "ConfigEntry"):

        class ConfigEntry:
            pass

        config_entries.ConfigEntry = ConfigEntry

    core = _mod("homeassistant.core")
    if not hasattr(core, "HomeAssistant"):

        class HomeAssistant:
            pass

        core.HomeAssistant = HomeAssistant

    helpers = _mod("homeassistant.helpers")
    device_registry = _mod("homeassistant.helpers.device_registry")
    if not hasattr(device_registry, "DeviceInfo"):

        class DeviceInfo(dict):
            pass

        device_registry.DeviceInfo = DeviceInfo
    if not hasattr(device_registry, "async_get"):
        device_registry.async_get = lambda hass: None
    helpers.device_registry = device_registry

    update_coordinator = _mod("homeassistant.helpers.update_coordinator")
    if not hasattr(update_coordinator, "DataUpdateCoordinator"):

        class DataUpdateCoordinator:
            def __class_getitem__(cls, item):  # allow ``DataUpdateCoordinator[...]``
                return cls

            def __init__(self, *args, **kwargs) -> None:  # unused (bypass __init__)
                pass

        update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator

    util = _mod("homeassistant.util")
    dt_mod = _mod("homeassistant.util.dt")
    if not hasattr(dt_mod, "now"):
        dt_mod.now = lambda: NOW
    util.dt = dt_mod


def _load_coordinator():
    """Load ``coordinator.py`` under ``hk`` with fake HA-aware sibling modules."""
    existing = sys.modules.get("hk.coordinator")
    # ``test_calendar.py`` registers a bare *stub* ``hk.coordinator`` (just a
    # ``HomeKeeperCoordinator`` placeholder) to satisfy calendar.py's relative
    # import. Only reuse a module that's the *real* one (carries the const import).
    if existing is not None and hasattr(existing, "OPTION_ONE_OFF_RETENTION_DAYS"):
        return existing
    sys.modules.pop("hk.coordinator", None)
    _install_ha_stubs()

    # Fake the HA-aware siblings coordinator imports so we don't drag in the whole
    # integration surface. models/recurrence/transitions are the real pure modules
    # (loaded by tests/conftest.py); companions/notifier/options/store are fakes.
    companions = types.ModuleType("hk.companions")
    companions.async_reconcile = lambda hass: None
    sys.modules["hk.companions"] = companions

    notifier = types.ModuleType("hk.notifier")

    async def _async_send_auto(hass, coord, kinds):  # pragma: no cover - unused
        return None

    notifier.async_send_auto = _async_send_auto
    sys.modules["hk.notifier"] = notifier

    options = types.ModuleType("hk.options")
    options.current_options = lambda entry: entry.options
    sys.modules["hk.options"] = options

    store_mod = types.ModuleType("hk.store")

    class HomeKeeperStore:
        pass

    store_mod.HomeKeeperStore = HomeKeeperStore
    sys.modules["hk.store"] = store_mod

    spec = importlib.util.spec_from_file_location(
        "hk.coordinator", str(_COMPONENT_DIR / "coordinator.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hk.coordinator"] = module
    spec.loader.exec_module(module)
    # Pin the coordinator's clock to our fixed NOW directly on the loaded module, so
    # the purge is deterministic regardless of the shared ``homeassistant.util.dt``
    # stub (``test_calendar.py`` installs one whose ``now()`` deliberately raises).
    module.dt_util = types.SimpleNamespace(now=lambda: NOW)
    return module


coordinator = _load_coordinator()


# ── fakes ────────────────────────────────────────────────────────────────────
class _FakeConfigEntries:
    def __init__(self) -> None:
        self.reloaded: list[str] = []

    def async_reload(self, entry_id: str):
        # Record the call synchronously (before the coroutine is awaited) so the test
        # sees the reload target even though the scheduled task is never driven to
        # completion. Returns a coroutine, mirroring HA's coroutine function.
        self.reloaded.append(entry_id)
        return self._noop()

    async def _noop(self) -> None:
        return None


class _FakeHass:
    def __init__(self) -> None:
        self.config_entries = _FakeConfigEntries()
        self.created: list = []

    def async_create_task(self, coro):
        # Record that a task was scheduled, then close the coroutine so it doesn't
        # warn about never being awaited (we assert on scheduling, not execution).
        self.created.append(coro)
        coro.close()


class _FakeEntry:
    def __init__(self, retention: int) -> None:
        self.entry_id = "entry-1"
        self.options = {coordinator.OPTION_ONE_OFF_RETENTION_DAYS: retention}


class _FakeStore:
    def __init__(self, tasks: dict) -> None:
        self._tasks = tasks
        self.deleted: list[str] = []

    def get_tasks(self) -> dict:
        return dict(self._tasks)

    async def delete_task(self, tid: str) -> None:
        self.deleted.append(tid)
        self._tasks.pop(tid, None)


def _make_coord(tasks: dict, *, retention: int = 30):
    coord = object.__new__(coordinator.HomeKeeperCoordinator)
    coord.config_entry = _FakeEntry(retention)
    coord.store = _FakeStore(tasks)
    coord.hass = _FakeHass()
    return coord


def _one_off(tid: str, *, days_ago: int, device_id: str | None, enabled: bool = True):
    return {
        "id": tid,
        "name": f"Task {tid}",
        "recurrence_type": "one-off",
        "enabled": enabled,
        "device_id": device_id,
        "next_due": None,
        "last_completed": (NOW - timedelta(days=days_ago)).isoformat(),
    }


# ── tests ────────────────────────────────────────────────────────────────────
def test_purge_with_entities_defers_reload():
    """An expired device-attached one-off is deleted and schedules a deferred reload."""
    tasks = {"t1": _one_off("t1", days_ago=60, device_id="dev-1")}
    coord = _make_coord(tasks)
    asyncio.run(coord._purge_expired_one_offs())
    assert coord.store.deleted == ["t1"]
    # Reload was scheduled (deferred), not awaited inline.
    assert len(coord.hass.created) == 1
    assert coord.hass.config_entries.reloaded == ["entry-1"]


def test_purge_without_entities_no_reload():
    """An expired device-less one-off is deleted but needs no entry reload."""
    tasks = {"t1": _one_off("t1", days_ago=60, device_id=None)}
    coord = _make_coord(tasks)
    asyncio.run(coord._purge_expired_one_offs())
    assert coord.store.deleted == ["t1"]
    assert coord.hass.created == []
    assert coord.hass.config_entries.reloaded == []


def test_purge_disabled_device_task_no_reload():
    """A disabled device-attached task owns no per-task entities → no reload."""
    tasks = {"t1": _one_off("t1", days_ago=60, device_id="dev-1", enabled=False)}
    coord = _make_coord(tasks)
    asyncio.run(coord._purge_expired_one_offs())
    assert coord.store.deleted == ["t1"]
    assert coord.hass.created == []


def test_purge_reloads_once_for_mixed_batch():
    """Multiple expired tasks reload the entry exactly once (single deferred task)."""
    tasks = {
        "with": _one_off("with", days_ago=60, device_id="dev-1"),
        "without": _one_off("without", days_ago=60, device_id=None),
    }
    coord = _make_coord(tasks)
    asyncio.run(coord._purge_expired_one_offs())
    assert set(coord.store.deleted) == {"with", "without"}
    assert len(coord.hass.created) == 1


def test_purge_noop_when_nothing_expired():
    """Retention not yet elapsed → nothing deleted, no reload."""
    tasks = {"t1": _one_off("t1", days_ago=5, device_id="dev-1")}
    coord = _make_coord(tasks)
    asyncio.run(coord._purge_expired_one_offs())
    assert coord.store.deleted == []
    assert coord.hass.created == []


def test_purge_disabled_when_retention_zero():
    """Retention 0 (keep-forever default) purges nothing."""
    tasks = {"t1": _one_off("t1", days_ago=999, device_id="dev-1")}
    coord = _make_coord(tasks, retention=0)
    asyncio.run(coord._purge_expired_one_offs())
    assert coord.store.deleted == []
    assert coord.hass.created == []
