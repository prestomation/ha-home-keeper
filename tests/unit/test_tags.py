"""Unit tests for NFC/RFID tag routing and scan authorization.

Two rules carry the feature: which tasks a scanned tag completes, and which
completions a scan-only task will accept. Both are pure, so they are pinned here
rather than through a bus event.
"""

import hk_tags as tags
import pytest

# The two system origins that are Home Keeper completing a task itself, plus the
# scan marker. Spelled out rather than imported so a rename of the constants can't
# quietly re-open the gate this test exists to keep shut.
TAG_SCAN = "home_keeper_tag_scan"
SENSOR_RECOVER = "home_keeper_sensor_recover"
PROBLEM_SYNC = "home_keeper_problem_sensor_sync"
NOTIFICATION_ACTION = "home_keeper_notification_action"


def _task(**kwargs):
    return {"id": "t1", "name": "Descale", **kwargs}


# ── tasks_for_tag ────────────────────────────────────────────────────────────


def test_tasks_for_tag_matches_every_task_bound_to_the_tag():
    # One sticker, several jobs: scanning the coffee machine completes both.
    descale = _task(id="t1", tag_id="coffee")
    beans = _task(id="t2", tag_id="coffee")
    other = _task(id="t3", tag_id="kettle")
    assert tags.tasks_for_tag([descale, beans, other], "coffee") == [descale, beans]


def test_tasks_for_tag_excludes_disabled_tasks():
    # A disabled task is invisible everywhere else; a scan must not be a back door.
    assert tags.tasks_for_tag([_task(tag_id="coffee", enabled=False)], "coffee") == []


def test_tasks_for_tag_includes_a_task_with_no_enabled_key():
    # ``enabled`` defaults to True, as it does on every other surface.
    task = _task(tag_id="coffee")
    assert "enabled" not in task
    assert tags.tasks_for_tag([task], "coffee") == [task]


def test_tasks_for_tag_includes_an_explicitly_enabled_task():
    task = _task(tag_id="coffee", enabled=True)
    assert tags.tasks_for_tag([task], "coffee") == [task]


def test_tasks_for_tag_ignores_a_different_tag():
    assert tags.tasks_for_tag([_task(tag_id="kettle")], "coffee") == []


def test_tasks_for_tag_ignores_untagged_tasks():
    assert tags.tasks_for_tag([_task(), _task(tag_id=None)], "coffee") == []


def test_tasks_for_tag_matches_exactly_not_by_prefix():
    assert tags.tasks_for_tag([_task(tag_id="coffee-machine")], "coffee") == []


def test_tasks_for_tag_on_no_tasks_is_empty():
    assert tags.tasks_for_tag([], "coffee") == []


# ── completion_allowed ───────────────────────────────────────────────────────

ALL_ORIGINS = [
    None,
    "",
    TAG_SCAN,
    SENSOR_RECOVER,
    PROBLEM_SYNC,
    NOTIFICATION_ACTION,
    "pawsistant",
    "HOME_KEEPER_TAG_SCAN",
]


@pytest.mark.parametrize("origin", ALL_ORIGINS)
def test_completion_allowed_for_a_task_without_the_flag(origin):
    # No requirement, no gate: every origin completes an ordinary task, including a
    # tagged one (a tag is a convenience until the flag makes it the only way).
    assert tags.completion_allowed(_task(), origin) is True
    assert tags.completion_allowed(_task(tag_id="coffee"), origin) is True
    assert tags.completion_allowed(_task(require_tag_scan=False), origin) is True


@pytest.mark.parametrize("origin", [TAG_SCAN, SENSOR_RECOVER, PROBLEM_SYNC])
def test_completion_allowed_for_the_authorized_origins(origin):
    task = _task(tag_id="coffee", require_tag_scan=True)
    assert tags.completion_allowed(task, origin) is True


@pytest.mark.parametrize(
    "origin",
    [None, "", NOTIFICATION_ACTION, "pawsistant", "HOME_KEEPER_TAG_SCAN", "tag_scan"],
)
def test_completion_rejected_for_every_other_origin(origin):
    # The bare service call (no origin), a notification tap, a contributing
    # integration, and near-miss spellings of the marker all stay out.
    task = _task(tag_id="coffee", require_tag_scan=True)
    assert tags.completion_allowed(task, origin) is False


def test_scan_allowed_origins_is_exactly_the_three_system_markers():
    assert set(tags.SCAN_ALLOWED_ORIGINS) == {TAG_SCAN, SENSOR_RECOVER, PROBLEM_SYNC}
