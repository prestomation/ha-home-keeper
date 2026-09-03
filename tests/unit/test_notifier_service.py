"""What ``home_keeper.notify`` answers, and what it puts on the wire.

Both halves of issue #255's follow-up report live here.

The **response** is the panel's Test button's only source of truth for whether anything
went out, and its shape is easy to read wrong: ``sent`` is the *task id* a walk surfaced
(``None`` for a digest, and for an empty queue), while ``matched`` is the count. The
panel read ``sent`` as a count, so every real delivery reported "no task is due". A test
that only checked ``matched`` would not have caught that — the assertion has to pin
``sent``'s **type**, not just its truthiness.

The **payload** is where a saved notification's channel and urgency have to end up:
``data.channel`` for Android, ``data.push`` for iOS. ``payload_data`` is unit-tested on
its own, but nothing asserted that the *service* path — resolve a saved notification out
of stored options, normalize it, build, send — carries those two fields all the way to
``notify.mobile_app_*``. That is the only path the Test button and an automation use.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from notifier_harness import FakeCoord, FakeHass, load_notifier, overdue_task

notifier = load_notifier()
# Loading the notifier is what puts its pure siblings on ``hk`` — read them from there
# rather than importing them again, so the test normalizes with the same code the
# module under test resolves.
notifications = sys.modules["hk.notifications"]
profiles = sys.modules["hk.profiles"]

PROFILE_ID = "p1"


def _options(**notification: Any) -> dict[str, Any]:
    """Stored options holding one all-due profile and one notification over it."""
    profile = profiles.normalize_profile(
        {"id": PROFILE_ID, "name": "Everything", "filter": {"status": "all"}}
    )
    notif = notifications.normalize_notification(
        {
            "id": "n1",
            "name": "Bins",
            "profile_id": PROFILE_ID,
            "targets": ["mobile_app_phone"],
            "actions": ["complete"],
            "style": "walk",
            **notification,
        }
    )
    return {"profiles": [profile], "notifications": [notif]}


def _run(hass, coord, data: dict[str, Any]):
    return asyncio.run(notifier.async_run_notify(hass, coord, data))


def test_response_reports_the_matched_count_and_the_task_it_walked_to():
    """``sent`` is a task id, not a count — the misread behind #255's Test button.

    Asserting the id itself (rather than that ``sent`` is truthy) is the point: a task
    id is a string, so a caller treating it as a number gets ``NaN`` and reads every
    delivery as "nothing was sent".
    """
    hass = FakeHass()
    coord = FakeCoord({"t1": overdue_task("t1", days=3)}, _options())

    response, error = _run(hass, coord, {"notification": "n1"})

    assert error is None
    assert response == {"matched": 1, "sent": "t1"}
    assert isinstance(response["sent"], str)
    assert hass.services.calls, "expected a notify.mobile_app_phone call"


def test_a_digest_that_delivered_reports_no_task():
    """A digest names no task, so only ``matched`` says the send happened.

    This is the case that makes ``sent`` unusable as a delivery signal: it is ``None``
    on a run that did deliver.
    """
    hass = FakeHass()
    coord = FakeCoord({"t1": overdue_task("t1", days=3)}, _options(style="digest"))

    response, error = _run(hass, coord, {"notification": "n1"})

    assert error is None
    assert response == {"matched": 1, "sent": None}
    assert hass.services.calls, "a digest with a due task must still send"


def test_an_empty_queue_reports_nothing_and_sends_nothing():
    """No task due is a success with ``matched: 0``, not an error."""
    hass = FakeHass()
    coord = FakeCoord({}, _options())

    response, error = _run(hass, coord, {"notification": "n1"})

    assert error is None
    assert response == {"matched": 0, "sent": None}
    assert hass.services.calls == []


def test_a_saved_channel_and_urgency_reach_the_notify_payload():
    """The service path carries both fields through to the mobile-app ``data`` block.

    ``payload_data`` is covered on its own; what this pins is that nothing between the
    stored notification and ``notify.mobile_app_*`` drops them — the reporter on #255
    saw a notification arrive on Android's General channel with a channel configured,
    and this is the half of that path Home Keeper owns.
    """
    hass = FakeHass()
    coord = FakeCoord(
        {"t1": overdue_task("t1", days=3)},
        _options(channel="Trash", urgency="high"),
    )

    _run(hass, coord, {"notification": "n1"})

    (domain, service, payload) = hass.services.calls[0]
    assert (domain, service) == ("notify", "mobile_app_phone")
    data = payload["data"]
    assert data["channel"] == "Trash"  # Android: the notification channel
    assert data["importance"] == "high"  # Android: the channel's importance
    assert data["push"]["thread-id"] == "Trash"  # iOS: no channels, so a thread
    assert data["push"]["interruption-level"] == "time-sensitive"


def test_an_unconfigured_notification_adds_no_channel_keys():
    """No channel at normal urgency sends what it sent before the fields existed.

    The guarantee ``payload_data`` is written around, asserted here on the real service
    path so a well-meant default added anywhere in between would fail.
    """
    hass = FakeHass()
    coord = FakeCoord({"t1": overdue_task("t1", days=3)}, _options())

    _run(hass, coord, {"notification": "n1"})

    data = hass.services.calls[0][2]["data"]
    assert "channel" not in data
    assert "importance" not in data
    assert "push" not in data
