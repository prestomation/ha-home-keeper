"""Integration coverage for the README's "Deadlines and follow-ups" recipes.

The README documents two automations that give a recurring task a deadline: miss it
and this week's occurrence is written off with ``skip_task``; make it and a triggered
follow-up task is armed with ``trigger_task``. Both read the task's own ``next_due``
and ``last_completed`` back out of ``list_tasks``.

Those recipes are load-bearing documentation, so they are not pasted into this file.
``ha_config/recipes.yaml`` holds them verbatim, Home Assistant loads it, and
``test_recipes_match_readme`` fails if the README and the fixture drift apart. The
rest of the module drives the loaded automations against real tasks.
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

CANCEL = "automation.trash_cancel_the_occurrence_if_the_bin_never_went_out"
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

    The occurrence lands either *due_in_seconds* ahead (so a test can wait for it to
    go overdue) or *occurrence_hours_ago* in the past. A fixed task rolls forward to
    the next future occurrence when it is created, so the anchor goes a week before
    the occurrence we actually want.
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
    # A triggered task is born *armed* (next_due == creation time). The README tells
    # readers to complete it once so it starts dormant; do the same here, and assert
    # it, so the instruction stays true.
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
    """Run an automation's action sequence and wait for it to finish.

    ``skip_condition`` stays at its default, so only the top-level "is it Thursday
    at 09:00" condition is bypassed; every condition inside the action sequence —
    the ones carrying the recipe's actual logic — still has to pass.

    Waits on the entity's own ``last_triggered`` advancing and its ``current`` run
    count falling back to zero, rather than on a fixed sleep. A loaded runner can
    take longer than any sleep worth writing, and a test that asserts mid-run reads
    the state the automation was about to change.

    ``current`` reaching zero is taken to mean the recipe's service calls have
    landed in the store, not merely that they were dispatched. That holds because
    Home Assistant's automation runner awaits each action in sequence, and every
    ``store`` mutation awaits its own ``_save()`` before returning — so the run
    cannot be counted as finished while a write is still in flight. If a future
    Home Assistant ever decrements ``current`` earlier, these tests go flaky rather
    than silently wrong, which is the failure mode to want.
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
    """Keep each test isolated, with the event-driven recipe off by default.

    The one-off variant is an *alternative* to the triggered follow-up and creates a
    task of the same name, so it stays disabled except in the test that drives it.
    """
    call_service(ha, "automation", "turn_off", {"entity_id": ONEOFF})
    _delete_recipe_tasks(ha)
    yield
    _delete_recipe_tasks(ha)
    call_service(ha, "automation", "turn_off", {"entity_id": ONEOFF})


# ── the recipes are the documentation ───────────────────────────────────────


def _readme_recipe_yaml():
    """Parse the automations out of the README's "Deadlines and follow-ups" section."""
    readme = (REPO_ROOT / "README.md").read_text()
    start = readme.index("### Deadlines and follow-ups")
    end = readme.index("## Integrations", start)
    section = readme[start:end]
    blocks = re.findall(r"```yaml\n(.*?)```", section, re.DOTALL)
    assert blocks, "the README section should carry yaml blocks"
    automations = []
    for block in blocks:
        loaded = yaml.safe_load(block)
        # The first block is a full `automation:` mapping; the variant is a bare
        # list item continuing it.
        automations.extend(loaded["automation"] if isinstance(loaded, dict) else loaded)
    return automations


def test_recipes_match_readme():
    """The fixture Home Assistant loads is the README's text, character for character.

    Without this a README edit could leave the tested automations behind, and the
    suite would happily go green on a recipe nobody can copy out of the docs.
    """
    documented = _readme_recipe_yaml()
    loaded = yaml.safe_load(RECIPES.read_text())
    assert [a["alias"] for a in loaded] == [a["alias"] for a in documented]
    assert loaded == documented


# ── cancelling a missed occurrence ──────────────────────────────────────────


def test_missed_deadline_cancels_the_occurrence(ha):
    _make_trash(ha, due_in_seconds=2)
    before = _wait_overdue(ha)

    _run(ha, CANCEL)

    after = _task(ha, TRASH)
    assert datetime.fromisoformat(after["next_due"]) - datetime.fromisoformat(
        before["next_due"]
    ) == timedelta(days=7), "a fixed task should advance exactly one occurrence"
    assert after["completions"] == [], "a cancelled week is not a completed week"
    assert after["last_completed"] is None


def test_completed_task_is_left_alone_by_the_deadline(ha):
    _make_trash(ha, due_in_seconds=2)
    _wait_overdue(ha)
    call_service(ha, "home_keeper", "complete_task", {"task_id": TRASH})
    before = _task(ha, TRASH)

    _run(ha, CANCEL)

    assert _task(ha, TRASH)["next_due"] == before["next_due"]


def test_time_trigger_runs_the_cancel_recipe(ha):
    """A real ``trigger: time`` firing drives the sequence, not just a manual run."""
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
    """Pin ``grace_hours`` itself, not just "somewhere between 3h and 30h".

    Each case completes the task *now* and moves the occurrence to sit either side
    of 12 hours earlier, so the completion lands minutes inside or outside the
    documented window. Widening or narrowing `grace_hours` fails one of the two.
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
    """The window has a floor as well as a ceiling.

    A completion back-dated to before the occurrence belongs to an earlier week, so
    it must not arm this week's follow-up. Without the `>= occurrence` half of the
    condition this passes on the ceiling alone, which is why it gets its own test.
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
    """``last_completed`` is null on a task nobody has ever done."""
    _make_trash(ha, occurrence_hours_ago=3)
    assert _task(ha, TRASH)["last_completed"] is None

    _run(ha, ARM)

    assert _task(ha, FOLLOW)["next_due"] is None


def test_completion_after_the_grace_window_does_not_arm_the_follow_up(ha):
    # The occurrence was 30h ago and the recipe allows 12h, so completing it now is
    # too late for the truck.
    _make_trash(ha, occurrence_hours_ago=30)
    call_service(ha, "home_keeper", "complete_task", {"task_id": TRASH})

    _run(ha, ARM)

    assert _task(ha, FOLLOW)["next_due"] is None


def test_cancelled_occurrence_never_arms_the_follow_up(ha):
    _make_trash(ha, due_in_seconds=2)
    _wait_overdue(ha)

    _run(ha, CANCEL)
    _run(ha, ARM)

    assert _task(ha, FOLLOW)["next_due"] is None


# ── the one-off variant ─────────────────────────────────────────────────────


def test_one_off_variant_creates_a_dated_follow_up(ha):
    _make_trash(ha, occurrence_hours_ago=3)
    # This variant replaces the triggered follow-up, so drop it before enabling.
    call_service(ha, "home_keeper", "delete_task", {"task_id": FOLLOW, "force": True})
    call_service(ha, "automation", "turn_on", {"entity_id": ONEOFF})

    call_service(ha, "home_keeper", "complete_task", {"task_id": TRASH})
    time.sleep(2)

    follow = _task(ha, FOLLOW)
    assert follow is not None, "completing the trash task should create the follow-up"
    assert follow["recurrence_type"] == "one-off"
    assert follow["next_due"][11:16] == "20:00"
    tomorrow = (_local_now(ha) + timedelta(days=1)).date().isoformat()
    assert follow["next_due"][:10] == tomorrow
