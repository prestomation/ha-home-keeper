"""Task life cycle as a state machine: add, complete, undo, skip, move and edit.

Each rule is one user action on a fixed task. After every step, the invariants say that
the task shows a time the user can explain: a date of the schedule (a move counts), or a
snooze or due-today target. An undo straight after a completion gives back the exact
state from before it, including the moved dates that the completion pruned (goal G4,
"defer without loss").

Run just these: `pytest tests/unit -m property`.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import hk_models as models
import hk_recurrence as r
import pytest
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

_ZONES = ("America/New_York", "Europe/London", "Australia/Lord_Howe", "UTC")
_RULES = ("FREQ=DAILY", "FREQ=WEEKLY;BYDAY=MO,TH", "FREQ=DAILY;INTERVAL=3")
_START = datetime(2026, 1, 1, 12, tzinfo=ZoneInfo("UTC"))


class TaskLifeCycle(RuleBasedStateMachine):
    """One fixed task, driven by the same pure functions that the store calls."""

    @initialize(
        zone=st.sampled_from(_ZONES),
        rrule=st.sampled_from(_RULES),
        hour=st.integers(0, 23),
        minute=st.sampled_from((0, 30)),
    )
    def add(self, zone, rrule, hour, minute):
        self.tz = ZoneInfo(zone)
        self.now = _START.astimezone(self.tz)
        anchor = datetime(2025, 10, 31, hour, minute, tzinfo=self.tz)
        self.task = models.build_task(
            {
                "name": "x",
                "recurrence_type": "fixed",
                "rrule": rrule,
                "anchor": anchor.isoformat(),
            },
            now=self.now,
        )
        # Instants that a snooze or a due-today put off the grid on purpose.
        self.deferred: set[str] = set()
        # State from before the last action, when that action was a completion.
        self.before_completion: dict | None = None

    def _tick(self, minutes: int) -> None:
        self.now = self.now + timedelta(minutes=minutes)

    def _shown(self) -> datetime:
        return datetime.fromisoformat(self.task["next_due"]).astimezone(self.tz)

    @rule(minutes=st.integers(1, 60 * 24 * 6))
    def tick(self, minutes):
        self._tick(minutes)
        self.before_completion = None

    @rule(minutes=st.integers(1, 60 * 24 * 6))
    def complete(self, minutes):
        self._tick(minutes)
        self.before_completion = {
            "next_due": self.task["next_due"],
            "moves": [dict(m) for m in self.task.get("moved_occurrences") or []],
            "last_completed": self.task.get("last_completed"),
            "count": len(self.task["completions"]),
        }
        r.apply_completion(self.task, self.now, now=self.now)
        self.completed_ts = self.task["completions"][-1]["ts"]

    @precondition(lambda self: self.before_completion is not None)
    @rule()
    def undo(self):
        r.remove_completion(self.task, self.completed_ts, now=self.now)
        before = self.before_completion
        assert self.task["next_due"] == before["next_due"]
        # The rows are keyed by their original date, so their order is not part of the
        # state.
        assert sorted(
            self.task.get("moved_occurrences") or [], key=lambda m: m["from"]
        ) == sorted(before["moves"], key=lambda m: m["from"])
        assert self.task.get("last_completed") == before["last_completed"]
        assert len(self.task["completions"]) == before["count"]
        self.before_completion = None

    @rule(minutes=st.integers(1, 60 * 24 * 6))
    def skip(self, minutes):
        self._tick(minutes)
        count = len(self.task["completions"])
        r.skip_occurrence(self.task, now=self.now)
        assert len(self.task["completions"]) == count
        self.before_completion = None

    @rule(minutes=st.integers(1, 60 * 24 * 6), snooze=st.integers(1, 60 * 24 * 3))
    def defer(self, minutes, snooze):
        self._tick(minutes)
        until = r.snooze_from(self.task, self.now) + timedelta(minutes=snooze)
        r.defer(self.task, until, now=self.now)
        self.deferred.add(self.task["next_due"])
        self.before_completion = None

    @rule(shift=st.integers(1, 60 * 24))
    def move(self, shift):
        shown = self._shown()
        target = shown + timedelta(minutes=shift)
        try:
            r.move_occurrence(self.task, shown, target, now=self.now)
        except ValueError:
            pass  # A refused move leaves the task as it was.
        self.before_completion = None

    @rule(rrule=st.sampled_from(_RULES))
    def edit_rule(self, rrule):
        try:
            self.task = models.merge_update(self.task, {"rrule": rrule}, now=self.now)
        except models.TaskValidationError:
            pass
        self.before_completion = None

    @rule(name=st.text(alphabet="abcxyz", min_size=1, max_size=8))
    def edit_name(self, name):
        shown = self.task["next_due"]
        self.task = models.merge_update(self.task, {"name": name}, now=self.now)
        assert self.task["next_due"] == shown
        self.before_completion = None

    @invariant()
    def shown_date_is_explained(self):
        if not hasattr(self, "task"):
            return
        due = self.task["next_due"]
        assert due is not None
        when = self._shown()
        assert when.tzinfo is not None
        if due in self.deferred:
            return
        assert r.is_task_occurrence(self.task, when, tz=self.tz), (
            f"next_due {due} is on no schedule date and has no move"
        )


TaskLifeCycle.TestCase.settings = settings(
    # Fixed in CI. 200 examples missed a removed undo restore of moved dates (#529).
    # `HK_STATEFUL_EXAMPLES` lets a developer search longer by hand.
    max_examples=int(os.environ.get("HK_STATEFUL_EXAMPLES", "600")),
    stateful_step_count=12,
    deadline=None,
    derandomize=True,
    database=None,
)
TestTaskLifeCycle = TaskLifeCycle.TestCase
