"""A change made on the to-do list side reaches Home Keeper once, and the syncs settle.

``test_sync_fixed_point_properties.py`` checks that a planner settles on what it wrote
itself. This file checks the other direction: after the sync has settled, the household
ticks a line off, deletes it, renames it, gives it a new date or adds a line of their
own. The planner then runs in a closed loop with the fake list and the tasks, as the
drivers run it: list ops go to the list, completions and moves go to the tasks, and the
next pass plans from the result. The loop must end, and the change must have the effect
that the guide promises, 1 time.

Run just these: `pytest tests/unit -m property`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import hk_assets as assets_model
import hk_models as models
import hk_profiles as profiles
import hk_recurrence as recurrence
import hk_shopping as sh
import hk_todo_list as tm
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from test_sync_fixed_point_properties import FakeList, _apply, _ops

pytestmark = pytest.mark.property

LIST = "todo.family"
NOW = datetime(2026, 6, 15, 9, 0, tzinfo=timezone(timedelta(hours=-4)))
# More passes than a settling sync needs. A loop that uses them all does not settle.
# A pass with no list call can still change the bookkeeping (an add seen back), so
# the loop ends at the first pass that changes neither.
MAX_PASSES = 6

EDITS = ("tick", "delete", "rename", "move", "foreign")


def _plain_list(*, uids: bool) -> FakeList:
    return FakeList(title=str, note=str, due=lambda day: day, uids=uids)


def _open_line(fake: FakeList, text: str) -> dict[str, Any] | None:
    lines = [
        item
        for item in fake.items
        if item["summary"] == text and item["status"] == tm.STATUS_NEEDS_ACTION
    ]
    return lines[0] if lines else None


def _edit(fake: FakeList, line: dict[str, Any], edit: str, day: str) -> None:
    """Make one change on the list, as a person does in the to-do app."""
    if edit == "tick":
        line["status"] = tm.STATUS_COMPLETED
    elif edit == "delete":
        fake.items.remove(line)
    elif edit == "rename":
        line["summary"] = "Our own words"
    elif edit == "move":
        line["due"] = day
    else:
        fake.add("Milk", None, None)


# ── to-do list sync ───────────────────────────────────────────────────────────


def _todo_loop(fake, tasks, synced, caps, tracked, at):
    """Run passes to a fixed point. Returns ``(tracked, completed, moved)``."""
    completed: list[str] = []
    moved: list[tuple[str, str]] = []
    for _ in range(MAX_PASSES):
        desired = tm.desired_by_sync(synced, list(tasks.values()), now=at)
        plan = tm.plan_sync(
            synced=synced,
            tracked=tracked,
            desired=desired,
            items_by_entity={LIST: fake.snapshot()},
            capabilities={LIST: caps},
            now=at,
        )
        if not _ops(plan) and plan.tracked == tracked:
            return tracked, completed, moved
        _apply(fake, plan)
        for op in plan.complete:
            recurrence.apply_completion(tasks[op.task_id], at, now=at)
            completed.append(op.task_id)
        for op in plan.reschedule:
            task = tasks[op.task_id]
            until = tm.reschedule_until(str(task["next_due"]), op.due, now=at)
            recurrence.defer(task, until, now=at)
            moved.append((op.task_id, op.due))
        tracked = plan.tracked
    raise AssertionError(f"the to-do list sync did not settle: {fake.items!r}")


@settings(max_examples=150, deadline=None)
@given(
    count=st.integers(1, 3),
    pick=st.integers(0, 2),
    edit=st.sampled_from(EDITS),
    two_way=st.booleans(),
    vanish=st.booleans(),
    uids=st.booleans(),
    caps=st.sets(st.sampled_from([tm.CAP_DUE_DATE, tm.CAP_DESCRIPTION])).map(frozenset),
    minutes=st.sampled_from([0, 30]),
)
def test_a_change_on_the_todo_side_acts_once_and_settles(
    count, pick, edit, two_way, vanish, uids, caps, minutes
):
    """Kills: the ``complete`` call for a two-way tick and for a vanished line in
    ``todo_list.plan_sync``, and the ``settled`` set that stops a second copy."""
    names = ["Water plants", "Clean filter", "Check smoke alarm"][:count]
    tasks = {
        task["id"]: task
        for task in (
            models.build_task({"name": name, "interval": 3, "unit": "days"}, now=NOW)
            for name in names
        )
    }
    synced = [
        profiles.normalize_profile(
            {
                "id": "chores",
                "name": "Chores",
                "filter": {"status": "all"},
                "sync": {
                    "entity_id": LIST,
                    "two_way": two_way,
                    "vanish_as_completed": vanish,
                },
            }
        )
    ]
    fake = _plain_list(uids=uids)
    tracked, completed, _ = _todo_loop(fake, tasks, synced, caps, {}, NOW)
    assert completed == []
    assert len(fake.items) == count

    task = list(tasks.values())[pick % count]
    line = _open_line(fake, task["name"])
    assert line is not None
    day = (NOW + timedelta(days=5)).date().isoformat()
    _edit(fake, line, edit, day)

    later = NOW + timedelta(minutes=minutes)
    tracked, completed, moved = _todo_loop(fake, tasks, synced, caps, tracked, later)

    # A tick on a two-way sync completes the task. A line that goes away completes
    # it only where the list drops ticked lines, and only with a uid to prove it.
    ticked = edit == "tick" and two_way
    vanished = edit == "delete" and two_way and vanish and uids
    assert completed == ([task["id"]] if ticked or vanished else [])
    if edit == "move" and two_way and uids and tm.CAP_DUE_DATE in caps:
        assert moved == [(task["id"], day)]
        assert task["next_due"][:10] == day
        assert _open_line(fake, task["name"])["due"] == day
    else:
        assert moved == []
    if edit == "rename" and uids:
        # The household's name wins on the line, and the task keeps its own.
        assert line in fake.items
        assert line["summary"] == "Our own words"
        assert task["name"] in names
    if edit == "foreign":
        assert _open_line(fake, "Milk") is not None
    # No task gets a second open line.
    for other in tasks.values():
        open_lines = [
            item
            for item in fake.items
            if item["summary"] == other["name"]
            and item["status"] == tm.STATUS_NEEDS_ACTION
        ]
        assert len(open_lines) <= 1


# ── shopping-list sync ────────────────────────────────────────────────────────


def _shopping_loop(fake, tasks, assets, caps, tracked, at):
    """Run passes to a fixed point. Returns ``(tracked, completed)``."""
    completed: list[str] = []
    for _ in range(MAX_PASSES):
        desired = sh.buy_tasks_by_part(tasks, assets)
        plan = sh.plan_sync(
            tracked=tracked,
            desired=desired,
            items_by_entity={LIST: fake.snapshot()},
            target=LIST,
            now=at,
            capabilities={LIST: caps},
        )
        if not _ops(plan) and plan.tracked == tracked:
            return tracked, completed
        _apply(fake, plan)
        for op in plan.complete:
            recurrence.apply_completion(tasks[op.task_id], at, now=at)
            completed.append(op.task_id)
        tracked = plan.tracked
    raise AssertionError(f"the shopping-list sync did not settle: {fake.items!r}")


@settings(max_examples=150, deadline=None)
@given(
    count=st.integers(1, 3),
    pick=st.integers(0, 2),
    edit=st.sampled_from(EDITS),
    uids=st.booleans(),
    caps=st.sets(st.sampled_from([tm.CAP_DUE_DATE, tm.CAP_DESCRIPTION])).map(frozenset),
    minutes=st.sampled_from([0, 30]),
)
def test_a_change_on_the_shopping_list_acts_once_and_settles(
    count, pick, edit, uids, caps, minutes
):
    """Kills: the kept entry of a deleted line in ``shopping.plan_sync`` (the line
    came back), and the ``CompleteOp`` of a tick."""
    names = ["Softener", "Filter", "Batteries"][:count]
    parts = [
        {
            "name": name,
            "type": "consumable",
            "stock": 0,
            "reorder_at": 1,
            "create_buy_task": True,
        }
        for name in names
    ]
    asset = assets_model.build_asset({"name": "House", "parts": parts}, now=NOW)
    assets = {asset["id"]: asset}
    tasks = {}
    for part in asset["parts"]:
        source = {"buy": {"asset_id": asset["id"], "part_id": part["id"]}}
        task = models.build_task(
            {
                "name": f"Buy {part['name']}",
                "recurrence_type": "one-off",
                "source": source,
            },
            now=NOW,
        )
        tasks[task["id"]] = task
    fake = _plain_list(uids=uids)
    tracked, completed = _shopping_loop(fake, tasks, assets, caps, {}, NOW)
    assert completed == []
    assert len(fake.items) == count

    task = list(tasks.values())[pick % count]
    line = _open_line(fake, task["name"])
    assert line is not None
    _edit(fake, line, edit, (NOW + timedelta(days=5)).date().isoformat())

    later = NOW + timedelta(minutes=minutes)
    tracked, completed = _shopping_loop(fake, tasks, assets, caps, tracked, later)

    # A tick says "bought": the reminder completes 1 time. A deleted line says
    # "not this one", so it stays off the list and completes nothing.
    assert completed == ([task["id"]] if edit == "tick" else [])
    if edit == "delete":
        assert _open_line(fake, task["name"]) is None
    if edit == "rename" and uids:
        assert line in fake.items
        assert line["summary"] == "Our own words"
    if edit == "foreign":
        assert _open_line(fake, "Milk") is not None
    for other in tasks.values():
        open_lines = [
            item
            for item in fake.items
            if item["summary"] == other["name"]
            and item["status"] == tm.STATUS_NEEDS_ACTION
        ]
        assert len(open_lines) <= 1
