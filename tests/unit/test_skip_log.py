"""The skip log: recording, amending, re-dating and undoing a skipped occurrence.

A skip is deliberately *not* a completion. It lives in its own ``skips`` list so that
"a skip never counts as work done" is true by construction rather than by filtering at
every reader of ``completions`` — see ``recurrence.skip_occurrence``. These tests pin
that separation, and the metadata handling that mirrors the completion trio.
"""

from datetime import datetime, timedelta, timezone

import hk_recurrence as r
import pytest
from hk_models import TaskValidationError, build_task, normalize_completion_metadata

TZ = timezone(timedelta(hours=-4))
SKIP_FIELDS = ("note", "who", "reading")


def dt(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def floating(**over):
    task = {
        "recurrence_type": "floating",
        "interval": 1,
        "unit": "months",
        "last_completed": "2026-01-01T00:00:00-04:00",
        "next_due": "2026-02-01T00:00:00-04:00",
        "completions": [{"ts": "2026-01-01T00:00:00-04:00"}],
        "skips": [],
    }
    task.update(over)
    return task


# ── recording ───────────────────────────────────────────────────────────────


def test_skip_records_its_metadata():
    now = dt(2026, 6, 13, 10)
    out = r.skip_occurrence(
        floating(), now=now, metadata={"note": "away", "who": "sam"}
    )
    assert out["skips"] == [{"ts": now.isoformat(), "note": "away", "who": "sam"}]


def test_skip_without_metadata_records_only_the_timestamp():
    now = dt(2026, 6, 13, 10)
    out = r.skip_occurrence(floating(), now=now, metadata={})
    assert out["skips"] == [{"ts": now.isoformat()}]


def test_two_skips_at_the_same_instant_collapse_to_one():
    """A double-tapped notification action must not create an ambiguous twin.

    The same dedup ``apply_completion`` applies to completions: the entry at that
    ``ts`` is replaced, because ``ts`` is a skip's identity for edit and undo, and two
    entries sharing one would make both unaddressable.
    """
    now = dt(2026, 6, 13, 10)
    once = r.skip_occurrence(floating(), now=now, metadata={"note": "first"})
    twice = r.skip_occurrence(once, now=now, metadata={"note": "second"})
    assert twice["skips"] == [{"ts": now.isoformat(), "note": "second"}]


def test_skips_accumulate_and_are_capped():
    task = floating()
    for day in range(1, 6):
        task = r.skip_occurrence(task, now=dt(2026, 6, day))
    assert len(task["skips"]) == 5
    assert task["skips"][0]["ts"] == dt(2026, 6, 1).isoformat()
    assert task["skips"][-1]["ts"] == dt(2026, 6, 5).isoformat()


def test_the_log_is_capped_and_drops_its_oldest_entries():
    """Both logs share one insert, so the cap is one behaviour rather than two.

    Uncapped, a task skipped by an automation every hour would grow its stored
    document without bound — the storage file is one JSON blob rewritten on every
    save, so the cost is paid on every write, not just at read time.
    """
    task = floating()
    cap = r.MAX_COMPLETION_HISTORY
    task["skips"] = [
        {"ts": dt(2020, 1, 1).isoformat(), "note": f"n{i}"} for i in range(cap)
    ]
    # Distinct timestamps, so none of these collapse into each other.
    for i in range(cap):
        task["skips"][i]["ts"] = (dt(2020, 1, 1) + timedelta(minutes=i)).isoformat()
    oldest = task["skips"][0]["ts"]

    out = r.skip_occurrence(task, now=dt(2026, 6, 13))

    assert len(out["skips"]) == cap
    assert all(s["ts"] != oldest for s in out["skips"])
    assert out["skips"][-1]["ts"] == dt(2026, 6, 13).isoformat()


def test_the_log_is_not_trimmed_before_it_reaches_the_cap():
    task = floating()
    cap = r.MAX_COMPLETION_HISTORY
    task["skips"] = [
        {"ts": (dt(2020, 1, 1) + timedelta(minutes=i)).isoformat()}
        for i in range(cap - 1)
    ]
    out = r.skip_occurrence(task, now=dt(2026, 6, 13))
    assert len(out["skips"]) == cap


def test_a_skip_never_becomes_last_completed():
    """The floating clock measures from work done, not from a decision to defer.

    If a skip set ``last_completed`` the next due date would be measured from the
    skip, quietly turning "I'm not doing this now" into "I did this now".
    """
    task = r.skip_occurrence(floating(), now=dt(2026, 6, 13))
    assert task["last_completed"] == "2026-01-01T00:00:00-04:00"
    assert task["completions"] == [{"ts": "2026-01-01T00:00:00-04:00"}]


def test_undoing_a_completion_ignores_the_skip_log():
    """``remove_completion`` re-derives ``last_completed`` from ``completions`` alone.

    With one shared list, a later skip would become the new ``last_completed`` when an
    earlier completion was undone, jumping the schedule a full interval. Keeping the
    logs apart is what makes that impossible rather than merely unlikely.
    """
    task = floating(
        completions=[
            {"ts": "2026-01-01T00:00:00-04:00"},
            {"ts": "2026-03-01T00:00:00-04:00"},
        ],
    )
    task = r.skip_occurrence(task, now=dt(2026, 5, 1))
    out = r.remove_completion(task, "2026-03-01T00:00:00-04:00", now=dt(2026, 6, 13))
    assert out["last_completed"] == "2026-01-01T00:00:00-04:00"


# ── amending ────────────────────────────────────────────────────────────────


def test_update_skip_sets_and_clears_fields():
    now = dt(2026, 6, 13, 10)
    task = r.skip_occurrence(
        floating(), now=now, metadata={"note": "away", "who": "sam"}
    )
    out = r.update_skip(
        task, now.isoformat(), {"note": "on holiday"}, fields=SKIP_FIELDS
    )
    entry = out["skips"][0]
    assert entry["note"] == "on holiday"
    # An omitted field is cleared, not preserved — the same rule update_completion
    # follows, so a blanked note removes the key rather than storing "".
    assert "who" not in entry


def test_update_skip_leaves_the_schedule_alone():
    now = dt(2026, 6, 13, 10)
    task = r.skip_occurrence(floating(), now=now)
    before = task["next_due"]
    out = r.update_skip(task, now.isoformat(), {"note": "x"}, fields=SKIP_FIELDS)
    assert out["next_due"] == before
    assert out["skips"][0]["ts"] == now.isoformat()


def test_update_skip_on_a_missing_timestamp_raises():
    task = r.skip_occurrence(floating(), now=dt(2026, 6, 13))
    with pytest.raises(ValueError, match="no skip at"):
        r.update_skip(task, "2020-01-01T00:00:00-04:00", {}, fields=SKIP_FIELDS)


# ── re-dating ───────────────────────────────────────────────────────────────


def test_move_skip_keeps_the_entry_and_its_metadata():
    now = dt(2026, 6, 13, 10)
    task = r.skip_occurrence(floating(), now=now, metadata={"note": "away"})
    out = r.move_skip(task, now.isoformat(), dt(2026, 6, 1, 9).isoformat(), now=now)
    assert out["skips"] == [{"ts": dt(2026, 6, 1, 9).isoformat(), "note": "away"}]


def test_move_skip_qualifies_a_naive_timestamp():
    """A naive value would poison every later aware-vs-naive comparison."""
    now = dt(2026, 6, 13, 10)
    task = r.skip_occurrence(floating(), now=now)
    out = r.move_skip(task, now.isoformat(), "2026-06-01T09:00:00", now=now)
    assert out["skips"][0]["ts"] == dt(2026, 6, 1, 9).isoformat()


def test_move_skip_onto_an_existing_skip_collapses_them():
    task = floating()
    task = r.skip_occurrence(task, now=dt(2026, 6, 1), metadata={"note": "first"})
    task = r.skip_occurrence(task, now=dt(2026, 6, 5), metadata={"note": "second"})
    out = r.move_skip(
        task,
        dt(2026, 6, 5).isoformat(),
        dt(2026, 6, 1).isoformat(),
        now=dt(2026, 6, 13),
    )
    # The moved entry wins, as it does for completions.
    assert out["skips"] == [{"ts": dt(2026, 6, 1).isoformat(), "note": "second"}]


def test_move_skip_does_not_touch_the_schedule():
    """A skip's date does not drive ``next_due``.

    Unlike a completion, the due date a skip set was computed at the time; re-deriving
    it from a corrected date would be guesswork about a schedule the user may have
    moved on from since.
    """
    now = dt(2026, 6, 13, 10)
    task = r.skip_occurrence(floating(), now=now)
    before = task["next_due"]
    out = r.move_skip(task, now.isoformat(), dt(2026, 6, 1).isoformat(), now=now)
    assert out["next_due"] == before


def test_move_skip_on_a_missing_timestamp_raises():
    task = r.skip_occurrence(floating(), now=dt(2026, 6, 13))
    with pytest.raises(ValueError, match="no skip at"):
        r.move_skip(
            task,
            "2020-01-01T00:00:00-04:00",
            "2026-06-01T00:00:00-04:00",
            now=dt(2026, 6, 13),
        )


# ── undoing ─────────────────────────────────────────────────────────────────


def test_remove_skip_drops_only_the_named_entry():
    task = floating()
    task = r.skip_occurrence(task, now=dt(2026, 6, 1))
    task = r.skip_occurrence(task, now=dt(2026, 6, 5))
    out = r.remove_skip(task, dt(2026, 6, 1).isoformat())
    assert [s["ts"] for s in out["skips"]] == [dt(2026, 6, 5).isoformat()]


def test_remove_skip_leaves_the_schedule_alone():
    now = dt(2026, 6, 13, 10)
    task = r.skip_occurrence(floating(), now=now)
    before = task["next_due"]
    out = r.remove_skip(task, now.isoformat())
    assert out["skips"] == []
    assert out["next_due"] == before


def test_remove_skip_is_a_no_op_for_an_unknown_timestamp():
    task = r.skip_occurrence(floating(), now=dt(2026, 6, 13))
    out = r.remove_skip(dict(task), "2020-01-01T00:00:00-04:00")
    assert out["skips"] == task["skips"]


# ── the task model ──────────────────────────────────────────────────────────


def test_a_new_task_starts_with_an_empty_skip_log():
    task = build_task(
        {"name": "Change filter", "interval": 1, "unit": "months"}, now=dt(2026, 6, 13)
    )
    assert task["skips"] == []


def test_a_task_written_before_skips_existed_reads_as_having_none():
    """Every reader uses ``.get("skips", [])`` — the key is additive, with no
    storage-version bump, exactly as ``assets`` and ``shopping_items`` were."""
    legacy = floating()
    del legacy["skips"]
    out = r.skip_occurrence(legacy, now=dt(2026, 6, 13))
    assert len(out["skips"]) == 1


def test_removing_a_skip_from_a_pre_skip_document_is_a_no_op():
    """Undo has to survive a document stored before the log existed, which is every
    document there is — the key is absent, not empty."""
    legacy = floating()
    del legacy["skips"]
    out = r.remove_skip(legacy, "2026-06-13T00:00:00-04:00")
    assert out["skips"] == []


def test_amending_a_skip_on_a_pre_skip_document_raises_rather_than_crashing():
    legacy = floating()
    del legacy["skips"]
    with pytest.raises(ValueError, match="no skip at"):
        r.update_skip(legacy, "2026-06-13T00:00:00-04:00", {}, fields=SKIP_FIELDS)


def test_moving_a_skip_on_a_pre_skip_document_raises_rather_than_crashing():
    legacy = floating()
    del legacy["skips"]
    with pytest.raises(ValueError, match="no skip at"):
        r.move_skip(
            legacy,
            "2026-06-13T00:00:00-04:00",
            "2026-06-01T00:00:00-04:00",
            now=dt(2026, 6, 13),
        )


def test_an_empty_string_clears_a_field_rather_than_being_stored():
    """A blanked note must remove the key, not store ``""`` — otherwise the history
    row renders an empty note block instead of no note at all."""
    now = dt(2026, 6, 13, 10)
    task = r.skip_occurrence(floating(), now=now, metadata={"note": "away"})
    out = r.update_skip(task, now.isoformat(), {"note": ""}, fields=SKIP_FIELDS)
    assert "note" not in out["skips"][0]


def test_amending_a_skip_invents_no_new_keys_on_the_task():
    now = dt(2026, 6, 13, 10)
    task = r.skip_occurrence(floating(), now=now, metadata={"note": "away"})
    before = set(task)
    out = r.update_skip(task, now.isoformat(), {"note": "x"}, fields=SKIP_FIELDS)
    assert set(out) == before


def test_a_task_with_no_recurrence_type_skips_as_a_floating_one():
    """``floating`` is the documented default across the engine, and skip follows it
    rather than raising on a task shape every other function accepts."""
    now = dt(2026, 6, 13, 10)
    out = r.skip_occurrence({"interval": 7, "unit": "days"}, now=now)
    assert out["next_due"] == (now + timedelta(days=7)).isoformat()


def test_a_reading_is_refused_for_a_task_with_no_meter():
    """The store cleans a skip's metadata through the completion normalizer, so a
    reading on a task that has no sensor to read is rejected rather than dropped —
    silently discarding it would let a caller believe the skip recorded a meter."""
    with pytest.raises(TaskValidationError, match="reading is only valid"):
        normalize_completion_metadata({"reading": 30000}, allow_reading=False)


def test_a_reading_survives_for_a_metered_task():
    assert normalize_completion_metadata({"reading": 30000}, allow_reading=True) == {
        "reading": 30000.0
    }
