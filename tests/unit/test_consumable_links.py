"""The list of consumable links on a task (#493): the pure readers and the migration.

A task can take more than 1 consumable part. The user's links live in
``source.parts``, a list of ``{asset_id, part_id, quantity?}``. A task stored before
the list existed keeps 1 manual link in ``source.part``. The store moves it into the
list on load, and every reader also reads the old shape.
"""

from datetime import datetime, timedelta, timezone

import hk_reconcile as rc
import pytest

NOW = datetime(2026, 6, 13, 10, tzinfo=timezone(timedelta(hours=-4)))

LINK_A = {"asset_id": "a1", "part_id": "p1"}
LINK_B = {"asset_id": "a1", "part_id": "p2", "quantity": 2}


def _task(source):
    return {"id": "t1", "name": "Water filters", "source": source}


# ── consumable_links ─────────────────────────────────────────────────────────


def test_the_list_is_read_in_order():
    task = _task({"parts": [LINK_A, LINK_B]})
    assert rc.consumable_links(task) == [LINK_A, LINK_B]


def test_an_old_manual_link_is_not_read_at_run_time():
    # The load migrates it (migrate_consumable_link), and no writer makes it again.
    legacy = {**LINK_A, "manual": True, "quantity": 3}
    assert rc.consumable_links(_task({"part": legacy})) == []


def test_a_wear_part_source_is_no_consumable_link():
    assert rc.consumable_links(_task({"part": LINK_A})) == []


@pytest.mark.parametrize(
    "source",
    [None, {}, {"parts": None}, {"parts": "a1:p1"}, {"glue": {"x": 1}}, "junk"],
)
def test_a_task_with_no_links_reads_empty(source):
    assert rc.consumable_links(_task(source)) == []


def test_a_malformed_list_entry_is_skipped():
    task = _task({"parts": [LINK_A, {"asset_id": "a1"}, "a1:p2", {"part_id": "p3"}]})
    assert rc.consumable_links(task) == [LINK_A]


def test_the_list_wins_over_an_old_link():
    task = _task({"parts": [LINK_B], "part": {**LINK_A, "manual": True}})
    assert rc.consumable_links(task) == [LINK_B]


def test_an_empty_list_is_no_link_even_beside_an_old_link():
    task = _task({"parts": [], "part": {**LINK_A, "manual": True}})
    assert rc.consumable_links(task) == []


def test_a_malformed_old_link_is_no_link():
    assert rc.consumable_links(_task({"part": {"manual": True}})) == []
    assert rc.consumable_links(_task({"part": "a1:p1"})) == []


# ── stock_links: what a completion draws ─────────────────────────────────────


def test_a_wear_task_draws_its_own_part():
    assert rc.stock_links(_task({"part": LINK_A})) == [LINK_A]


def test_a_linked_task_draws_every_link():
    assert rc.stock_links(_task({"parts": [LINK_A, LINK_B]})) == [LINK_A, LINK_B]


def test_a_source_part_draws_its_part_whatever_its_flags():
    legacy = {**LINK_A, "manual": True}
    assert rc.stock_links(_task({"part": legacy})) == [legacy]


def test_a_plain_task_draws_nothing():
    assert rc.stock_links(_task(None)) == []
    assert rc.stock_links(_task({"buy": LINK_A})) == []


# ── migrate_consumable_link ──────────────────────────────────────────────────


def test_the_migration_moves_an_old_link_into_the_list():
    task = _task({"part": {**LINK_A, "manual": True, "quantity": 2}, "glue": {"x": 1}})
    assert rc.migrate_consumable_link(task) is True
    assert task["source"] == {
        "glue": {"x": 1},
        "parts": [{"asset_id": "a1", "part_id": "p1", "quantity": 2}],
    }
    # The second run finds nothing to move.
    assert rc.migrate_consumable_link(task) is False


def test_the_migration_keeps_no_quantity_that_the_link_did_not_state():
    task = _task({"part": {**LINK_A, "manual": True}})
    rc.migrate_consumable_link(task)
    assert task["source"] == {"parts": [LINK_A]}


def test_the_migration_leaves_a_wear_task_alone():
    task = _task({"part": dict(LINK_A)})
    assert rc.migrate_consumable_link(task) is False
    assert task["source"] == {"part": LINK_A}


@pytest.mark.parametrize("source", [None, {}, {"glue": {"x": 1}}, "junk"])
def test_the_migration_leaves_a_task_with_no_link_alone(source):
    task = _task(source)
    assert rc.migrate_consumable_link(task) is False
    assert task["source"] == source


def test_the_migration_drops_an_old_link_beside_a_list():
    task = _task({"parts": [LINK_B], "part": {**LINK_A, "manual": True}})
    assert rc.migrate_consumable_link(task) is True
    assert task["source"] == {"parts": [LINK_B]}


def test_the_migration_drops_a_malformed_old_link():
    task = _task({"part": {"manual": True}, "glue": {"x": 1}})
    assert rc.migrate_consumable_link(task) is True
    assert task["source"] == {"glue": {"x": 1}}


# ── prune_consumable_links ───────────────────────────────────────────────────


def test_prune_keeps_the_links_to_live_parts():
    task = _task({"parts": [LINK_A, LINK_B], "glue": {"x": 1}})
    pruned = rc.prune_consumable_links(task, lambda link: link["part_id"] == "p2")
    assert pruned == {"parts": [LINK_B], "glue": {"x": 1}}
    assert task["source"]["parts"] == [LINK_A, LINK_B], "the input is not mutated"


def test_prune_of_the_last_link_drops_the_key():
    task = _task({"parts": [LINK_A], "glue": {"x": 1}})
    assert rc.prune_consumable_links(task, lambda link: False) == {"glue": {"x": 1}}


def test_prune_of_the_only_namespace_gives_no_source():
    task = _task({"parts": [LINK_A]})
    assert rc.prune_consumable_links(task, lambda link: False) is None


def test_prune_with_nothing_to_drop_answers_the_same_source():
    task = _task({"parts": [LINK_A]})
    assert rc.prune_consumable_links(task, lambda link: True) is task["source"]
    plain = _task({"glue": {"x": 1}})
    assert rc.prune_consumable_links(plain, lambda link: False) is plain["source"]


def test_prune_leaves_an_old_link_to_the_migration():
    task = _task({"part": {**LINK_A, "manual": True}, "glue": {"x": 1}})
    assert rc.prune_consumable_links(task, lambda link: False) is task["source"]


def test_prune_leaves_a_wear_source():
    task = _task({"part": dict(LINK_A)})
    assert rc.prune_consumable_links(task, lambda link: False) is task["source"]


# ── reconcile_part_tasks clears links to removed parts ───────────────────────


def test_reconcile_drops_only_the_link_whose_part_was_removed():
    assets = {"a1": {"id": "a1", "name": "Water", "parts": [{"id": "p2"}]}}
    task = _task({"parts": [LINK_A, LINK_B], "glue": {"x": 1}})
    result, changed = rc.reconcile_part_tasks(assets, {"t1": task}, now=NOW)
    assert changed is True
    assert result["t1"]["source"] == {"parts": [LINK_B], "glue": {"x": 1}}


def test_reconcile_keeps_live_links_and_reports_no_change():
    parts = [{"id": "p1"}, {"id": "p2"}]
    assets = {"a1": {"id": "a1", "name": "Water", "parts": parts}}
    task = _task({"parts": [LINK_A, LINK_B]})
    result, changed = rc.reconcile_part_tasks(assets, {"t1": task}, now=NOW)
    assert changed is False
    assert result["t1"] is task


# ── refuse_mixed_link_forms ──────────────────────────────────────────────────


def test_a_list_alone_or_a_single_link_alone_is_accepted():
    rc.refuse_mixed_link_forms({"task_id": "t", "parts": []})
    rc.refuse_mixed_link_forms({"task_id": "t", "asset_id": "a", "part_id": "p"})
    # A single field that is None beside a list is not a second form.
    rc.refuse_mixed_link_forms({"parts": [LINK_A], "asset_id": None, "part_id": None})


@pytest.mark.parametrize(
    ("extra", "named"),
    [
        ({"asset_id": "a"}, "asset_id"),
        ({"part_id": "p"}, "part_id"),
        ({"quantity": 2}, "quantity"),
        ({"asset_id": "a", "part_id": "p"}, "asset_id, part_id"),
        # A falsy value is still a second form: it must not be ignored in silence.
        ({"quantity": 0}, "quantity"),
        ({"asset_id": ""}, "asset_id"),
    ],
)
def test_a_list_beside_a_single_field_is_refused(extra, named):
    with pytest.raises(rc.models.TaskValidationError) as err:
        rc.refuse_mixed_link_forms({"parts": [LINK_A], **extra})
    assert str(err.value) == f"send parts, or {named}, not both"


# ── ids that are not text (review item 7) ────────────────────────────────────


@pytest.mark.parametrize("bad", [["a1"], {"id": "a1"}, 7, None])
def test_a_link_with_an_id_that_is_not_text_is_skipped(bad):
    task = _task({"parts": [{"asset_id": bad, "part_id": "p1"}, LINK_B]})
    assert rc.consumable_links(task) == [LINK_B]
    task = _task({"parts": [{"asset_id": "a1", "part_id": bad}, LINK_B]})
    assert rc.consumable_links(task) == [LINK_B]


def test_reconcile_survives_a_hand_edited_id_that_is_a_list():
    assets = {"a1": {"id": "a1", "name": "Water", "parts": [{"id": "p2"}]}}
    task = _task({"parts": [{"asset_id": ["a1"], "part_id": "p1"}, LINK_B]})
    result, _changed = rc.reconcile_part_tasks(assets, {"t1": task}, now=NOW)
    assert rc.consumable_links(result["t1"]) == [LINK_B]
