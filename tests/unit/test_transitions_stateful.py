"""Due-soon, overdue and resolved announcements as a state machine.

The machine adds tasks of 3 types and then does what a household does: time passes,
Done, undo of Done, snooze, a new trigger, disable, enable, delete and a restart. After
each action it runs 1 coordinator pass: ``detect_transitions`` and ``auto_crossings``
on the edge state of the pass before. A restart drops the edge state and takes a
silent baseline, as the coordinator does at startup.

The oracle is short and does not read the code under test:

1. Per task, ``overdue`` and ``overdue_resolved`` alternate, and ``overdue_resolved``
   comes only after an open ``overdue``.
2. A task announces ``due_soon`` 1 time for a date. A return to the date by an undo
   does not announce it again.
3. A task sends 1 automatic notification of a kind for a date between 2 restarts.

The plain tests at the end keep each sequence that the machine found as 1 step test.

Run just these: `pytest tests/unit -m property`.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import hk_lifecycle as lifecycle
import hk_models as models
import hk_recurrence as r
import hk_transitions as t
import pytest
from hk_const import (
    EVENT_TASK_DUE_SOON,
    EVENT_TASK_OVERDUE,
    EVENT_TASK_OVERDUE_RESOLVED,
)
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
)

pytestmark = pytest.mark.property

_TZ = ZoneInfo("Europe/London")
_START = datetime(2026, 3, 1, 12, tzinfo=_TZ)
_TYPES = ("floating", "fixed", "triggered")
# How many dates a task keeps as announced. A date that is older than this can
# announce again, so the oracle only checks a repeat inside this window.
_MEMORY = t.ANNOUNCED_MEMORY


def _payload(rec_type: str, now: datetime) -> dict:
    if rec_type == "floating":
        return {"name": "x", "interval": 2, "unit": "days"}
    if rec_type == "fixed":
        anchor = (now - timedelta(days=3)).replace(hour=9, minute=0)
        return {
            "name": "x",
            "recurrence_type": "fixed",
            "rrule": "FREQ=DAILY;INTERVAL=4",
            "anchor": anchor.isoformat(),
        }
    return {"name": "x", "recurrence_type": "triggered"}


def _due(payload: dict) -> str | None:
    return payload.get("next_due")


class Announcements(RuleBasedStateMachine):
    """Up to 3 tasks and the coordinator's edge state between passes."""

    @initialize(rec_type=st.sampled_from(_TYPES))
    def start(self, rec_type):
        self.now = _START
        self.added = 0
        self.tasks: dict[str, dict] = {}
        self.state: t.StateMap = {}
        self.done: dict[str, str] = {}
        # Oracle state.
        self.open: dict[str, bool] = {}
        self.seen: dict[str, list[tuple[str, str]]] = {}
        self.pushed: dict[str, list[tuple[str, str]]] = {}
        self._add(rec_type)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _add(self, rec_type: str) -> None:
        task = models.build_task(_payload(rec_type, self.now), now=self.now)
        # A fixed id, so that each run draws from the same list.
        self.added = getattr(self, "added", 0) + 1
        task["id"] = f"t{self.added}"
        self.tasks[task["id"]] = task
        self._pass()

    def _act(self, minutes: int = 1) -> None:
        self.now += timedelta(minutes=minutes)
        self.done = {}

    @staticmethod
    def _remember(log: list[tuple[str, str]], pair: tuple[str, str]) -> None:
        if pair in log:
            log.remove(pair)
        log.append(pair)

    def _pass(self) -> None:
        fired, state = t.detect_transitions(self.state, self.tasks, now=self.now)
        crossed = t.auto_crossings(self.state, fired)
        self.state = state
        for name, payload in fired:
            tid = payload["task_id"]
            seen = self.seen.setdefault(tid, [])
            if name == EVENT_TASK_OVERDUE:
                assert not self.open.get(tid), "a second overdue with none resolved"
                self.open[tid] = True
                self._remember(seen, ("overdue", _due(payload)))
            elif name == EVENT_TASK_OVERDUE_RESOLVED:
                assert self.open.get(tid), "resolved with no open overdue"
                self.open[tid] = False
            elif name == EVENT_TASK_DUE_SOON:
                pair = ("due_soon", _due(payload))
                assert pair not in seen[-_MEMORY:], "due soon again for 1 date"
                self._remember(seen, pair)
        for kind, tid in crossed:
            pair = (kind, self.tasks[tid]["next_due"])
            pushed = self.pushed.setdefault(tid, [])
            assert pair not in pushed[-_MEMORY:], f"a second push: {pair}"
            self._remember(pushed, pair)

    def _ids(self, data, check=lambda task: True) -> str:
        ids = sorted(tid for tid, task in self.tasks.items() if check(task))
        return data.draw(st.sampled_from(ids))

    def _any(self, check) -> bool:
        return any(check(task) for task in self.tasks.values())

    # ── Rules ────────────────────────────────────────────────────────────────

    @precondition(lambda self: len(self.tasks) < 3)
    @rule(rec_type=st.sampled_from(_TYPES))
    def add(self, rec_type):
        self._act()
        self._add(rec_type)

    @rule(minutes=st.integers(1, 60 * 24 * 3))
    def tick(self, minutes):
        self._act(minutes)
        self._pass()

    @precondition(lambda self: self.tasks)
    @rule(data=st.data())
    def complete(self, data):
        tid = self._ids(data)
        self._act()
        r.apply_completion(self.tasks[tid], self.now, now=self.now)
        self._pass()
        self.done = {tid: self.tasks[tid]["completions"][-1]["ts"]}

    @precondition(lambda self: self.done)
    @rule()
    def undo(self):
        [(tid, ts)] = self.done.items()
        r.remove_completion(self.tasks[tid], ts, now=self.now)
        self.done = {}
        self._pass()

    @precondition(lambda self: self._any(lambda task: task["next_due"]))
    @rule(data=st.data(), hours=st.integers(1, 24 * 4))
    def snooze(self, data, hours):
        tid = self._ids(data, lambda task: task["next_due"])
        self._act()
        task = self.tasks[tid]
        until = r.snooze_from(task, self.now) + timedelta(hours=hours)
        r.defer(task, until, now=self.now)
        self._pass()

    @precondition(lambda self: self._any(lambda x: x["recurrence_type"] == "triggered"))
    @rule(data=st.data())
    def trigger(self, data):
        tid = self._ids(data, lambda task: task["recurrence_type"] == "triggered")
        self._act()
        lifecycle.arm(self.tasks[tid], now=self.now)
        self._pass()

    @precondition(lambda self: self.tasks)
    @rule(data=st.data(), enabled=st.booleans())
    def set_enabled(self, data, enabled):
        tid = self._ids(data)
        self._act()
        self.tasks[tid]["enabled"] = enabled
        self._pass()

    @precondition(lambda self: len(self.tasks) > 1)
    @rule(data=st.data())
    def delete(self, data):
        tid = self._ids(data)
        self._act()
        del self.tasks[tid]
        self.open.pop(tid, None)
        self._pass()

    @rule()
    def restart(self):
        """Home Assistant starts again with no edge state and a silent baseline."""
        self._act()
        fired, self.state = t.detect_transitions({}, self.tasks, now=self.now)
        self.open = {
            tid: r.is_overdue(task, now=self.now) and task.get("enabled", True)
            for tid, task in self.tasks.items()
        }
        # The announced dates are kept in memory only, so a restart forgets them.
        self.seen = {}
        self.pushed = {}
        for _name, payload in fired:
            pair = (
                "overdue" if _name == EVENT_TASK_OVERDUE else "due_soon",
                _due(payload),
            )
            self._remember(self.seen.setdefault(payload["task_id"], []), pair)

    @invariant()
    def every_task_has_edge_state(self):
        if hasattr(self, "tasks"):
            assert set(self.state) == set(self.tasks)


Announcements.TestCase.settings = settings(
    # Fixed in CI. `HK_STATEFUL_EXAMPLES` lets a developer search longer by hand.
    max_examples=int(os.environ.get("HK_STATEFUL_EXAMPLES", "600")),
    stateful_step_count=15,
    deadline=None,
    # `HK_STATEFUL_SEARCH=1` draws new sequences on each run for a long search.
    derandomize=not os.environ.get("HK_STATEFUL_SEARCH"),
    database=None,
)
TestAnnouncements = Announcements.TestCase


# ── Sequences that the machine found ─────────────────────────────────────────

_NOW = datetime(2026, 3, 1, 12, tzinfo=_TZ)


def _fixed(next_due: datetime) -> dict:
    task = models.build_task(
        {
            "name": "x",
            "recurrence_type": "fixed",
            "rrule": "FREQ=WEEKLY",
            "anchor": (next_due - timedelta(weeks=4)).isoformat(),
        },
        now=_NOW,
    )
    # Done on the due date moves the schedule past it, as the store does.
    task["next_due"] = next_due.isoformat()
    return task


def _done_then_undo(task: dict) -> list[tuple[list, list]]:
    """1 pass, Done and 1 pass, undo and 1 pass. Return the events and pushes."""
    tasks = {task["id"]: task}
    passes = []
    state: t.StateMap = {}
    for step in ("start", "done", "undo"):
        if step == "done":
            r.apply_completion(task, _NOW, now=_NOW)
        elif step == "undo":
            r.remove_completion(task, _NOW.isoformat(), now=_NOW)
        fired, next_state = t.detect_transitions(state, tasks, now=_NOW)
        passes.append(([name for name, _ in fired], t.auto_crossings(state, fired)))
        state = next_state
    return passes


def test_done_then_undo_does_not_announce_due_soon_again():
    task = _fixed(_NOW + timedelta(days=1))
    start, _done, undo = _done_then_undo(task)
    assert start == ([EVENT_TASK_DUE_SOON], [("due_soon", task["id"])])
    assert undo == ([], [])


def test_done_then_undo_does_not_push_overdue_again():
    task = _fixed(_NOW - timedelta(days=1))
    start, done, undo = _done_then_undo(task)
    assert start == ([EVENT_TASK_OVERDUE], [("overdue", task["id"])])
    assert done[0] == [EVENT_TASK_OVERDUE_RESOLVED]
    # The bus gets the overdue again, so an automation that tracks the open overdue
    # stays right. The push is not sent again.
    assert undo == ([EVENT_TASK_OVERDUE], [])
