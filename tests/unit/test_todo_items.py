"""Unit tests for the shared to-do item matching (``todo_items.py``).

Four small answers about somebody else's to-do list that both syncs lean on
before either state machine runs: how an item is addressed in a service call,
whether it has been ticked off, which live item a bookkeeping entry points at,
and whether an open line already reads like this. Their planners
(``test_shopping.py`` / ``test_todo_list.py``) exercise them in anger; what is
pinned here is each rule on its own, because a helper that quietly picks the
wrong line makes both syncs write to somebody else's chore.
"""

import hk_todo_items as ti

LIST = "todo.family"
OTHER = "todo.chores"
NAME = "Change the filter"


def _item(summary=NAME, uid="i1", status=ti.STATUS_NEEDS_ACTION, **extra):
    return {"uid": uid, "summary": summary, "status": status, **extra}


def _done(summary=NAME, uid="i1"):
    return _item(summary=summary, uid=uid, status=ti.STATUS_COMPLETED)


# ── item_identity ─────────────────────────────────────────────────────────────


def test_a_uid_is_how_an_item_is_addressed():
    assert ti.item_identity(_item(uid="abc")) == "abc"


def test_an_item_without_a_uid_is_addressed_by_its_summary():
    # ``todo.update_item``/``remove_item`` take either, so a list that hands out
    # no uids is still reachable.
    assert ti.item_identity({"summary": NAME}) == NAME


def test_an_empty_uid_is_not_a_uid():
    # The falsy half of the guard: an empty string would address nothing.
    assert ti.item_identity(_item(uid="")) == NAME


def test_a_non_string_uid_is_not_a_uid():
    # Providers hand back what they like; only a str is an item handle.
    assert ti.item_identity(_item(uid=7)) == NAME
    assert ti.item_identity(_item(uid=None)) == NAME
    assert ti.item_identity(_item(uid=["i1"])) == NAME


def test_an_item_with_neither_addresses_as_the_empty_string():
    assert ti.item_identity({}) == ""
    assert ti.item_identity({"uid": "", "summary": None}) == ""
    assert ti.item_identity({"uid": "", "summary": ""}) == ""


def test_a_non_string_summary_is_still_stringified():
    assert ti.item_identity({"uid": "", "summary": 12}) == "12"


# ── item_is_open ──────────────────────────────────────────────────────────────


def test_only_a_completed_item_is_closed():
    assert ti.item_is_open(_item()) is True
    assert ti.item_is_open(_done()) is False


def test_an_item_with_no_status_reads_as_open():
    # A list that reports no status has not told us anyone ticked it off, and
    # guessing "done" would drop a chore nobody did.
    assert ti.item_is_open({"summary": NAME}) is True
    assert ti.item_is_open({"summary": NAME, "status": None}) is True
    assert ti.item_is_open({"summary": NAME, "status": "needs_action"}) is True
    assert ti.item_is_open({"summary": NAME, "status": "COMPLETED"}) is True


# ── resolve_tracked ───────────────────────────────────────────────────────────


def _resolve(items, *, uid="i1", summary=NAME, entity_id=LIST, claimed=None):
    return ti.resolve_tracked(
        items,
        entity_id=entity_id,
        uid=uid,
        summary=summary,
        claimed=set() if claimed is None else claimed,
    )


def test_the_uid_wins_over_a_summary_match():
    # The line we bound to was renamed on the list, and another line happens to
    # read what ours used to. The uid is the one thing that cannot drift.
    renamed = _item(summary="Change the HVAC filter", uid="i1")
    impostor = _item(summary=NAME, uid="i2")
    assert _resolve([impostor, renamed]) is renamed


def test_a_uid_match_that_is_already_claimed_is_passed_over():
    # Two entries pointing at one line: the first pass claimed it, so the second
    # must not resolve to it as well.
    taken = _item(summary="Something else", uid="i1")
    mine = _item(summary=NAME, uid="i2")
    claimed = {(LIST, "i1")}
    assert _resolve([taken, mine], claimed=claimed) is mine


def test_a_claim_on_another_list_does_not_hide_our_item():
    # The claim set is keyed by (entity_id, identity) precisely so two lists can
    # hold identically-named lines without shadowing each other.
    item = _item()
    assert _resolve([item], claimed={(OTHER, "i1")}) is item


def test_no_captured_uid_falls_back_to_the_summary():
    # A freshly added item has no uid yet — ``todo.add_item`` answers with
    # nothing — so this is how the next pass binds one.
    fresh = _item(summary=NAME, uid="generated-later")
    assert _resolve([fresh], uid=None) is fresh
    assert _resolve([fresh], uid="") is fresh
    assert _resolve([fresh], uid=17) is fresh


def test_a_non_string_uid_is_never_matched_against_the_list():
    # The guard is ``isinstance`` *and* truthy for a reason: a provider handing
    # back a numeric uid must not have it compared to what we stored, or a
    # bookkeeping entry that never captured one binds to whichever line happens
    # to answer the same way.
    numeric = _item(summary="Somebody else's chore", uid=17)
    ours = _item(summary=NAME, uid="i9")
    assert _resolve([numeric, ours], uid=17) is ours


def test_an_unmatched_uid_still_falls_back_to_the_summary():
    # The list dropped and recreated the line (a resync, an export/import): the
    # uid is gone but the text is ours, so we re-attach rather than duplicate.
    recreated = _item(uid="i9")
    assert _resolve([recreated], uid="i1") is recreated


def test_an_open_line_wins_over_a_ticked_off_one_reading_the_same():
    # Last cycle's completed record sits above this cycle's fresh line; binding
    # to the record would tick off a chore nobody has done.
    record = _done(uid="old")
    live = _item(uid="new")
    assert _resolve([record, live], uid=None) is live


def test_the_first_ticked_off_line_is_taken_when_none_are_open():
    # Order matters: the earliest match is the one we bound to, and the later
    # copies are somebody's own duplicates.
    first = _done(uid="a")
    second = _done(uid="b")
    third = _done(uid="c")
    assert _resolve([first, second, third], uid=None) is first


def test_a_summary_that_matches_nothing_resolves_to_nothing():
    assert _resolve([_item(summary="Something else")], uid=None) is None
    assert _resolve([], uid="i1") is None


def test_every_summary_match_being_claimed_resolves_to_nothing():
    assert _resolve([_item()], uid=None, claimed={(LIST, "i1")}) is None


def test_a_summary_match_is_exact():
    # No trimming, no case folding: the driver writes the summary itself, so a
    # near-miss is somebody else's line.
    assert _resolve([_item(summary=NAME + " ")], uid=None) is None
    assert _resolve([_item(summary=NAME.lower())], uid=None) is None


def test_a_uid_less_line_is_claimed_by_its_summary():
    # Its identity *is* the summary, so claiming it must exclude it from the
    # summary fallback too.
    item = {"summary": NAME, "status": ti.STATUS_NEEDS_ACTION}
    assert _resolve([item], uid=None) is item
    assert _resolve([item], uid=None, claimed={(LIST, NAME)}) is None


# ── find_open ─────────────────────────────────────────────────────────────────


def _find(items, *, summary=NAME, entity_id=LIST, claimed=None):
    return ti.find_open(
        items,
        entity_id=entity_id,
        summary=summary,
        claimed=set() if claimed is None else claimed,
    )


def test_an_open_line_already_saying_this_is_adopted():
    item = _item()
    assert _find([item]) is item


def test_a_ticked_off_line_is_never_adopted():
    # Adopting it would resurrect somebody's completed record as this cycle's
    # chore; the caller adds a fresh line instead.
    assert _find([_done()]) is None


def test_the_first_open_match_is_taken():
    first = _item(uid="a")
    second = _item(uid="b")
    assert _find([_done(uid="x"), first, second]) is first


def test_a_different_summary_is_not_adopted():
    assert _find([_item(summary="Something else")]) is None
    assert _find([]) is None


def test_a_claimed_line_is_not_adopted_twice():
    # Two tasks whose names collide must not both bind to the one line.
    assert _find([_item()], claimed={(LIST, "i1")}) is None


def test_a_claim_on_another_list_does_not_block_adoption():
    item = _item()
    assert _find([item], claimed={(OTHER, "i1")}) is item


def test_a_uid_less_open_line_is_claimed_by_its_summary():
    item = {"summary": NAME}
    assert _find([item]) is item
    assert _find([item], claimed={(LIST, NAME)}) is None
