"""Every sync planner and reconciler reaches a fixed point.

A planner that writes something and then reads it back must find nothing more to do.
When it does find more, each pass writes again, and each write is a service call, a
save, an event or a logbook row: a flood that nobody asked for.

Each property here runs a planner, applies its plan to a fake target, and runs the
planner again. The second pass must plan nothing. For the 2 to-do list syncs the
fake list changes what it stores, as real lists do: another case, trimmed or
collapsed white space, a due date as a datetime in UTC. The planners must read that
as the text and the date they wrote (R5, R6, R7 in the noise audit).

Run just these: `pytest tests/unit -m property`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta, timezone
from itertools import count
from typing import Any

import hk_assets as assets_model
import hk_card_resource as cr
import hk_declarative_companions as dc
import hk_models as models
import hk_problem_tasks as pt
import hk_profiles as profiles
import hk_reconcile as rc
import hk_recurrence as recurrence
import hk_shopping as sh
import hk_todo_list as tm
import property_strategies as ps
import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

pytestmark = pytest.mark.property

LIST = "todo.family"
ENTRY = "cfg_entry_1"
DAY = datetime(2026, 6, 15, 9, 0)

# Offsets that put local midnight on another UTC date (east), on the same date
# (west), on a half hour, and on UTC itself.
_OFFSETS = (-10, -4, 0, 2, 5.5, 13)


def _now(offset: float) -> datetime:
    return DAY.replace(tzinfo=timezone(timedelta(hours=offset)))


# ── what a list does to what it stores ────────────────────────────────────────

_TITLE_FORMS = {
    "as_is": lambda s: s,
    "lower": str.lower,
    "upper": str.upper,
    "trimmed": str.strip,
    "collapsed": lambda s: " ".join(s.split()),
}
_NOTE_FORMS = {
    "as_is": lambda s: s,
    "trimmed": str.strip,
    "collapsed": lambda s: " ".join(s.split()),
}


def _due_forms(now: datetime) -> dict[str, Any]:
    zone = now.tzinfo

    def local_midnight(day: str, tz: Any) -> str:
        start = datetime.combine(datetime.fromisoformat(day).date(), time(0), zone)
        return start.astimezone(tz).isoformat()

    return {
        "date": lambda day: day,
        # A list that stores a date as midnight in UTC.
        "utc_midnight": lambda day: f"{day}T00:00:00+00:00",
        # A list that stores local midnight and gives it back in UTC (R7).
        "local_midnight_in_utc": lambda day: local_midnight(day, UTC),
        # A list that stores local midnight with the local offset.
        "local_midnight": lambda day: local_midnight(day, zone),
    }


@dataclass
class FakeList:
    """A to-do list that stores what it is sent in its own form."""

    title: Any
    note: Any
    due: Any
    uids: bool
    items: list[dict[str, Any]] = field(default_factory=list)
    _ids: Any = field(default_factory=lambda: count(1))

    def _find(self, identity: str) -> dict[str, Any]:
        found = [
            item
            for item in self.items
            if (item.get("uid") or item.get("summary")) == identity
        ]
        assert found, f"no item {identity!r} on {self.items!r}"
        return found[0]

    def add(self, summary: str, due: str | None, description: str | None) -> None:
        item: dict[str, Any] = {
            "uid": f"u{next(self._ids)}" if self.uids else None,
            "summary": self.title(summary),
            "status": tm.STATUS_NEEDS_ACTION,
        }
        if due is not None:
            item["due"] = self.due(due)
        if description is not None:
            item["description"] = self.note(description)
        self.items.append(item)

    def update(self, op: Any) -> None:
        item = self._find(op.item)
        if op.status is not None:
            item["status"] = op.status
        if op.rename is not None:
            item["summary"] = self.title(op.rename)
        if getattr(op, "due", None) is not None:
            item["due"] = self.due(op.due)
        if op.description is not None:
            item["description"] = self.note(op.description)

    def remove(self, identity: str) -> None:
        self.items.remove(self._find(identity))

    def snapshot(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.items]


def _apply(fake: FakeList, plan: Any) -> None:
    for op in plan.remove:
        fake.remove(op.item)
    for op in plan.update:
        fake.update(op)
    for op in plan.add:
        fake.add(op.summary, getattr(op, "due", None), op.description)


def _ops(plan: Any) -> list[Any]:
    ops = [*plan.add, *plan.update, *plan.remove, *plan.complete]
    return [*ops, *getattr(plan, "reschedule", [])]


def _key(text: str) -> str:
    """Text as ``todo_items.same_text`` compares it."""
    return "".join(text.split()).casefold()


# Short words from a small alphabet, so case and white space collide often.
_words = st.text(alphabet="aAbB c", min_size=1, max_size=8).filter(str.strip)
_notes = st.text(alphabet="xX y", max_size=6)


def _fake_list(form: tuple[str, str, str, bool], now: datetime) -> FakeList:
    title, note, due, uids = form
    return FakeList(
        title=_TITLE_FORMS[title],
        note=_NOTE_FORMS[note],
        due=_due_forms(now)[due],
        uids=uids,
    )


# How one list stores a title, a note and a due date, and if it gives uids.
_forms = st.tuples(
    st.sampled_from(sorted(_TITLE_FORMS)),
    st.sampled_from(sorted(_NOTE_FORMS)),
    st.sampled_from(sorted(_due_forms(_now(0)))),
    st.booleans(),
)
_BOTH = frozenset({tm.CAP_DUE_DATE, tm.CAP_DESCRIPTION})


_CAPS = st.sets(st.sampled_from([tm.CAP_DUE_DATE, tm.CAP_DESCRIPTION])).map(frozenset)


# ── to-do list sync ───────────────────────────────────────────────────────────


@settings(max_examples=150)
# R5: a list that stores the title in lower case, seen after the hold.
@example(
    form=("lower", "as_is", "date", True),
    offset=-4,
    names=["Ab"],
    notes=["", "", ""],
    foreign=[],
    caps=frozenset(),
    minutes=25,
)
# R6: a list that trims the notes.
@example(
    form=("as_is", "trimmed", "date", True),
    offset=-4,
    names=["Ab"],
    notes=["x ", "", ""],
    foreign=[],
    caps=_BOTH,
    minutes=0,
)
# R7: a list east of UTC that gives local midnight in UTC.
@example(
    form=("as_is", "as_is", "local_midnight_in_utc", True),
    offset=2,
    names=["Ab"],
    notes=["", "", ""],
    foreign=[],
    caps=_BOTH,
    minutes=0,
)
# A list west of UTC that stores the date as midnight in UTC.
@example(
    form=("as_is", "as_is", "utc_midnight", True),
    offset=-4,
    names=["Ab"],
    notes=["", "", ""],
    foreign=[],
    caps=_BOTH,
    minutes=0,
)
@given(
    form=_forms,
    offset=st.sampled_from(_OFFSETS),
    names=st.lists(_words, min_size=1, max_size=3, unique_by=_key),
    notes=st.lists(_notes, min_size=3, max_size=3),
    foreign=st.lists(_words, max_size=2),
    caps=_CAPS,
    minutes=st.sampled_from([0, 5, 25, 90]),
)
def test_todo_list_sync_settles_on_a_list_that_normalizes(
    form, offset, names, notes, foreign, caps, minutes
):
    """Kills: the exact summary match in ``todo_items._by_text`` (R5), the exact
    description compare in ``todo_list.plan_sync`` (R6), and the ``[:10]`` due date
    read with no zone in ``todo_list._live_date`` (R7)."""
    now = _now(offset)
    fake = _fake_list(form, now)
    for text in foreign:
        fake.add(text, None, None)
    tasks = [
        models.build_task(
            {"name": name, "interval": 3, "unit": "days", "notes": note}, now=now
        )
        for name, note in zip(names, notes, strict=False)
    ]
    synced = [
        profiles.normalize_profile(
            {"id": "m1", "name": "m1", "filter": {}, "sync": {"entity_id": LIST}}
        )
    ]
    desired = tm.desired_by_sync(synced, tasks, now=now)
    assert len(desired["m1"]) == len(tasks)

    def run(tracked: dict[str, Any], at: datetime) -> Any:
        return tm.plan_sync(
            synced=synced,
            tracked=tracked,
            desired=desired,
            items_by_entity={LIST: fake.snapshot()},
            capabilities={LIST: caps},
            now=at,
        )

    first = run({}, now)
    _apply(fake, first)
    later = now + timedelta(minutes=minutes)
    second = run(first.tracked, later)
    assert _ops(second) == []
    third = run(second.tracked, later + timedelta(minutes=minutes))
    assert _ops(third) == []
    assert third.tracked == second.tracked


@pytest.mark.xfail(
    strict=True,
    reason="A list that cuts a long title gets a second copy after each hold. The "
    "planner matches text that differs in case and white space only, not a cut.",
)
@settings(max_examples=5)
@example(name="Replace the water filter in the kitchen")
@given(name=st.just("Replace the water filter in the kitchen"))
def test_todo_list_sync_settles_on_a_list_that_cuts_the_title(name):
    now = _now(-4)
    fake = FakeList(title=lambda s: s[:20], note=str, due=str, uids=False)
    task = models.build_task({"name": name, "interval": 3, "unit": "days"}, now=now)
    synced = [
        profiles.normalize_profile(
            {"id": "m1", "name": "m1", "filter": {}, "sync": {"entity_id": LIST}}
        )
    ]
    desired = tm.desired_by_sync(synced, [task], now=now)
    first = tm.plan_sync(
        synced=synced,
        tracked={},
        desired=desired,
        items_by_entity={LIST: fake.snapshot()},
        capabilities={LIST: frozenset()},
        now=now,
    )
    _apply(fake, first)
    second = tm.plan_sync(
        synced=synced,
        tracked=first.tracked,
        desired=desired,
        items_by_entity={LIST: fake.snapshot()},
        capabilities={LIST: frozenset()},
        now=now + timedelta(minutes=25),
    )
    assert _ops(second) == []


# ── shopping-list sync ────────────────────────────────────────────────────────


@settings(max_examples=150)
# A list with no uids that stores the title in upper case.
@example(
    form=("upper", "as_is", "date", False),
    names=["Ab"],
    amounts=[None, None, None],
    foreign=[],
    caps=frozenset(),
    minutes=0,
)
@given(
    form=_forms,
    names=st.lists(_words, min_size=1, max_size=3, unique_by=_key),
    amounts=st.lists(st.sampled_from([None, 2, 500]), min_size=3, max_size=3),
    foreign=st.lists(_words, max_size=2),
    caps=_CAPS,
    minutes=st.sampled_from([0, 5, 25, 90]),
)
def test_shopping_sync_settles_on_a_list_that_normalizes(
    form, names, amounts, foreign, caps, minutes
):
    """Kills: the exact title compare for ``user_named`` and ``rename`` in
    ``shopping.plan_sync``, which renamed a line on each pass on a list with no
    uid that stores the title in another case."""
    now = _now(-4)
    fake = _fake_list(form, now)
    for text in foreign:
        fake.add(text, None, None)
    parts = [
        {
            "name": f"Part {index}",
            "type": "consumable",
            "stock": 0,
            "reorder_at": 1,
            "stock_unit": "ml" if amount == 500 else "",
            "restock_quantity": amount,
            "create_buy_task": True,
        }
        for index, amount in enumerate(amounts[: len(names)])
    ]
    asset = assets_model.build_asset({"name": "Heater", "parts": parts}, now=now)
    tasks = {}
    for name, part in zip(names, asset["parts"], strict=False):
        source = {"buy": {"asset_id": asset["id"], "part_id": part["id"]}}
        task = models.build_task(
            {"name": name, "recurrence_type": "one-off", "source": source}, now=now
        )
        tasks[task["id"]] = task
    desired = sh.buy_tasks_by_part(tasks, {asset["id"]: asset})
    assert len(desired) == len(tasks)

    def run(tracked: dict[str, Any], at: datetime) -> Any:
        return sh.plan_sync(
            tracked=tracked,
            desired=desired,
            items_by_entity={LIST: fake.snapshot()},
            target=LIST,
            now=at,
            capabilities={LIST: caps},
        )

    first = run({}, now)
    _apply(fake, first)
    later = now + timedelta(minutes=minutes)
    second = run(first.tracked, later)
    assert _ops(second) == []
    third = run(second.tracked, later + timedelta(minutes=minutes))
    assert _ops(third) == []
    assert third.tracked == second.tracked


# ── problem sensors ───────────────────────────────────────────────────────────

_ids = st.sampled_from([None, "x1", "x2"])


@st.composite
def _eligible(draw: Any) -> dict[str, dict[str, Any]]:
    count_ = draw(st.integers(1, 3))
    return {
        f"binary_sensor.p{index}": {
            "name": draw(_words),
            "device_id": draw(_ids),
            "area_id": draw(_ids),
            "is_problem": draw(st.booleans()),
            "name_live": True,
        }
        for index in range(count_)
    }


@settings(max_examples=100)
# A sensor name with a space at the end.
@example(
    eligible={
        "binary_sensor.p0": {
            "name": "Ab ",
            "device_id": None,
            "area_id": None,
            "is_problem": False,
            "name_live": True,
        }
    },
    restored="Cd",
    notes="",
)
@given(eligible=_eligible(), restored=_words, notes=_notes)
def test_problem_reconcile_settles_and_a_restored_name_renames_nothing(
    eligible, restored, notes
):
    """Kills: dropping the ``name_live`` gate in ``problem_tasks``, which renamed
    every problem task after a restart (the rename loop of #500)."""
    now = _now(-4)
    notes_by_entity = dict.fromkeys(eligible, notes)

    def run(sensors: dict[str, Any], tasks: dict[str, Any]) -> Any:
        return pt.reconcile_problem_tasks(
            sensors,
            tasks,
            config_entry_id=ENTRY,
            now=now,
            notes_by_entity=notes_by_entity,
        )

    first, *_ = run(eligible, {})
    second, ops, changed = run(eligible, first)
    assert (ops, changed) == ([], False)
    assert second == first
    # After a restart a sensor has no live state yet, so its name comes from the
    # registry. A task keeps the name it has.
    booted = {
        entity_id: {**meta, "name": restored, "name_live": False}
        for entity_id, meta in eligible.items()
    }
    _third, ops, changed = run(booted, second)
    assert (ops, changed) == ([], False)


# ── declarative companions ────────────────────────────────────────────────────


def _spec() -> dict[str, Any]:
    return dc.normalize_declarative_companion(
        {
            "name": "Spec",
            "selection": {
                "target_integration": "device_pulse",
                "entity_regex": r".*_pings$",
            },
            "trigger": {
                "mode": "threshold",
                "comparison": ">",
                "value": 0,
                "for_seconds": 60,
                "clear_on_recover": True,
            },
            "task_template": {"name_template": "Check", "notes_template": ""},
        }
    )


@st.composite
def _registry(draw: Any) -> dict[str, Any]:
    count_ = draw(st.integers(1, 3))
    return {
        "entities": [
            {
                "entity_registry_id": f"reg{index}",
                "entity_id": f"sensor.d{index}_pings",
                "platform": "device_pulse",
                "domain": "sensor",
                "device_class": None,
                "original_device_class": None,
                "device_id": draw(_ids),
                "area_id": draw(_ids),
                "labels": set(),
                "disabled": False,
                "name": None,
                "original_name": None,
                "translation_key": None,
            }
            for index in range(count_)
        ]
    }


@settings(max_examples=100)
@given(
    registry=_registry(),
    names=st.lists(_words, min_size=3, max_size=3),
    notes=_notes,
    baseline=st.one_of(st.none(), st.floats(0, 1e6, allow_nan=False)),
)
def test_declarative_reconcile_settles(registry, names, notes, baseline):
    """Kills: a rewrite of the ``sensor`` block that drops the watcher's
    ``baseline`` (``merge_sensor_binding``), and any drift compare in
    ``reconcile_declarative_tasks`` that reads its own write as a change."""
    now = _now(-4)
    spec = _spec()
    matches = dc.expand_spec(spec, registry)
    rendered = {
        key: (name, notes) for key, name in zip(sorted(matches), names, strict=False)
    }

    def run(tasks: dict[str, Any]) -> Any:
        return dc.reconcile_declarative_tasks(
            spec, matches, tasks, rendered, config_entry_id=ENTRY, now=now
        )

    first, *_ = run({})
    if baseline is not None:
        # The watcher stamps the meter on the first reading.
        for task in first.values():
            if task["sensor"].get("mode") == "usage":
                task["sensor"]["baseline"] = baseline
    second, ops, changed = run(first)
    assert (ops, changed) == ([], False)
    assert second == first


@settings(max_examples=100)
@given(
    existing=st.fixed_dictionaries(
        {"mode": st.sampled_from(["usage", "threshold", "state"])},
        optional={"baseline": st.floats(0, 1e6, allow_nan=False)},
    ),
    fresh=st.fixed_dictionaries(
        {"mode": st.sampled_from(["usage", "threshold", "state"])},
        optional={"baseline": st.floats(0, 1e6, allow_nan=False)},
    ),
)
def test_merge_sensor_binding_is_idempotent(existing, fresh):
    once = dc.merge_sensor_binding(existing, fresh)
    assert dc.merge_sensor_binding(once, fresh) == once


# ── wear parts and buy reminders ──────────────────────────────────────────────


@st.composite
def _assets(draw: Any, now: datetime) -> dict[str, dict[str, Any]]:
    parts = []
    for index in range(draw(st.integers(1, 3))):
        if draw(st.booleans()):
            parts.append(
                {
                    "name": f"Wear {index}",
                    "type": "wear",
                    "replace_interval": draw(st.integers(1, 24)),
                    "replace_unit": draw(st.sampled_from(["days", "weeks", "months"])),
                }
            )
        else:
            parts.append(
                {
                    "name": f"Stock {index}",
                    "type": "consumable",
                    "stock": draw(st.integers(0, 3)),
                    "reorder_at": 1,
                    "create_buy_task": draw(st.booleans()),
                }
            )
    asset = assets_model.build_asset(
        {"name": draw(_words), "device_id": draw(_ids), "parts": parts}, now=now
    )
    return {asset["id"]: asset}


@settings(max_examples=60)
@given(data=st.data())
def test_part_and_buy_reconcilers_settle_together(data):
    """Kills: a drift compare in ``reconcile_part_tasks`` or ``reconcile_buy_tasks``
    that reads its own write as a change, or a pair that undo each other."""
    now = _now(-4)
    assets = data.draw(_assets(now))
    tasks, _ = rc.reconcile_part_tasks(assets, {}, now=now)
    tasks, _ = rc.reconcile_buy_tasks(assets, tasks, now=now)
    again, changed = rc.reconcile_part_tasks(assets, tasks, now=now)
    assert changed is False
    assert again == tasks
    again, changed = rc.reconcile_buy_tasks(assets, tasks, now=now)
    assert changed is False
    assert again == tasks


# ── due time snap ─────────────────────────────────────────────────────────────


@settings(max_examples=60)
@given(
    tasks=st.lists(ps.floating_tasks(now=_now(-4)), min_size=1, max_size=3),
    due_time=st.one_of(st.none(), st.times()),
    days=st.integers(-3, 10),
)
def test_snap_future_floating_settles(tasks, due_time, days):
    now = _now(-4)
    by_id = {}
    for task in tasks:
        task["next_due"] = (now + timedelta(days=days, hours=3)).isoformat()
        by_id[task["id"]] = task
    recurrence.snap_future_floating(by_id, due_time, now=now)
    assert recurrence.snap_future_floating(by_id, due_time, now=now) == []


# ── card resource ─────────────────────────────────────────────────────────────

_PATH = "/home_keeper_card/home-keeper-card.js"


@settings(max_examples=60)
@given(
    rows=st.lists(
        st.fixed_dictionaries(
            {
                "url": st.sampled_from(
                    [
                        _PATH,
                        f"{_PATH}?v=1",
                        f"http://ha.local:8123{_PATH}?v=0",
                        "/local/home-keeper-card.js",
                    ]
                ),
                "type": st.sampled_from(["module", "js"]),
            }
        ),
        max_size=4,
    ),
)
def test_card_resource_plan_settles(rows):
    """Kills: a stale check in ``plan_card_resource`` that reads its own update as
    stale, which rewrote the Lovelace resources on each start."""
    desired = f"{_PATH}?v=2"
    items = [{"id": str(index), **row} for index, row in enumerate(rows)]
    plan = cr.plan_card_resource(items, desired)
    items = [item for item in items if item["id"] not in plan.delete_ids]
    for item in items:
        if item["id"] == plan.update_id:
            item.update(url=desired, type=cr.RESOURCE_TYPE)
    if plan.create:
        items.append({"id": "new", "url": desired, "type": cr.RESOURCE_TYPE})
    assert cr.plan_card_resource(items, desired) == cr.ResourcePlan()
