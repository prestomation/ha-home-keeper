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
``ha_stubs.py``; this follows the same pattern for ``notifier.py``. The loader and the
fakes live in ``notifier_harness.py``, shared with ``test_notifier_service.py``.
"""

from __future__ import annotations

import asyncio
import sys
import threading

from notifier_harness import FakeCoord, FakeHass, load_notifier, overdue_task

notifier = load_notifier()
notifications = sys.modules["hk.notifications"]
profiles = sys.modules["hk.profiles"]


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

    task = overdue_task("t1", days=3)  # multi-day overdue -> exercises _tn/plural_form
    coord = FakeCoord({"t1": task})
    hass = FakeHass()
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
