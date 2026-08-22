"""Unit tests for the pure shopping-list mirror planner (``shopping.py``).

The planner decides, from three inputs — what we mirrored last pass, which
auto-buy reminders exist now, and what is actually on the to-do list — which
items to add, tick off, rename or remove, and which reminders the shopper has
already ticked off for us. Every branch is exercised here without a Home
Assistant runtime; ``shopping_sync.py`` (the driver that reads the list and
applies the plan) has its own suite.
"""

import hk_shopping as sh

TARGET = "todo.shopping_list"
OTHER = "todo.groceries"
KEY = "asset1:part1"


# ── fixtures ──────────────────────────────────────────────────────────────────


def _buy_task(tid="t1", name="Buy Anode rod", asset="asset1", part="part1", **extra):
    """A minted auto-buy reminder, open unless *extra* says otherwise."""
    return {
        "id": tid,
        "name": name,
        "recurrence_type": "one-off",
        "next_due": "2026-06-13T10:00:00-04:00",
        "last_completed": None,
        "source": {"buy": {"asset_id": asset, "part_id": part}},
        **extra,
    }


def _completed(task):
    """The same reminder after it was completed (a one-off goes dormant)."""
    return {**task, "next_due": None, "last_completed": "2026-06-14T09:00:00-04:00"}


def _item(summary="Buy Anode rod", uid="i1", status=sh.STATUS_NEEDS_ACTION):
    return {"uid": uid, "summary": summary, "status": status}


def _tracked(entity_id=TARGET, summary="Buy Anode rod", uid="i1", key=KEY):
    return {key: {"entity_id": entity_id, "summary": summary, "uid": uid}}


def _plan(tracked=None, desired=None, items=None, target=TARGET, entity=None):
    """Run one pass. *items* is the target list's contents (None = unreadable)."""
    by_entity = {}
    if items is not None:
        by_entity[entity or target or TARGET] = items
    return sh.plan_sync(
        tracked=tracked or {},
        desired=desired or {},
        items_by_entity=by_entity,
        target=target,
    )


# ── normalize_target ──────────────────────────────────────────────────────────


def test_normalize_target_accepts_a_todo_entity_and_tidies_it():
    assert sh.normalize_target("  Todo.Shopping_List  ") == "todo.shopping_list"
    assert sh.normalize_target("todo.shopping_list") == "todo.shopping_list"


def test_normalize_target_rejects_everything_that_is_not_a_todo_entity():
    assert sh.normalize_target("") == ""
    assert sh.normalize_target("   ") == ""
    assert sh.normalize_target("sensor.shopping_list") == ""
    assert sh.normalize_target("todo.") == ""
    assert sh.normalize_target("shopping_list") == ""
    assert sh.normalize_target(None) == ""
    assert sh.normalize_target(42) == ""
    assert sh.normalize_target(["todo.shopping_list"]) == ""
    # An entity id is exactly domain.object_id — one dot, both halves filled.
    assert sh.normalize_target("todo.shopping.list") == ""
    assert sh.normalize_target(".shopping_list") == ""


# ── buy_tasks_by_part ─────────────────────────────────────────────────────────


def test_buy_tasks_by_part_indexes_only_buy_reminders():
    # The unrelated tasks come first on purpose: skipping one must not stop the
    # walk before it reaches the reminder.
    tasks = {
        "t2": {"id": "t2", "name": "Replace filter", "source": {"part": {}}},
        "t3": {"id": "t3", "name": "Vacuum"},
        "t4": _buy_task(tid="t4", name="", asset="a9", part="p9"),
        "stored-under-something-else": _buy_task(tid="t1"),
    }
    indexed = sh.buy_tasks_by_part(tasks)
    assert indexed == {
        KEY: {"task_id": "t1", "name": "Buy Anode rod", "completed": False}
    }


def test_buy_tasks_by_part_marks_a_completed_reminder():
    indexed = sh.buy_tasks_by_part({"t1": _completed(_buy_task())})
    assert indexed[KEY]["completed"] is True


def test_buy_tasks_by_part_skips_a_nameless_reminder():
    # An empty summary is not something a to-do list can hold.
    assert sh.buy_tasks_by_part({"t1": _buy_task(name="   ")}) == {}
    assert sh.buy_tasks_by_part({"t1": _buy_task(name="")}) == {}


def test_buy_tasks_by_part_tidies_the_summary_it_will_put_on_the_list():
    indexed = sh.buy_tasks_by_part({"t1": _buy_task(name="  Buy Anode rod  ")})
    assert indexed[KEY]["name"] == "Buy Anode rod"


def test_buy_tasks_by_part_falls_back_to_the_map_key_for_a_task_without_an_id():
    task = _buy_task()
    del task["id"]
    assert (
        sh.buy_tasks_by_part({"stored-under": task})[KEY]["task_id"] == "stored-under"
    )


def test_buy_tasks_by_part_keeps_the_first_of_two_open_reminders():
    tasks = {"a": _buy_task(tid="a"), "b": _buy_task(tid="b")}
    assert sh.buy_tasks_by_part(tasks)[KEY]["task_id"] == "a"


def test_buy_tasks_by_part_prefers_the_open_reminder_for_a_part():
    tasks = {
        "done": _completed(_buy_task(tid="done")),
        "open": _buy_task(tid="open"),
    }
    assert sh.buy_tasks_by_part(tasks)[KEY]["task_id"] == "open"
    # …whichever order storage happens to hand them over in.
    assert sh.buy_tasks_by_part(dict(reversed(tasks.items())))[KEY]["task_id"] == "open"


def test_buy_tasks_by_part_ignores_a_malformed_buy_source():
    tasks = {"t1": {"id": "t1", "name": "Buy X", "source": {"buy": {"asset_id": "a"}}}}
    assert sh.buy_tasks_by_part(tasks) == {}


# ── normalize_items ───────────────────────────────────────────────────────────


def test_normalize_items_reads_the_service_response():
    response = {TARGET: {"items": [_item(), "junk"]}}
    assert sh.normalize_items(response, TARGET) == [_item()]


def test_normalize_items_returns_none_for_anything_unreadable():
    # None means "we could not see this list", which is not the same as "empty".
    assert sh.normalize_items(None, TARGET) is None
    assert sh.normalize_items({}, TARGET) is None
    assert sh.normalize_items({TARGET: []}, TARGET) is None
    assert sh.normalize_items({TARGET: {}}, TARGET) is None
    assert sh.normalize_items({OTHER: {"items": []}}, TARGET) is None
    assert sh.normalize_items({TARGET: {"items": []}}, TARGET) == []


# ── adding ────────────────────────────────────────────────────────────────────


def test_an_open_reminder_is_added_to_the_target_list():
    plan = _plan(desired=sh.buy_tasks_by_part({"t1": _buy_task()}), items=[])
    assert plan.add == [sh.AddOp(KEY, TARGET, "Buy Anode rod")]
    assert plan.tracked == {
        KEY: {"entity_id": TARGET, "summary": "Buy Anode rod", "uid": None}
    }
    assert plan.update == [] and plan.remove == [] and plan.complete == []


def test_a_reminder_already_completed_is_never_added():
    plan = _plan(
        desired=sh.buy_tasks_by_part({"t1": _completed(_buy_task())}), items=[]
    )
    assert plan.add == []
    assert plan.tracked == {}


def test_an_existing_matching_item_is_adopted_instead_of_duplicated():
    plan = _plan(
        desired=sh.buy_tasks_by_part({"t1": _buy_task()}),
        items=[_item(uid="theirs")],
    )
    assert plan.add == []
    assert plan.tracked == {
        KEY: {"entity_id": TARGET, "summary": "Buy Anode rod", "uid": "theirs"}
    }


def test_a_ticked_off_lookalike_is_not_adopted():
    # Last week's "Buy Anode rod", already bought, must not stand in for this
    # week's reminder — that would leave the shopper nothing to buy.
    plan = _plan(
        desired=sh.buy_tasks_by_part({"t1": _buy_task()}),
        items=[_item(uid="old", status=sh.STATUS_COMPLETED)],
    )
    assert plan.add == [sh.AddOp(KEY, TARGET, "Buy Anode rod")]


def test_two_reminders_reading_the_same_never_share_one_item():
    desired = sh.buy_tasks_by_part(
        {
            "t1": _buy_task(tid="t1", asset="a1", part="p1"),
            "t2": _buy_task(tid="t2", asset="a2", part="p2"),
        }
    )
    plan = _plan(desired=desired, items=[_item(uid="only")])
    assert len(plan.add) == 1
    adopted = [k for k, v in plan.tracked.items() if v["uid"] == "only"]
    assert len(adopted) == 1


def test_nothing_is_added_when_the_target_list_cannot_be_read():
    plan = _plan(desired=sh.buy_tasks_by_part({"t1": _buy_task()}), items=None)
    assert plan.add == []
    assert plan.tracked == {}


def test_nothing_is_added_when_no_list_is_configured():
    plan = _plan(desired=sh.buy_tasks_by_part({"t1": _buy_task()}), target="", items=[])
    assert plan.add == []
    assert plan.tracked == {}


# ── keeping a mirrored item in step ───────────────────────────────────────────


def test_an_open_reminder_keeps_its_item_and_captures_the_uid():
    plan = _plan(
        tracked=_tracked(uid=None),
        desired=sh.buy_tasks_by_part({"t1": _buy_task()}),
        items=[_item(uid="captured")],
    )
    assert plan.add == [] and plan.update == [] and plan.remove == []
    assert plan.tracked == {
        KEY: {"entity_id": TARGET, "summary": "Buy Anode rod", "uid": "captured"}
    }


def test_a_renamed_reminder_renames_its_item():
    # Generated names are localized at write time, so switching the household
    # language rewrites them.
    plan = _plan(
        tracked=_tracked(),
        desired=sh.buy_tasks_by_part({"t1": _buy_task(name="Anodenstab kaufen")}),
        items=[_item()],
    )
    assert plan.update == [sh.UpdateOp(KEY, TARGET, "i1", rename="Anodenstab kaufen")]
    assert plan.tracked == {
        KEY: {"entity_id": TARGET, "summary": "Anodenstab kaufen", "uid": "i1"}
    }
    assert plan.remove == [] and plan.add == []


def test_completing_the_reminder_in_home_keeper_ticks_the_item_off():
    plan = _plan(
        tracked=_tracked(),
        desired=sh.buy_tasks_by_part({"t1": _completed(_buy_task())}),
        items=[_item()],
    )
    assert plan.update == [sh.UpdateOp(KEY, TARGET, "i1", status=sh.STATUS_COMPLETED)]
    assert plan.remove == []
    assert plan.tracked == {}


def test_a_reminder_that_went_away_unbought_takes_its_item_with_it():
    plan = _plan(tracked=_tracked(), desired={}, items=[_item()])
    assert plan.remove == [sh.RemoveOp(KEY, TARGET, "i1")]
    assert plan.tracked == {}


def test_switching_the_target_list_moves_the_item():
    plan = sh.plan_sync(
        tracked=_tracked(entity_id=OTHER),
        desired=sh.buy_tasks_by_part({"t1": _buy_task()}),
        items_by_entity={OTHER: [_item()], TARGET: []},
        target=TARGET,
    )
    assert plan.remove == [sh.RemoveOp(KEY, OTHER, "i1")]
    assert plan.add == [sh.AddOp(KEY, TARGET, "Buy Anode rod")]
    assert plan.tracked == {
        KEY: {"entity_id": TARGET, "summary": "Buy Anode rod", "uid": None}
    }


def test_turning_the_mirror_off_clears_the_items_it_put_there():
    plan = sh.plan_sync(
        tracked=_tracked(),
        desired=sh.buy_tasks_by_part({"t1": _buy_task()}),
        items_by_entity={TARGET: [_item()]},
        target="",
    )
    assert plan.remove == [sh.RemoveOp(KEY, TARGET, "i1")]
    assert plan.add == []
    assert plan.tracked == {}


def test_an_item_addressed_by_summary_when_the_list_hands_out_no_uid():
    plan = _plan(
        tracked=_tracked(uid=None),
        desired={},
        items=[{"summary": "Buy Anode rod", "status": sh.STATUS_NEEDS_ACTION}],
    )
    assert plan.remove == [sh.RemoveOp(KEY, TARGET, "Buy Anode rod")]


def test_an_unreadable_list_leaves_its_bookkeeping_untouched():
    tracked = _tracked()
    plan = sh.plan_sync(tracked=tracked, desired={}, items_by_entity={}, target=TARGET)
    assert plan.remove == [] and plan.update == [] and plan.add == []
    assert plan.tracked == tracked


# ── the shopper's side ────────────────────────────────────────────────────────


def test_ticking_the_item_off_completes_the_home_keeper_reminder():
    plan = _plan(
        tracked=_tracked(),
        desired=sh.buy_tasks_by_part({"t1": _buy_task()}),
        items=[_item(status=sh.STATUS_COMPLETED)],
    )
    assert plan.complete == [sh.CompleteOp(KEY, "t1")]
    # The item they just ticked off is left exactly as it is — and no second copy
    # is put back on the list while Home Keeper catches up.
    assert plan.update == [] and plan.remove == [] and plan.add == []
    assert plan.tracked == {}


def test_a_ticked_off_item_whose_reminder_is_already_done_is_left_alone():
    plan = _plan(
        tracked=_tracked(),
        desired=sh.buy_tasks_by_part({"t1": _completed(_buy_task())}),
        items=[_item(status=sh.STATUS_COMPLETED)],
    )
    assert plan.complete == []
    assert plan.update == [] and plan.remove == []
    assert plan.tracked == {}


def test_a_ticked_off_item_whose_reminder_is_gone_is_left_alone():
    plan = _plan(
        tracked=_tracked(), desired={}, items=[_item(status=sh.STATUS_COMPLETED)]
    )
    assert plan.complete == [] and plan.remove == []
    assert plan.tracked == {}


def test_deleting_the_item_by_hand_is_not_argued_with():
    # No re-add: the shopper took it off the list on purpose. The bookkeeping is
    # kept so the mirror stays quiet for the rest of this low spell.
    tracked = _tracked()
    plan = _plan(
        tracked=tracked,
        desired=sh.buy_tasks_by_part({"t1": _buy_task()}),
        items=[],
    )
    assert plan.add == [] and plan.remove == [] and plan.update == []
    assert plan.tracked == tracked


def test_a_deleted_item_stops_being_tracked_once_its_reminder_ends():
    plan = _plan(tracked=_tracked(), desired={}, items=[])
    assert plan.tracked == {}
    assert plan.remove == []


# ── lists_to_read ─────────────────────────────────────────────────────────────


def test_lists_to_read_covers_the_target_and_anything_still_held():
    tracked = {
        "a:1": {"entity_id": OTHER, "summary": "x", "uid": None},
        "a:2": {"entity_id": TARGET, "summary": "y", "uid": None},
        "a:3": {"entity_id": "", "summary": "z", "uid": None},
    }
    assert sh.lists_to_read(tracked, target=TARGET) == [OTHER, TARGET]


def test_lists_to_read_still_names_a_left_behind_list_when_the_mirror_is_off():
    # Turning the mirror off must not blind it to the list it has to tidy up.
    tracked = {"a:1": {"entity_id": OTHER, "summary": "x", "uid": None}}
    assert sh.lists_to_read(tracked, target="") == [OTHER]
    assert sh.lists_to_read({}, target="") == []
    assert sh.lists_to_read({}, target=TARGET) == [TARGET]


# ── needs_pass ────────────────────────────────────────────────────────────────


def _needs(tracked=None, desired=None, target=TARGET):
    return sh.needs_pass(tracked=tracked or {}, desired=desired or {}, target=target)


def test_needs_pass_is_false_for_a_settled_mirror():
    # The common case: nothing changed, so no to-do list is read at all.
    assert (
        _needs(tracked=_tracked(), desired=sh.buy_tasks_by_part({"t1": _buy_task()}))
        is False
    )
    assert _needs() is False


def test_needs_pass_notices_a_new_reminder():
    assert _needs(desired=sh.buy_tasks_by_part({"t1": _buy_task()})) is True


def test_needs_pass_ignores_a_reminder_that_is_already_done():
    assert (
        _needs(desired=sh.buy_tasks_by_part({"t1": _completed(_buy_task())})) is False
    )


def test_needs_pass_notices_a_reminder_that_ended():
    assert _needs(tracked=_tracked(), desired={}) is True


def test_needs_pass_notices_a_reminder_completed_in_home_keeper():
    assert (
        _needs(
            tracked=_tracked(),
            desired=sh.buy_tasks_by_part({"t1": _completed(_buy_task())}),
        )
        is True
    )


def test_needs_pass_notices_a_rename():
    assert (
        _needs(
            tracked=_tracked(),
            desired=sh.buy_tasks_by_part({"t1": _buy_task(name="Anodenstab kaufen")}),
        )
        is True
    )


def test_needs_pass_notices_the_target_moving_or_being_cleared():
    desired = sh.buy_tasks_by_part({"t1": _buy_task()})
    assert _needs(tracked=_tracked(entity_id=OTHER), desired=desired) is True
    assert _needs(tracked=_tracked(), desired=desired, target="") is True


def test_needs_pass_does_not_add_without_a_target():
    assert _needs(desired=sh.buy_tasks_by_part({"t1": _buy_task()}), target="") is False


# ── the retry contract ────────────────────────────────────────────────────────


def test_every_operation_names_the_reminder_it_belongs_to():
    # The driver puts a tracked entry back when a call fails, so each op has to
    # say which entry that is.
    add = _plan(desired=sh.buy_tasks_by_part({"t1": _buy_task()}), items=[]).add[0]
    assert add.key == KEY
    removal = _plan(tracked=_tracked(), desired={}, items=[_item()]).remove[0]
    assert removal.key == KEY
    tick = _plan(
        tracked=_tracked(),
        desired=sh.buy_tasks_by_part({"t1": _completed(_buy_task())}),
        items=[_item()],
    ).update[0]
    assert tick.key == KEY
    done = _plan(
        tracked=_tracked(),
        desired=sh.buy_tasks_by_part({"t1": _buy_task()}),
        items=[_item(status=sh.STATUS_COMPLETED)],
    ).complete[0]
    assert done.key == KEY


# ── which list item a tracked entry points at ─────────────────────────────────


def test_the_uid_wins_over_a_lookalike_summary():
    plan = _plan(
        tracked=_tracked(uid="i1", summary="Buy Anode rod"),
        desired={},
        items=[
            _item(uid="other", summary="Buy Anode rod"),
            _item(uid="i1", summary="Buy anode rod (renamed by hand)"),
        ],
    )
    assert plan.remove == [sh.RemoveOp(KEY, TARGET, "i1")]


def test_a_uid_that_no_longer_exists_falls_back_to_the_summary():
    # A list that hands out fresh uids (or an item recreated by hand) still
    # matches on the text we put there.
    plan = _plan(
        tracked=_tracked(uid="gone"),
        desired={},
        items=[_item(uid="fresh", summary="Buy Anode rod")],
    )
    assert plan.remove == [sh.RemoveOp(KEY, TARGET, "fresh")]


def test_an_open_item_wins_over_a_ticked_off_one_reading_the_same():
    plan = _plan(
        tracked=_tracked(uid=None),
        desired={},
        items=[
            _item(uid="old", status=sh.STATUS_COMPLETED),
            _item(uid="live"),
        ],
    )
    assert plan.remove == [sh.RemoveOp(KEY, TARGET, "live")]


def test_a_ticked_off_item_is_matched_when_it_is_the_only_one():
    # The tick we are looking for is on last week's line, because that is the
    # line we added; falling through to it is what closes the loop.
    plan = _plan(
        tracked=_tracked(uid=None),
        desired=sh.buy_tasks_by_part({"t1": _buy_task()}),
        items=[_item(uid="old", status=sh.STATUS_COMPLETED)],
    )
    assert plan.complete == [sh.CompleteOp(KEY, "t1")]


def test_two_entries_reading_the_same_never_resolve_to_one_item():
    tracked = {
        "a1:p1": {"entity_id": TARGET, "summary": "Buy Anode rod", "uid": None},
        "a2:p2": {"entity_id": TARGET, "summary": "Buy Anode rod", "uid": None},
    }
    plan = _plan(tracked=tracked, desired={}, items=[_item(uid="only")])
    assert plan.remove == [sh.RemoveOp("a1:p1", TARGET, "only")]


def test_an_item_with_no_uid_at_all_is_addressed_by_its_text():
    plan = _plan(
        tracked=_tracked(uid=None),
        desired={},
        items=[{"summary": "Buy Anode rod", "status": sh.STATUS_NEEDS_ACTION}],
    )
    assert plan.remove == [sh.RemoveOp(KEY, TARGET, "Buy Anode rod")]


def test_an_item_with_a_blank_uid_is_addressed_by_its_text():
    plan = _plan(
        tracked=_tracked(uid=None),
        desired={},
        items=[_item(uid="")],
    )
    assert plan.remove == [sh.RemoveOp(KEY, TARGET, "Buy Anode rod")]


def test_a_tracked_entry_with_no_list_of_its_own_is_carried_untouched():
    tracked = {KEY: {"summary": "Buy Anode rod", "uid": "i1"}}
    plan = _plan(tracked=tracked, desired={}, items=[_item()])
    assert plan.remove == [] and plan.add == []
    assert plan.tracked == tracked


def test_a_deleted_item_whose_reminder_was_completed_stops_being_tracked():
    plan = _plan(
        tracked=_tracked(),
        desired=sh.buy_tasks_by_part({"t1": _completed(_buy_task())}),
        items=[],
    )
    assert plan.tracked == {}
    assert plan.update == [] and plan.remove == []


# ── several parts at once ─────────────────────────────────────────────────────


def test_each_part_is_planned_independently_in_one_pass():
    """A household has more than one low part, and they are rarely in step.

    Every branch of the walk ends in a ``continue`` — one part being handled
    must never stop the next from being looked at.
    """
    tracked = {
        # Already mirrored and still wanted: left alone.
        "a:keep": {"entity_id": TARGET, "summary": "Buy filter", "uid": "k"},
        # Reminder ended unbought: its line comes off.
        "a:gone": {"entity_id": TARGET, "summary": "Buy belt", "uid": "g"},
        # Completed in Home Keeper: its line is ticked off.
        "a:done": {"entity_id": TARGET, "summary": "Buy bulb", "uid": "d"},
        # Ticked off at the shop: the reminder gets completed.
        "a:shop": {"entity_id": TARGET, "summary": "Buy fuse", "uid": "s"},
        # Renamed (the household switched language).
        "a:name": {"entity_id": TARGET, "summary": "Buy soap", "uid": "n"},
        # On the list we no longer mirror onto.
        "a:moved": {"entity_id": OTHER, "summary": "Buy oil", "uid": "m"},
    }
    desired = {
        "a:keep": {"task_id": "t-keep", "name": "Buy filter", "completed": False},
        "a:done": {"task_id": "t-done", "name": "Buy bulb", "completed": True},
        "a:shop": {"task_id": "t-shop", "name": "Buy fuse", "completed": False},
        "a:name": {"task_id": "t-name", "name": "Seife kaufen", "completed": False},
        "a:moved": {"task_id": "t-moved", "name": "Buy oil", "completed": False},
        # Brand new: nothing on the list for it yet.
        "a:new": {"task_id": "t-new", "name": "Buy anode", "completed": False},
    }
    plan = sh.plan_sync(
        tracked=tracked,
        desired=desired,
        items_by_entity={
            TARGET: [
                _item("Buy filter", "k"),
                _item("Buy belt", "g"),
                _item("Buy bulb", "d"),
                _item("Buy fuse", "s", sh.STATUS_COMPLETED),
                _item("Buy soap", "n"),
            ],
            OTHER: [_item("Buy oil", "m")],
        },
        target=TARGET,
    )
    assert plan.add == [
        sh.AddOp("a:moved", TARGET, "Buy oil"),
        sh.AddOp("a:new", TARGET, "Buy anode"),
    ]
    assert plan.remove == [
        sh.RemoveOp("a:gone", TARGET, "g"),
        sh.RemoveOp("a:moved", OTHER, "m"),
    ]
    assert plan.update == [
        sh.UpdateOp("a:done", TARGET, "d", status=sh.STATUS_COMPLETED),
        sh.UpdateOp("a:name", TARGET, "n", rename="Seife kaufen"),
    ]
    assert plan.complete == [sh.CompleteOp("a:shop", "t-shop")]
    assert plan.tracked == {
        "a:keep": {"entity_id": TARGET, "summary": "Buy filter", "uid": "k"},
        "a:name": {"entity_id": TARGET, "summary": "Seife kaufen", "uid": "n"},
        "a:moved": {"entity_id": TARGET, "summary": "Buy oil", "uid": None},
        "a:new": {"entity_id": TARGET, "summary": "Buy anode", "uid": None},
    }


def test_a_blank_uid_on_a_tracked_entry_is_not_treated_as_a_uid():
    # "" is the absence of a uid, not a uid to match on — matching it would bind
    # the entry to whichever unrelated item also lacks one.
    plan = _plan(
        tracked=_tracked(uid=""),
        desired={},
        items=[
            _item(uid="", summary="Milk"),
            _item(uid="x", summary="Buy Anode rod"),
        ],
    )
    assert plan.remove == [sh.RemoveOp(KEY, TARGET, "x")]
