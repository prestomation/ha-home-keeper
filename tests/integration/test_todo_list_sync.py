"""Integration coverage for the task sync, against a real to-do list.

The unit tier proves the planner and the driver in isolation; what only a real
Home Assistant can show is that ``todo.get_items`` / ``add_item`` / ``update_item``
behave the way the driver assumes, that a due date written by the sync survives
the round trip through somebody else's to-do integration, and that ticking a chore
off on that list actually reaches the store as a completion carrying the sync's
origin. The container seeds a ``local_todo`` list ("Family chores",
``todo.family_chores``) purely as something to sync onto — it stands in for the
Todoist project or kitchen-tablet list a household already checks.

**A sync is a profile**, so every test here configures one by saving ``profiles``
— the call the panel's Settings tab makes — with a profile carrying a ``sync`` block
naming the list. There is no second record to keep in step and no separate id: the
profile's own filter is the sync's filter, and clearing ``sync.entity_id`` is both
the off switch and the delete, which gets a case of its own below.

``local_todo`` is a deliberate choice of stand-in: it supports due dates and
descriptions, and it *reports* completed items rather than dropping them, so a tick
here arrives as a real ``completed`` status. That is also why the profiles below sync
with ``vanish_as_completed`` **off**, which is what the README tells a ``local_todo``
user to do: with it on, an item that merely goes missing is read as done, and the
unit tier already covers that path exhaustively. Everything else is the panel's own
default (two-way on), so these tests exercise what a user actually gets.

What a completion does to the line depends on whether the profile still wants the
task afterwards, and both halves are pinned here because the difference is
invisible from the panel: on an **overdue** profile a completed chore reschedules
out of the selection and its line is *removed*, while on an **"all"** profile the
task is still wanted, so the line is *ticked off in place* and a fresh one goes on
beside it.

Each test owns the state it creates. Profiles are shared state — the seeded
``demo_me`` drives other suites and the screenshot capture — so a test *appends* its
own profile and puts the saved list back afterwards rather than replacing it
wholesale. Restoring is also what clears the lines the profile wrote; the probe tasks
are then deleted and the list swept clean, leaving the committed fixture and the
container unchanged. The sweep takes the *whole* list, not just this suite's own
lines: an overdue profile also puts every seeded overdue chore on it, and a ticked-off
line is never removed by the sync itself (it is the household's record). Nothing
else in this tier writes to the seeded list, so it is this suite's to leave empty.
"""

import time
from contextlib import contextmanager
from datetime import datetime

import pytest
from conftest import call_service, poll_state
from ha_registry import ws_command

SYNC_LIST = "todo.family_chores"
#: Every task and item this suite creates. Shares the "probe" marker
#: ``tests/unit/test_integration_fixture_clean.py`` watches for, so a leaked task
#: fails the fast unit lane rather than quietly joining the seed fixture.
PROBE = "Task sync probe"
#: The completion event's origin, synced into a helper by the capture automation
#: in ``ha_config/configuration.yaml``.
ORIGIN_SENTINEL = "input_text.hk_last_completed_origin"
ORIGIN_TODO_SYNC = "home_keeper_todo_sync"


def _sync(**overrides):
    """A profile's ``sync`` block, pointed at the household's list.

    ``vanish_as_completed`` is off because the target reports its completions — see
    the module docstring. ``two_way`` stays on, which is the panel's own default.
    """
    return {
        "entity_id": SYNC_LIST,
        "two_way": True,
        "vanish_as_completed": False,
        **overrides,
    }


def _profile(profile_id, name, status, **sync_overrides):
    return {
        "id": profile_id,
        "name": name,
        "filter": {"status": status, "labels": [], "areas": [], "devices": []},
        "sync": _sync(**sync_overrides),
    }


#: A profile that wants a task while it is due — the shape of sync that takes a
#: chore back off the list once completing it has rescheduled it.
DUE_NOW_PROFILE = _profile("itest_todo_list_due", "Task sync probe profile", "overdue")
#: A profile that wants a task whatever its due date — the shape of sync that
#: keeps a chore on the list across its completion.
ALL_PROFILE = _profile("itest_todo_list_all", "Task sync probe profile (all)", "all")


def _list_tasks(ha):
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    return resp.get("service_response", resp)["tasks"]


def _get_task(ha, task_id):
    return next((t for t in _list_tasks(ha) if t["id"] == task_id), None)


def _items(ha, status=None):
    """The synced list's items, optionally filtered by status."""
    data = {"entity_id": SYNC_LIST}
    if status is not None:
        data["status"] = status
    resp = call_service(ha, "todo", "get_items", data, return_response=True)
    body = resp.get("service_response", resp)
    return body[SYNC_LIST]["items"]


def _summaries(ha, status=None):
    return [item["summary"] for item in _items(ha, status)]


def _find(ha, summary, status=None):
    """The item on the list reading *summary*, or None."""
    return next((i for i in _items(ha, status) if i["summary"] == summary), None)


def _poll(fn, *, timeout=60):
    """First truthy ``fn()`` within *timeout*, tolerating mid-reload 500s.

    Configuring a sync settles through an entry reload, so a read taken right
    after one can transiently hit "No active coordinator" (same reason
    ``test_shopping_sync._poll`` exists). A sync pass is also a chain of service
    calls into somebody else's integration, so the window is wider than the
    shopping sync's.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = fn()
            if value:
                return value
        except Exception:
            pass
        time.sleep(1)
    return None


def _set_options(ha, options):
    """Save options, retrying through the entry-reload window a save opens."""
    assert _poll(
        lambda: call_service(ha, "home_keeper", "set_options", options) or True
    ), f"home_keeper.set_options never succeeded for {sorted(options)}"


def _call(ha, service, data):
    """Call a Home Keeper service, retrying through the entry-reload window."""
    assert _poll(lambda: call_service(ha, "home_keeper", service, data) or True), (
        f"home_keeper.{service} never succeeded"
    )


def _options(ha):
    """The saved options, read the way the panel reads them (past a reload)."""
    return _poll(lambda: ws_command(ha, "home_keeper/get_options")["options"]) or {}


def _saved_profiles(ha):
    return _options(ha).get("profiles", [])


def _saved_profile(ha, profile_id):
    """One saved profile by id, as the panel would read it back."""
    return next((p for p in _saved_profiles(ha) if p["id"] == profile_id), None)


def _add_probe(ha, suffix):
    """An overdue floating task — no ``last_completed``, so it is due immediately."""
    resp = call_service(
        ha,
        "home_keeper",
        "add_task",
        {
            "name": f"{PROBE} {suffix}",
            "notes": f"Notes for probe {suffix.lower()}",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "days",
        },
        return_response=True,
    )
    return resp.get("service_response", resp)["task_id"]


def _delete_probe_tasks(ha):
    for task in _list_tasks(ha):
        if task["name"].startswith(PROBE):
            call_service(ha, "home_keeper", "delete_task", {"task_id": task["id"]})


def _clear_list(ha):
    """Empty the household's list.

    Everything on it got there from a profile this suite configured — the probes and,
    on an overdue profile, the seeded overdue chores too — and the *ticked-off* lines
    are ones the sync deliberately never removes (they are the household's record),
    so without this they would pile up across runs.
    """
    leftovers = [i["uid"] for i in _items(ha)]
    if leftovers:
        call_service(
            ha, "todo", "remove_item", {"entity_id": SYNC_LIST, "item": leftovers}
        )


def _restore(ha, saved_profiles):
    """Put the saved profiles back, then sweep the tasks and lines they leave behind.

    Order matters, and the wait in the middle is not padding. Dropping the syncing
    profile is what clears the open lines it wrote — the planner reads a tracked entry
    whose profile is gone exactly as it reads a cleared picker — so that goes first;
    the sweep then has to wait for that pass to actually land, or it races a run still
    in flight, and a sweep that removes a line the sync still believes it owns is
    exactly the "the household deleted it" input the sync is built to react to.
    """
    _set_options(ha, {"profiles": saved_profiles})
    _poll(lambda: not _items(ha, ["needs_action"]), timeout=30)
    _delete_probe_tasks(ha)
    _clear_list(ha)


@contextmanager
def _syncing(ha, profile):
    """Append *profile* (which syncs onto the household's list) for one test.

    Appended rather than saved on its own because profiles are shared state: the
    seeded ``demo_me`` drives other suites and the screenshot capture, so replacing
    the list wholesale would be this suite reaching into somebody else's fixture.
    """
    before = _saved_profiles(ha)
    _set_options(ha, {"profiles": [*before, profile]})
    try:
        yield
    finally:
        _restore(ha, before)


@pytest.fixture
def synced(ha):
    """A profile that wants a task while it is due, syncing onto the family's list."""
    with _syncing(ha, DUE_NOW_PROFILE):
        yield


@pytest.fixture
def synced_all(ha):
    """A profile that wants a task whatever its due date, syncing onto that list."""
    with _syncing(ha, ALL_PROFILE):
        yield


def test_an_overdue_task_reaches_the_synced_list(ha, synced):
    """The point of the feature: the chore turns up where the household looks."""
    task_id = _add_probe(ha, "A")
    name = f"{PROBE} A"

    item = _poll(lambda: _find(ha, name, ["needs_action"]))
    assert item, "an overdue task should have been synced onto the household's list"

    # The item is not just a summary: it carries the task's own due date, which is
    # what makes the line actionable on a phone. To-do lists work in whole days, so
    # the date half of next_due is what should have been written.
    task = _get_task(ha, task_id)
    expected_due = datetime.fromisoformat(task["next_due"]).date().isoformat()
    assert item["due"] == expected_due, (
        f"the synced item should carry the task's due date ({expected_due})"
    )


def test_completing_it_in_home_keeper_ticks_the_item_off(ha, synced_all):
    """Outbound: Done in the panel ticks the line off, and never deletes it.

    Deleting would be the easy implementation and the wrong one — the household's
    list is their record, so a chore they can see was done has to stay visible as
    done, with the next occurrence beside it. Asserting on the *uid* is what makes
    that a real claim: a remove-and-add would satisfy "there is a completed line
    reading X".
    """
    task_id = _add_probe(ha, "B")
    name = f"{PROBE} B"
    open_item = _poll(lambda: _find(ha, name, ["needs_action"]))
    assert open_item, "expected the synced item"

    _call(ha, "complete_task", {"task_id": task_id})

    ticked = _poll(lambda: _find(ha, name, ["completed"]))
    assert ticked, "completing the task should have ticked its synced item off"
    assert ticked["uid"] == open_item["uid"], (
        "the line must be ticked off in place, not removed and re-added"
    )

    # The chore recurs, so a *fresh* line for the next occurrence goes on beside the
    # ticked-off one — carrying the rescheduled due date, not the old one.
    fresh = _poll(lambda: _find(ha, name, ["needs_action"]))
    assert fresh, "the next occurrence should have been synced alongside the record"
    task = _get_task(ha, task_id)
    assert fresh["due"] == datetime.fromisoformat(task["next_due"]).date().isoformat()
    assert fresh["uid"] != open_item["uid"]


def test_completing_a_task_the_sync_stops_wanting_takes_its_line_off(ha, synced):
    """The other half: on an overdue profile, completing takes the chore off the list.

    Completing reschedules the task a day out, so the profile no longer selects it —
    and a sync only holds what its profile currently wants. That is the same rule
    as disabling a task or filtering it out, and it is why a household that wants the
    done line kept gives the syncing profile an "all" filter.
    """
    task_id = _add_probe(ha, "D")
    name = f"{PROBE} D"
    assert _poll(lambda: _find(ha, name, ["needs_action"])), "expected the synced item"

    _call(ha, "complete_task", {"task_id": task_id})

    assert _poll(lambda: name not in _summaries(ha)), (
        "a task the sync no longer wants should have its line taken off the list"
    )


def test_ticking_the_item_off_completes_the_task(ha, synced):
    """Inbound: the loop closes from the household's list, marked as the sync's.

    This is the half no amount of unit testing reaches — a tick lands on somebody
    else's ``todo`` entity, and Home Keeper has to notice it, record a completion,
    and stamp it with an origin an automation can tell apart from a tap on Done.
    """
    task_id = _add_probe(ha, "C")
    name = f"{PROBE} C"
    item = _poll(lambda: _find(ha, name, ["needs_action"]))
    assert item, "expected the synced item"

    # Park the sentinel first: it holds the *last* completion's origin, so a value
    # left by an earlier run would let the assertion below pass without this tick
    # ever reaching the store.
    call_service(
        ha, "input_text", "set_value", {"entity_id": ORIGIN_SENTINEL, "value": "unset"}
    )

    # Tick it off the way the household would — on their own list, not in the panel.
    call_service(
        ha,
        "todo",
        "update_item",
        {"entity_id": SYNC_LIST, "item": item["uid"], "status": "completed"},
    )

    assert _poll(lambda: (_get_task(ha, task_id) or {}).get("last_completed")), (
        "ticking the item off should have completed the Home Keeper task"
    )
    task = _get_task(ha, task_id)
    assert len(task["completions"]) == 1, "the tick belongs in the completion history"

    # The completion event says where it came from, which is what lets an
    # automation (or another sync) tell a remote tick from a tap on Done.
    poll_state(ha, ORIGIN_SENTINEL, lambda s: s == ORIGIN_TODO_SYNC, timeout=60)


def test_clearing_the_list_takes_the_profiles_lines_back_off(ha, synced):
    """Clearing the picker is the off switch *and* the delete, in one gesture.

    Worth a case of its own because it is the whole shape of the new model. There is
    no sync record to delete, so "stop syncing" is a save of the same profile with
    an empty ``entity_id`` — and that save has to take the open lines with it, or a
    household would be left with chores stranded on a list nothing updates any more.
    The profile itself must survive: they cleared a list, not a saved filter.
    """
    _add_probe(ha, "E")
    name = f"{PROBE} E"
    assert _poll(lambda: _find(ha, name, ["needs_action"])), "expected the synced item"

    # Exactly what the panel writes when the To-do list field is cleared: the same
    # profiles list, with this one's sync target emptied.
    _set_options(
        ha,
        {
            "profiles": [
                {**p, "sync": {**p["sync"], "entity_id": ""}}
                if p["id"] == DUE_NOW_PROFILE["id"]
                else p
                for p in _saved_profiles(ha)
            ]
        },
    )

    assert _poll(lambda: name not in _summaries(ha, ["needs_action"])), (
        "clearing the picker should have taken the profile's open lines off the list"
    )

    # The filter the household saved is still theirs — only the sync went off.
    after = _saved_profile(ha, DUE_NOW_PROFILE["id"])
    assert after is not None, "clearing the list must not delete the profile"
    assert after["sync"]["entity_id"] == ""
    assert after["filter"]["status"] == DUE_NOW_PROFILE["filter"]["status"]
