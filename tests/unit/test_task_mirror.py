"""Unit tests for the pure task-mirror planner (``task_mirror.py``).

A task mirror *is* a profile: the ``sync`` block on a profile names the external
to-do list its tasks are kept in step with, and clearing that entity is the off
switch. The planner decides, from four inputs — what each profile mirrored last
pass, which tasks it wants there now, what is actually on the lists, and which
optional fields those lists can hold — what to add, update, remove, and which
tasks the household has ticked off for us. Every branch is exercised here without
a Home Assistant runtime; ``task_mirror_sync.py`` (the driver that reads the lists
and applies the plan) has its own suite. The ``sync`` block's own coercion rules
live with the rest of the profile, in ``test_profiles.py``.
"""

from datetime import datetime, timedelta, timezone

import hk_profiles as profiles
import hk_task_mirror as tm

LIST = "todo.family"
OTHER = "todo.chores"
GHOST = "todo.gone"

M1 = "m1"
M2 = "m2"
T1 = "t1"
KEY = tm.mirror_key(M1, T1)

NAME = "Change the filter"
DUE = "2026-06-14"

# 09:00 on the 15th, in the household's own offset.
NOW = datetime(2026, 6, 15, 9, 0, tzinfo=timezone(timedelta(hours=-4)))
OVERDUE_ISO = "2026-06-14T09:00:00-04:00"
SOON_ISO = "2026-06-17T09:00:00-04:00"
FAR_ISO = "2026-09-14T09:00:00-04:00"
DONE_ISO = "2026-06-15T08:00:00-04:00"
OLD_ISO = "2026-05-01T08:00:00-04:00"

BOTH = frozenset({tm.CAP_DUE_DATE, tm.CAP_DESCRIPTION})
CAPS = {LIST: BOTH, OTHER: BOTH, GHOST: BOTH}


# ── fixtures ──────────────────────────────────────────────────────────────────


def _mirror(mid=M1, entity_id=LIST, filt=None, **sync):
    """A profile mirroring onto *entity_id* — the whole of what a mirror is now.

    No *filt* means the profile's own default: every enabled, scheduled task that
    is overdue.
    """
    return profiles.normalize_profile(
        {
            "id": mid,
            "name": mid,
            "filter": filt or {},
            "sync": {"entity_id": entity_id, **sync},
        }
    )


def _task(tid=T1, name=NAME, due=OVERDUE_ISO, **extra):
    """An ordinary, enabled, overdue task as the driver hands it over."""
    return {
        "id": tid,
        "name": name,
        "next_due": due,
        "last_completed": None,
        "enabled": True,
        "notes": "",
        **extra,
    }


def _want(tid=T1, name=NAME, due=DUE, notes="", last_completed=None):
    return {
        "task_id": tid,
        "name": name,
        "due": due,
        "notes": notes,
        "last_completed": last_completed,
    }


def _desired(wants, profile_id=M1):
    """``{profile_id: {task_id: want}}`` for one mirror."""
    return {profile_id: {want["task_id"]: want for want in wants}}


def _item(summary=NAME, uid="i1", status=tm.STATUS_NEEDS_ACTION, **extra):
    """A list item already in step with what we wanted, unless *extra* says so."""
    return {
        "uid": uid,
        "summary": summary,
        "status": status,
        "due": DUE,
        "description": "",
        **extra,
    }


def _entry(entity_id=LIST, uid="i1", summary=NAME, due=DUE, last_completed=None):
    return {
        "entity_id": entity_id,
        "uid": uid,
        "summary": summary,
        "due": due,
        "last_completed": last_completed,
    }


def _tracked(entry=None, key=KEY):
    return {key: _entry() if entry is None else entry}


def _plan(
    *, mirrors=None, tracked=None, desired=None, items=None, lists=None, caps=None
):
    """Run one pass. *items* is LIST's contents (None = unreadable list)."""
    if lists is None:
        lists = {} if items is None else {LIST: items}
    return tm.plan_sync(
        mirrors=[_mirror()] if mirrors is None else mirrors,
        tracked=tracked or {},
        desired=desired or {},
        items_by_entity=lists,
        capabilities=CAPS if caps is None else caps,
    )


# ── mirror_key ────────────────────────────────────────────────────────────────


def test_mirror_key_names_one_task_on_one_profiles_list():
    assert tm.mirror_key("m1", "t1") == "m1:t1"
    # The first colon splits it, so a task id may hold one of its own.
    assert tm.mirror_key("m1", "t:1").partition(":")[2] == "t:1"


# ── completed_since ───────────────────────────────────────────────────────────


def test_completed_since_reads_a_first_completion_against_no_snapshot():
    assert tm.completed_since(None, DONE_ISO) is True
    assert tm.completed_since("", DONE_ISO) is True


def test_completed_since_is_false_for_the_very_same_instant():
    assert tm.completed_since(DONE_ISO, DONE_ISO) is False


def test_completed_since_notices_a_newer_completion():
    assert tm.completed_since("2026-06-15T08:00:00-04:00", "2026-06-15T08:00:01-04:00")


def test_completed_since_reads_an_undone_completion_as_no_completion():
    # Undo moves the value backwards, or clears it: the item stays open.
    assert tm.completed_since(DONE_ISO, "2026-05-01T08:00:00-04:00") is False
    assert tm.completed_since(DONE_ISO, None) is False
    assert tm.completed_since(None, None) is False


def test_completed_since_compares_instants_rather_than_text():
    # One moment, two spellings: a change of offset is not a completion…
    assert tm.completed_since("2026-06-15T12:00:00+00:00", DONE_ISO) is False
    # …and a later completion is caught even when its text sorts earlier.
    assert tm.completed_since("2026-06-15T12:00:00+00:00", "2026-06-15T09:00:00-04:00")


def test_completed_since_refuses_to_guess_from_anything_unparsable():
    assert tm.completed_since(None, "whenever") is False
    assert tm.completed_since("rubbish", DONE_ISO) is False
    assert tm.completed_since(None, "") is False
    # A naive stamp cannot be ordered against an aware one, so it says nothing.
    assert tm.completed_since(DONE_ISO, "2026-06-16T09:00:00") is False


# ── desired_by_mirror ─────────────────────────────────────────────────────────


def test_desired_by_mirror_selects_what_its_profile_surfaces():
    # The skipped tasks come first on purpose: skipping one must not stop the
    # walk before it reaches the task that belongs on the list.
    tasks = [
        _task("off", name="Disabled", enabled=False),
        _task("dormant", name="Dormant", due=None),
        # A synced problem sensor belongs to the Profile (#248) but not on a to-do
        # list: only the integration that owns the sensor can mark it done, so an
        # item for it could never be ticked off. Keyed off the same
        # ``managed_by.completion_blocked`` the panel and notification buttons read.
        _task(
            "sensor",
            name="Leak detected",
            source={"problem_sensor": {"entity_id": "binary_sensor.leak"}},
            managed_by={"integration": "home_keeper", "completion_blocked": True},
        ),
        _task(
            "buy",
            name="Buy anode rod",
            source={"buy": {"asset_id": "a1", "part_id": "p1"}},
        ),
        _task("blank", name="   "),
        _task("nameless", name=None),
        _task("soon", name="Descale", due=SOON_ISO),
        _task("later", name="Service the boiler", due=FAR_ISO),
        _task("due", notes="Under the sink"),
    ]
    assert tm.desired_by_mirror([_mirror()], tasks, now=NOW) == {
        M1: {
            "due": {
                "task_id": "due",
                "name": NAME,
                "due": DUE,
                "notes": "Under the sink",
                "last_completed": None,
            }
        }
    }


def test_desired_by_mirror_takes_its_timing_from_the_profiles_own_status():
    tasks = [_task("due"), _task("soon", due=SOON_ISO), _task("later", due=FAR_ISO)]
    soon = tm.desired_by_mirror([_mirror(filt={"status": "due_soon"})], tasks, now=NOW)
    assert sorted(soon[M1]) == ["due", "soon"]
    every = tm.desired_by_mirror([_mirror(filt={"status": "all"})], tasks, now=NOW)
    assert sorted(every[M1]) == ["due", "later", "soon"]


def test_desired_by_mirror_applies_a_profiles_other_filters_too():
    mirrors = [_mirror(filt={"status": "all", "areas": ["kitchen"]})]
    tasks = [_task("in", area_id="kitchen"), _task("out", area_id="garage")]
    assert sorted(tm.desired_by_mirror(mirrors, tasks, now=NOW)[M1]) == ["in"]


def test_desired_by_mirror_honours_a_widened_due_soon_window():
    mirrors = [_mirror(filt={"status": "due_soon"})]
    tasks = [_task("later", due=FAR_ISO)]
    assert tm.desired_by_mirror(mirrors, tasks, now=NOW) == {M1: {}}
    wide = tm.desired_by_mirror(mirrors, tasks, now=NOW, window=timedelta(days=120))
    assert sorted(wide[M1]) == ["later"]


def test_desired_by_mirror_tidies_the_summary_it_will_put_on_the_list():
    wanted = tm.desired_by_mirror([_mirror()], [_task(name=f"  {NAME}  ")], now=NOW)
    assert wanted[M1][T1]["name"] == NAME


def test_desired_by_mirror_reduces_a_due_instant_to_the_date_a_list_holds():
    task = _task(due="2026-06-14T23:30:00-04:00")
    wanted = tm.desired_by_mirror([_mirror()], [task], now=NOW)
    assert wanted[M1][T1]["due"] == DUE


def test_desired_by_mirror_carries_a_task_without_notes_as_an_empty_description():
    task = _task()
    del task["notes"]
    wanted = tm.desired_by_mirror([_mirror()], [task], now=NOW)
    assert wanted[M1][T1]["notes"] == ""


def test_desired_by_mirror_carries_the_completion_stamp_it_binds_against():
    task = _task(last_completed=DONE_ISO)
    wanted = tm.desired_by_mirror([_mirror()], [task], now=NOW)
    assert wanted[M1][T1]["last_completed"] == DONE_ISO


def test_desired_by_mirror_skips_a_profile_whose_sync_is_switched_off():
    # A cleared picker is the off switch, so the profile is left out of the wanted
    # map altogether — which is also how the planner knows to tidy its list.
    mirrors = [_mirror(entity_id=""), _mirror(mid=M2)]
    wanted = tm.desired_by_mirror(mirrors, [_task()], now=NOW)
    assert sorted(wanted) == [M2]


def test_desired_by_mirror_gives_each_profile_its_own_selection():
    mirrors = [
        _mirror(),
        _mirror(mid=M2, entity_id=OTHER, filt={"status": "all"}),
    ]
    tasks = [_task("due"), _task("later", due=FAR_ISO)]
    wanted = tm.desired_by_mirror(mirrors, tasks, now=NOW)
    assert sorted(wanted[M1]) == ["due"]
    assert sorted(wanted[M2]) == ["due", "later"]


# ── putting a chore on the list ───────────────────────────────────────────────


def test_a_due_task_with_no_item_yet_is_added_to_the_list():
    plan = _plan(desired=_desired([_want(notes="Under the sink")]), items=[])
    assert plan.add == [
        tm.AddOp(KEY, LIST, NAME, due=DUE, description="Under the sink")
    ]
    assert plan.tracked == {
        KEY: {
            "entity_id": LIST,
            "uid": None,
            "summary": NAME,
            "due": DUE,
            "last_completed": None,
        }
    }
    assert plan.update == [] and plan.remove == [] and plan.complete == []


def test_a_list_that_holds_neither_extra_is_told_neither():
    # A list without due dates would otherwise be told one it silently drops.
    plan = _plan(
        desired=_desired([_want(notes="Under the sink")]), items=[], caps={LIST: BOTH}
    )
    assert plan.add == [
        tm.AddOp(KEY, LIST, NAME, due=DUE, description="Under the sink")
    ]
    bare = _plan(desired=_desired([_want(notes="Under the sink")]), items=[], caps={})
    assert bare.add == [tm.AddOp(KEY, LIST, NAME, due=None, description=None)]


def test_a_task_with_no_notes_is_added_without_a_description():
    plan = _plan(desired=_desired([_want()]), items=[])
    assert plan.add == [tm.AddOp(KEY, LIST, NAME, due=DUE, description=None)]


def test_the_next_pass_binds_the_uid_of_the_item_it_added():
    # ``todo.add_item`` answers with nothing, so the uid is captured by summary.
    plan = _plan(
        tracked=_tracked(_entry(uid=None)),
        desired=_desired([_want()]),
        items=[_item(uid="captured")],
    )
    assert plan.add == [] and plan.update == [] and plan.remove == []
    assert plan.complete == []
    assert plan.tracked == {
        KEY: {
            "entity_id": LIST,
            "uid": "captured",
            "summary": NAME,
            "due": DUE,
            "last_completed": None,
        }
    }


def test_an_open_item_already_reading_the_same_is_adopted():
    plan = _plan(desired=_desired([_want()]), items=[_item(uid="theirs")])
    assert plan.add == []
    assert plan.tracked == {KEY: _entry(uid="theirs")}


def test_a_ticked_off_lookalike_is_never_adopted():
    # Last month's line, already done, must not stand in for this month's chore.
    plan = _plan(
        desired=_desired([_want()]),
        items=[_item(uid="old", status=tm.STATUS_COMPLETED)],
    )
    assert plan.add == [tm.AddOp(KEY, LIST, NAME, due=DUE)]
    assert plan.tracked == {KEY: _entry(uid=None)}


# ── keeping a mirrored chore in step ──────────────────────────────────────────


def test_an_item_that_still_says_the_right_thing_is_left_alone():
    plan = _plan(
        tracked=_tracked(),
        desired=_desired([_want(notes="Under the sink")]),
        items=[_item(description="Under the sink")],
    )
    assert plan.add == [] and plan.update == [] and plan.remove == []
    assert plan.complete == []
    assert plan.tracked == _tracked()


def test_a_rename_a_new_date_and_new_notes_are_one_update():
    plan = _plan(
        tracked=_tracked(),
        desired=_desired(
            [_want(name="Change the water filter", due="2026-07-01", notes="Under it")]
        ),
        items=[_item()],
    )
    assert plan.update == [
        tm.UpdateOp(
            KEY,
            LIST,
            "i1",
            rename="Change the water filter",
            due="2026-07-01",
            description="Under it",
        )
    ]
    assert plan.remove == [] and plan.add == [] and plan.complete == []
    assert plan.tracked == {
        KEY: {
            "entity_id": LIST,
            "uid": "i1",
            "summary": "Change the water filter",
            "due": "2026-07-01",
            "last_completed": None,
        }
    }


def test_a_due_date_a_list_cannot_hold_is_never_diffed():
    # The churn guard: diffing a field the list drops would rewrite the same
    # item on every pass, forever.
    plan = _plan(
        tracked=_tracked(),
        desired=_desired([_want(due="2026-07-01")]),
        items=[_item(due=None)],
        caps={LIST: frozenset()},
    )
    assert plan.update == []
    # The bookkeeping still records what we wanted, so needs_pass stays quiet.
    assert plan.tracked[KEY]["due"] == "2026-07-01"
    # A list we could not read the capabilities of is read as holding neither.
    unknown = _plan(
        tracked=_tracked(),
        desired=_desired([_want(due="2026-07-01")]),
        items=[_item(due=None)],
        caps={},
    )
    assert unknown.update == []


def test_a_description_a_list_cannot_hold_is_never_diffed():
    plan = _plan(
        tracked=_tracked(),
        desired=_desired([_want(notes="Under the sink")]),
        items=[_item(description=None)],
        caps={LIST: frozenset({tm.CAP_DUE_DATE})},
    )
    assert plan.update == []


def test_an_items_due_datetime_is_compared_as_the_date_we_asked_for():
    # Some providers answer with a datetime; only the date half is ours.
    plan = _plan(
        tracked=_tracked(),
        desired=_desired([_want()]),
        items=[_item(due="2026-06-14T00:00:00+00:00")],
    )
    assert plan.update == []


def test_notes_cleared_in_home_keeper_clear_the_items_description():
    plan = _plan(
        tracked=_tracked(),
        desired=_desired([_want()]),
        items=[_item(description="Under the sink")],
    )
    assert plan.update == [tm.UpdateOp(KEY, LIST, "i1", description="")]


# ── the household's side ──────────────────────────────────────────────────────


def test_ticking_the_item_off_completes_the_task():
    plan = _plan(
        tracked=_tracked(),
        desired=_desired([_want()]),
        items=[_item(status=tm.STATUS_COMPLETED)],
    )
    assert plan.complete == [tm.CompleteOp(KEY, T1)]
    # The line they ticked is left as it is, and no second copy goes back on the
    # list while Home Keeper catches up.
    assert plan.add == [] and plan.update == [] and plan.remove == []
    assert plan.tracked == {}


def test_a_one_way_mirror_never_completes_a_task_from_a_tick():
    tracked = _tracked()
    plan = _plan(
        mirrors=[_mirror(two_way=False)],
        tracked=tracked,
        desired=_desired([_want()]),
        items=[_item(status=tm.STATUS_COMPLETED)],
    )
    # Frozen, not forgotten: still being tracked is what stops the chore going
    # straight back on the list and arguing with whoever ticked it off.
    assert plan.complete == [] and plan.add == []
    assert plan.update == [] and plan.remove == []
    assert plan.tracked == tracked


def test_a_frozen_entry_is_released_once_its_task_stops_being_mirrored():
    plan = _plan(
        mirrors=[_mirror(two_way=False)],
        tracked=_tracked(),
        desired={M1: {}},
        items=[_item(status=tm.STATUS_COMPLETED)],
    )
    assert plan.tracked == {}
    assert plan.complete == [] and plan.remove == [] and plan.update == []


def test_a_tick_home_keeper_already_knows_about_is_not_sent_back():
    # Home Keeper completed the task first, so the ticked line is only the
    # record of that and nothing travels back inbound. The task is due again,
    # so the next one goes on the list beside it.
    plan = _plan(
        tracked=_tracked(),
        desired=_desired([_want(due="2026-09-14", last_completed=DONE_ISO)]),
        items=[_item(status=tm.STATUS_COMPLETED)],
    )
    assert plan.complete == [] and plan.update == [] and plan.remove == []
    assert plan.add == [tm.AddOp(KEY, LIST, NAME, due="2026-09-14")]
    assert plan.tracked == {
        KEY: _entry(uid=None, due="2026-09-14", last_completed=DONE_ISO)
    }


# ── completed inside Home Keeper ──────────────────────────────────────────────


def test_a_completion_older_than_the_binding_is_not_a_new_completion():
    # The task was last done before this item ever went on the list, so the
    # stamp the entry was bound against *is* that completion, not a newer one.
    entry = _entry(last_completed=OLD_ISO)
    want = _want(last_completed=OLD_ISO)
    settled = _plan(tracked={KEY: entry}, desired=_desired([want]), items=[_item()])
    assert settled.update == [] and settled.add == [] and settled.complete == []
    assert settled.tracked == {KEY: entry}
    # …and a tick on that same item is still someone completing it now.
    ticked = _plan(
        tracked={KEY: entry},
        desired=_desired([want]),
        items=[_item(status=tm.STATUS_COMPLETED)],
    )
    assert ticked.complete == [tm.CompleteOp(KEY, T1)]


def test_completing_the_task_ticks_the_item_off_and_the_next_one_is_fresh():
    # A mirror on an "all" profile still wants the task: completing a recurring
    # chore schedules it again. The ticked-off line stays as the record and the
    # new one goes on beside it — the history a to-do list is for.
    plan = _plan(
        tracked=_tracked(),
        desired=_desired([_want(due="2026-09-14", last_completed=DONE_ISO)]),
        items=[_item()],
    )
    assert plan.update == [tm.UpdateOp(KEY, LIST, "i1", status=tm.STATUS_COMPLETED)]
    assert plan.add == [tm.AddOp(KEY, LIST, NAME, due="2026-09-14")]
    assert plan.remove == [] and plan.complete == []
    assert plan.tracked == {
        KEY: {
            "entity_id": LIST,
            "uid": None,
            "summary": NAME,
            "due": "2026-09-14",
            "last_completed": DONE_ISO,
        }
    }


def test_completing_a_task_that_is_done_for_good_only_ticks_the_item_off():
    plan = _plan(
        tracked=_tracked(),
        desired={M1: {}},
        items=[_item()],
    )
    assert plan.remove == [tm.RemoveOp(KEY, LIST, "i1")]
    assert plan.tracked == {}


def test_an_undone_completion_reads_as_drift_and_never_as_a_tick():
    plan = _plan(
        tracked=_tracked(_entry(due="2026-09-14", last_completed=DONE_ISO)),
        desired=_desired([_want(due=DUE, last_completed=None)]),
        items=[_item(due="2026-09-14")],
    )
    assert plan.complete == [] and plan.remove == []
    assert plan.update == [tm.UpdateOp(KEY, LIST, "i1", due=DUE)]
    assert plan.tracked == {KEY: _entry()}


# ── an item that is simply gone ───────────────────────────────────────────────


def test_a_vanished_item_completes_the_task_when_the_mirror_opted_in():
    # Todoist's todo entity drops a completed item rather than reporting it, so
    # for a mirror that opted in this is how a tick reaches Home Keeper at all.
    plan = _plan(tracked=_tracked(), desired=_desired([_want()]), items=[])
    assert plan.complete == [tm.CompleteOp(KEY, T1)]
    assert plan.add == [] and plan.remove == [] and plan.update == []
    assert plan.tracked == {}


def test_a_vanished_item_we_never_confirmed_is_re_added_not_completed():
    # No uid means no proof our add ever landed, and completing a task on the
    # strength of a write we cannot confirm is the one mistake with no undo.
    plan = _plan(
        tracked=_tracked(_entry(uid=None)), desired=_desired([_want()]), items=[]
    )
    assert plan.complete == []
    assert plan.add == [tm.AddOp(KEY, LIST, NAME, due=DUE)]
    assert plan.tracked == {KEY: _entry(uid=None)}


def test_a_vanished_item_is_re_added_when_the_mirror_reads_deletion_as_deletion():
    plan = _plan(
        mirrors=[_mirror(vanish_as_completed=False)],
        tracked=_tracked(),
        desired=_desired([_want()]),
        items=[],
    )
    assert plan.complete == []
    assert plan.add == [tm.AddOp(KEY, LIST, NAME, due=DUE)]


def test_a_vanished_item_is_re_added_when_the_mirror_is_one_way():
    plan = _plan(
        mirrors=[_mirror(two_way=False)],
        tracked=_tracked(),
        desired=_desired([_want()]),
        items=[],
    )
    assert plan.complete == []
    assert plan.add == [tm.AddOp(KEY, LIST, NAME, due=DUE)]


def test_a_vanished_item_whose_task_stopped_matching_is_simply_forgotten():
    plan = _plan(tracked=_tracked(), desired={M1: {}}, items=[])
    assert plan.complete == [] and plan.add == [] and plan.remove == []
    assert plan.tracked == {}


# ── a task that stopped being mirrored ────────────────────────────────────────


def test_a_task_that_stopped_matching_has_its_open_item_removed():
    plan = _plan(tracked=_tracked(), desired={M1: {}}, items=[_item()])
    assert plan.remove == [tm.RemoveOp(KEY, LIST, "i1")]
    assert plan.add == [] and plan.update == [] and plan.complete == []
    assert plan.tracked == {}


def test_a_task_that_stopped_matching_leaves_a_ticked_off_item_as_the_record():
    plan = _plan(
        tracked=_tracked(),
        desired={M1: {}},
        items=[_item(status=tm.STATUS_COMPLETED)],
    )
    assert plan.remove == [] and plan.update == [] and plan.complete == []
    assert plan.tracked == {}


# ── moving, switching off, deleting ───────────────────────────────────────────


def test_pointing_a_mirror_at_another_list_moves_the_chore():
    plan = _plan(
        tracked=_tracked(_entry(entity_id=OTHER)),
        desired=_desired([_want()]),
        lists={OTHER: [_item()], LIST: []},
    )
    assert plan.remove == [tm.RemoveOp(KEY, OTHER, "i1")]
    assert plan.add == [tm.AddOp(KEY, LIST, NAME, due=DUE)]
    assert plan.tracked == {KEY: _entry(uid=None)}


def test_deleting_a_mirror_clears_what_it_wrote():
    # Turning a mirror off clears its chores: leaving them behind strands them
    # on a list nothing updates any more.
    plan = _plan(mirrors=[], tracked=_tracked(), desired={}, items=[_item()])
    assert plan.remove == [tm.RemoveOp(KEY, LIST, "i1")]
    assert plan.add == [] and plan.complete == []
    assert plan.tracked == {}


def test_clearing_a_mirrors_list_clears_what_it_wrote():
    plan = _plan(
        mirrors=[_mirror(entity_id="")],
        tracked=_tracked(),
        desired={},
        items=[_item()],
    )
    assert plan.remove == [tm.RemoveOp(KEY, LIST, "i1")]
    assert plan.tracked == {}


def test_a_deleted_mirror_leaves_a_ticked_off_item_as_the_record():
    plan = _plan(
        mirrors=[],
        tracked=_tracked(),
        desired={},
        items=[_item(status=tm.STATUS_COMPLETED)],
    )
    assert plan.remove == [] and plan.update == [] and plan.complete == []
    assert plan.tracked == {}


def test_a_deleted_mirror_forgets_an_item_that_is_already_gone():
    plan = _plan(mirrors=[], tracked=_tracked(), desired={}, items=[])
    assert plan.remove == [] and plan.complete == []
    assert plan.tracked == {}


def test_a_deleted_mirror_finds_its_line_by_uid_after_someone_renamed_it():
    plan = _plan(
        mirrors=[],
        tracked=_tracked(),
        desired={},
        items=[_item(summary="Filter (renamed by hand)")],
    )
    assert plan.remove == [tm.RemoveOp(KEY, LIST, "i1")]


def test_two_deleted_entries_reading_the_same_never_clear_one_line_twice():
    plan = _plan(
        mirrors=[],
        tracked={"m5:a": _entry(uid=None), "m6:a": _entry(uid=None)},
        desired={},
        items=[_item(uid="only")],
    )
    assert plan.remove == [tm.RemoveOp("m5:a", LIST, "only")]
    assert plan.tracked == {}


# ── lists we could not see, and mirrors we could not plan ─────────────────────


def test_an_unreadable_list_is_left_strictly_alone():
    # Unreadable is not empty: a to-do integration that failed to load must not
    # make the mirror forget what it put there.
    tracked = _tracked()
    plan = _plan(tracked=tracked, desired=_desired([_want()]), items=None)
    assert plan.add == [] and plan.remove == []
    assert plan.update == [] and plan.complete == []
    assert plan.tracked == tracked


def test_an_unreadable_list_is_left_alone_while_tidying_up_too():
    tracked = _tracked()
    plan = _plan(mirrors=[], tracked=tracked, desired={}, items=None)
    assert plan.remove == [] and plan.complete == []
    assert plan.tracked == tracked


def test_an_entry_naming_a_list_nobody_read_is_carried_forward():
    tracked = _tracked(_entry(entity_id=GHOST))
    plan = _plan(tracked=tracked, desired=_desired([_want()]), items=[_item()])
    assert plan.remove == [] and plan.update == []
    assert plan.tracked[KEY] == tracked[KEY]


def test_a_chore_moved_onto_a_list_nobody_could_read_still_leaves_the_old_one():
    # Half a move: the old line comes off, and the new one waits for a pass that
    # can actually see where it is going.
    plan = _plan(
        mirrors=[_mirror(entity_id=GHOST)],
        tracked=_tracked(),
        desired=_desired([_want()]),
        lists={LIST: [_item()]},
    )
    assert plan.remove == [tm.RemoveOp(KEY, LIST, "i1")]
    assert plan.add == [] and plan.tracked == {}


def test_a_wanted_mirror_that_is_not_configured_at_all_is_skipped():
    plan = _plan(desired={"ghost": {T1: _want()}, M1: {T1: _want()}}, items=[])
    assert plan.add == [tm.AddOp(KEY, LIST, NAME, due=DUE)]
    assert sorted(plan.tracked) == [KEY]


def test_one_unreadable_list_does_not_stop_another_mirror_being_planned():
    plan = _plan(
        mirrors=[_mirror(), _mirror(mid=M2, entity_id=OTHER)],
        desired={M1: {T1: _want()}, M2: {T1: _want()}},
        lists={OTHER: []},
    )
    assert plan.add == [tm.AddOp(tm.mirror_key(M2, T1), OTHER, NAME, due=DUE)]


# ── several mirrors, one list ─────────────────────────────────────────────────


def test_two_mirrors_hold_the_same_task_on_two_lists():
    plan = _plan(
        mirrors=[_mirror(), _mirror(mid=M2, entity_id=OTHER)],
        desired={M1: {T1: _want()}, M2: {T1: _want()}},
        lists={LIST: [], OTHER: []},
    )
    assert plan.add == [
        tm.AddOp("m1:t1", LIST, NAME, due=DUE),
        tm.AddOp("m2:t1", OTHER, NAME, due=DUE),
    ]
    assert plan.tracked["m1:t1"]["entity_id"] == LIST
    assert plan.tracked["m2:t1"]["entity_id"] == OTHER


def test_two_mirrors_on_one_list_never_share_a_line():
    plan = _plan(
        mirrors=[_mirror(), _mirror(mid=M2)],
        desired={M1: {T1: _want()}, M2: {T1: _want()}},
        items=[_item(uid="only")],
    )
    # The first adopts the line that is there; the second gets one of its own.
    assert plan.add == [tm.AddOp("m2:t1", LIST, NAME, due=DUE)]
    assert plan.tracked["m1:t1"]["uid"] == "only"
    assert plan.tracked["m2:t1"]["uid"] is None


def test_two_tasks_reading_the_same_never_share_a_line():
    plan = _plan(
        tracked={"m1:t1": _entry(uid=None), "m1:t2": _entry(uid=None)},
        desired={M1: {T1: _want(), "t2": _want(tid="t2")}},
        items=[_item(uid="only")],
    )
    assert plan.tracked["m1:t1"]["uid"] == "only"
    assert plan.tracked["m1:t2"]["uid"] is None
    assert plan.add == [tm.AddOp("m1:t2", LIST, NAME, due=DUE)]


# ── which list item a tracked entry points at ─────────────────────────────────


def test_the_uid_wins_over_a_lookalike_summary():
    plan = _plan(
        tracked=_tracked(),
        desired={M1: {}},
        items=[
            _item(uid="other"),
            _item(uid="i1", summary="Change the filter (renamed by hand)"),
        ],
    )
    assert plan.remove == [tm.RemoveOp(KEY, LIST, "i1")]


def test_a_uid_that_no_longer_exists_falls_back_to_the_summary():
    plan = _plan(
        tracked=_tracked(_entry(uid="gone")),
        desired={M1: {}},
        items=[_item(uid="fresh")],
    )
    assert plan.remove == [tm.RemoveOp(KEY, LIST, "fresh")]


def test_an_open_item_wins_over_a_ticked_off_one_reading_the_same():
    plan = _plan(
        tracked=_tracked(_entry(uid=None)),
        desired={M1: {}},
        items=[_item(uid="old", status=tm.STATUS_COMPLETED), _item(uid="live")],
    )
    assert plan.remove == [tm.RemoveOp(KEY, LIST, "live")]


def test_a_ticked_off_item_is_matched_when_it_is_the_only_one():
    # The tick we are looking for is on the line we added, so falling through to
    # it is what closes the loop.
    plan = _plan(
        tracked=_tracked(_entry(uid=None)),
        desired=_desired([_want()]),
        items=[_item(uid="old", status=tm.STATUS_COMPLETED)],
    )
    assert plan.complete == [tm.CompleteOp(KEY, T1)]


def test_an_item_with_no_uid_at_all_is_addressed_by_its_text():
    plan = _plan(
        tracked=_tracked(_entry(uid=None)),
        desired={M1: {}},
        items=[{"summary": NAME, "status": tm.STATUS_NEEDS_ACTION}],
    )
    assert plan.remove == [tm.RemoveOp(KEY, LIST, NAME)]
    # "" is the absence of a uid, not a uid, so it is addressed by text too.
    blank = _plan(
        tracked=_tracked(_entry(uid=None)),
        desired={M1: {}},
        items=[_item(uid="")],
    )
    assert blank.remove == [tm.RemoveOp(KEY, LIST, NAME)]


def test_a_uid_we_hold_outlives_a_response_that_stopped_reporting_one():
    # Some providers answer without uids. Forgetting ours would throw away the
    # binding we have, so the item's uid only replaces it when there is one.
    plan = _plan(
        tracked=_tracked(),
        desired=_desired([_want()]),
        items=[{"summary": NAME, "status": tm.STATUS_NEEDS_ACTION, "due": DUE}],
    )
    assert plan.update == []
    assert plan.tracked == {KEY: _entry(uid="i1")}


def test_a_task_id_with_a_colon_of_its_own_still_finds_its_mirror():
    # Only the first colon separates the two halves of a key: task ids are
    # opaque and may well hold one.
    key = tm.mirror_key(M1, "t:1")
    desired = {M1: {"t:1": _want(tid="t:1")}}
    plan = _plan(tracked={key: _entry()}, desired=desired, items=[_item()])
    assert plan.remove == [] and plan.update == [] and plan.add == []
    assert plan.tracked == {key: _entry()}
    assert (
        tm.needs_pass(tracked={key: _entry()}, desired=desired, mirrors=[_mirror()])
        is False
    )


def test_a_blank_uid_is_the_absence_of_a_uid_on_both_sides():
    # "" is not a uid to match on: matching it would bind the entry to whichever
    # unrelated item also lacks one.
    plan = _plan(
        tracked=_tracked(_entry(uid="")),
        desired={M1: {}},
        items=[_item(uid="", summary="Something else"), _item(uid="x")],
    )
    assert plan.remove == [tm.RemoveOp(KEY, LIST, "x")]


# ── lists_to_read ─────────────────────────────────────────────────────────────


def test_lists_to_read_covers_every_mirror_and_everything_still_held():
    tracked = {
        "m1:t1": _entry(entity_id=OTHER),
        "m1:t2": _entry(entity_id=LIST),
        "m2:t1": _entry(entity_id=LIST),
    }
    mirrors = [_mirror(), _mirror(mid=M2, entity_id="")]
    assert tm.lists_to_read(tracked, mirrors) == [OTHER, LIST]


def test_lists_to_read_still_names_a_list_a_deleted_mirror_left_behind():
    # Deleting a mirror must not blind the next pass to the list it has to tidy.
    assert tm.lists_to_read({"m1:t1": _entry(entity_id=OTHER)}, []) == [OTHER]
    assert tm.lists_to_read({}, []) == []
    assert tm.lists_to_read({}, [_mirror()]) == [LIST]


def test_lists_to_read_says_nothing_about_an_entry_with_no_list_of_its_own():
    assert tm.lists_to_read({"m1:t1": {"summary": NAME}}, []) == []
    assert tm.lists_to_read({"m1:t1": {"entity_id": ""}}, []) == []


# ── needs_pass ────────────────────────────────────────────────────────────────


def _needs(tracked=None, desired=None, mirrors=None):
    return tm.needs_pass(
        tracked=tracked or {},
        desired=desired or {},
        mirrors=[_mirror()] if mirrors is None else mirrors,
    )


def test_needs_pass_is_false_for_a_settled_mirror():
    # The common case: nothing changed, so no to-do list is read at all.
    assert _needs(tracked=_tracked(), desired=_desired([_want()])) is False
    assert _needs() is False
    # Including one whose task was last done before it was ever mirrored: the
    # stamp it is bound against is that completion, not a newer one.
    old = _desired([_want(last_completed=OLD_ISO)])
    assert _needs(tracked={KEY: _entry(last_completed=OLD_ISO)}, desired=old) is False


def test_needs_pass_notices_a_task_that_started_matching():
    assert _needs(desired=_desired([_want()])) is True


def test_needs_pass_notices_a_task_that_stopped_matching():
    assert _needs(tracked=_tracked(), desired={M1: {}}) is True


def test_needs_pass_notices_a_rename():
    renamed = _desired([_want(name="Change the water filter")])
    assert _needs(tracked=_tracked(), desired=renamed) is True


def test_needs_pass_notices_a_rescheduled_task():
    assert _needs(tracked=_tracked(), desired=_desired([_want(due="2026-07-01")])) is (
        True
    )


def test_needs_pass_notices_a_completion_made_inside_home_keeper():
    done = _desired([_want(last_completed=DONE_ISO)])
    assert _needs(tracked=_tracked(), desired=done) is True


def test_needs_pass_notices_a_profile_that_went_away_or_lost_its_list():
    desired = _desired([_want()])
    assert _needs(tracked=_tracked(), desired=desired, mirrors=[]) is True
    assert (
        _needs(tracked=_tracked(), desired=desired, mirrors=[_mirror(entity_id="")])
        is True
    )


def test_needs_pass_notices_a_profile_pointed_at_another_list():
    tracked = {KEY: _entry(entity_id=OTHER)}
    assert _needs(tracked=tracked, desired=_desired([_want()])) is True


def test_needs_pass_keeps_looking_past_an_entry_that_is_in_step():
    # One settled chore must not end the walk before the drifted one behind it.
    tracked = {
        tm.mirror_key(M2, T1): _entry(),  # in step…
        KEY: _entry(summary="Stale name"),  # …and this one has drifted
    }
    desired = {M1: {T1: _want()}, M2: {T1: _want()}}
    mirrors = [_mirror(), _mirror(mid=M2)]
    assert tm.needs_pass(tracked=tracked, desired=desired, mirrors=mirrors) is True


def test_needs_pass_notices_a_profile_switched_off_with_items_still_out_there():
    # Clearing a profile's list drops it out of the wanted map altogether, so its
    # bookkeeping is the only thing left saying there is tidying up to do.
    assert _needs(tracked=_tracked(), desired={}, mirrors=[_mirror(entity_id="")]) is (
        True
    )
    assert _needs(tracked=_tracked(), desired={}, mirrors=[]) is True


# ── the retry contract ────────────────────────────────────────────────────────


def test_every_operation_names_the_task_it_belongs_to():
    # The driver puts a tracked entry back when a call fails, so every op has to
    # say which entry that is.
    added = _plan(desired=_desired([_want()]), items=[]).add[0]
    assert added.key == KEY
    removed = _plan(tracked=_tracked(), desired={M1: {}}, items=[_item()]).remove[0]
    assert removed.key == KEY
    ticked = _plan(
        tracked=_tracked(),
        desired=_desired([_want(last_completed=DONE_ISO)]),
        items=[_item()],
    ).update[0]
    assert ticked.key == KEY
    done = _plan(
        tracked=_tracked(),
        desired=_desired([_want()]),
        items=[_item(status=tm.STATUS_COMPLETED)],
    ).complete[0]
    assert done.key == KEY


# ── everything at once ────────────────────────────────────────────────────────


def test_every_tracked_entry_is_planned_independently_in_one_pass():
    """A household runs several mirroring profiles, never in step with each other.

    Every branch of the walk ends by moving on to the next entry — one chore
    being handled must never stop the next from being looked at.
    """
    mirrors = [
        _mirror("m1", LIST),
        _mirror("m3", ""),  # a profile whose sync was switched off
        _mirror("m9", OTHER),
    ]
    desired = {
        "m1": {
            "a": _want("a", name="Descale the kettle"),
            "c": _want("c", name="Clean the gutters"),
            "d": _want(
                "d",
                name="Change the smoke alarm",
                due="2026-09-14",
                last_completed=DONE_ISO,
            ),
            "e": _want("e", name="Bleed the radiators"),
            "f": _want("f", name="Wash the windows"),
            "h": _want("h", name="Sweep the chimney"),
            "i": _want("i", name="Oil the hinges"),
            "k": _want("k", name="Test the RCD"),
            "z": _want("z", name="Defrost the freezer"),
        },
        "m9": {"a": _want("a", name="Rake the leaves")},
    }
    tracked = {
        # In step: left exactly as it is.
        "m1:a": _entry(uid="ia", summary="Descale the kettle"),
        # Its task stopped matching: the open line comes off.
        "m1:b": _entry(uid="ib", summary="Mop the floor"),
        # Ticked off on the list while the task is open: the task gets completed.
        "m1:c": _entry(uid="ic", summary="Clean the gutters"),
        # Completed inside Home Keeper: tick the line off, add the next one.
        "m1:d": _entry(uid="id", summary="Change the smoke alarm"),
        # Vanished, and we hold a uid: the mirror reads that as done.
        "m1:e": _entry(uid="ie", summary="Bleed the radiators"),
        # Vanished with no uid to vouch for it: put it back instead.
        "m1:f": _entry(uid=None, summary="Wash the windows"),
        # Vanished, and nobody wants it any more.
        "m1:g": _entry(uid="ig", summary="Polish the taps"),
        # Left on the list this mirror used to point at.
        "m1:h": _entry(entity_id=OTHER, uid="ih", summary="Sweep the chimney"),
        # On a list nobody could read.
        "m1:i": _entry(entity_id=GHOST, uid="ii", summary="Oil the hinges"),
        # Ticked off, and its task stopped matching: the line is the record.
        "m1:j": _entry(uid="ij", summary="Hoover the stairs"),
        # Its profile is still there, with its list picker cleared.
        "m3:a": _entry(uid="i3", summary="Book the service"),
        # Its profile was deleted outright.
        "m5:a": _entry(uid="i5a", summary="Change the batteries"),
        "m5:b": _entry(uid="i5b", summary="Flush the boiler"),
        "m5:c": _entry(uid="i5c", summary="Seal the deck"),
        "m5:d": _entry(entity_id=GHOST, uid="i5d", summary="Wax the car"),
        # Renamed since it was mirrored.
        "m9:a": _entry(entity_id=OTHER, uid="i9", summary="Rake up the leaves"),
    }
    plan = tm.plan_sync(
        mirrors=mirrors,
        tracked=tracked,
        desired=desired,
        items_by_entity={
            LIST: [
                _item("Descale the kettle", "ia"),
                _item("Mop the floor", "ib"),
                _item("Clean the gutters", "ic", tm.STATUS_COMPLETED),
                _item("Change the smoke alarm", "id"),
                _item("Hoover the stairs", "ij", tm.STATUS_COMPLETED),
                _item("Book the service", "i3"),
                _item("Change the batteries", "i5a"),
                _item("Flush the boiler", "i5b", tm.STATUS_COMPLETED),
                _item("Test the RCD", "ik"),
            ],
            OTHER: [
                _item("Sweep the chimney", "ih"),
                _item("Rake up the leaves", "i9"),
            ],
        },
        capabilities=CAPS,
    )
    assert plan.remove == [
        tm.RemoveOp("m1:b", LIST, "ib"),
        tm.RemoveOp("m1:h", OTHER, "ih"),
        tm.RemoveOp("m3:a", LIST, "i3"),
        tm.RemoveOp("m5:a", LIST, "i5a"),
    ]
    assert plan.update == [
        tm.UpdateOp("m1:d", LIST, "id", status=tm.STATUS_COMPLETED),
        tm.UpdateOp("m9:a", OTHER, "i9", rename="Rake the leaves"),
    ]
    assert plan.complete == [
        tm.CompleteOp("m1:c", "c"),
        tm.CompleteOp("m1:e", "e"),
    ]
    assert plan.add == [
        tm.AddOp("m1:d", LIST, "Change the smoke alarm", due="2026-09-14"),
        tm.AddOp("m1:f", LIST, "Wash the windows", due=DUE),
        tm.AddOp("m1:h", LIST, "Sweep the chimney", due=DUE),
        tm.AddOp("m1:z", LIST, "Defrost the freezer", due=DUE),
    ]
    assert plan.tracked == {
        "m1:a": _entry(uid="ia", summary="Descale the kettle"),
        "m1:d": _entry(
            uid=None,
            summary="Change the smoke alarm",
            due="2026-09-14",
            last_completed=DONE_ISO,
        ),
        "m1:f": _entry(uid=None, summary="Wash the windows"),
        "m1:h": _entry(uid=None, summary="Sweep the chimney"),
        "m1:i": _entry(entity_id=GHOST, uid="ii", summary="Oil the hinges"),
        # Adopted: a line already reading the same is never duplicated.
        "m1:k": _entry(uid="ik", summary="Test the RCD"),
        "m1:z": _entry(uid=None, summary="Defrost the freezer"),
        "m5:d": _entry(entity_id=GHOST, uid="i5d", summary="Wax the car"),
        "m9:a": _entry(entity_id=OTHER, uid="i9", summary="Rake the leaves"),
    }
