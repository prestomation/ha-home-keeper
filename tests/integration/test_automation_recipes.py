"""Integration coverage for the README "Deadlines and follow-ups" example.

The README documents 2 automations that give a recurring task a deadline. If the task
is late, ``skip_task`` moves the occurrence forward. If the task is complete in time,
``trigger_task`` arms a triggered follow-up task. Both automations read ``next_due``
and ``last_completed`` from ``list_tasks``.

The automations are documentation, so this file does not hold a copy of them.
``ha_config/recipes.yaml`` holds them verbatim and Home Assistant loads that file.
``test_recipes_match_readme`` fails if the README and the fixture become different.
The rest of this module drives the loaded automations against real tasks.
"""

import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml
from conftest import HA_URL, call_service, get_state

REPO_ROOT = Path(__file__).resolve().parents[2]
RECIPES = Path(__file__).parent / "ha_config" / "recipes.yaml"

TRASH = "Take out trash"
FOLLOW = "Bring the bin back in"

SKIP = "automation.trash_skip_the_occurrence_if_the_bin_did_not_go_out"
ARM = "automation.trash_arm_bring_the_bin_back_in_if_it_went_out_in_time"
ONEOFF = "automation.trash_create_a_dated_one_off_follow_up"


# ── helpers ─────────────────────────────────────────────────────────────────


def _tasks(ha):
    return call_service(ha, "home_keeper", "list_tasks", return_response=True)[
        "service_response"
    ]["tasks"]


def _task(ha, name):
    return next((t for t in _tasks(ha) if t["name"] == name), None)


def _local_now(ha):
    """HA's own idea of local time, so the test and the templates agree."""
    r = ha.post(f"{HA_URL}/api/template", json={"template": "{{ now().isoformat() }}"})
    r.raise_for_status()
    return datetime.fromisoformat(r.text)


def _delete_recipe_tasks(ha):
    for task in _tasks(ha):
        if task["name"] in (TRASH, FOLLOW):
            call_service(
                ha, "home_keeper", "delete_task", {"task_id": task["id"], "force": True}
            )


def _make_trash(ha, *, due_in_seconds=None, occurrence_hours_ago=None):
    """Create the weekly trash task plus a dormant triggered follow-up.

    The occurrence is either *due_in_seconds* in the future, so that a test can wait
    for the task to become overdue, or *occurrence_hours_ago* in the past. Home Keeper
    moves a new fixed task forward to the next occurrence in the future. The anchor is
    therefore 7 days before the occurrence that the test needs.
    """
    now = _local_now(ha)
    if due_in_seconds is not None:
        occurrence = now + timedelta(seconds=due_in_seconds)
    else:
        occurrence = now - timedelta(hours=occurrence_hours_ago)
    call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": TRASH,
            "recurrence_type": "fixed",
            "freq": "WEEKLY",
            "interval": 1,
            "anchor": (occurrence - timedelta(days=7)).isoformat(),
        },
    )
    call_service(
        ha, "home_keeper", "add_task", {"name": FOLLOW, "recurrence_type": "triggered"}
    )
    # Home Keeper creates a triggered task armed, with next_due set to the creation
    # time. The README tells the reader to complete the task 1 time to make it
    # dormant. This test does the same, and asserts it, to keep that instruction true.
    call_service(ha, "home_keeper", "complete_task", {"task_id": FOLLOW})
    assert _task(ha, FOLLOW)["next_due"] is None


def _wait_overdue(ha, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = _task(ha, TRASH)
        if task["next_due"] <= _local_now(ha).isoformat():
            return task
        time.sleep(0.5)
    raise TimeoutError(f"{TRASH} never went overdue")


def _run(ha, entity_id, timeout=30):
    """Run the action sequence of an automation and wait for the run to finish.

    ``skip_condition`` keeps its default value. Home Assistant therefore skips only
    the top-level weekday and time condition. Every condition inside the action
    sequence still must pass, and those conditions hold the logic of the example.

    This function waits for ``last_triggered`` to change and for the ``current`` run
    count to return to 0. A fixed sleep is not sufficient. A loaded runner can be slow,
    and a test that asserts during a run reads the state before the automation changes
    it.

    A ``current`` count of 0 means that the service calls are in the store, and not
    only that Home Assistant dispatched them. The automation runner awaits each action
    in sequence, and every ``store`` mutation awaits ``_save()`` before it returns. A
    run cannot finish while a write is in progress. If a later Home Assistant version
    decrements ``current`` earlier, these tests become flaky instead of incorrect.
    """
    before = get_state(ha, entity_id)["attributes"].get("last_triggered")
    call_service(ha, "automation", "trigger", {"entity_id": entity_id})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        attrs = get_state(ha, entity_id)["attributes"]
        if attrs.get("last_triggered") != before and not attrs.get("current"):
            return
        time.sleep(0.2)
    raise TimeoutError(f"{entity_id} did not finish a run within {timeout}s")


@pytest.fixture(autouse=True)
def recipe_tasks(ha):
    """Isolate each test, and disable the event-driven automation by default.

    The one-off automation is an alternative to the triggered follow-up task, and it
    creates a task with the same name. It stays disabled except in the test that drives
    it.
    """
    call_service(ha, "automation", "turn_off", {"entity_id": ONEOFF})
    _delete_recipe_tasks(ha)
    yield
    _delete_recipe_tasks(ha)
    call_service(ha, "automation", "turn_off", {"entity_id": ONEOFF})


# ── the recipes are the documentation ───────────────────────────────────────


def _readme_recipe_yaml():
    """Read the automations from the README "Deadlines and follow-ups" section."""
    readme = (REPO_ROOT / "README.md").read_text()
    start = readme.index("### Deadlines and follow-ups")
    end = readme.index("## Integrations", start)
    section = readme[start:end]
    blocks = re.findall(r"```yaml\n(.*?)```", section, re.DOTALL)
    assert blocks, "the README section should carry yaml blocks"
    automations = []
    for block in blocks:
        loaded = yaml.safe_load(block)
        # The first block is a complete `automation:` mapping. The second block is a
        # list item that continues it.
        automations.extend(loaded["automation"] if isinstance(loaded, dict) else loaded)
    return automations


def test_recipes_match_readme():
    """The fixture that Home Assistant loads is the text of the README.

    Without this test, an edit to the README can leave the tested automations behind.
    The suite then passes for an example that a reader cannot copy from the document.
    """
    documented = _readme_recipe_yaml()
    loaded = yaml.safe_load(RECIPES.read_text())
    assert [a["alias"] for a in loaded] == [a["alias"] for a in documented]
    assert loaded == documented


# ── skip a missed occurrence ────────────────────────────────────────────────


def test_missed_deadline_skips_the_occurrence(ha):
    _make_trash(ha, due_in_seconds=2)
    before = _wait_overdue(ha)

    _run(ha, SKIP)

    after = _task(ha, TRASH)
    assert datetime.fromisoformat(after["next_due"]) - datetime.fromisoformat(
        before["next_due"]
    ) == timedelta(days=7), "a fixed task must move forward exactly 1 occurrence"
    assert after["completions"] == [], "a skipped week is not a completed week"
    assert after["last_completed"] is None


def test_completed_task_is_left_alone_by_the_deadline(ha):
    _make_trash(ha, due_in_seconds=2)
    _wait_overdue(ha)
    call_service(ha, "home_keeper", "complete_task", {"task_id": TRASH})
    before = _task(ha, TRASH)

    _run(ha, SKIP)

    assert _task(ha, TRASH)["next_due"] == before["next_due"]


def test_time_trigger_runs_the_cancel_recipe(ha):
    """A real ``trigger: time`` event drives the sequence, and not only a manual run."""
    _make_trash(ha, due_in_seconds=2)
    before = _wait_overdue(ha)
    call_service(
        ha,
        "input_text",
        "set_value",
        {"entity_id": "input_text.hk_probe_result", "value": "none"},
    )
    fire_at = (_local_now(ha) + timedelta(seconds=20)).replace(microsecond=0)
    call_service(
        ha,
        "input_datetime",
        "set_datetime",
        {
            "entity_id": "input_datetime.hk_probe_at",
            "datetime": fire_at.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )

    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if get_state(ha, "input_text.hk_probe_result")["state"] == "skipped":
            break
        time.sleep(1)
    else:
        pytest.fail("the time-triggered automation never ran")

    assert _task(ha, TRASH)["next_due"] > before["next_due"]


# ── arming the follow-up ────────────────────────────────────────────────────


def test_completion_inside_the_grace_window_arms_the_follow_up(ha):
    _make_trash(ha, occurrence_hours_ago=3)
    call_service(ha, "home_keeper", "complete_task", {"task_id": TRASH})

    _run(ha, ARM)

    assert _task(ha, FOLLOW)["next_due"] is not None


def test_grace_window_boundary_is_twelve_hours(ha):
    """Pin the value of ``grace_hours``, and not a range between 3h and 30h.

    Each case completes the task now, and puts the occurrence on one side of the
    12-hour point. The completion is therefore minutes inside or outside the documented
    window. A larger or a smaller ``grace_hours`` fails one of the 2 cases.
    """
    _make_trash(ha, occurrence_hours_ago=12 - (5 / 60))
    call_service(ha, "home_keeper", "complete_task", {"task_id": TRASH})
    _run(ha, ARM)
    assert _task(ha, FOLLOW)["next_due"] is not None, "11h55m should be inside 12h"

    _delete_recipe_tasks(ha)
    _make_trash(ha, occurrence_hours_ago=12 + (5 / 60))
    call_service(ha, "home_keeper", "complete_task", {"task_id": TRASH})
    _run(ha, ARM)
    assert _task(ha, FOLLOW)["next_due"] is None, "12h05m should be outside 12h"


def test_completion_before_the_occurrence_does_not_arm_the_follow_up(ha):
    """The window has a lower limit and an upper limit.

    A completion with a date before the occurrence belongs to an earlier week. It must
    not arm the follow-up task for this week. Without the `>= occurrence` part of the
    condition, the upper limit alone accepts it. This case therefore needs its own test.
    """
    _make_trash(ha, occurrence_hours_ago=3)
    call_service(ha, "home_keeper", "complete_task", {"task_id": TRASH})
    task = _task(ha, TRASH)
    occurrence = datetime.fromisoformat(task["next_due"]) - timedelta(days=7)
    call_service(
        ha,
        "home_keeper",
        "move_completion",
        {
            "task_id": TRASH,
            "old_ts": task["completions"][-1]["ts"],
            "new_completed_at": (occurrence - timedelta(hours=1)).isoformat(),
        },
    )
    moved = _task(ha, TRASH)
    assert datetime.fromisoformat(moved["last_completed"]) < occurrence

    _run(ha, ARM)

    assert _task(ha, FOLLOW)["next_due"] is None


def test_never_completed_task_does_not_arm_the_follow_up(ha):
    """``last_completed`` is null for a task that nobody completed."""
    _make_trash(ha, occurrence_hours_ago=3)
    assert _task(ha, TRASH)["last_completed"] is None

    _run(ha, ARM)

    assert _task(ha, FOLLOW)["next_due"] is None


def test_completion_after_the_grace_window_does_not_arm_the_follow_up(ha):
    # The occurrence was 30h in the past, and the example allows 12h. A completion now
    # is too late for the truck.
    _make_trash(ha, occurrence_hours_ago=30)
    call_service(ha, "home_keeper", "complete_task", {"task_id": TRASH})

    _run(ha, ARM)

    assert _task(ha, FOLLOW)["next_due"] is None


def test_skipped_occurrence_never_arms_the_follow_up(ha):
    _make_trash(ha, due_in_seconds=2)
    _wait_overdue(ha)

    _run(ha, SKIP)
    _run(ha, ARM)

    assert _task(ha, FOLLOW)["next_due"] is None


# ── the one-off variant ─────────────────────────────────────────────────────


def test_one_off_variant_creates_a_dated_follow_up(ha):
    _make_trash(ha, occurrence_hours_ago=3)
    # This automation replaces the triggered follow-up task. Delete that task first.
    call_service(ha, "home_keeper", "delete_task", {"task_id": FOLLOW, "force": True})
    call_service(ha, "automation", "turn_on", {"entity_id": ONEOFF})

    call_service(ha, "home_keeper", "complete_task", {"task_id": TRASH})
    time.sleep(2)

    follow = _task(ha, FOLLOW)
    assert follow is not None, "a trash task completion must create the follow-up"
    assert follow["recurrence_type"] == "one-off"
    assert follow["next_due"][11:16] == "20:00"
    tomorrow = (_local_now(ha) + timedelta(days=1)).date().isoformat()
    assert follow["next_due"][:10] == tomorrow
