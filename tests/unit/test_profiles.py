"""Unit tests for the pure profile (saved-filter) helpers."""

from datetime import datetime, timedelta, timezone

import hk_profiles as p

TZ = timezone(timedelta(hours=-4))


def dt(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def task(tid, name, next_due, **extra):
    base = {
        "id": tid,
        "name": name,
        "next_due": next_due.isoformat() if next_due else None,
        "enabled": True,
        "recurrence_type": "floating",
    }
    base.update(extra)
    return base


# ── profile normalization ───────────────────────────────────────────────────


def test_normalize_profile_defaults_and_id():
    prof = p.normalize_profile({"name": "Me"})
    assert prof["name"] == "Me"
    assert prof["id"]  # generated
    # A nameless profile still has to read as something in every picker it fills.
    assert p.normalize_profile({})["name"] == "Tasks"
    assert p.normalize_profile({"name": ""})["name"] == "Tasks"
    assert prof["filter"]["status"] == p.STATUS_OVERDUE
    assert prof["filter"] == {
        "labels": [],
        "areas": [],
        "devices": [],
        "companions": [],
        "exclude_labels": [],
        "exclude_areas": [],
        "exclude_devices": [],
        "exclude_companions": [],
        "status": "overdue",
    }


def test_normalize_profile_preserves_id_and_coerces_filter():
    prof = p.normalize_profile(
        {"id": "x", "name": "Kitchen", "filter": {"status": "all", "labels": ["k"]}}
    )
    assert prof["id"] == "x"
    assert prof["filter"]["status"] == "all"
    assert prof["filter"]["labels"] == ["k"]


def test_normalize_profile_bad_status_falls_back():
    assert p.normalize_profile({"filter": {"status": "nope"}})["filter"]["status"] == (
        "overdue"
    )


# ── the to-do list a profile syncs onto ─────────────────────────────────────


def test_a_profile_saved_before_sync_existed_reads_back_switched_off():
    # The migration case: every stored profile predates the block, and
    # ``current_options`` re-normalizes on every read, so this is the whole
    # migration. Off means the driver plans nothing for it.
    prof = p.normalize_profile({"id": "x", "name": "Kitchen"})
    assert prof["sync"] == {
        "entity_id": "",
        "two_way": True,
        "vanish_as_completed": True,
    }


def test_normalize_sync_defaults_both_toggles_on():
    sync = p.normalize_sync({"entity_id": "todo.family"})
    assert sync["entity_id"] == "todo.family"
    assert sync["two_way"] is True
    assert sync["vanish_as_completed"] is True


def test_normalize_sync_makes_the_two_toggles_booleans():
    sync = p.normalize_sync({"two_way": 0, "vanish_as_completed": "yes"})
    assert sync["two_way"] is False
    assert sync["vanish_as_completed"] is True


def test_normalize_sync_coerces_the_target_through_the_shared_rule():
    # The same coercion the shopping mirror's target uses, so a typo switches the
    # sync off rather than half-working.
    assert p.normalize_sync({"entity_id": "  Todo.Family  "})["entity_id"] == (
        "todo.family"
    )
    assert p.normalize_sync({"entity_id": "sensor.family"})["entity_id"] == ""
    assert p.normalize_sync({"entity_id": None})["entity_id"] == ""
    assert p.normalize_sync({})["entity_id"] == ""


def test_normalize_sync_survives_something_that_is_not_a_mapping():
    assert p.normalize_sync("nonsense")["entity_id"] == ""
    assert p.normalize_sync(None)["two_way"] is True


def test_normalize_sync_drops_a_key_it_does_not_declare():
    # Rebuilt from a fixed key set, so the block doubles as the allowlist.
    assert "profile_id" not in p.normalize_sync({"profile_id": "p1"})


def test_normalize_profile_coerces_the_sync_block_it_is_given():
    prof = p.normalize_profile(
        {"id": "x", "name": "Kitchen", "sync": {"entity_id": "todo.family"}}
    )
    assert prof["sync"]["entity_id"] == "todo.family"
    assert prof["sync"]["two_way"] is True


def test_synced_profiles_keeps_only_the_ones_actually_syncing():
    off = p.normalize_profile({"id": "a", "name": "Off"})
    on = p.normalize_profile(
        {"id": "b", "name": "On", "sync": {"entity_id": "todo.family"}}
    )
    cleared = p.normalize_profile(
        {"id": "c", "name": "Typo", "sync": {"entity_id": "sensor.nope"}}
    )
    assert [prof["id"] for prof in p.synced_profiles([off, on, cleared])] == ["b"]
    assert p.synced_profiles([]) == []


def test_resolve_profile_by_id_then_name():
    profiles = [p.normalize_profile({"id": "a", "name": "Me"})]
    assert p.resolve_profile(profiles, "a")["name"] == "Me"
    assert p.resolve_profile(profiles, "Me")["id"] == "a"
    assert p.resolve_profile(profiles, "nope") is None
    assert p.resolve_profile(profiles, None) is None


# ── filtering & queue ───────────────────────────────────────────────────────


def test_matches_filter_status_overdue_vs_due_soon():
    now = dt(2026, 6, 13, 12)
    overdue = task("1", "A", dt(2026, 6, 10))
    soon = task("2", "B", dt(2026, 6, 14))
    far = task("3", "C", dt(2026, 9, 1))
    assert p.matches_filter(overdue, {"status": "overdue"}, now=now)
    assert not p.matches_filter(soon, {"status": "overdue"}, now=now)
    assert p.matches_filter(soon, {"status": "due_soon"}, now=now)
    assert p.matches_filter(overdue, {"status": "due_soon"}, now=now)
    assert not p.matches_filter(far, {"status": "due_soon"}, now=now)
    assert p.matches_filter(far, {"status": "all"}, now=now)


def test_matches_filter_defaults_to_overdue_without_a_status():
    # The default has to be `overdue`, not "everything": a filter block with no status
    # that matched every dated task would push the whole list at once.
    now = dt(2026, 6, 13, 12)
    assert p.matches_filter(task("1", "A", dt(2026, 6, 10)), {}, now=now)
    assert not p.matches_filter(task("2", "B", dt(2026, 6, 20)), {}, now=now)


def test_matches_filter_excludes_disabled_and_dormant():
    now = dt(2026, 6, 13, 12)
    f = {"status": "all"}
    assert not p.matches_filter(
        task("1", "A", dt(2026, 6, 10), enabled=False), f, now=now
    )
    assert not p.matches_filter(task("2", "B", None), f, now=now)


def test_matches_filter_includes_an_armed_problem_sensor_task():
    # #248: these were dropped outright, under every status, so a synced problem never
    # showed under any Profile. An armed one carries next_due = when the sensor went
    # bad, so it belongs to every tier exactly like any other overdue task.
    now = dt(2026, 6, 13, 12)
    armed = task(
        "1", "A", dt(2026, 6, 10), source={"problem_sensor": {"entity_id": "x"}}
    )
    assert p.matches_filter(armed, {"status": "all"}, now=now)
    assert p.matches_filter(armed, {"status": "overdue"}, now=now)
    assert p.matches_filter(armed, {"status": "due_soon"}, now=now)
    # The include/exclude lists still apply to it like any other task.
    assert not p.matches_filter(armed, {"status": "all", "labels": ["mine"]}, now=now)


def test_matches_filter_excludes_a_dormant_problem_sensor_task():
    # Sensor back to OK -> the sync clears next_due, and an undated task is out.
    now = dt(2026, 6, 13, 12)
    dormant = task("1", "A", None, source={"problem_sensor": {"entity_id": "x"}})
    assert not p.matches_filter(dormant, {"status": "all"}, now=now)


def test_matches_filter_labels_areas_devices():
    now = dt(2026, 6, 13, 12)
    t = task(
        "1", "A", dt(2026, 6, 10), labels=["mine"], area_id="kitchen", device_id="dev1"
    )
    assert p.matches_filter(t, {"status": "all", "labels": ["mine"]}, now=now)
    assert not p.matches_filter(t, {"status": "all", "labels": ["hers"]}, now=now)
    assert p.matches_filter(t, {"status": "all", "areas": ["kitchen"]}, now=now)
    assert not p.matches_filter(t, {"status": "all", "areas": ["garage"]}, now=now)
    assert p.matches_filter(t, {"status": "all", "devices": ["dev1"]}, now=now)
    assert not p.matches_filter(t, {"status": "all", "devices": ["dev2"]}, now=now)


# ── exclusions ──────────────────────────────────────────────────────────────


def test_normalize_filter_reads_every_input_key():
    # A distinct value per key, so a slot fed from the wrong key — or one that is never
    # read at all and silently comes back empty — lands somewhere visible.
    raw = {
        "labels": ["l"],
        "areas": ["a"],
        "devices": ["d"],
        "companions": ["c"],
        "exclude_labels": ["xl"],
        "exclude_areas": ["xa"],
        "exclude_devices": ["xd"],
        "exclude_companions": ["xc"],
        "status": "all",
    }
    assert p.normalize_filter(raw) == raw


def test_normalize_filter_defaults_and_coerces_exclusions():
    filt = p.normalize_filter(
        {"exclude_labels": ["pro", None, ""], "exclude_devices": ("dev1",)}
    )
    # None/"" are dropped, tuples are accepted, and the untouched list still defaults.
    assert filt["exclude_labels"] == ["pro"]
    assert filt["exclude_devices"] == ["dev1"]
    assert filt["exclude_areas"] == []


def test_matches_filter_exclusions_drop_a_task():
    now = dt(2026, 6, 13, 12)
    t = task(
        "1", "A", dt(2026, 6, 10), labels=["mine"], area_id="kitchen", device_id="dev1"
    )
    assert not p.matches_filter(
        t, {"status": "all", "exclude_labels": ["mine"]}, now=now
    )
    assert not p.matches_filter(
        t, {"status": "all", "exclude_areas": ["kitchen"]}, now=now
    )
    assert not p.matches_filter(
        t, {"status": "all", "exclude_devices": ["dev1"]}, now=now
    )
    # An exclusion the task doesn't hit leaves it alone.
    assert p.matches_filter(t, {"status": "all", "exclude_labels": ["hers"]}, now=now)
    assert p.matches_filter(t, {"status": "all", "exclude_areas": ["garage"]}, now=now)
    assert p.matches_filter(t, {"status": "all", "exclude_devices": ["dev2"]}, now=now)


def test_matches_filter_empty_exclusions_exclude_nothing():
    # The failure that would hurt most: an inverted check turning "no exclusions" into
    # "exclude everything" empties every profile at once.
    now = dt(2026, 6, 13, 12)
    t = task(
        "1", "A", dt(2026, 6, 10), labels=["mine"], area_id="kitchen", device_id="dev1"
    )
    assert p.matches_filter(
        t,
        {
            "status": "all",
            "exclude_labels": [],
            "exclude_areas": [],
            "exclude_devices": [],
        },
        now=now,
    )
    # A filter block predating exclusions omits the keys entirely.
    assert p.matches_filter(t, {"status": "all"}, now=now)


def test_matches_filter_exclusion_beats_a_satisfied_include():
    now = dt(2026, 6, 13, 12)
    t = task("1", "A", dt(2026, 6, 10), labels=["mine", "pro"], area_id="kitchen")
    assert p.matches_filter(t, {"status": "all", "labels": ["mine"]}, now=now)
    assert not p.matches_filter(
        t, {"status": "all", "labels": ["mine"], "exclude_labels": ["pro"]}, now=now
    )
    assert not p.matches_filter(
        t,
        {"status": "all", "areas": ["kitchen"], "exclude_areas": ["kitchen"]},
        now=now,
    )


def test_matches_filter_unset_area_or_device_survives_an_exclusion():
    # A task with no area must not be dropped by "exclude the garage" — it isn't there.
    now = dt(2026, 6, 13, 12)
    t = task("1", "A", dt(2026, 6, 10))
    assert p.matches_filter(t, {"status": "all", "exclude_areas": ["garage"]}, now=now)
    assert p.matches_filter(t, {"status": "all", "exclude_devices": ["dev1"]}, now=now)


def test_due_queue_applies_exclusions():
    # The queue is what a notification actually sends, so the exclusion has to survive
    # the trip through due_queue, not just the bare predicate.
    now = dt(2026, 6, 13, 12)
    tasks = [
        task("1", "Mine", dt(2026, 6, 1), labels=["mine"]),
        task("2", "Call someone", dt(2026, 6, 8), labels=["pro"]),
    ]
    q = p.due_queue(tasks, {"status": "overdue", "exclude_labels": ["pro"]}, now=now)
    assert [t["name"] for t in q] == ["Mine"]


def test_due_queue_orders_most_overdue_first():
    now = dt(2026, 6, 13, 12)
    tasks = [
        task("1", "Later", dt(2026, 6, 12)),
        task("2", "Earliest", dt(2026, 6, 1)),
        task("3", "Middle", dt(2026, 6, 8)),
        task("4", "Future", dt(2026, 12, 1)),  # filtered out by overdue
    ]
    q = p.due_queue(tasks, {"status": "overdue"}, now=now)
    assert [t["name"] for t in q] == ["Earliest", "Middle", "Later"]


def test_conformance_fixture_matches_filter():
    """Run the shared cross-language conformance cases through the Python matcher.

    The same fixture drives the TypeScript ``profileMatches`` test (see
    ``frontend/test/card-filter.test.js``), so a Profile selects the same tasks in a
    notification, the admin list, and the card. If you add a case here, both sides must
    still agree.
    """
    import json
    from pathlib import Path

    fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "profile_filter_cases.json"
    )
    data = json.loads(fixture.read_text())
    default_now = datetime.fromisoformat(data["now"].replace("Z", "+00:00"))
    for case in data["cases"]:
        now = default_now
        if "now" in case:
            now = datetime.fromisoformat(case["now"].replace("Z", "+00:00"))
        got = p.matches_filter(case["task"], case["filter"], now=now)
        assert got is case["expected"], (
            f"{case['name']}: expected {case['expected']}, got {got}"
        )


# ── companions (filter by the integration that owns the task) ───────────────


def _owned(tid="1", integration="battery_notes"):
    """An overdue task owned by *integration*, as a companion's add_task creates it."""
    return task(
        tid,
        "Replace battery",
        dt(2026, 6, 10),
        managed_by={"integration": integration, "display_name": "Battery Notes"},
    )


def test_companions_selects_only_the_named_owner():
    now = dt(2026, 6, 13, 12)
    assert p.matches_filter(
        _owned(), {"status": "all", "companions": ["battery_notes"]}, now=now
    )
    assert not p.matches_filter(
        _owned(integration="printer_glue"),
        {"status": "all", "companions": ["battery_notes"]},
        now=now,
    )


def test_companions_matches_any_of_several():
    now = dt(2026, 6, 13, 12)
    filt = {"status": "all", "companions": ["battery_notes", "dog_glue"]}
    assert p.matches_filter(_owned(integration="dog_glue"), filt, now=now)
    assert not p.matches_filter(_owned(integration="printer_glue"), filt, now=now)


def test_an_unowned_task_is_never_selected_by_a_companions_list():
    # A task the user made in the panel has no managed_by block, so it belongs to no
    # companion. It must not leak into "just the battery tasks".
    now = dt(2026, 6, 13, 12)
    hand_made = task("2", "Water plants", dt(2026, 6, 10))
    assert not p.matches_filter(
        hand_made, {"status": "all", "companions": ["battery_notes"]}, now=now
    )
    # ...and the same task is untouched by an exclude list, which is the other half of
    # the rule: excluding a companion must not sweep up everything unowned.
    assert p.matches_filter(
        hand_made, {"status": "all", "exclude_companions": ["battery_notes"]}, now=now
    )


def test_an_explicitly_null_managed_by_owns_nothing():
    # `managed_by: None` is not the same shape as an absent key, and both reach the
    # matcher: `add_task` stores what it is given. They must read the same.
    now = dt(2026, 6, 13, 12)
    t = task("5", "Nulled", dt(2026, 6, 10), managed_by=None)
    assert not p.matches_filter(
        t, {"status": "all", "companions": ["battery_notes"]}, now=now
    )
    assert p.matches_filter(
        t, {"status": "all", "exclude_companions": ["battery_notes"]}, now=now
    )


def test_a_managed_by_without_an_integration_key_owns_nothing():
    # managed_by is a free-form dict at the service boundary, so a block missing the
    # required key must read as "unowned" rather than crash or match everything.
    now = dt(2026, 6, 13, 12)
    t = task("3", "Odd", dt(2026, 6, 10), managed_by={"display_name": "Nameless"})
    assert not p.matches_filter(
        t, {"status": "all", "companions": ["battery_notes"]}, now=now
    )
    assert p.matches_filter(
        t, {"status": "all", "exclude_companions": ["battery_notes"]}, now=now
    )


def test_exclude_companions_drops_the_owner_and_wins_over_an_include():
    now = dt(2026, 6, 13, 12)
    assert not p.matches_filter(
        _owned(), {"status": "all", "exclude_companions": ["battery_notes"]}, now=now
    )
    assert p.matches_filter(
        _owned(integration="dog_glue"),
        {"status": "all", "exclude_companions": ["battery_notes"]},
        now=now,
    )
    # Exclusions are applied last and win, exactly as they do for labels/areas/devices.
    assert not p.matches_filter(
        _owned(),
        {
            "status": "all",
            "companions": ["battery_notes"],
            "exclude_companions": ["battery_notes"],
        },
        now=now,
    )


def test_an_empty_companions_list_selects_every_owner():
    now = dt(2026, 6, 13, 12)
    assert p.matches_filter(_owned(), {"status": "all", "companions": []}, now=now)
    assert p.matches_filter(_owned(integration="dog_glue"), {"status": "all"}, now=now)


def test_companions_is_anded_with_the_other_axes():
    # Each axis narrows: the right owner in the wrong area is still dropped.
    now = dt(2026, 6, 13, 12)
    t = task(
        "4",
        "Replace battery",
        dt(2026, 6, 10),
        area_id="kitchen",
        managed_by={"integration": "battery_notes", "display_name": "Battery Notes"},
    )
    filt = {"status": "all", "companions": ["battery_notes"], "areas": ["garage"]}
    assert not p.matches_filter(t, filt, now=now)
    assert p.matches_filter(t, {**filt, "areas": ["kitchen"]}, now=now)


def test_normalize_filter_coerces_companion_lists():
    filt = p.normalize_filter(
        {"companions": ["battery_notes", None, ""], "exclude_companions": ("dog_glue",)}
    )
    # None/"" are dropped so an unowned task can never be named by a list, and a tuple
    # is accepted like the other axes.
    assert filt["companions"] == ["battery_notes"]
    assert filt["exclude_companions"] == ["dog_glue"]
