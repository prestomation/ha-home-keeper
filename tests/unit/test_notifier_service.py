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

from notifier_harness import (
    FakeCoord,
    FakeHass,
    future_task,
    load_notifier,
    overdue_task,
)

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
    """No task due is a success with ``matched: 0``, not an error.

    The **default** contract, and it must not move: an automation on a time pattern
    calls this all day, and README promises it costs nothing on a quiet day. Only a
    caller that asks for ``when_empty: all_clear`` gets a delivery — see below.
    """
    hass = FakeHass()
    coord = FakeCoord({}, _options())

    response, error = _run(hass, coord, {"notification": "n1"})

    assert error is None
    assert response == {"matched": 0, "sent": None}
    assert hass.services.calls == []


# ── the per-call overrides that make the Test button useful ─────────────────


def test_when_empty_all_clear_delivers_instead_of_sending_nothing():
    """An empty queue still lands something, so delivery can be checked on demand.

    ``matched: 0`` keeps its value and gains a second meaning: with this override it
    says *which* card went out, not whether one did. The panel reads it exactly so.
    """
    hass = FakeHass()
    coord = FakeCoord({}, _options())

    response, error = _run(
        hass, coord, {"notification": "n1", "when_empty": "all_clear"}
    )

    assert error is None
    assert response == {"matched": 0, "sent": None}
    assert len(hass.services.calls) == 1
    payload = hass.services.calls[0][2]
    assert payload["title"] == "All caught up"
    # No buttons on it: there is no task for them to act on.
    assert "actions" not in payload["data"]


def test_when_empty_all_clear_suits_a_digest_too():
    """A digest with nothing in it is the all-clear, not "0 tasks due"."""
    hass = FakeHass()
    coord = FakeCoord({}, _options(style="digest"))

    _, error = _run(hass, coord, {"notification": "n1", "when_empty": "all_clear"})

    assert error is None
    assert hass.services.calls[0][2]["title"] == "All caught up"


def test_status_all_reaches_a_task_an_overdue_profile_would_skip():
    """The case the Test button exists for: something to send, none of it late.

    The saved profile is ``overdue``, so it queues nothing today. The override widens
    it for this one call, and the message says how far off the task is rather than
    calling a task two weeks out "due soon".
    """
    hass = FakeHass()
    options = _options()
    options["profiles"][0]["filter"]["status"] = "overdue"
    coord = FakeCoord({"t1": future_task("t1", days=14)}, options)

    bare, _ = _run(hass, coord, {"notification": "n1"})
    assert bare == {"matched": 0, "sent": None}
    assert hass.services.calls == []

    response, error = _run(hass, coord, {"notification": "n1", "status": "all"})

    assert error is None
    assert response == {"matched": 1, "sent": "t1"}
    assert hass.services.calls[0][2]["message"] == "Due in 14 days."


def test_status_none_forces_the_all_clear_even_with_a_task_due():
    """How the panel offers the other card while the profile has work in it."""
    hass = FakeHass()
    coord = FakeCoord({"t1": overdue_task("t1", days=3)}, _options())

    response, error = _run(
        hass, coord, {"notification": "n1", "status": "none", "when_empty": "all_clear"}
    )

    assert error is None
    assert response == {"matched": 0, "sent": None}
    assert hass.services.calls[0][2]["title"] == "All caught up"


def test_a_status_override_does_not_reach_the_stored_profile():
    """One call must not rewrite the filter every other consumer reads.

    ``resolve_profile`` hands back the live options entry, so an override applied in
    place would leak "everything" into a profile saved as "overdue" — and into the
    card, the admin list and the to-do sync with it.
    """
    hass = FakeHass()
    options = _options()
    options["profiles"][0]["filter"]["status"] = "overdue"
    coord = FakeCoord({"t1": future_task("t1", days=14)}, options)

    _run(hass, coord, {"notification": "n1", "status": "all"})

    assert coord.entry.options["profiles"][0]["filter"]["status"] == "overdue"


def test_an_empty_queue_with_no_target_still_reports_rather_than_sends():
    """``all_clear`` does not invent a destination.

    The service rejects a target-less notification before it reaches the send, so this
    is the auto/internal path: nothing to send to means nothing sent, and no warning
    about "0 task(s)" either.
    """
    hass = FakeHass()
    coord = FakeCoord({}, _options(targets=[]))
    notification = coord.entry.options["notifications"][0]
    profile = profiles.normalize_profile(coord.entry.options["profiles"][0])

    matched, sent = asyncio.run(
        notifier._send(
            hass,
            coord,
            notification,
            profile,
            reason="test",
            when_empty=notifications.WHEN_EMPTY_ALL_CLEAR,
        )
    )

    assert (matched, sent) == (0, None)
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
