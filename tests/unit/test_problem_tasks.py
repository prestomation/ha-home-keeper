"""Unit tests for the pure problem-sensor → task reconciler (``problem_tasks.py``).

These exercise the create / arm / clear / orphan / metadata branches directly,
without a Home Assistant runtime. The store wraps this with persistence + event
firing (integration tests); ``problem_sync.py`` provides the HA-aware enumeration.
"""

from datetime import datetime, timedelta, timezone

import hk_problem_tasks as pt
import pytest

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


# ── indeterminate (unavailable/unknown) state ─────────────────────────────────
def test_indeterminate_does_not_clear_an_armed_task():
    # Regression: an armed task must NOT be cleared/completed when the sensor goes
    # unavailable/unknown (is_problem=None) — that fired spurious completions at
    # setup (before other integrations restored state) and on device-offline blips.
    tasks, _, _ = _reconcile(_eligible(is_problem=True))
    tasks2, ops, changed = _reconcile(_eligible(is_problem=None), tasks)
    assert ops == []
    assert changed is False
    task = _only(tasks2)
    assert task["next_due"] is not None  # still armed
    assert task["completions"] == []  # no spurious completion recorded


def test_indeterminate_does_not_arm_a_dormant_task():
    tasks, _, _ = _reconcile(_eligible(is_problem=False))
    tasks2, ops, changed = _reconcile(_eligible(is_problem=None), tasks)
    assert ops == []
    assert changed is False
    assert _only(tasks2)["next_due"] is None  # still dormant


def test_creates_dormant_task_when_sensor_indeterminate():
    # A brand-new sensor whose state hasn't restored yet starts dormant, not armed.
    tasks, ops, _ = _reconcile(_eligible(is_problem=None))
    task = _only(tasks)
    assert task["next_due"] is None
    assert [kind for kind, _ in ops] == ["created"]


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
def test_b18_4_updates_name_device_area_with_an_updated_op():
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
    # One update, and no arm or clear: the sensor is still in problem.
    assert ops == [("updated", task)]


def test_b18_4_no_drift_gives_no_op_and_no_change():
    tasks, _, _ = _reconcile(_eligible(is_problem=True))
    _tasks2, ops, changed = _reconcile(_eligible(is_problem=True), tasks)
    assert ops == []
    assert changed is False


def test_b18_4_an_update_comes_before_the_clear_of_the_same_task():
    tasks, _, _ = _reconcile(_eligible(is_problem=True, name="Old"))
    _tasks2, ops, _ = _reconcile(_eligible(is_problem=False, name="New"), tasks)
    assert [kind for kind, _task in ops] == ["updated", "cleared"]


@pytest.mark.parametrize(
    "over", [{"name": "N2"}, {"device_id": "dev9"}, {"area_id": "garage"}]
)
def test_b18_4_each_owned_field_alone_gives_an_update(over):
    tasks, _, _ = _reconcile(_eligible(is_problem=True))
    _tasks2, ops, changed = _reconcile(_eligible(is_problem=True, **over), tasks)
    assert [kind for kind, _task in ops] == ["updated"]
    assert changed is True


def test_b18_4_a_new_language_alone_updates_managed_by():
    tasks, _, _ = _reconcile(_eligible(is_problem=True))
    prompt = _only(tasks)["managed_by"]["completion_prompt"]
    _tasks2, ops, changed = pt.reconcile_problem_tasks(
        _eligible(is_problem=True), tasks, config_entry_id=ENTRY, now=NOW, lang="de"
    )
    assert [kind for kind, _task in ops] == ["updated"]
    assert ops[0][1]["managed_by"]["completion_prompt"] != prompt
    assert changed is True


# ── source helpers ────────────────────────────────────────────────────────────
def test_problem_source_helpers():
    task = _only(_reconcile(_eligible(is_problem=True))[0])
    assert pt.problem_source(task) == {"entity_id": "binary_sensor.washer_problem"}
    assert pt.problem_sensor_entity_id(task) == "binary_sensor.washer_problem"
    assert pt.problem_source({"source": None}) is None
    assert pt.problem_source({"source": {"part": {}}}) is None


# ── durable notes hydration ───────────────────────────────────────────────────
ENTITY = "binary_sensor.washer_problem"


def test_new_task_hydrates_note_from_notes_by_entity():
    # A note the user saved previously (kept in the store's entity-keyed side-store)
    # seeds the freshly created mirror, so it's there the next time the problem fires.
    tasks, ops, _ = pt.reconcile_problem_tasks(
        _eligible(is_problem=True),
        {},
        config_entry_id=ENTRY,
        now=NOW,
        notes_by_entity={ENTITY: "Reset breaker in garage panel"},
    )
    task = _only(tasks)
    assert task["notes"] == "Reset breaker in garage panel"
    assert [kind for kind, _ in ops] == ["created"]


def test_new_task_without_stored_note_defaults_empty():
    tasks, _, _ = pt.reconcile_problem_tasks(
        _eligible(is_problem=True),
        {},
        config_entry_id=ENTRY,
        now=NOW,
        notes_by_entity={"binary_sensor.other": "unrelated"},
    )
    assert _only(tasks)["notes"] == ""


def test_note_hydration_only_seeds_new_tasks_not_existing_ones():
    # An existing mirror keeps its live note; re-reconciling never clobbers it from
    # the side-store (write-back flows the other way, in the store on update_task).
    tasks, _, _ = _reconcile(_eligible(is_problem=True))
    tid = next(iter(tasks))
    tasks[tid]["notes"] = "edited on the task"
    tasks2, ops, _ = pt.reconcile_problem_tasks(
        _eligible(is_problem=False),  # sensor clears
        tasks,
        config_entry_id=ENTRY,
        now=NOW + timedelta(hours=1),
        notes_by_entity={ENTITY: "stale side-store value"},
    )
    assert tasks2[tid]["notes"] == "edited on the task"
    assert [kind for kind, _ in ops] == ["cleared"]


# ── entity_id rename (B18-2) ──────────────────────────────────────────────────
OLD = "binary_sensor.node_5_problem"
NEW = "binary_sensor.sump_pump_problem"


def test_b18_2_a_rename_keeps_the_mirror_its_labels_history_and_note():
    # A rename was a delete of the old mirror and a create of an empty new one.
    tasks, _ops, _ = _reconcile(_eligible(OLD, is_problem=True))
    task = _only(tasks)
    task["labels"] = ["sump"]
    task["completions"] = [{"ts": NOW.isoformat()}]
    notes = {OLD: "Check the float", "binary_sensor.other": "x"}

    assert pt.rename_problem_entity(tasks, notes, OLD, NEW) is True
    assert pt.problem_sensor_entity_id(task) == NEW
    assert notes == {NEW: "Check the float", "binary_sensor.other": "x"}

    after, ops, _ = pt.reconcile_problem_tasks(
        _eligible(NEW, is_problem=True),
        tasks,
        config_entry_id=ENTRY,
        now=NOW,
        notes_by_entity=notes,
    )
    kept = _only(after)
    assert kept["id"] == task["id"]
    assert kept["labels"] == ["sump"]
    assert kept["completions"] == [{"ts": NOW.isoformat()}]
    # The new sensor gives the mirror a new prompt: an update, not a create.
    assert [kind for kind, _ in ops] == ["updated"]
    assert NEW in kept["managed_by"]["completion_prompt"]


def test_b18_2_a_rename_without_a_note_moves_only_the_task():
    tasks, _ops, _ = _reconcile(_eligible(OLD, is_problem=False))
    notes: dict[str, str] = {}
    assert pt.rename_problem_entity(tasks, notes, OLD, NEW) is True
    assert pt.problem_sensor_entity_id(_only(tasks)) == NEW
    assert notes == {}


def test_b18_2_a_rename_of_an_entity_with_no_mirror_changes_nothing():
    tasks, _ops, _ = _reconcile(_eligible(OLD, is_problem=False))
    notes = {"binary_sensor.a": "note"}
    assert pt.rename_problem_entity(tasks, notes, "binary_sensor.a", NEW) is False
    assert notes == {"binary_sensor.a": "note"}
    assert pt.problem_sensor_entity_id(_only(tasks)) == OLD


def test_b18_2_a_rename_onto_an_existing_mirror_changes_nothing():
    tasks, _ops, _ = _reconcile(
        {**_eligible(OLD, is_problem=False), **_eligible(NEW, is_problem=False)}
    )
    notes = {OLD: "old note"}
    assert pt.rename_problem_entity(tasks, notes, OLD, NEW) is False
    assert notes == {OLD: "old note"}
    assert sorted(pt.problem_sensor_entity_id(t) for t in tasks.values()) == [
        OLD,
        NEW,
    ]


def test_b18_2_a_rename_to_the_same_id_changes_nothing():
    tasks, _ops, _ = _reconcile(_eligible(OLD, is_problem=False))
    notes = {OLD: "note"}
    assert pt.rename_problem_entity(tasks, notes, OLD, OLD) is False
    assert notes == {OLD: "note"}
