"""Skipping a usage task actually defers it (issue #268).

Before this, skipping a meter task was a no-op that bounced straight back: it cleared
``next_due`` but left ``sensor.baseline`` alone, so ``evaluate_usage`` still saw the
target exceeded and re-armed the task on the very next watcher tick. Fixing it takes
two halves, and only doing the first leaves the bug half-alive — with the default
``combinator: "any"``, an elapsed time backstop re-arms the task no matter where the
meter stands. These tests pin both halves and the undo path.
"""

from datetime import datetime, timedelta, timezone

import hk_recurrence as r
import hk_sensor_tasks as st

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 8, 30, 9, tzinfo=TZ)


def usage_task(**sensor_over):
    """ "Change the oil every 5,000 miles", meter last anchored at 25,000."""
    sensor = {
        "mode": "usage",
        "entity_id": "sensor.odometer",
        "target": 5000,
        "baseline": 25000,
    }
    sensor.update(sensor_over)
    return {
        "id": "t1",
        "recurrence_type": "sensor",
        "created": "2026-01-01T00:00:00-04:00",
        "last_completed": None,
        "completions": [],
        "skips": [],
        "next_due": NOW.isoformat(),
        "sensor": sensor,
    }


def skip(task, *, now=NOW, reading=None):
    """What ``store.skip_task`` does: advance the schedule, then reset the meter."""
    metadata = {"reading": reading} if reading is not None else {}
    out = r.skip_occurrence(dict(task), now=now, metadata=metadata)
    out["sensor"] = dict(task["sensor"])
    if reading is not None:
        out["skips"][-1]["meter_start"] = out["sensor"].get("baseline")
        out["sensor"]["baseline"] = reading
    return out


# ── the regression ──────────────────────────────────────────────────────────


def test_an_unskipped_usage_task_arms_once_the_meter_passes_its_target():
    task = usage_task()
    task["next_due"] = None  # dormant, waiting on the meter
    assert st.evaluate_usage(task, reading=30000, now=NOW)["action"] == st.ACTION_ARM


def test_skipping_a_usage_task_does_not_re_arm_it_on_the_next_tick():
    """The bug: with the baseline left behind, this returned ``arm`` immediately."""
    out = skip(usage_task(), reading=30000)
    assert out["sensor"]["baseline"] == 30000
    assert st.evaluate_usage(out, reading=30000, now=NOW)["action"] is None


def test_a_skipped_usage_task_comes_due_one_full_interval_later():
    out = skip(usage_task(), reading=30000)
    assert st.evaluate_usage(out, reading=34999, now=NOW)["action"] is None
    assert st.evaluate_usage(out, reading=35000, now=NOW)["action"] == st.ACTION_ARM


# ── the time backstop, the other half ───────────────────────────────────────


def test_the_backstop_measures_from_the_skip_not_the_creation_date():
    """A skip is a decision about the task, so the calendar half defers with it.

    Without this, "every 5,000 miles or 6 months" would re-arm the moment the original
    six months elapsed, however recently the user skipped it — the meter half deferred
    and the calendar half not.
    """
    task = usage_task(also_every={"interval": 6, "unit": "months"})
    out = skip(task, reading=30000)
    due = st.backstop_due(out, out["sensor"])
    assert due == r.add_interval(NOW, 6, "months")


def test_a_skipped_task_with_a_backstop_stays_quiet_until_the_backstop_elapses():
    task = usage_task(also_every={"interval": 6, "unit": "months"})
    out = skip(task, reading=30000)
    # Five months on, meter untouched: neither half is met.
    assert (
        st.evaluate_usage(out, reading=30000, now=NOW + timedelta(days=150))["action"]
        is None
    )
    # Past six months: the backstop alone arms it, which is what `any` means.
    assert (
        st.evaluate_usage(out, reading=30000, now=NOW + timedelta(days=200))["action"]
        == st.ACTION_ARM
    )


def test_the_backstop_still_falls_back_to_created_when_nothing_has_happened():
    task = usage_task(also_every={"interval": 6, "unit": "months"})
    assert st.backstop_due(task, task["sensor"]) == r.add_interval(
        datetime(2026, 1, 1, tzinfo=TZ), 6, "months"
    )


def test_a_completion_still_wins_when_it_is_the_most_recent_decision():
    task = usage_task(also_every={"interval": 6, "unit": "months"})
    task = skip(task, now=datetime(2026, 3, 1, tzinfo=TZ), reading=27000)
    task["last_completed"] = "2026-05-01T00:00:00-04:00"
    assert st.latest_decision_ts(task) == "2026-05-01T00:00:00-04:00"


def test_a_skip_wins_when_it_is_the_most_recent_decision():
    task = usage_task()
    task["last_completed"] = "2026-05-01T00:00:00-04:00"
    out = skip(task, now=datetime(2026, 7, 1, tzinfo=TZ), reading=28000)
    assert st.latest_decision_ts(out) == datetime(2026, 7, 1, tzinfo=TZ).isoformat()


def test_no_decision_yet_reads_as_none():
    assert st.latest_decision_ts(usage_task()) is None


def test_an_unparseable_stamp_is_ignored_rather_than_raising():
    task = usage_task()
    task["skips"] = [{"ts": "not a date"}]
    task["last_completed"] = "2026-05-01T00:00:00-04:00"
    assert st.latest_decision_ts(task) == "2026-05-01T00:00:00-04:00"


# ── undo ────────────────────────────────────────────────────────────────────


def test_deleting_the_anchoring_skip_restores_the_meter_it_moved():
    """Otherwise the partial progress the user had stays lost at the skip's reading."""
    out = skip(usage_task(), reading=30000)
    removed = out["skips"][0]
    after = r.remove_skip(dict(out), removed["ts"])
    should_set, restored = st.baseline_after_delete(after, removed, was_latest=True)
    assert (should_set, restored) == (True, 25000)


def test_deleting_an_older_skip_leaves_the_meter_alone():
    task = skip(usage_task(), now=datetime(2026, 6, 1, tzinfo=TZ), reading=27000)
    older = task["skips"][0]
    task = skip(task, now=datetime(2026, 7, 1, tzinfo=TZ), reading=29000)
    after = r.remove_skip(dict(task), older["ts"])
    # The later skip is the anchor now, so undoing the older row is bookkeeping only.
    assert st.baseline_after_delete(after, older, was_latest=False) == (False, None)


def test_a_non_usage_task_never_moves_its_baseline():
    task = usage_task()
    task["sensor"]["mode"] = "threshold"
    out = skip(task, reading=30000)
    assert st.baseline_after_delete(out, out["skips"][0], was_latest=True) == (
        False,
        None,
    )
