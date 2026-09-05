"""Load ``notifier.py`` under the synthetic ``hk`` package, with fakes for the rest.

``notifier.py`` is the Home Assistant boundary of the notification stack, so it cannot
be imported the way the pure core is. Two suites drive it directly —
``test_notifier_blocking`` (the payload build must not block the event loop) and
``test_notifier_service`` (what ``home_keeper.notify`` answers, and what reaches the
``notify`` service) — and both need the same loader, the same pinned clock and the same
minimal ``hass``. They live here rather than in either suite so neither has to import
the other's test module, and so the two cannot drift into disagreeing about what a
notifier under test looks like.

Everything is deliberately small: a fake ``hass`` with a real executor hand-off, a fake
coordinator over ``FakeTaskSnapshotStore``, and stubs for the registries. Nothing here
stands up Home Assistant.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fakes import FakeTaskSnapshotStore
from ha_stubs import install_ha_stubs

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 1, tzinfo=TZ)


def load_notifier():
    """Load ``notifier.py`` under ``hk`` with fake HA-aware sibling modules."""
    existing = sys.modules.get("hk.notifier")
    if existing is not None and hasattr(existing, "async_send_for_notification"):
        return existing
    sys.modules.pop("hk.notifier", None)
    install_ha_stubs()

    # ``options.py`` itself imports HA (ConfigEntry/HomeAssistant) only to type its
    # own params — fake it rather than dragging that in, like coordinator's test does.
    options = types.ModuleType("hk.options")
    options.current_options = lambda entry: entry.options
    sys.modules["hk.options"] = options

    spec = importlib.util.spec_from_file_location(
        "hk.notifier", str(_COMPONENT_DIR / "notifier.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["hk.notifier"] = module
    spec.loader.exec_module(module)
    module.dt_util = types.SimpleNamespace(now=lambda: NOW)
    # Our fake tasks carry no device_id/area_id, so the registries themselves are
    # never consulted — but when *real* HA is installed (as in CI, via
    # pytest-homeassistant-custom-component), the real ``device_registry``/
    # ``area_registry`` ``async_get`` are HA's ``@singleton``-decorated helpers,
    # which need a real ``hass.data`` dict our minimal ``FakeHass`` doesn't have.
    # Overriding the names notifier.py bound (``dr``/``ar``) sidesteps that
    # regardless of whether real HA is present, the same way ``dt_util`` is pinned
    # above.
    module.dr = types.SimpleNamespace(async_get=lambda hass: None)
    module.ar = types.SimpleNamespace(async_get=lambda hass: None)
    return module


class FakeServices:
    """Records every domain, not just ``todo``, and never answers a read.

    What ``_send`` needs from ``hass.services`` is that a ``notify.mobile_app_*``
    call was made and with what — nothing the to-do drivers' services double does.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((domain, service, data))


class FakeHass:
    """``async_add_executor_job`` is a *real* thread hand-off here.

    ``test_notifier_blocking`` asserts on which thread the string-table and CLDR reads
    happen, so a version that runs the job inline would make that suite vacuous.
    """

    def __init__(self, language: str = "en") -> None:
        self.config = types.SimpleNamespace(language=language)
        self.services = FakeServices()

    async def async_add_executor_job(self, func, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, func, *args)


class FakeCoord:
    """Takes tasks rather than a store, and settles nothing.

    *options* becomes the config entry's options, which is where ``notifier`` reads
    saved profiles and notifications back from.
    """

    def __init__(
        self, tasks: dict[str, Any], options: dict[str, Any] | None = None
    ) -> None:
        self.store = FakeTaskSnapshotStore(tasks)
        self.entry = types.SimpleNamespace(options=options or {})


def overdue_task(tid: str, *, days: int) -> dict[str, Any]:
    """A task overdue by *days*, with the fields the filter and the builders read."""
    return _task(tid, -days)


def future_task(tid: str, *, days: int) -> dict[str, Any]:
    """A task not due for *days* yet — nothing an ``overdue`` filter would queue.

    The state a notification is configured in: something to send, none of it late.
    """
    return _task(tid, days)


def _task(tid: str, offset_days: int) -> dict[str, Any]:
    return {
        "id": tid,
        "name": f"Task {tid}",
        "next_due": (NOW + timedelta(days=offset_days)).isoformat(),
        "labels": [],
        "area_id": None,
        "device_id": None,
    }
