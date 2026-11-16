"""Task life cycle of every recurrence type as a state machine.

Each rule is 1 action that the store accepts: tick, Done, skip, snooze, due today,
trigger, undo of the latest Done, delete of any completion or skip, and a move of any
completion. The preconditions copy the gates of the store. After each step the
invariants say:

1. ``last_completed`` is the latest completion ``ts``, or None.
2. A one-off is due only when its completion log and its skip log are both empty.
3. An undo straight after Done gives back the ``next_due`` from before Done (goal G4).
4. Every stored date is aware.

The plain tests at the end keep each sequence that the machine found as 1 step test.

Run just these: `pytest tests/unit -m property`.
"""

from __future__ import annotations

import os
from datetime import datetime, time, timedelta
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
_START = datetime(2026, 3, 1, 12, tzinfo=ZoneInfo("UTC"))
_TYPES = ("floating", "fixed", "one-off", "triggered", "sensor")
_MINUTES = st.integers(1, 60 * 24 * 4)


def _payload(rec_type: str, now: datetime) -> dict:
    """The add_task data for 1 task of *rec_type*."""
    if rec_type == "floating":
        return {"name": "x", "interval": 3, "unit": "days"}
    if rec_type == "fixed":
        anchor = (now - timedelta(days=10)).replace(hour=9, minute=0)
        return {
            "name": "x",
            "recurrence_type": "fixed",
            "rrule": "FREQ=WEEKLY",
            "anchor": anchor.isoformat(),
        }
    if rec_type == "one-off":
        return {
            "name": "x",
            "recurrence_type": "one-off",
            "due": (now + timedelta(days=2)).isoformat(),
        }
    if rec_type == "sensor":
        return {
            "name": "x",
            "recurrence_type": "sensor",
            "sensor": {"entity_id": "sensor.probe", "mode": "usage", "target": 100},
        }
    return {"name": "x", "recurrence_type": rec_type}


def _aware(value: object) -> bool:
    return value is None or datetime.fromisoformat(str(value)).tzinfo is not None


class TaskLifeCycleAllTypes(RuleBasedStateMachine):
    """1 task of any type, driven by the pure functions that the store calls."""

    @initialize(
        rec_type=st.sampled_from(_TYPES),
        zone=st.sampled_from(_ZONES),
        set_time=st.booleans(),
    )
    def add(self, rec_type, zone, set_time):
        self.tz = ZoneInfo(zone)
        self.now = _START.astimezone(self.tz)
        self.due_time = time(9, 0) if set_time else None
        self.task = models.build_task(
            _payload(rec_type, self.now), now=self.now, due_time=self.due_time
        )
        # The state before the last action, when that action was Done.
        self.before_done: dict | None = None

    @property
    def armed(self) -> bool:
        return self.task.get("next_due") is not None

    def _act(self, minutes: int) -> None:
        self.now = self.now + timedelta(minutes=minutes)
        self.before_done = None

    @rule(minutes=_MINUTES)
    def tick(self, minutes):
        self._act(minutes)

    @rule(minutes=_MINUTES)
    def complete(self, minutes):
        self._act(minutes)
        before = {
            "next_due": self.task.get("next_due"),
            "last_completed": self.task.get("last_completed"),
            "count": len(self.task["completions"]),
        }
        r.apply_completion(self.task, self.now, now=self.now, due_time=self.due_time)
        self.done_ts = self.task["completions"][-1]["ts"]
        self.before_done = before

    @rule(minutes=_MINUTES)
    def skip(self, minutes):
        self._act(minutes)
        r.skip_occurrence(self.task, now=self.now, due_time=self.due_time)

    @precondition(lambda self: self.armed)
    @rule(minutes=_MINUTES, length=st.integers(1, 60 * 24 * 5))
    def snooze(self, minutes, length):
        self._act(minutes)
        until = r.snooze_from(self.task, self.now) + timedelta(minutes=length)
        if self.task["recurrence_type"] == "floating":
            until = r.snap_to_due_time(until, self.due_time, round_up=True)
        r.defer(self.task, until, now=self.now)

    @precondition(lambda self: self.armed)
    @rule(minutes=_MINUTES)
    def due_today(self, minutes):
        self._act(minutes)
        r.defer(self.task, self.now, now=self.now)

    @precondition(lambda self: self.task["recurrence_type"] in ("triggered", "sensor"))
    @rule(minutes=_MINUTES)
    def trigger(self, minutes):
        self._act(minutes)
        # store.trigger_task: arm the task at now.
        self.task["next_due"] = self.now.isoformat()

    @precondition(lambda self: self.before_done is not None)
    @rule()
    def undo(self):
        before = self.before_done
        r.remove_completion(
            self.task, self.done_ts, now=self.now, due_time=self.due_time
        )
        assert self.task.get("next_due") == before["next_due"]
        assert self.task.get("last_completed") == before["last_completed"]
        assert len(self.task["completions"]) == before["count"]
        self.before_done = None

    @precondition(lambda self: self.task["completions"])
    @rule(data=st.data())
    def delete_completion(self, data):
        entry = data.draw(st.sampled_from(self.task["completions"]))
        self._act(1)
        r.remove_completion(
            self.task, entry["ts"], now=self.now, due_time=self.due_time
        )

    @precondition(lambda self: self.task.get("skips"))
    @rule(data=st.data())
    def delete_skip(self, data):
        entry = data.draw(st.sampled_from(self.task["skips"]))
        self._act(1)
        r.remove_skip(self.task, entry["ts"])

    @precondition(lambda self: self.task["completions"])
    @rule(data=st.data(), back=st.integers(1, 60 * 24 * 20))
    def move_completion(self, data, back):
        entry = data.draw(st.sampled_from(self.task["completions"]))
        self._act(1)
        new_ts = datetime.fromisoformat(entry["ts"]) - timedelta(minutes=back)
        r.move_completion(
            self.task,
            entry["ts"],
            new_ts.isoformat(),
            now=self.now,
            due_time=self.due_time,
        )

    @invariant()
    def last_completed_is_the_latest_completion(self):
        if not hasattr(self, "task"):
            return
        stamps = [datetime.fromisoformat(e["ts"]) for e in self.task["completions"]]
        latest = self.task.get("last_completed")
        if not stamps:
            assert latest is None
        else:
            assert datetime.fromisoformat(latest) == max(stamps)

    @invariant()
    def one_off_is_due_only_with_empty_logs(self):
        if not hasattr(self, "task") or self.task["recurrence_type"] != "one-off":
            return
        if self.armed:
            assert not self.task["completions"]
            assert not self.task.get("skips")

    @invariant()
    def every_date_is_aware(self):
        if not hasattr(self, "task"):
            return
        assert _aware(self.task.get("next_due"))
        assert _aware(self.task.get("last_completed"))
        for entry in self.task["completions"] + list(self.task.get("skips") or []):
            assert _aware(entry["ts"])
            assert _aware(entry.get(r.PRIOR_DUE))


TaskLifeCycleAllTypes.TestCase.settings = settings(
    # Fixed in CI. `HK_STATEFUL_EXAMPLES` lets a developer search longer by hand.
    max_examples=int(os.environ.get("HK_STATEFUL_EXAMPLES", "600")),
    stateful_step_count=15,
    deadline=None,
    derandomize=True,
    database=None,
)
TestTaskLifeCycleAllTypes = pytest.mark.xfail(strict=True)(
    TaskLifeCycleAllTypes.TestCase
)


# ── Sequences that the machine found ─────────────────────────────────────────

_NOW = datetime(2026, 3, 1, 12, tzinfo=ZoneInfo("UTC"))


def _one_off() -> dict:
    return models.build_task(_payload("one-off", _NOW), now=_NOW)


@pytest.mark.xfail(strict=True, reason="F1: undo of Done ignores an earlier skip")
def test_one_off_skip_done_undo_stays_dormant():
    task = _one_off()
    r.skip_occurrence(task, now=_NOW)
    later = _NOW + timedelta(hours=1)
    r.apply_completion(task, later, now=later)
    r.remove_completion(task, later.isoformat(), now=later)
    assert task["next_due"] is None
    assert len(task["skips"]) == 1


@pytest.mark.xfail(strict=True, reason="F2: undo of Done loses the snooze date")
def test_one_off_snooze_done_undo_gives_back_the_snooze_date():
    task = _one_off()
    snoozed = _NOW + timedelta(days=5)
    r.defer(task, snoozed, now=_NOW)
    later = _NOW + timedelta(hours=1)
    r.apply_completion(task, later, now=later)
    r.remove_completion(task, later.isoformat(), now=later)
    assert task["next_due"] == snoozed.isoformat()
