"""Unit tests for the pure problem-sensor → task reconciler (``problem_tasks.py``).

These exercise the create / arm / clear / orphan / metadata branches directly,
without a Home Assistant runtime. The store wraps this with persistence + event
firing (integration tests); ``problem_sync.py`` provides the HA-aware enumeration.
"""

from datetime import datetime, timedelta, timezone

import hk_problem_tasks as pt

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 19, 9, tzinfo=TZ)
ENTRY = "cfg_entry_1"


def _eligible(entity_id="binary_sensor.washer_problem", *, is_problem, **meta):
    return {
        entity_id: {
            "name": meta.get("name", "Washer problem"),
            "device_id": meta.get("device_id"),
            "area_id": meta.get("area_id"),
            "is_problem": is_problem,
        }
    }


def _reconcile(eligible, tasks=None):
    return pt.reconcile_problem_tasks(
        eligible, tasks or {}, config_entry_id=ENTRY, now=NOW
    )


def _only(tasks):
    assert len(tasks) == 1, tasks
    return next(iter(tasks.values()))


# ── creation ──────────────────────────────────────────────────────────────────
def test_creates_armed_task_when_sensor_in_problem():
    tasks, ops, changed = _reconcile(
        _eligible(is_problem=True, device_id="dev1", area_id="garage")
    )
    assert changed is True
    task = _only(tasks)
    assert task["recurrence_type"] == "triggered"
    assert task["source"]["problem_sensor"] == {
        "entity_id": "binary_sensor.washer_problem"
    }
    assert task["device_id"] == "dev1"
    assert task["area_id"] == "garage"
    assert task["next_due"] is not None  # armed (due now)
    assert task["managed_by"]["completion_blocked"] is True
    assert task["managed_by"]["deletion_protected"] is True
    assert task["managed_by"]["config_entry_id"] == ENTRY
    assert [kind for kind, _ in ops] == ["created"]


def test_creates_dormant_task_when_sensor_ok():
    tasks, ops, _ = _reconcile(_eligible(is_problem=False))
    task = _only(tasks)
    assert task["next_due"] is None  # dormant
    assert [kind for kind, _ in ops] == ["created"]


# ── arm / clear transitions ───────────────────────────────────────────────────
def test_arms_dormant_task_when_problem_appears():
    tasks, _, _ = _reconcile(_eligible(is_problem=False))
    tasks2, ops, changed = _reconcile(_eligible(is_problem=True), tasks)
    assert changed is True
    assert [kind for kind, _ in ops] == ["armed"]
    assert _only(tasks2)["next_due"] is not None


def test_clears_armed_task_when_problem_resolves():
    tasks, _, _ = _reconcile(_eligible(is_problem=True))
    tasks2, ops, changed = _reconcile(_eligible(is_problem=False), tasks)
    assert changed is True
    assert [kind for kind, _ in ops] == ["cleared"]
    task = _only(tasks2)
    assert task["next_due"] is None  # back to dormant
    # Clearing records a completion so the recurrence history accumulates.
    assert len(task["completions"]) == 1


def test_no_op_when_state_unchanged():
    tasks, _, _ = _reconcile(_eligible(is_problem=True))
    _, ops, changed = _reconcile(_eligible(is_problem=True), tasks)
    assert ops == []
    assert changed is False


# ── orphan removal ────────────────────────────────────────────────────────────
def test_removes_task_when_sensor_no_longer_eligible():
    tasks, _, _ = _reconcile(_eligible(is_problem=True))
    # Empty eligible map == syncing off / sensor removed / excluded.
    tasks2, ops, changed = _reconcile({}, tasks)
    assert changed is True
    assert tasks2 == {}
    assert [kind for kind, _ in ops] == ["deleted"]


def test_carries_through_unrelated_tasks():
    other = {"t1": {"id": "t1", "name": "Flush water heater", "source": None}}
    tasks, _ops, changed = _reconcile(_eligible(is_problem=True), dict(other))
    assert "t1" in tasks
    assert len(tasks) == 2  # the unrelated task plus the new synced one
    assert changed is True


# ── metadata follows the sensor ───────────────────────────────────────────────
def test_updates_name_device_area_without_an_op():
    tasks, _, _ = _reconcile(
        _eligible(is_problem=True, name="Old name", device_id="dev1")
    )
    tid = next(iter(tasks))
    moved = _eligible(
        is_problem=True, name="New name", device_id="dev2", area_id="kitchen"
    )
    tasks2, ops, changed = _reconcile(moved, tasks)
    task = tasks2[tid]
    assert task["name"] == "New name"
    assert task["device_id"] == "dev2"
    assert task["area_id"] == "kitchen"
    assert changed is True
    assert ops == []  # metadata churn isn't announced as an arm/clear


# ── source helpers ────────────────────────────────────────────────────────────
def test_problem_source_helpers():
    task = _only(_reconcile(_eligible(is_problem=True))[0])
    assert pt.problem_source(task) == {"entity_id": "binary_sensor.washer_problem"}
    assert pt.problem_sensor_entity_id(task) == "binary_sensor.washer_problem"
    assert pt.problem_source({"source": None}) is None
    assert pt.problem_source({"source": {"part": {}}}) is None
