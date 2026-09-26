"""The NFC/RFID binding a wear part hands to the task the reconciler derives from it.

A part carries ``tag_id``/``require_tag_scan``; exactly one of its tasks wears them —
the use task of a counted wear item, the maintenance task otherwise — and the other
half is kept clear. The part is the one place the binding is edited, so the
reconciler treats it like ``device_id``: created from it, re-derived on drift.
"""

from datetime import datetime, timedelta, timezone

import hk_reconcile as rc

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)


def _asset(aid="a1", name="Heater", parts=None, **extra):
    return {"id": aid, "name": name, "parts": parts or [], **extra}


def _wear_part(pid="p1", name="Anode", interval=12, unit="months", **extra):
    return {
        "id": pid,
        "name": name,
        "type": "wear",
        "replace_interval": interval,
        "replace_unit": unit,
        **extra,
    }


def _counted_part(pid="p1", name="DWR", target=25, **extra):
    return _wear_part(pid, name, target, "uses", **extra)


def _reconcile(assets, tasks=None):
    return rc.reconcile_part_tasks(assets, tasks or {}, now=NOW)


def _only(tasks):
    assert len(tasks) == 1, tasks
    return next(iter(tasks.values()))


def _by_role(tasks):
    """A counted part's 2 tasks, keyed ``use``/``replace``."""
    out = {rc.part_role(t): t for t in tasks.values() if rc.part_source(t)}
    assert set(out) == {"use", "replace"}, tasks
    return out


def _binding(task):
    return task.get("tag_id"), task.get("require_tag_scan")


# ── creation ──────────────────────────────────────────────────────────────────
def test_time_measured_part_puts_the_binding_on_its_task():
    asset = _asset(parts=[_wear_part(tag_id="anode-tag", require_tag_scan=True)])
    task = _only(_reconcile({"a1": asset})[0])
    assert _binding(task) == ("anode-tag", True)


def test_a_tag_without_the_flag_leaves_the_task_completable_from_anywhere():
    asset = _asset(parts=[_wear_part(tag_id="anode-tag")])
    assert _binding(_only(_reconcile({"a1": asset})[0])) == ("anode-tag", False)


def test_a_part_without_a_tag_creates_an_unbound_task():
    task = _only(_reconcile({"a1": _asset(parts=[_wear_part()])})[0])
    assert _binding(task) == (None, False)


def test_a_blank_tag_reads_as_none_on_the_task():
    """Storage is normalized, but the reconciler reads raw dicts: an empty string must
    not become a tag no scan can match."""
    task = _only(_reconcile({"a1": _asset(parts=[_wear_part(tag_id="")])})[0])
    assert task["tag_id"] is None


def test_a_flag_beside_no_tag_is_not_copied():
    """``models.build_task`` refuses the pair; the part normalizer never produces it,
    but a hand-edited storage document could."""
    asset = _asset(parts=[_wear_part(require_tag_scan=True)])
    assert _binding(_only(_reconcile({"a1": asset})[0])) == (None, False)


def test_counted_part_puts_the_binding_on_the_use_task_only():
    asset = _asset(parts=[_counted_part(tag_id="jacket-tag", require_tag_scan=True)])
    tasks = _by_role(_reconcile({"a1": asset})[0])
    assert _binding(tasks["use"]) == ("jacket-tag", True)
    # One tag, one task: a scan records a wear and never also replaces the coating.
    assert _binding(tasks["replace"]) == (None, False)


def test_counted_part_without_a_tag_creates_two_unbound_tasks():
    tasks = _by_role(_reconcile({"a1": _asset(parts=[_counted_part()])})[0])
    assert _binding(tasks["use"]) == (None, False)
    assert _binding(tasks["replace"]) == (None, False)


# ── drift ─────────────────────────────────────────────────────────────────────
def test_binding_a_tag_later_updates_the_task():
    tasks, _ = _reconcile({"a1": _asset(parts=[_wear_part()])})
    tasks, changed = _reconcile(
        {"a1": _asset(parts=[_wear_part(tag_id="anode-tag")])}, tasks
    )
    assert changed is True
    assert _binding(_only(tasks)) == ("anode-tag", False)


def test_changing_the_tag_updates_the_task():
    tasks, _ = _reconcile({"a1": _asset(parts=[_wear_part(tag_id="old-tag")])})
    tasks, changed = _reconcile(
        {"a1": _asset(parts=[_wear_part(tag_id="new-tag")])}, tasks
    )
    assert changed is True
    assert _only(tasks)["tag_id"] == "new-tag"


def test_turning_the_flag_on_alone_updates_the_task():
    tasks, _ = _reconcile({"a1": _asset(parts=[_wear_part(tag_id="anode-tag")])})
    tasks, changed = _reconcile(
        {"a1": _asset(parts=[_wear_part(tag_id="anode-tag", require_tag_scan=True)])},
        tasks,
    )
    assert changed is True
    assert _binding(_only(tasks)) == ("anode-tag", True)


def test_turning_the_flag_off_alone_updates_the_task():
    tasks, _ = _reconcile(
        {"a1": _asset(parts=[_wear_part(tag_id="anode-tag", require_tag_scan=True)])}
    )
    tasks, changed = _reconcile(
        {"a1": _asset(parts=[_wear_part(tag_id="anode-tag")])}, tasks
    )
    assert changed is True
    assert _binding(_only(tasks)) == ("anode-tag", False)


def test_clearing_the_tag_clears_the_flag_with_it():
    """Sent together on purpose: ``merge_update`` refuses a bare tag clear while the
    flag stands, and a task left demanding a scan of nothing could never be done."""
    tasks, _ = _reconcile(
        {"a1": _asset(parts=[_wear_part(tag_id="anode-tag", require_tag_scan=True)])}
    )
    tasks, changed = _reconcile({"a1": _asset(parts=[_wear_part()])}, tasks)
    assert changed is True
    assert _binding(_only(tasks)) == (None, False)


def test_an_unchanged_binding_is_not_churn():
    asset = _asset(parts=[_wear_part(tag_id="anode-tag", require_tag_scan=True)])
    tasks, _ = _reconcile({"a1": asset})
    again, changed = _reconcile({"a1": asset}, tasks)
    assert changed is False
    assert again == tasks


def test_a_flag_stored_as_a_missing_key_does_not_read_as_drift():
    """A task written before the field existed has no ``require_tag_scan`` at all; that
    is ``False``, not a change to re-save on every pass."""
    asset = _asset(parts=[_wear_part(tag_id="anode-tag")])
    tasks, _ = _reconcile({"a1": asset})
    task = _only(tasks)
    del task["require_tag_scan"]
    _again, changed = _reconcile({"a1": asset}, tasks)
    assert changed is False


def test_switching_to_uses_moves_the_tag_to_the_new_use_task():
    tasks, _ = _reconcile({"a1": _asset(parts=[_wear_part(tag_id="jacket-tag")])})
    replace_id = _only(tasks)["id"]
    tasks, changed = _reconcile(
        {"a1": _asset(parts=[_counted_part(tag_id="jacket-tag")])}, tasks
    )
    assert changed is True
    by_role = _by_role(tasks)
    # Same replacement task, converted — and no longer wearing the tag.
    assert by_role["replace"]["id"] == replace_id
    assert _binding(by_role["replace"]) == (None, False)
    assert _binding(by_role["use"]) == ("jacket-tag", False)


def test_switching_back_to_months_moves_the_tag_back():
    part = _counted_part(tag_id="jacket-tag", require_tag_scan=True)
    tasks, _ = _reconcile({"a1": _asset(parts=[part])})
    replace_id = _by_role(tasks)["replace"]["id"]
    tasks, changed = _reconcile(
        {"a1": _asset(parts=[_wear_part(tag_id="jacket-tag", require_tag_scan=True)])},
        tasks,
    )
    assert changed is True
    task = _only(tasks)
    assert task["id"] == replace_id
    assert _binding(task) == ("jacket-tag", True)


def test_a_manual_link_keeps_its_own_binding():
    """A user-owned task that merely consumes the part's stock is not the reconciler's
    to rebind — its tag is edited in the task form, as before."""
    manual = {
        "id": "t-manual",
        "name": "Descale",
        "recurrence_type": "floating",
        "interval": 3,
        "unit": "months",
        "enabled": True,
        "tag_id": "my-own-tag",
        "require_tag_scan": True,
        "source": {"part": {"asset_id": "a1", "part_id": "p1", "manual": True}},
    }
    asset = _asset(parts=[_wear_part(tag_id="anode-tag")])
    tasks, _ = _reconcile({"a1": asset}, {"t-manual": manual})
    assert _binding(tasks["t-manual"]) == ("my-own-tag", True)


# ── adopting a tag set on the task before parts carried one ───────────────────
def _derived(asset, part, tag_id=None, require=None, role=None):
    tasks, _ = _reconcile({asset["id"]: asset})
    task = _by_role(tasks)[role] if role else _only(tasks)
    if tag_id is not None:
        task["tag_id"] = tag_id
    if require is not None:
        task["require_tag_scan"] = require
    return tasks


def test_adopts_a_task_tag_onto_a_part_without_one():
    part = _wear_part()
    asset = _asset(parts=[part])
    tasks = _derived(asset, part, tag_id="legacy-tag", require=True)
    assert rc.adopt_part_tags({"a1": asset}, tasks) is True
    assert part["tag_id"] == "legacy-tag"
    assert part["require_tag_scan"] is True


def test_adoption_then_reconcile_keeps_the_binding():
    """The whole point: the first pass after the upgrade must not clear the tag."""
    part = _wear_part()
    asset = _asset(parts=[part])
    tasks = _derived(asset, part, tag_id="legacy-tag")
    rc.adopt_part_tags({"a1": asset}, tasks)
    tasks, changed = _reconcile({"a1": asset}, tasks)
    assert changed is False
    assert _binding(_only(tasks)) == ("legacy-tag", False)


def test_an_absent_flag_is_adopted_as_false():
    part = _wear_part()
    asset = _asset(parts=[part])
    tasks = _derived(asset, part, tag_id="legacy-tag")
    rc.adopt_part_tags({"a1": asset}, tasks)
    assert part["require_tag_scan"] is False


def test_does_not_overwrite_a_part_that_names_a_tag():
    part = _wear_part(tag_id="part-tag")
    asset = _asset(parts=[part])
    tasks = _derived(asset, part)
    _only(tasks)["tag_id"] = "task-tag"
    assert rc.adopt_part_tags({"a1": asset}, tasks) is False
    assert part["tag_id"] == "part-tag"


def test_ignores_an_untagged_task():
    part = _wear_part()
    asset = _asset(parts=[part])
    tasks = _derived(asset, part)
    assert rc.adopt_part_tags({"a1": asset}, tasks) is False
    assert "tag_id" not in part


def test_ignores_a_task_wearing_a_blank_tag():
    part = _wear_part()
    asset = _asset(parts=[part])
    tasks = _derived(asset, part, tag_id="")
    assert rc.adopt_part_tags({"a1": asset}, tasks) is False


def test_ignores_a_manual_link():
    part = _wear_part()
    asset = _asset(parts=[part])
    manual = {
        "id": "t-manual",
        "tag_id": "my-own-tag",
        "source": {"part": {"asset_id": "a1", "part_id": "p1", "manual": True}},
    }
    assert rc.adopt_part_tags({"a1": asset}, {"t-manual": manual}) is False
    assert "tag_id" not in part


def test_ignores_a_task_whose_role_the_tag_does_not_go_to():
    """A counted part's tag lives on its use task. A tag someone put on the replacement
    half is left for the reconciler to clear rather than moved to the wrong task."""
    part = _counted_part()
    asset = _asset(parts=[part])
    tasks = _derived(asset, part, tag_id="legacy-tag", role="replace")
    assert rc.adopt_part_tags({"a1": asset}, tasks) is False
    assert "tag_id" not in part


def test_adopts_from_the_use_task_of_a_counted_part():
    part = _counted_part()
    asset = _asset(parts=[part])
    tasks = _derived(asset, part, tag_id="jacket-tag", role="use")
    assert rc.adopt_part_tags({"a1": asset}, tasks) is True
    assert part["tag_id"] == "jacket-tag"


def test_ignores_a_task_whose_part_is_gone():
    part = _wear_part()
    asset = _asset(parts=[part])
    tasks = _derived(asset, part, tag_id="legacy-tag")
    assert rc.adopt_part_tags({"a1": _asset(parts=[])}, tasks) is False


def test_ignores_a_part_with_no_id():
    part = _wear_part()
    asset = _asset(parts=[part])
    tasks = _derived(asset, part, tag_id="legacy-tag")
    del part["id"]
    assert rc.adopt_part_tags({"a1": asset}, tasks) is False


def test_an_asset_with_no_parts_key_is_skipped_not_crashed():
    """A bare asset record has no ``parts`` at all; the index reads it as empty."""
    part = _wear_part()
    asset = _asset(parts=[part])
    tasks = _derived(asset, part, tag_id="legacy-tag")
    bare = {"id": "a2", "name": "Bare"}
    assert rc.adopt_part_tags({"a2": bare, "a1": asset}, tasks) is True
    assert part["tag_id"] == "legacy-tag"


def test_a_skipped_task_does_not_stop_the_sweep():
    """One task the sweep passes over must not end it for the tasks after it."""
    taken = _wear_part(pid="p1", tag_id="own-tag")
    bare = _wear_part(pid="p2", name="Filter")
    asset = _asset(parts=[taken, bare])
    tasks, _ = _reconcile({"a1": asset})
    by_part = {rc.part_source(t)["part_id"]: t for t in tasks.values()}
    # The passed-over task comes first in iteration order.
    ordered = {
        by_part["p1"]["id"]: {**by_part["p1"], "tag_id": "task-tag"},
        by_part["p2"]["id"]: {**by_part["p2"], "tag_id": "legacy-tag"},
    }
    assert rc.adopt_part_tags({"a1": asset}, ordered) is True
    assert taken["tag_id"] == "own-tag"
    assert bare["tag_id"] == "legacy-tag"


# ── a tag the part cannot hold, named for the upgrade log ─────────────────────
def test_names_a_tag_on_a_counted_parts_maintenance_task():
    """Both halves tagged before the upgrade: the use task's tag moves to the part,
    and the maintenance task's tag is named, because the next pass clears it."""
    part = _counted_part()
    asset = _asset(parts=[part])
    tasks = _derived(asset, part, tag_id="use-tag", role="use")
    replace = _by_role(tasks)["replace"]
    replace["tag_id"] = "replace-tag"
    rc.adopt_part_tags({"a1": asset}, tasks)
    assert rc.stray_part_tags({"a1": asset}, tasks) == [
        {"task_id": replace["id"], "name": replace["name"], "tag_id": "replace-tag"}
    ]
    tasks, _ = _reconcile({"a1": asset}, tasks)
    assert _binding(_by_role(tasks)["replace"]) == (None, False)
    assert _binding(_by_role(tasks)["use"]) == ("use-tag", False)


def test_names_a_task_tag_that_differs_from_the_parts_own():
    part = _wear_part(tag_id="part-tag")
    asset = _asset(parts=[part])
    tasks = _derived(asset, part)
    _only(tasks)["tag_id"] = "task-tag"
    stray = rc.stray_part_tags({"a1": asset}, tasks)
    assert [s["tag_id"] for s in stray] == ["task-tag"]


def test_names_nothing_once_the_part_holds_the_tag():
    part = _wear_part()
    asset = _asset(parts=[part])
    tasks = _derived(asset, part, tag_id="legacy-tag")
    rc.adopt_part_tags({"a1": asset}, tasks)
    assert rc.stray_part_tags({"a1": asset}, tasks) == []


def test_names_no_manual_link_no_untagged_task_and_no_orphan():
    part = _wear_part()
    asset = _asset(parts=[part])
    tasks = _derived(asset, part)
    tasks["t-manual"] = {
        "id": "t-manual",
        "tag_id": "my-own-tag",
        "source": {"part": {"asset_id": "a1", "part_id": "p1", "manual": True}},
    }
    tasks["t-orphan"] = {
        "id": "t-orphan",
        "tag_id": "gone-tag",
        "source": {"part": {"asset_id": "a1", "part_id": "gone", "role": "replace"}},
    }
    assert rc.stray_part_tags({"a1": asset}, tasks) == []


# ── update_task may not change a tag the part owns ────────────────────────────
def _tagged_task(tag_id="anode-tag", require=True):
    part = _wear_part(tag_id=tag_id, require_tag_scan=require)
    return _only(_reconcile({"a1": _asset(parts=[part])})[0])


def test_changing_the_tag_on_a_derived_task_is_refused():
    task = _tagged_task()
    assert rc.is_part_owned_tag_update(task, {"tag_id": "other"}) is True
    assert rc.is_part_owned_tag_update(task, {"tag_id": None}) is True


def test_changing_the_flag_on_a_derived_task_is_refused():
    task = _tagged_task()
    assert rc.is_part_owned_tag_update(task, {"require_tag_scan": False}) is True


def test_sending_the_current_binding_back_is_not_a_change():
    """A caller that sends the whole task back, tag included, is not refused."""
    task = _tagged_task()
    updates = {"tag_id": " anode-tag ", "require_tag_scan": True, "notes": "x"}
    assert rc.is_part_owned_tag_update(task, updates) is False


def test_an_update_without_tag_keys_is_not_refused():
    assert rc.is_part_owned_tag_update(_tagged_task(), {"notes": "x"}) is False


def test_a_manual_link_and_a_plain_task_keep_their_own_tag():
    manual = {
        "id": "t-manual",
        "tag_id": None,
        "source": {"part": {"asset_id": "a1", "part_id": "p1", "manual": True}},
    }
    assert rc.is_part_owned_tag_update(manual, {"tag_id": "x"}) is False
    assert rc.is_part_owned_tag_update({"id": "t"}, {"tag_id": "x"}) is False


def test_a_skipped_task_does_not_stop_the_stray_sweep():
    """An untagged task and a task whose part is gone come first; the stray tag after
    them is still named. An asset with no ``parts`` key is skipped, not crashed."""
    part = _wear_part(tag_id="part-tag")
    asset = _asset(parts=[part])
    derived = _only(_derived(asset, part))
    derived["tag_id"] = "task-tag"
    tasks = {
        "t-plain": {"id": "t-plain", "tag_id": None},
        "t-orphan": {
            "id": "t-orphan",
            "tag_id": "gone-tag",
            "source": {"part": {"asset_id": "a1", "part_id": "gone"}},
        },
        derived["id"]: derived,
    }
    bare = {"id": "a2", "name": "Bare"}
    stray = rc.stray_part_tags({"a2": bare, "a1": asset}, tasks)
    assert [s["task_id"] for s in stray] == [derived["id"]]
