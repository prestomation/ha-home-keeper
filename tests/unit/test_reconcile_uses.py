"""Unit tests for counted wear items — the ``uses`` half of the reconciler.

A wear part measured in uses generates 2 tasks instead of 1: a **use task** the
household completes once per use, and a **replacement task** that arms once the count
reaches the target or the optional time backstop elapses. These exercise the pure
reconciler and the pure settle step directly, with no Home Assistant runtime.
"""

from datetime import UTC, datetime, timedelta, timezone

import hk_reconcile as rc
import hk_recurrence as recurrence
import pytest

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 6, 13, 10, tzinfo=TZ)


def _asset(aid="a1", name="Rain jacket", parts=None, **extra):
    return {"id": aid, "name": name, "parts": parts or [], **extra}


def _counted_part(pid="p1", name="DWR", target=25, **extra):
    """A wear part measured in uses. Mirrors what ``assets._normalize_part`` writes."""
    return {
        "id": pid,
        "name": name,
        "type": "wear",
        "replace_interval": target,
        "replace_unit": "uses",
        "replace_also_every": None,
        "action": "replace",
        "use_noun": "wear",
        "use_task_name": "",
        **extra,
    }


def _reconcile(assets, tasks=None, **kwargs):
    return rc.reconcile_part_tasks(assets, tasks or {}, now=NOW, **kwargs)


def _by_role(tasks):
    out = {}
    for task in tasks.values():
        out[rc.part_role(task)] = task
    return out


def _complete(task, when):
    """Record a use at *when*, the way ``recurrence.apply_completion`` does."""
    task.setdefault("completions", []).append({"ts": when.isoformat()})
    task["last_completed"] = when.isoformat()


def _uses(task, count, *, start=None):
    """Record *count* uses, one per hour, ending before NOW."""
    first = start or (NOW - timedelta(hours=count + 1))
    for i in range(count):
        _complete(task, first + timedelta(hours=i))


# ── the pair ──────────────────────────────────────────────────────────────────
def test_counted_part_generates_both_tasks():
    tasks, changed = _reconcile({"a1": _asset(parts=[_counted_part()])})
    assert changed is True
    assert len(tasks) == 2
    roles = _by_role(tasks)
    assert roles["use"]["name"] == "Use Rain jacket"
    assert roles["use"]["recurrence_type"] == "use"
    assert roles["replace"]["name"] == "Replace DWR (Rain jacket)"
    assert roles["replace"]["recurrence_type"] == "triggered"


def test_time_measured_part_still_generates_one_task():
    """The existing shape is untouched: months means 1 floating task, no use task."""
    part = {
        "id": "p1",
        "name": "Anode",
        "type": "wear",
        "replace_interval": 12,
        "replace_unit": "months",
    }
    tasks, _ = _reconcile({"a1": _asset(parts=[part])})
    assert len(tasks) == 1
    task = next(iter(tasks.values()))
    assert task["recurrence_type"] == "floating"
    # No role written for the replacement half, so a wear part in the wild keeps the
    # exact source it already had.
    assert task["source"]["part"] == {"asset_id": "a1", "part_id": "p1"}


def test_use_task_carries_its_role_in_the_source():
    tasks, _ = _reconcile({"a1": _asset(parts=[_counted_part()])})
    use = _by_role(tasks)["use"]
    assert use["source"]["part"] == {
        "asset_id": "a1",
        "part_id": "p1",
        "role": "use",
    }


def test_use_task_is_never_due():
    tasks, _ = _reconcile({"a1": _asset(parts=[_counted_part()])})
    assert _by_role(tasks)["use"]["next_due"] is None


def test_replacement_task_is_born_dormant():
    """``build_task`` arms a triggered task; a counted wear item has earned nothing.

    Without the explicit reset in the reconciler every counted wear item would ship
    overdue the moment its part is saved.
    """
    tasks, _ = _reconcile({"a1": _asset(parts=[_counted_part()])})
    assert _by_role(tasks)["replace"]["next_due"] is None


def test_part_may_name_its_own_use_task():
    part = _counted_part(use_task_name="Wear rain jacket")
    tasks, _ = _reconcile({"a1": _asset(parts=[part])})
    assert _by_role(tasks)["use"]["name"] == "Wear rain jacket"


def test_action_picks_the_replacement_task_name():
    part = _counted_part(action="renew")
    tasks, _ = _reconcile({"a1": _asset(parts=[part])}, language="en")
    assert _by_role(tasks)["replace"]["name"] == "Renew DWR (Rain jacket)"


def test_action_name_is_localized():
    part = _counted_part(action="clean")
    tasks, _ = _reconcile({"a1": _asset(parts=[part])}, language="de")
    assert _by_role(tasks)["replace"]["name"] == "DWR reinigen (Rain jacket)"


def test_replace_action_uses_the_caller_supplied_template():
    """The default action keeps the caller's string, so no existing name moves."""
    part = _counted_part(action="replace")
    tasks, _ = _reconcile(
        {"a1": _asset(parts=[part])},
        name_template="Wymień {part} ({asset})",
        language="pl",
    )
    assert _by_role(tasks)["replace"]["name"] == "Wymień DWR (Rain jacket)"


# ── the index keeps 2 tasks per part apart ────────────────────────────────────
def test_reconcile_is_idempotent_for_a_pair():
    """Keyed by the part alone the 2 tasks collide and one is deleted every pass."""
    assets = {"a1": _asset(parts=[_counted_part()])}
    first, _ = _reconcile(assets)
    second, changed = _reconcile(assets, dict(first))
    assert changed is False
    assert set(second) == set(first)


def test_orphan_removes_both_tasks():
    assets = {"a1": _asset(parts=[_counted_part()])}
    tasks, _ = _reconcile(assets)
    assert len(tasks) == 2
    emptied, changed = _reconcile({"a1": _asset(parts=[])}, dict(tasks))
    assert changed is True
    assert emptied == {}


def test_switching_from_uses_to_months_retires_the_use_task():
    assets = {"a1": _asset(parts=[_counted_part()])}
    tasks, _ = _reconcile(assets)
    timed = {
        "id": "p1",
        "name": "DWR",
        "type": "wear",
        "replace_interval": 12,
        "replace_unit": "months",
    }
    after, changed = _reconcile({"a1": _asset(parts=[timed])}, dict(tasks))
    assert changed is True
    assert len(after) == 1
    task = next(iter(after.values()))
    assert task["recurrence_type"] == "floating"
    assert task["next_due"] is not None


def test_switching_from_months_to_uses_starts_the_cycle_dormant():
    """Converting into a triggered task arms it; a fresh count has earned nothing."""
    timed = {
        "id": "p1",
        "name": "DWR",
        "type": "wear",
        "replace_interval": 12,
        "replace_unit": "months",
    }
    tasks, _ = _reconcile({"a1": _asset(parts=[timed])})
    after, changed = _reconcile({"a1": _asset(parts=[_counted_part()])}, dict(tasks))
    assert changed is True
    roles = _by_role(after)
    assert roles["replace"]["recurrence_type"] == "triggered"
    assert roles["replace"]["next_due"] is None


# ── the count ─────────────────────────────────────────────────────────────────
def test_count_is_every_completion_before_the_first_replacement():
    use = {"completions": []}
    _uses(use, 7)
    assert rc.uses_since_replacement(use, {"last_completed": None}) == 7


def test_count_restarts_after_a_replacement():
    use = {"completions": []}
    _uses(use, 5, start=NOW - timedelta(days=10))
    replaced_at = NOW - timedelta(days=5)
    _uses(use, 3, start=NOW - timedelta(days=2))
    assert (
        rc.uses_since_replacement(use, {"last_completed": replaced_at.isoformat()}) == 3
    )


def test_a_completion_exactly_at_the_replacement_does_not_count():
    """The replacement itself is the boundary, and it is not a use of the part."""
    when = NOW - timedelta(days=1)
    use = {"completions": [{"ts": when.isoformat()}]}
    assert rc.uses_since_replacement(use, {"last_completed": when.isoformat()}) == 0


def test_count_compares_instants_not_strings():
    """A history that has seen a timezone change holds mixed offsets."""
    replaced_at = datetime(2026, 6, 12, 20, tzinfo=UTC)
    later = replaced_at + timedelta(hours=1)
    use = {"completions": [{"ts": later.astimezone(TZ).isoformat()}]}
    assert (
        rc.uses_since_replacement(use, {"last_completed": replaced_at.isoformat()}) == 1
    )


def test_a_malformed_completion_does_not_take_the_count_down():
    use = {"completions": [{"ts": "not-a-date"}, {"ts": NOW.isoformat()}]}
    assert rc.uses_since_replacement(use, {"last_completed": None}) == 2


# ── arming ────────────────────────────────────────────────────────────────────
def _pair(part=None, uses=0, replaced_at=None):
    part = part or _counted_part()
    assets = {"a1": _asset(parts=[part])}
    tasks, _ = _reconcile(assets)
    roles = _by_role(tasks)
    _uses(roles["use"], uses)
    if replaced_at is not None:
        roles["replace"]["last_completed"] = replaced_at.isoformat()
    return assets, tasks, roles


def test_replacement_arms_at_the_target():
    assets, tasks, roles = _pair(uses=25)
    to_arm, _ = rc.settle_use_tasks(assets, tasks, now=NOW)
    assert to_arm == [roles["replace"]["id"]]


def test_replacement_stays_dormant_below_the_target():
    assets, tasks, _ = _pair(uses=24)
    to_arm, _ = rc.settle_use_tasks(assets, tasks, now=NOW)
    assert to_arm == []


def test_an_already_armed_replacement_is_not_armed_again():
    """Otherwise a count left running past the target fires an event every tick."""
    assets, tasks, roles = _pair(uses=30)
    roles["replace"]["next_due"] = NOW.isoformat()
    to_arm, _ = rc.settle_use_tasks(assets, tasks, now=NOW)
    assert to_arm == []


def test_time_backstop_arms_on_time_alone():
    part = _counted_part(replace_also_every={"interval": 12, "unit": "months"})
    assets, tasks, roles = _pair(
        part=part, uses=2, replaced_at=NOW - timedelta(days=400)
    )
    to_arm, _ = rc.settle_use_tasks(assets, tasks, now=NOW)
    assert to_arm == [roles["replace"]["id"]]


def test_time_backstop_does_not_arm_early():
    part = _counted_part(replace_also_every={"interval": 12, "unit": "months"})
    assets, tasks, _ = _pair(part=part, uses=2, replaced_at=NOW - timedelta(days=30))
    to_arm, _ = rc.settle_use_tasks(assets, tasks, now=NOW)
    assert to_arm == []


def test_count_still_arms_when_a_backstop_is_set():
    """Whichever comes first — the count is not gated on the clock."""
    part = _counted_part(replace_also_every={"interval": 12, "unit": "months"})
    assets, tasks, roles = _pair(
        part=part, uses=25, replaced_at=NOW - timedelta(days=30)
    )
    to_arm, _ = rc.settle_use_tasks(assets, tasks, now=NOW)
    assert to_arm == [roles["replace"]["id"]]


def test_backstop_falls_back_to_last_replaced_before_any_completion():
    part = _counted_part(
        replace_also_every={"interval": 1, "unit": "months"},
        last_replaced="2020-01-01",
    )
    assets, tasks, roles = _pair(part=part, uses=0)
    to_arm, _ = rc.settle_use_tasks(assets, tasks, now=NOW)
    assert to_arm == [roles["replace"]["id"]]


def test_a_part_with_no_backstop_never_arms_on_time():
    assets, tasks, _ = _pair(uses=1, replaced_at=NOW - timedelta(days=4000))
    to_arm, _ = rc.settle_use_tasks(assets, tasks, now=NOW)
    assert to_arm == []


# ── the trim ──────────────────────────────────────────────────────────────────
def test_trim_keeps_two_targets_worth():
    use = {"completions": []}
    _uses(use, 80)
    assert rc.trim_use_completions(use, {"last_completed": NOW.isoformat()}, cap=50)
    assert len(use["completions"]) == 50


def test_trim_is_a_no_op_below_the_cap():
    use = {"completions": []}
    _uses(use, 10)
    assert not rc.trim_use_completions(use, {"last_completed": None}, cap=50)
    assert len(use["completions"]) == 10


def test_trim_never_eats_a_load_bearing_entry():
    """The entries since the last replacement *are* the count.

    Dropping one lowers the count silently, and the replacement task then never comes
    due — with nothing on any surface to say why.
    """
    use = {"completions": []}
    _uses(use, 200)
    replace = {"last_completed": None}
    before = rc.uses_since_replacement(use, replace)
    rc.trim_use_completions(use, replace, cap=50)
    assert rc.uses_since_replacement(use, replace) == before


def test_trim_drops_the_oldest_first():
    use = {"completions": []}
    _uses(use, 60)
    newest = use["completions"][-1]["ts"]
    oldest = use["completions"][0]["ts"]
    rc.trim_use_completions(use, {"last_completed": NOW.isoformat()}, cap=50)
    stamps = [entry["ts"] for entry in use["completions"]]
    assert newest in stamps
    assert oldest not in stamps


def test_settle_reports_a_trim():
    part = _counted_part(target=25)
    assets, tasks, roles = _pair(part=part, uses=200, replaced_at=NOW)
    _, trimmed = rc.settle_use_tasks(assets, tasks, now=NOW)
    assert trimmed is True
    # 2 x 25 = 50, the retention cap for a 25-use target.
    assert len(roles["use"]["completions"]) == 50


# ── pairing ───────────────────────────────────────────────────────────────────
def test_a_half_pair_is_skipped_rather_than_half_processed():
    assets, tasks, roles = _pair(uses=25)
    del tasks[roles["use"]["id"]]
    to_arm, trimmed = rc.settle_use_tasks(assets, tasks, now=NOW)
    assert to_arm == []
    assert trimmed is False


def test_is_use_task_reads_both_the_type_and_the_role():
    tasks, _ = _reconcile({"a1": _asset(parts=[_counted_part()])})
    roles = _by_role(tasks)
    assert rc.is_use_task(roles["use"]) is True
    assert rc.is_use_task(roles["replace"]) is False


@pytest.mark.parametrize(
    "task",
    [
        {},
        {"source": None},
        {"source": {"part": {"asset_id": "a1", "part_id": "p1"}}},
        {"source": {"part": {"asset_id": "a1", "part_id": "p1", "role": "replace"}}},
    ],
)
def test_an_absent_role_reads_as_replace(task):
    """The whole migration: a task written before counted wear items keeps identity."""
    assert rc.part_role(task) == "replace"


# ── skip restarts the cycle ───────────────────────────────────────────────────
def _skip(task, when):
    """Log a skip at *when*, the way ``recurrence.skip_occurrence`` does."""
    task.setdefault("skips", []).append({"ts": when.isoformat()})
    task["next_due"] = None


def test_a_skipped_replacement_is_not_armed_again():
    """Skip means "not this cycle", so it must restart the count.

    ``skip_occurrence`` leaves ``last_completed`` alone by contract and sets
    ``next_due`` to None, which is exactly the state ``settle_use_tasks`` arms from.
    Without the skip in the marker the task re-arms on the next coordinator tick and
    fires a fresh ``home_keeper_task_triggered``, so Skip is a no-op that bounces
    straight back. This is #268 in a new place.
    """
    assets, tasks, roles = _pair(uses=25)
    to_arm, _ = rc.settle_use_tasks(assets, tasks, now=NOW)
    assert to_arm == [roles["replace"]["id"]]
    _skip(roles["replace"], NOW)
    to_arm, _ = rc.settle_use_tasks(assets, tasks, now=NOW + timedelta(minutes=5))
    assert to_arm == []


def test_a_skip_restarts_the_count_from_zero():
    _assets, _tasks, roles = _pair(uses=25)
    _skip(roles["replace"], NOW)
    assert rc.uses_since_replacement(roles["use"], roles["replace"]) == 0


def test_uses_recorded_after_a_skip_count_again():
    _assets, _tasks, roles = _pair(uses=25)
    _skip(roles["replace"], NOW)
    _complete(roles["use"], NOW + timedelta(hours=1))
    assert rc.uses_since_replacement(roles["use"], roles["replace"]) == 1


def test_a_skip_restarts_the_time_backstop():
    """The backstop measures from the same instant the count does."""
    part = _counted_part(replace_also_every={"interval": 12, "unit": "months"})
    assets, tasks, roles = _pair(
        part=part, uses=2, replaced_at=NOW - timedelta(days=400)
    )
    _skip(roles["replace"], NOW)
    to_arm, _ = rc.settle_use_tasks(assets, tasks, now=NOW + timedelta(minutes=5))
    assert to_arm == []


def test_a_completion_later_than_the_skip_still_marks_the_cycle():
    """The marker is the newer of the 2, so replacing after a skip wins."""
    _assets, _tasks, roles = _pair(uses=25)
    _skip(roles["replace"], NOW - timedelta(days=2))
    roles["replace"]["last_completed"] = NOW.isoformat()
    _complete(roles["use"], NOW + timedelta(hours=1))
    assert rc.uses_since_replacement(roles["use"], roles["replace"]) == 1


def test_an_unparseable_skip_does_not_take_the_count_down():
    """A skip log travels through import and is user-editable, like a completion."""
    _assets, _tasks, roles = _pair(uses=25)
    roles["replace"]["skips"] = [{"ts": "not-a-date"}]
    assert rc.uses_since_replacement(roles["use"], roles["replace"]) == 25


def test_a_disabled_replacement_task_is_not_armed():
    """Its twin the sensor watcher reads ``enabled``; this step must too.

    Arming a disabled task fires ``home_keeper_task_triggered`` at a device trigger
    nobody asked for, and leaves the task armed and overdue the moment it is
    re-enabled.
    """
    assets, tasks, roles = _pair(uses=25)
    roles["replace"]["enabled"] = False
    to_arm, _ = rc.settle_use_tasks(assets, tasks, now=NOW)
    assert to_arm == []


# ── a count carried in by an import ───────────────────────────────────────────
def test_a_carried_count_is_added_while_the_cycle_has_never_started():
    """The import case: the reconciler mints both halves fresh, with an empty log.

    The count *is* the use task's completion log, and neither derived task travels in
    the portable document, so a jacket at 24 of 25 wears came back at 0 of 25. The
    carry is what the document brings instead.
    """
    part = _counted_part(carried_uses=24)
    assets = {"a1": _asset(parts=[part])}
    tasks, _ = _reconcile(assets)
    roles = _by_role(tasks)
    assert rc.counted_uses(roles["use"], roles["replace"], part) == 24


def test_a_carried_count_adds_to_the_entries_recorded_here():
    part = _counted_part(carried_uses=20)
    assets = {"a1": _asset(parts=[part])}
    tasks, _ = _reconcile(assets)
    roles = _by_role(tasks)
    _uses(roles["use"], 3)
    assert rc.counted_uses(roles["use"], roles["replace"], part) == 23


def test_a_carried_count_arms_the_replacement_at_the_target():
    """The thing a user actually feels: the reminder still comes at 25."""
    part = _counted_part(target=25, carried_uses=24)
    assets = {"a1": _asset(parts=[part])}
    tasks, _ = _reconcile(assets)
    roles = _by_role(tasks)
    to_arm, _ = rc.settle_use_tasks(assets, tasks, now=NOW)
    assert to_arm == []
    _uses(roles["use"], 1)
    to_arm, _ = rc.settle_use_tasks(assets, tasks, now=NOW)
    assert to_arm == [roles["replace"]["id"]]


def test_a_carried_count_retires_itself_on_the_first_completion():
    """It self-expires, which is why there is no reset anywhere.

    The carry means "uses counted before this record arrived". Once the replacement
    task has been completed here, the log on this install is the whole truth.
    """
    part = _counted_part(carried_uses=24)
    assets = {"a1": _asset(parts=[part])}
    tasks, _ = _reconcile(assets)
    roles = _by_role(tasks)
    roles["replace"]["last_completed"] = NOW.isoformat()
    _complete(roles["use"], NOW + timedelta(hours=1))
    assert rc.counted_uses(roles["use"], roles["replace"], part) == 1


def test_a_carried_count_retires_itself_on_the_first_skip():
    """A skip starts the next cycle too, so it retires the carry the same way."""
    part = _counted_part(carried_uses=24)
    assets = {"a1": _asset(parts=[part])}
    tasks, _ = _reconcile(assets)
    roles = _by_role(tasks)
    _skip(roles["replace"], NOW)
    assert rc.counted_uses(roles["use"], roles["replace"], part) == 0


def test_a_part_with_no_carry_counts_exactly_what_it_did_before():
    part = _counted_part()
    assets = {"a1": _asset(parts=[part])}
    tasks, _ = _reconcile(assets)
    roles = _by_role(tasks)
    _uses(roles["use"], 6)
    assert rc.counted_uses(roles["use"], roles["replace"], part) == 6
    assert rc.uses_since_replacement(roles["use"], roles["replace"]) == 6


def test_the_trim_never_sees_the_carry():
    """``trim_use_completions`` protects the live window, which is the log alone.

    Routing the carry through it would inflate ``keep`` by up to 500 entries and grow
    retention for a figure that is not in the log at all.
    """
    part = _counted_part(target=3, carried_uses=200)
    assets = {"a1": _asset(parts=[part])}
    tasks, _ = _reconcile(assets)
    roles = _by_role(tasks)
    _uses(roles["use"], 80)
    cap = rc.use_retention_cap(part)
    trimmed = rc.trim_use_completions(roles["use"], roles["replace"], cap=cap)
    with_carry = len(roles["use"]["completions"])

    plain = _counted_part(target=3)
    assets2 = {"a1": _asset(parts=[plain])}
    tasks2, _ = _reconcile(assets2)
    roles2 = _by_role(tasks2)
    _uses(roles2["use"], 80)
    trimmed2 = rc.trim_use_completions(roles2["use"], roles2["replace"], cap=cap)
    assert (trimmed, with_carry) == (trimmed2, len(roles2["use"]["completions"]))


def test_undoing_a_replacement_brings_the_carried_count_back():
    """The carry revives when the completion that retired it is deleted, and should.

    The question this pins: ``counted_uses`` adds the carry only while
    :func:`cycle_start` is None, and deleting a replacement task's only completion
    through the history dialog puts it back to None. So the carry returns.

    That is right, not a leak. Deleting the completion says the replacement never
    happened, so the cycle it started never happened either — and the honest count is
    the one the part arrived with plus everything recorded since. The alternative,
    a carry that expires on first contact and never returns, would silently lose 24
    wears the moment a household corrected a mistaken Done.
    """
    part = _counted_part(carried_uses=24)
    assets = {"a1": _asset(parts=[part])}
    tasks, _ = _reconcile(assets)
    roles = _by_role(tasks)
    use, replace = roles["use"], roles["replace"]

    assert rc.counted_uses(use, replace, part) == 24
    recurrence.apply_completion(replace, NOW, now=NOW)
    assert rc.counted_uses(use, replace, part) == 0

    _uses(use, 30, start=NOW + timedelta(hours=1))
    assert rc.counted_uses(use, replace, part) == 30

    recurrence.remove_completion(replace, replace["completions"][0]["ts"], now=NOW)
    assert rc.cycle_start(replace) is None
    assert rc.counted_uses(use, replace, part) == 54


def test_deleting_the_skip_that_retired_the_carry_brings_it_back_too():
    """A skip starts a cycle, so undoing one undoes that cycle, symmetrically."""
    part = _counted_part(carried_uses=24)
    assets = {"a1": _asset(parts=[part])}
    tasks, _ = _reconcile(assets)
    roles = _by_role(tasks)
    use, replace = roles["use"], roles["replace"]

    _skip(replace, NOW)
    assert rc.counted_uses(use, replace, part) == 0
    replace["skips"] = []
    assert rc.counted_uses(use, replace, part) == 24
