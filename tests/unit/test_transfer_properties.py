"""The portable document's claims, over generated stores rather than one worked example.

`transfer.py`'s module docstring states three properties by name, the first being
"export emits exactly what import accepts". `test_transfer_roundtrip.py` checks it
against one *maximal* record per recurrence type — every optional field set. That is a
good smoke test and it has a blind spot shaped exactly like itself: a field that
survives when everything is set, but not when it is absent, empty or falsy, is a case a
maximal record can never produce.

These generate the store instead. Each property below also names a mutant that is alive
on `main` and that the property kills, because "would a test have failed" is the only
useful measure of whether an assertion is real.

Run just these: `pytest tests/unit -m property`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import hk_transfer as tr
import pytest

pytest.importorskip("hypothesis", reason="property-based tests need hypothesis")

import property_strategies as ps
from hypothesis import given, settings
from hypothesis import strategies as st

pytestmark = pytest.mark.property

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)


def _excluded(table: tuple[tuple[str, str], ...]) -> set[str]:
    return {key for key, _reason in table}


@settings(max_examples=60)
@given(
    tasks=st.lists(
        ps.tasks(now=NOW), min_size=1, max_size=5, unique_by=lambda t: t["name"]
    ),
    assets=st.lists(ps.assets(now=NOW), max_size=3, unique_by=lambda a: a["name"]),
)
def test_t1_export_then_import_is_a_clean_create_of_the_same_records(tasks, assets):
    """T1. Symmetry, over a generated store: everything travels, nothing is remarked on.

    `problems == ()` is the half that matters and the half `_compare` in
    test_transfer_roundtrip.py structurally cannot assert: it walks the keys of the
    record it started with, so a field the *importer* did not recognise is invisible to
    it. Warnings are not cosmetic here — the panel shows them, and "a field nobody read
    is data that did not arrive" is the reason they exist.

    Kills `transfer.x__task_out__mutmut_15` and `_16`, which rename the exported key to
    `EXTERNAL_ID`: the round-trip still matches on every other field, and only a
    complaint about an unknown key gives it away.
    """
    document = tr.build_document(tasks, assets, version="test", now=NOW)
    plan = tr.plan_import(document, tasks={}, assets={}, now=NOW)

    assert plan.problems == (), [p.as_dict() for p in plan.problems]
    assert plan.ok

    planned_tasks = plan.for_section("tasks")
    portable = [t for t in tasks if tr.is_portable_task(t)]
    assert len(planned_tasks) == len(portable)
    assert {record.action for record in planned_tasks} <= {"create"}

    drop = _excluded(tr.EXCLUDED_TASK_KEYS)
    for original, record in zip(portable, planned_tasks, strict=True):
        expected = {k: v for k, v in original.items() if k not in drop}
        assert {k: record.payload.get(k) for k in expected} == expected


@settings(max_examples=60)
@given(order=st.randoms(use_true_random=False), with_reading=st.booleans())
def test_t2a_folding_history_does_not_depend_on_the_order_it_arrives_in(
    order, with_reading
):
    """T2a. The same entries in a different order fold to the same task.

    `apply_history` sorts before replaying, because `recurrence.apply_completion` stamps
    `last_completed` from whichever entry it is handed, and the history cap keeps the
    *tail* of the list. Replaying 2019 last would leave a task claiming it was serviced
    seven years ago.

    Timestamps are distinct here on purpose. Two completions at the same instant are
    genuinely order-dependent — `_record_entry` replaces on a duplicate `ts`, so the
    last one written wins — and asserting otherwise would be a false property. That
    case is T2b's.
    """
    pool = ps.timestamp_pool(now=NOW)
    payload: dict = {"name": "Flush it", "interval": 6, "unit": "months"}
    if with_reading:
        payload = {
            "name": "Flush it",
            "recurrence_type": "sensor",
            "sensor": {"entity_id": "sensor.probe", "mode": "usage", "target": 100},
        }
    history = [
        {"completed_at": ts, **({"reading": 10 * (i + 1)} if with_reading else {})}
        for i, ts in enumerate(pool[:4])
    ]
    skips = [{"skipped_at": ts} for ts in pool[4:6]]

    straight = tr.models.build_task(dict(payload), now=NOW)
    tr.apply_history(straight, list(history), list(skips), now=NOW)

    shuffled_history, shuffled_skips = list(history), list(skips)
    order.shuffle(shuffled_history)
    order.shuffle(shuffled_skips)
    jumbled = tr.models.build_task(dict(payload), now=NOW)
    tr.apply_history(jumbled, shuffled_history, shuffled_skips, now=NOW)

    for field in ("completions", "skips", "last_completed", "next_due"):
        assert jumbled.get(field) == straight.get(field), field


@given(
    # Plain letters: a whitespace-only note is normalized away, which would make the
    # "which note survived" assertion below meaningless rather than wrong.
    notes=st.lists(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=8),
        min_size=2,
        max_size=4,
        unique=True,
    ),
    skip_too=st.booleans(),
)
def test_t2b_entries_at_the_same_instant_carrying_different_notes_are_accepted(
    notes, skip_too
):
    """T2b. Same-instant entries with unequal metadata fold without raising.

    A double-tapped notification action or a duplicated automation produces exactly
    this: two completions at one instant whose metadata differs. The document is a
    generated file, so it is a shape an import has to survive rather than one a user
    would type.

    Kills `transfer.x_apply_history__mutmut_38` (`events.sort(key=None)`). With no key,
    Python compares the whole `(datetime, bool, dict)` tuple; equal timestamps and equal
    is-a-completion flags send it into comparing two dicts, which raises `TypeError`.
    Distinct timestamps never reach the third element, which is why every existing
    history test leaves this mutant alive.
    """
    pool = ps.timestamp_pool(now=NOW)
    task = tr.models.build_task(
        {"name": "Flush it", "interval": 6, "unit": "months"}, now=NOW
    )
    history = [{"completed_at": pool[0], "note": note} for note in notes]
    skips = [{"skipped_at": pool[0]}] if skip_too else []

    counted = tr.apply_history(task, history, skips, now=NOW)

    assert counted == (len(history), len(skips))
    # Deduped to one entry at that instant, and it is one of the ones supplied.
    at_instant = [c for c in task["completions"] if c["ts"] == pool[0]]
    assert len(at_instant) == 1
    assert at_instant[0].get("note") in notes


@settings(max_examples=80)
@given(graph=ps.parent_graphs())
def test_t3_every_parent_loop_is_found_and_only_loops_are_reported(graph):
    """T3. `_looping_parents` returns exactly the planned records inside a loop.

    The function's own docstring makes a generative claim: "a single document can
    re-parent both halves of a loop in the same run: taken one at a time, each edge
    looks harmless, and only the pair is wrong." A generator is the honest way to test
    a claim phrased like that.

    Kills `transfer.x__looping_parents__mutmut_28`, which turns the loop's `continue`
    into a `break`: the scan then stops at the first record that is *not* cyclic, so it
    survives only because every hand-written test happens to put the cyclic record
    first. The path assertion kills `_mutmut_31` (`Problem(None, ...)`) and `_mutmut_32`
    (`record.index` replaced by `None`).
    """
    count, edges = graph
    ids = [f"asset-{i}" for i in range(count)]
    parent_of = {
        ids[child]: (ids[parent] if parent is not None else None)
        for child, parent in edges
    }

    records = [
        tr.PlannedRecord(
            "appliances",
            index,
            asset_id,
            "",
            f"Appliance {index}",
            "create",
            None,
            {"id": asset_id, "parent_asset_id": parent_of.get(asset_id)},
        )
        for index, asset_id in enumerate(ids)
    ]
    problems: list[tr.Problem] = []
    looped = tr._looping_parents(records, {}, problems)

    def has_cycle(start: str, links: dict[str, str | None]) -> bool:
        """Pigeonhole, not a seen-set.

        `assets.would_create_cycle` — which `_looping_parents` calls — decides this by
        tracking the nodes it has visited. Writing the oracle the same way would make
        the two share a misconception and agree wrongly. So: a chain through `n` nodes
        that has not ended after `n` hops must be revisiting one.
        """
        cursor = links.get(start)
        for _ in range(len(links) + 1):
            if cursor is None:
                return False
            cursor = links.get(cursor)
        return True

    expected = {asset_id for asset_id in ids if has_cycle(asset_id, parent_of)}
    assert looped == expected

    # Removing exactly those ids leaves a graph with no loop left in it.
    survivors = {k: v for k, v in parent_of.items() if k not in looped}
    assert not any(has_cycle(k, survivors) for k in survivors)

    # Every problem points at a record that is actually in the returned set.
    for problem in problems:
        assert problem.section == "appliances"
        index = int(problem.path.removeprefix("appliances[").split("]")[0])
        assert records[index].record_id in looped
        assert problem.path == f"appliances[{index}].parent_asset_id"


@given(
    reserved=st.lists(st.sampled_from(sorted(tr._RECONCILER_SOURCES)), max_size=3),
    foreign=st.lists(
        st.sampled_from(["pawsistant", "battery_notes", "acme", "vendor"]), max_size=3
    ),
)
def test_t4_only_a_reserved_source_makes_a_task_unportable(reserved, foreign):
    """T4. A task is unportable if and only if its source names a reconciler namespace.

    Kills `transfer.x_is_portable_task__mutmut_6`, which turns the set intersection into
    a union. A union is non-empty whenever the task has any source at all, so the mutant
    silently refuses to export every task a companion integration tagged with its own
    provenance — which is what `source` is for. It survives today because no existing
    test gives a task a source that is dict-shaped but *not* reserved.
    """
    source = {key: {"ref": "1"} for key in [*reserved, *foreign]}
    task = tr.models.build_task(
        {"name": "T", "interval": 1, "unit": "days", "source": source or None},
        now=NOW,
    )
    assert tr.is_portable_task(task) is not bool(reserved)
