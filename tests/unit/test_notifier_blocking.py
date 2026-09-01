"""Regression test: notification payload building must not block the event loop.

``notifier._send`` builds actionable-notification payloads via
``notifications.build_notification``/``build_digest``, which resolve translated
strings (``_notification_strings``) and CLDR plural rules
(``_babel_locale().plural_form``) — both do blocking file I/O on first use per
language (see ``notifications.py`` module docstring for why that module stays
HA-free and can't call ``hass.async_add_executor_job`` itself). Building the
payload directly on the event loop thread trips Home Assistant's own
blocking-call detector — see the traceback pasted in issue #150's follow-up
comment. This drives ``_send`` on a real running event loop and asserts the
blocking lookups actually run off that thread (via
``hass.async_add_executor_job``), not on it.

The coordinator's own blocking-call test (``test_coordinator_purge.py``) loads the
real module under a synthetic ``hk`` package over the shared HA stub tree in
``ha_stubs.py``; this follows the same pattern for ``notifier.py``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import threading
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fakes import FakeTaskSnapshotStore
from ha_stubs import install_ha_stubs

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 1, tzinfo=TZ)


def _load_notifier():
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
    # which need a real ``hass.data`` dict our minimal ``_FakeHass`` doesn't have.
    # Overriding the names notifier.py bound (``dr``/``ar``) sidesteps that
    # regardless of whether real HA is present, the same way ``dt_util`` is pinned
    # above.
    module.dr = types.SimpleNamespace(async_get=lambda hass: None)
    module.ar = types.SimpleNamespace(async_get=lambda hass: None)
    return module


notifier = _load_notifier()
notifications = sys.modules["hk.notifications"]
profiles = sys.modules["hk.profiles"]


# ── fakes ────────────────────────────────────────────────────────────────────


class _FakeServices:
    """Private: records every domain, not just ``todo``, and never answers a read.

    What ``_send`` needs from ``hass.services`` is that a ``notify.mobile_app_*``
    call was made and with what — nothing the to-do drivers' services double does.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((domain, service, data))


class _FakeHass:
    """Private: ``async_add_executor_job`` is the whole point of this suite.

    It has to be a *real* thread hand-off, since the assertion is about which
    thread the string-table and CLDR reads happen on.
    """

    def __init__(self) -> None:
        self.config = types.SimpleNamespace(language="en")
        self.services = _FakeServices()

    async def async_add_executor_job(self, func, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, func, *args)


class _FakeCoord:
    """Private: takes tasks rather than a store, and settles nothing."""

    def __init__(self, tasks: dict) -> None:
        self.store = FakeTaskSnapshotStore(tasks)


def _overdue_task(tid: str, *, days: int) -> dict:
    return {
        "id": tid,
        "name": f"Task {tid}",
        "next_due": (NOW - timedelta(days=days)).isoformat(),
        "labels": [],
        "area_id": None,
        "device_id": None,
    }


# ── the test ─────────────────────────────────────────────────────────────────


def test_send_does_not_block_the_event_loop(monkeypatch):
    """Building a walk notification's payload must not read files on the loop thread.

    ``_notification_strings``/``_babel_locale`` are the two blocking lookups the
    reporter's traceback caught mid-flight (a ``.json`` string table read and a Babel
    CLDR plural-rules read). We spy on both — bypassing their ``functools.cache`` via
    ``__wrapped__`` so every call actually re-does the blocking work instead of
    hitting an already-warm cache from another test/import in this process — and
    assert neither is ever invoked on the thread driving the event loop.
    """
    orig_strings = notifications._notification_strings.__wrapped__
    orig_babel = notifications._babel_locale.__wrapped__
    call_threads: list[int] = []

    def spy_strings(lang):
        call_threads.append(threading.get_ident())
        return orig_strings(lang)

    def spy_babel(lang):
        call_threads.append(threading.get_ident())
        return orig_babel(lang)

    monkeypatch.setattr(notifications, "_notification_strings", spy_strings)
    monkeypatch.setattr(notifications, "_babel_locale", spy_babel)

    task = _overdue_task("t1", days=3)  # multi-day overdue -> exercises _tn/plural_form
    coord = _FakeCoord({"t1": task})
    hass = _FakeHass()
    notification = notifications.normalize_notification(
        {
            # A real companion-app target: `normalize_notification` drops anything
            # that is not a `mobile_app_*` service, so a stand-in name would make
            # this send a no-op and the test vacuous.
            "targets": ["mobile_app_phone"],
            "actions": ["complete"],
            "style": notifications.STYLE_WALK,
        }
    )
    profile = profiles.normalize_profile({})  # default status = overdue

    main_thread_id = threading.get_ident()
    matched, sent = asyncio.run(
        notifier._send(hass, coord, notification, profile, reason="test")
    )

    assert matched == 1
    assert sent == "t1"
    assert hass.services.calls, "expected a notify.mobile_app_phone call"
    assert call_threads, "expected the translation/plural-rule lookups to run"
    assert main_thread_id not in call_threads, (
        "notification string/plural-rule lookups ran on the event loop thread — "
        "blocking file I/O (json + Babel CLDR data) must go through "
        "hass.async_add_executor_job, not run inline in _send"
    )
