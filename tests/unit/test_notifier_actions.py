"""What a button tap and an automatic trigger do in ``notifier.py``.

The tap handler is the only path from a phone back into the store, so each test here
drives it the way the companion app does: an ``mobile_app_notification_action`` event
with an encoded action string. The store is a small fake that records which verb
reached it, and moves ``next_due`` the way the real one would, so the freshness token
on a second tap is really stale.

The automatic-trigger tests call ``async_send_auto`` with the ``(kind, task_id)`` pairs
the coordinator hands it, and read which notify targets were called.
"""

from __future__ import annotations

import asyncio
import sys
import types
from datetime import timedelta
from typing import Any

from notifier_harness import NOW, FakeHass, load_notifier, overdue_task

notifier = load_notifier()
notifications = sys.modules["hk.notifications"]
profiles = sys.modules["hk.profiles"]


class _ActionStore:
    """The slice of ``store.py`` the tap handler calls, with recorded calls."""

    def __init__(self, tasks: dict[str, dict[str, Any]]) -> None:
        self._tasks = tasks
        self.calls: list[tuple[str, str]] = []

    def get_tasks(self) -> dict[str, dict[str, Any]]:
        return dict(self._tasks)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self._tasks.get(task_id)

    async def complete_task(self, task_id, *, origin=None):
        self.calls.append(("complete", task_id))
        task = self._tasks[task_id]
        task["next_due"] = (NOW + timedelta(days=1)).isoformat()

    async def snooze_task(self, task_id, until, *, origin=None):
        self.calls.append(("snooze", task_id))
        self._tasks[task_id]["next_due"] = until.isoformat()

    async def skip_task(self, task_id, *, origin=None):
        self.calls.append(("skip", task_id))
        task = self._tasks[task_id]
        task["next_due"] = (NOW + timedelta(days=30)).isoformat()


class _Coord:
    def __init__(self, tasks, options) -> None:
        self.store = _ActionStore(tasks)
        self.entry = types.SimpleNamespace(options=options)

    async def async_settle_buy_tasks(self) -> None:
        return None

    async def async_request_refresh(self) -> None:
        return None


class _Bus:
    def __init__(self) -> None:
        self.listener = None

    def async_listen(self, event_type, listener):
        assert event_type == notifier.EVENT_MOBILE_APP_ACTION
        self.listener = listener
        return lambda: None


class _Hass(FakeHass):
    def __init__(self) -> None:
        super().__init__()
        self.bus = _Bus()
        self.pending: list[Any] = []

    def async_create_task(self, coro) -> None:
        self.pending.append(coro)


def _options(*, status="overdue", allow_snooze=True, **notification):
    profile = profiles.normalize_profile(
        {"id": "p1", "name": "Walk", "filter": {"status": status}}
    )
    notif = notifications.normalize_notification(
        {
            "id": "n1",
            "name": "Walk",
            "profile_id": "p1",
            "targets": ["mobile_app_phone"],
            "actions": ["complete", "snooze", "skip", "open"],
            "style": "walk",
            **notification,
        }
    )
    return {
        "profiles": [profile],
        "notifications": [notif],
        "allow_snooze": allow_snooze,
        "allow_skip": True,
    }


def _tap(hass: _Hass, *actions: str) -> None:
    """Fire each action string in turn, and run its handler to the end."""

    async def _run() -> None:
        for action in actions:
            hass.bus.listener(types.SimpleNamespace(data={"action": action}))
            while hass.pending:
                await hass.pending.pop(0)

    asyncio.run(_run())


def _setup(tasks, options):
    hass = _Hass()
    coord = _Coord(tasks, options)

    async def _live(_hass):
        return coord

    # The listener finds the coordinator for each tap (X02-5).
    notifier._async_live_coordinator = _live
    notifier.async_setup_notifications(hass)
    return hass, coord


def _action(verb: str, task: dict[str, Any]) -> str:
    return notifications.encode_action(
        verb, task["id"], "n1", notifications.due_token(task)
    )


# ── B16-2: Snooze and Skip check the freshness token ────────────────────────────────


def test_b16_2_a_stale_snooze_tap_does_not_move_the_task():
    """B16-2: a Snooze tap on a card for a schedule that has moved is ignored."""
    task = overdue_task("t1", days=3)
    hass, coord = _setup({"t1": task}, _options())
    snooze = _action("snooze", task)
    _tap(hass, _action("complete", task))
    moved_to = task["next_due"]

    _tap(hass, snooze)

    assert coord.store.calls == [("complete", "t1")]
    assert task["next_due"] == moved_to


def test_b16_2_a_stale_skip_tap_does_not_move_the_task():
    """B16-2: a Skip tap on a card for a schedule that has moved is ignored."""
    task = overdue_task("t1", days=3)
    hass, coord = _setup({"t1": task}, _options())
    skip = _action("skip", task)
    _tap(hass, _action("complete", task))

    _tap(hass, skip)

    assert coord.store.calls == [("complete", "t1")]


def test_b16_2_a_current_snooze_and_skip_tap_still_act():
    """B16-2: the token check refuses only a stale tap, not a current one."""
    task = overdue_task("t1", days=3)
    hass, coord = _setup({"t1": task}, _options())

    _tap(hass, _action("snooze", task))
    _tap(hass, _action("skip", task))

    assert coord.store.calls == [("snooze", "t1"), ("skip", "t1")]


def test_b16_2_a_legacy_snooze_or_skip_on_a_due_soon_task_still_acts():
    """B16-2: a tokenless Snooze or Skip is accepted on a task that is not overdue.

    A due-soon walk card offers both, so the ``is_overdue`` rule of Mark done would
    refuse a legacy tap that was valid when the card was built.
    """
    task = {
        **overdue_task("t1", days=0),
        "next_due": (NOW + timedelta(days=1)).isoformat(),
    }
    hass, coord = _setup({"t1": task}, _options(status="due_soon"))

    _tap(hass, "home_keeper::snooze::t1::n1")
    _tap(hass, "home_keeper::skip::t1::n1")

    assert coord.store.calls == [("snooze", "t1"), ("skip", "t1")]


def test_b16_2_a_legacy_complete_on_a_due_soon_task_is_still_refused():
    """B16-2: Mark done keeps its own rule — a tokenless tap needs an overdue task."""
    task = {
        **overdue_task("t1", days=0),
        "next_due": (NOW + timedelta(days=1)).isoformat(),
    }
    hass, coord = _setup({"t1": task}, _options(status="due_soon"))

    _tap(hass, "home_keeper::complete::t1::n1")

    assert coord.store.calls == []


def test_b16_2_a_tap_for_a_deleted_task_is_ignored():
    """B16-2: every verb reads the task first, so a deleted one is a no-op."""
    hass, coord = _setup({}, _options())

    _tap(hass, "home_keeper::snooze::gone::n1::2026-06-01T00:00:00-04:00")

    assert coord.store.calls == []
    assert hass.services.calls == []


# ── B16-3: the injected Snooze on a completion-blocked task works ───────────────────


def _blocked_task() -> dict[str, Any]:
    return {
        **overdue_task("t1", days=2),
        "managed_by": {"source": "problem_sensor", "completion_blocked": True},
    }


def test_b16_3_snooze_on_a_blocked_task_works_with_the_switch_off():
    """B16-3: the Snooze ``actions_for`` injects on a blocked task must act.

    With ``allow_snooze`` off, the card for a completion-blocked task shows Snooze
    only. If the tap is refused, the walk never moves past that task.
    """
    task = _blocked_task()
    hass, coord = _setup({"t1": task}, _options(allow_snooze=False))
    built = notifications.actions_for(
        task, ["complete", "open"], allow_snooze=False, allow_skip=True
    )
    assert built[0] == "snooze"

    _tap(hass, _action("snooze", task))

    assert coord.store.calls == [("snooze", "t1")]
    assert task["next_due"] == (NOW + timedelta(hours=24)).isoformat()


def test_b16_3_snooze_on_an_ordinary_task_stays_off_with_the_switch_off():
    """B16-3: the exception is for a blocked task only."""
    task = overdue_task("t1", days=2)
    hass, coord = _setup({"t1": task}, _options(allow_snooze=False))

    _tap(hass, _action("snooze", task))

    assert coord.store.calls == []
    assert hass.services.calls == []


def test_b16_3_skip_on_an_ordinary_task_stays_off_with_the_switch_off():
    """B16-3: ``allow_skip`` off still refuses Skip, blocked or not."""
    task = overdue_task("t1", days=2)
    options = _options()
    options["allow_skip"] = False
    hass, coord = _setup({"t1": task}, options)

    _tap(hass, _action("skip", task))

    assert coord.store.calls == []


# ── B16-5: the walk-advance does not re-send the task just acted on ─────────────────


def _last_payload(hass: _Hass) -> dict[str, Any]:
    domain, service, payload = hass.services.calls[-1]
    assert (domain, service) == ("notify", "mobile_app_phone")
    return payload


def test_b16_5_a_due_soon_walk_does_not_resend_the_completed_task():
    """B16-5: under ``due_soon`` a completed task can still be due; it is not re-sent.

    The fake store moves a completed task one day ahead, which is inside the
    due-soon window, so without the fix the walk sends it again with new buttons.
    """
    task = overdue_task("t1", days=1)
    hass, coord = _setup({"t1": task}, _options(status="due_soon"))

    _tap(hass, _action("complete", task))

    assert len(hass.services.calls) == 1
    payload = _last_payload(hass)
    assert "actions" not in payload["data"]
    notification = coord.entry.options["notifications"][0]
    assert payload["title"] == notifications.build_all_clear(notification)["title"]


def _routed_action(verb: str, task: dict[str, Any], notification_id: str) -> str:
    return notifications.encode_action(
        verb, task["id"], notification_id, notifications.due_token(task)
    )


def test_b16_8_a_walk_sent_with_a_target_override_goes_on_at_that_target():
    first = overdue_task("t1", days=2)
    second = overdue_task("t2", days=1)
    hass, coord = _setup({"t1": first, "t2": second}, _options())

    _tap(hass, _routed_action("complete", first, "n1@mobile_app_kid"))

    assert coord.store.calls == [("complete", "t1")]
    assert [c[1] for c in hass.services.calls] == ["mobile_app_kid"]
    payload = hass.services.calls[0][2]
    assert payload["data"]["tag"] == "home_keeper_n1@mobile_app_kid"
    head = notifications.decode_action(payload["data"]["actions"][0]["action"])
    assert head[1:3] == ("t2", "n1@mobile_app_kid")


def test_b16_7_an_adhoc_walk_goes_on_after_a_tap():
    first = overdue_task("t1", days=2)
    second = overdue_task("t2", days=1)
    hass, coord = _setup({"t1": first, "t2": second}, _options())

    _tap(hass, _routed_action("skip", first, "adhoc.p1@mobile_app_kid"))

    assert coord.store.calls == [("skip", "t1")]
    assert [c[1] for c in hass.services.calls] == ["mobile_app_kid"]
    head = notifications.decode_action(
        hass.services.calls[0][2]["data"]["actions"][0]["action"]
    )
    assert head[1:3] == ("t2", "adhoc.p1@mobile_app_kid")


def test_b16_12_no_all_clear_when_the_profile_is_gone():
    """B16-12: a walk whose profile was deleted sends nothing after a tap.

    The queue is not known, so an "All caught up" card would be false.
    """
    task = overdue_task("t1", days=1)
    hass, coord = _setup({"t1": task}, _options(profile_id="p_gone"))

    _tap(hass, _action("complete", task))

    assert coord.store.calls == [("complete", "t1")]
    assert hass.services.calls == []


def test_b16_5_a_due_soon_walk_moves_to_the_next_task_after_a_snooze():
    """B16-5: a snoozed task is left out, and the walk sends the task behind it."""
    first = overdue_task("t1", days=2)
    second = overdue_task("t2", days=1)
    hass, coord = _setup({"t1": first, "t2": second}, _options(status="due_soon"))

    _tap(hass, _action("snooze", first))

    assert coord.store.calls == [("snooze", "t1")]
    payload = _last_payload(hass)
    actions = [a["action"] for a in payload["data"]["actions"]]
    assert actions and all("::t2::" in a for a in actions)


def test_b16_5_the_exclusion_is_for_the_walk_advance_only():
    """B16-5: a plain send still includes every due task."""
    task = overdue_task("t1", days=1)
    hass, coord = _setup({"t1": task}, _options(status="due_soon"))
    notification = coord.entry.options["notifications"][0]

    matched, sent = asyncio.run(
        notifier.async_send_for_notification(hass, coord, notification)
    )

    assert (matched, sent) == (1, "t1")


# ── B16-1: an automatic trigger sends only for a task in the profile ────────────────


class _AreaRegistry:
    def async_get_area(self, area_id):
        return None


def _auto_options() -> dict[str, Any]:
    kitchen = profiles.normalize_profile(
        {"id": "pk", "name": "Kitchen", "filter": {"areas": ["kitchen"]}}
    )
    garage = profiles.normalize_profile(
        {"id": "pg", "name": "Garage", "filter": {"areas": ["garage"]}}
    )
    notifs = [
        notifications.normalize_notification(
            {
                "id": nid,
                "name": nid,
                "profile_id": pid,
                "targets": [target],
                "style": "walk",
                "auto": {"overdue": True},
            }
        )
        for nid, pid, target in (
            ("mom", "pk", "mobile_app_mom"),
            ("dad", "pg", "mobile_app_dad"),
        )
    ]
    return {"profiles": [kitchen, garage], "notifications": notifs}


def _auto_tasks() -> dict[str, dict[str, Any]]:
    return {
        "fridge": {**overdue_task("fridge", days=7), "area_id": "kitchen"},
        "oil": {**overdue_task("oil", days=0), "area_id": "garage"},
    }


def _send_auto(monkeypatch, crossed) -> list[str]:
    monkeypatch.setattr(
        notifier, "ar", types.SimpleNamespace(async_get=lambda hass: _AreaRegistry())
    )
    hass = FakeHass()
    coord = _Coord(_auto_tasks(), _auto_options())
    asyncio.run(notifier.async_send_auto(hass, coord, crossed))
    return [service for _, service, _ in hass.services.calls]


def test_b16_1_a_crossing_outside_the_profile_does_not_send(monkeypatch):
    """B16-1: a garage task going overdue sends the garage notification only.

    Before the fix the kitchen notification sent again too, and re-alerted with its
    week-old head task.
    """
    assert _send_auto(monkeypatch, [("overdue", "oil")]) == ["mobile_app_dad"]


def test_b16_1_each_notification_sends_once_for_its_own_crossing(monkeypatch):
    """B16-1: crossings in both profiles send both notifications, once each."""
    sent = _send_auto(monkeypatch, [("overdue", "oil"), ("overdue", "fridge")])
    assert sorted(sent) == ["mobile_app_dad", "mobile_app_mom"]


def test_b16_1_a_kind_the_notification_does_not_listen_for_does_not_send(monkeypatch):
    """B16-1: a due-soon crossing does not send a notification for overdue only."""
    assert _send_auto(monkeypatch, [("due_soon", "oil")]) == []


def test_b16_1_a_crossed_task_that_no_longer_exists_does_not_send(monkeypatch):
    """B16-1: a crossing for a task removed since is not a match."""
    assert _send_auto(monkeypatch, [("overdue", "gone")]) == []
