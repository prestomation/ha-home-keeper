"""Unit tests for the pure voice/intent task matcher (no Home Assistant).

These exercise the branchy resolution logic that backs the conversation intents —
exact vs fuzzy vs ambiguous vs not-found, area/device scoping, and due-task
selection — so the fragile parts get cheap, deterministic coverage. The HA wiring
that calls these (registry lookups, spoken responses) is covered by the integration
tests instead.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import hk_task_match as tm

TZ = timezone(timedelta(hours=-4))


def _task(name, **extra):
    return {
        "id": name.lower().replace(" ", "_"),
        "name": name,
        "enabled": True,
        **extra,
    }


# A small task set echoing the seeded integration fixture (three "Replace … filter"
# tasks, which is what makes keyword matching ambiguous).
TASKS = [
    _task("Replace fridge filter"),
    _task("Replace furnace filter"),
    _task("Replace water filter", device_id="dev_water", area_id="kitchen"),
    _task("Take medicine"),
]


def test_exact_name_matches_uniquely():
    result = tm.match_task(TASKS, "Replace furnace filter")
    assert result.matched
    assert result.task["name"] == "Replace furnace filter"


def test_exact_match_is_case_and_article_insensitive():
    result = tm.match_task(TASKS, "the take medicine")
    assert result.matched
    assert result.task["name"] == "Take medicine"


def test_fuzzy_typo_still_resolves():
    result = tm.match_task(TASKS, "take medecine")  # typo
    assert result.matched
    assert result.task["name"] == "Take medicine"


def test_unique_keyword_resolves_via_containment():
    result = tm.match_task(TASKS, "furnace filter")
    assert result.matched
    assert result.task["name"] == "Replace furnace filter"


def test_ambiguous_keyword_returns_candidates_not_a_guess():
    result = tm.match_task(TASKS, "filter")
    assert result.ambiguous
    names = {t["name"] for t in result.candidates}
    assert names == {
        "Replace fridge filter",
        "Replace furnace filter",
        "Replace water filter",
    }
    assert result.task is None


def test_unrelated_name_is_not_found():
    result = tm.match_task(TASKS, "walk the dog")
    assert result.not_found
    assert result.task is None and result.candidates == []


def test_area_filter_disambiguates():
    # "filter" alone is ambiguous, but scoped to the kitchen only one task qualifies.
    result = tm.match_task(TASKS, "filter", area_id="kitchen")
    assert result.matched
    assert result.task["name"] == "Replace water filter"


def test_device_filter_disambiguates():
    result = tm.match_task(TASKS, "filter", device_id="dev_water")
    assert result.matched
    assert result.task["name"] == "Replace water filter"


def test_area_filter_with_no_tasks_is_not_found():
    result = tm.match_task(TASKS, "filter", area_id="garage")
    assert result.not_found


def test_duplicate_exact_names_are_ambiguous():
    dupes = [_task("Water the plants"), _task("Water the plants")]
    result = tm.match_task(dupes, "water the plants")
    assert result.ambiguous
    assert len(result.candidates) == 2


# ── select_due_tasks ─────────────────────────────────────────────────────────────
NOW = datetime(2026, 6, 20, 12, 0, tzinfo=TZ)


def _due_task(name, due_iso, **extra):
    return _task(name, next_due=due_iso, **extra)


def test_due_selection_includes_overdue_and_due_now_sorted():
    tasks = [
        _due_task("A overdue", "2026-06-01T09:00:00-04:00"),
        _due_task("B future", "2026-12-01T09:00:00-04:00"),
        _due_task("C due now", NOW.isoformat()),
        _due_task("D dormant", None),  # triggered, not armed
    ]
    due = tm.select_due_tasks(tasks, NOW)
    assert [t["name"] for t in due] == ["A overdue", "C due now"]


def test_due_selection_excludes_disabled():
    tasks = [_due_task("Off", "2026-01-01T09:00:00-04:00", enabled=False)]
    assert tm.select_due_tasks(tasks, NOW) == []


def test_due_selection_tolerates_bad_timestamp():
    tasks = [
        _due_task("Bad", "not-a-date"),
        _due_task("Good", "2026-06-01T09:00:00-04:00"),
    ]
    due = tm.select_due_tasks(tasks, NOW)
    assert [t["name"] for t in due] == ["Good"]
