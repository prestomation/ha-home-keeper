"""Unit tests for the pure profile (saved-filter) helpers."""

from datetime import datetime, timedelta, timezone

import hk_profiles as p
import pytest

TZ = timezone(timedelta(hours=-4))

EMPTY_GROUP = {
    "labels": [],
    "labels_match": "any",
    "areas": [],
    "devices": [],
    "companions": [],
    "exclude_labels": [],
    "exclude_areas": [],
    "exclude_devices": [],
    "exclude_companions": [],
    "exclude_shopping": False,
}


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


def filt(status="all", *groups):
    """A filter block: a status plus the groups given, each written as a bare dict."""
    return {"status": status, "groups": list(groups)}


# ── profile normalization ───────────────────────────────────────────────────


def test_normalize_profile_defaults_and_id():
    prof = p.normalize_profile({"name": "Me"})
    assert prof["name"] == "Me"
    assert prof["id"]  # generated
    # A nameless profile still has to read as something in every picker it fills.
    assert p.normalize_profile({})["name"] == "Tasks"
    assert p.normalize_profile({"name": ""})["name"] == "Tasks"
    assert prof["filter"]["status"] == p.STATUS_OVERDUE
    assert prof["filter"] == {"groups": [EMPTY_GROUP], "status": "overdue"}


def test_normalize_profile_preserves_id_and_coerces_filter():
    prof = p.normalize_profile(
        {
            "id": "x",
            "name": "Kitchen",
            "filter": {"status": "all", "groups": [{"labels": ["k"]}]},
        }
    )
    assert prof["id"] == "x"
    assert prof["filter"]["status"] == "all"
    assert prof["filter"]["groups"][0]["labels"] == ["k"]


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


# ── filter groups: normalization ────────────────────────────────────────────


def test_normalize_group_reads_every_input_key():
    # A distinct value per key, so a slot fed from the wrong key — or one that is never
    # read at all and silently comes back empty — lands somewhere visible. The key
    # order is asserted too: the panel's group form reads the shape in this order.
    raw = {
        "labels": ["l"],
        "labels_match": "all",
        "areas": ["a"],
        "devices": ["d"],
        "companions": ["c"],
        "exclude_labels": ["xl"],
        "exclude_areas": ["xa"],
        "exclude_devices": ["xd"],
        "exclude_companions": ["xc"],
        "exclude_shopping": True,
    }
    assert p.normalize_group(raw) == raw
    assert list(p.normalize_group(raw)) == list(raw)


def test_normalize_group_defaults_every_key_and_coerces_the_lists():
    group = p.normalize_group(
        {"exclude_labels": ["pro", None, ""], "exclude_devices": ("dev1",)}
    )
    # None/"" are dropped, tuples are accepted, and the untouched lists still default.
    assert group["exclude_labels"] == ["pro"]
    assert group["exclude_devices"] == ["dev1"]
    assert group["exclude_areas"] == []
    assert group["labels"] == []
    assert group["exclude_shopping"] is False


def test_normalize_group_coerces_companion_lists():
    group = p.normalize_group(
        {"companions": ["battery_notes", None, ""], "exclude_companions": ("dog_glue",)}
    )
    # None/"" are dropped so an unowned task can never be named by a list, and a tuple
    # is accepted like the other axes.
    assert group["companions"] == ["battery_notes"]
    assert group["exclude_companions"] == ["dog_glue"]


def test_normalize_group_clamps_labels_match():
    assert p.normalize_group({})["labels_match"] == "any"
    assert p.normalize_group({"labels_match": "all"})["labels_match"] == "all"
    assert p.normalize_group({"labels_match": "any"})["labels_match"] == "any"
    # Anything else widens rather than narrowing: an unknown value must not silently
    # demand every listed label.
    for value in ("ALL", "sometimes", "", None, 1, ["all"]):
        assert p.normalize_group({"labels_match": value})["labels_match"] == "any"
    assert p.LABELS_MATCHES == ("any", "all")
    assert p.LABELS_MATCH_ANY == "any"
    assert p.LABELS_MATCH_ALL == "all"


def test_normalize_group_survives_something_that_is_not_a_mapping():
    assert p.normalize_group("nonsense") == EMPTY_GROUP
    assert p.normalize_group(None) == EMPTY_GROUP


def test_normalize_groups_always_returns_at_least_one_group():
    # Every form and every consumer reads groups[0] without a special case, so the
    # list is never empty. All four ways of arriving with nothing agree.
    assert p.normalize_groups([]) == [EMPTY_GROUP]
    assert p.normalize_groups(None) == [EMPTY_GROUP]
    assert p.normalize_groups("nonsense") == [EMPTY_GROUP]
    assert p.normalize_groups(["nonsense", 3]) == [EMPTY_GROUP]


def test_normalize_groups_drops_non_dict_entries_beside_real_ones():
    groups = p.normalize_groups([{"labels": ["dog"]}, "nonsense", {"areas": ["k"]}])
    assert [g["labels"] for g in groups] == [["dog"], []]
    assert [g["areas"] for g in groups] == [[], ["k"]]


def test_normalize_groups_keeps_several_groups_in_order():
    groups = p.normalize_groups([{"labels": ["a"]}, {"labels": ["b"]}])
    assert [g["labels"] for g in groups] == [["a"], ["b"]]


def test_normalize_filter_returns_groups_and_status_only():
    # The block is rebuilt from a fixed key set, so it doubles as the allowlist.
    out = p.normalize_filter({"status": "all", "groups": [{"labels": ["k"]}]})
    assert set(out) == {"groups", "status"}
    assert out["groups"][0]["labels"] == ["k"]


def test_normalize_filter_drops_the_pre_groups_keys_without_lifting_them():
    # The flat keys are read nowhere: a stored filter is converted once by
    # migrate_filter_v1, and a write that still carries them is refused. Lifting them
    # here instead would hide both.
    out = p.normalize_filter(
        {"status": "all", "labels": ["dog"], "exclude_areas": ["g"]}
    )
    assert out == {"groups": [EMPTY_GROUP], "status": "all"}


def test_normalize_filter_survives_something_that_is_not_a_mapping():
    canonical = {"groups": [EMPTY_GROUP], "status": "overdue"}
    assert p.normalize_filter("nonsense") == canonical


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
    # The groups still apply to it like any other task.
    assert not p.matches_filter(armed, filt("all", {"labels": ["mine"]}), now=now)


def test_matches_filter_excludes_a_dormant_problem_sensor_task():
    # Sensor back to OK -> the sync clears next_due, and an undated task is out.
    now = dt(2026, 6, 13, 12)
    dormant = task("1", "A", None, source={"problem_sensor": {"entity_id": "x"}})
    assert not p.matches_filter(dormant, {"status": "all"}, now=now)


def test_one_group_is_the_pre_groups_rule():
    # The migration's promise: a single group selects exactly what the flat filter it
    # was built from selected, on every axis.
    now = dt(2026, 6, 13, 12)
    t = task(
        "1", "A", dt(2026, 6, 10), labels=["mine"], area_id="kitchen", device_id="dev1"
    )
    assert p.matches_filter(t, filt("all", {"labels": ["mine"]}), now=now)
    assert not p.matches_filter(t, filt("all", {"labels": ["hers"]}), now=now)
    assert p.matches_filter(t, filt("all", {"areas": ["kitchen"]}), now=now)
    assert not p.matches_filter(t, filt("all", {"areas": ["garage"]}), now=now)
    assert p.matches_filter(t, filt("all", {"devices": ["dev1"]}), now=now)
    assert not p.matches_filter(t, filt("all", {"devices": ["dev2"]}), now=now)


def test_a_group_needs_every_include_list_it_carries():
    # AND inside a group: two axes right and one wrong is still a miss.
    now = dt(2026, 6, 13, 12)
    t = task(
        "1", "A", dt(2026, 6, 10), labels=["mine"], area_id="kitchen", device_id="dev1"
    )
    whole = {"labels": ["mine"], "areas": ["kitchen"], "devices": ["dev1"]}
    assert p.matches_filter(t, filt("all", whole), now=now)
    assert not p.matches_filter(t, filt("all", {**whole, "labels": ["hers"]}), now=now)
    assert not p.matches_filter(t, filt("all", {**whole, "areas": ["garage"]}), now=now)
    assert not p.matches_filter(t, filt("all", {**whole, "devices": ["dev2"]}), now=now)


def test_either_group_can_take_the_task():
    # The whole point of groups: the lists are ORed across them, so "the kitchen jobs
    # or anything on the boiler" is one profile.
    now = dt(2026, 6, 13, 12)
    kitchen = task("1", "A", dt(2026, 6, 10), area_id="kitchen")
    boiler = task("2", "B", dt(2026, 6, 10), device_id="dev1")
    neither = task("3", "C", dt(2026, 6, 10), area_id="garage")
    f = filt("all", {"areas": ["kitchen"]}, {"devices": ["dev1"]})
    assert p.matches_filter(kitchen, f, now=now)
    assert p.matches_filter(boiler, f, now=now)
    assert not p.matches_filter(neither, f, now=now)


def test_each_axis_can_be_the_deciding_group():
    # One group per axis, and a task that satisfies exactly one of them at a time. A
    # matcher that only ever read the first group would fail three of these four.
    now = dt(2026, 6, 13, 12)
    f = filt(
        "all",
        {"labels": ["mine"]},
        {"areas": ["kitchen"]},
        {"devices": ["dev1"]},
        {"companions": ["battery_notes"]},
    )
    by_label = task("1", "A", dt(2026, 6, 10), labels=["mine"])
    by_area = task("2", "B", dt(2026, 6, 10), area_id="kitchen")
    by_device = task("3", "C", dt(2026, 6, 10), device_id="dev1")
    by_owner = task(
        "4", "D", dt(2026, 6, 10), managed_by={"integration": "battery_notes"}
    )
    unrelated = task("5", "E", dt(2026, 6, 10), labels=["hers"], area_id="garage")
    for matching in (by_label, by_area, by_device, by_owner):
        assert p.matches_filter(matching, f, now=now), matching["id"]
    assert not p.matches_filter(unrelated, f, now=now)


def test_labels_match_all_needs_every_listed_label():
    now = dt(2026, 6, 13, 12)
    both = task("1", "A", dt(2026, 6, 10), labels=["dog", "outdoor"])
    one = task("2", "B", dt(2026, 6, 10), labels=["dog"])
    group = {"labels": ["dog", "outdoor"], "labels_match": "all"}
    assert p.matches_filter(both, filt("all", group), now=now)
    assert not p.matches_filter(one, filt("all", group), now=now)
    # An extra label the group never named does not spoil an "all" match.
    extra = task("3", "C", dt(2026, 6, 10), labels=["dog", "outdoor", "spring"])
    assert p.matches_filter(extra, filt("all", group), now=now)


def test_labels_match_any_needs_one_listed_label():
    now = dt(2026, 6, 13, 12)
    one = task("1", "A", dt(2026, 6, 10), labels=["dog"])
    none = task("2", "B", dt(2026, 6, 10), labels=["cat"])
    group = {"labels": ["dog", "outdoor"], "labels_match": "any"}
    assert p.matches_filter(one, filt("all", group), now=now)
    assert not p.matches_filter(none, filt("all", group), now=now)


def test_an_unknown_labels_match_reads_as_any_in_the_matcher():
    # The matcher reads what it is handed, so the clamp has to hold here too: an
    # unrecognized value must widen to "any", never narrow to "all".
    now = dt(2026, 6, 13, 12)
    one = task("1", "A", dt(2026, 6, 10), labels=["dog"])
    for value in ("sometimes", "ALL", "", None):
        group = {"labels": ["dog", "outdoor"], "labels_match": value}
        assert p.matches_filter(one, filt("all", group), now=now), value
    # ...and with no key at all, which is what a hand-written filter looks like.
    assert p.matches_filter(one, filt("all", {"labels": ["dog", "outdoor"]}), now=now)


def test_an_empty_labels_list_ignores_labels_match():
    # "all" over nothing is not "every label in the house"; an empty list means any.
    now = dt(2026, 6, 13, 12)
    t = task("1", "A", dt(2026, 6, 10), labels=["dog"])
    group = {"labels": [], "labels_match": "all"}
    assert p.matches_filter(t, filt("all", group), now=now)


# ── exclusions ──────────────────────────────────────────────────────────────


def test_exclusions_drop_a_task_inside_their_group():
    now = dt(2026, 6, 13, 12)
    t = task(
        "1", "A", dt(2026, 6, 10), labels=["mine"], area_id="kitchen", device_id="dev1"
    )
    assert not p.matches_filter(t, filt("all", {"exclude_labels": ["mine"]}), now=now)
    assert not p.matches_filter(t, filt("all", {"exclude_areas": ["kitchen"]}), now=now)
    assert not p.matches_filter(t, filt("all", {"exclude_devices": ["dev1"]}), now=now)
    # An exclusion the task doesn't hit leaves it alone.
    assert p.matches_filter(t, filt("all", {"exclude_labels": ["hers"]}), now=now)
    assert p.matches_filter(t, filt("all", {"exclude_areas": ["garage"]}), now=now)
    assert p.matches_filter(t, filt("all", {"exclude_devices": ["dev2"]}), now=now)


def test_an_exclude_only_group_is_active():
    # A group with nothing but an exclusion still filters. Reading it as inactive would
    # drop it from the OR and turn "everything except the call-outs" into "everything".
    now = dt(2026, 6, 13, 12)
    excluded = task("1", "A", dt(2026, 6, 10), labels=["pro"])
    kept = task("2", "B", dt(2026, 6, 10), labels=["dog"])
    f = filt("all", {"exclude_labels": ["pro"]})
    assert not p.matches_filter(excluded, f, now=now)
    assert p.matches_filter(kept, f, now=now)


def test_an_exclusion_only_wins_inside_its_own_group():
    # The rule groups exist for: a task group 1 excludes is still taken by group 2.
    now = dt(2026, 6, 13, 12)
    t = task("1", "A", dt(2026, 6, 10), labels=["dog", "pro"], area_id="kitchen")
    both = filt(
        "all", {"labels": ["dog"], "exclude_labels": ["pro"]}, {"areas": ["kitchen"]}
    )
    assert p.matches_filter(t, both, now=now)
    # ...and group 1 alone still drops it, so the sibling is what rescued it.
    assert not p.matches_filter(
        t, filt("all", {"labels": ["dog"], "exclude_labels": ["pro"]}), now=now
    )


def test_exclude_shopping_drops_the_auto_buy_reminders():
    # The reported workaround it replaces: keeping "Buy softener" out of a spoken
    # digest meant a script filtering on source.buy by hand (#220).
    now = dt(2026, 6, 13, 12)
    buy = task("1", "Buy softener", dt(2026, 6, 10))
    buy["source"] = {"buy": {"asset_id": "a1", "part_id": "p1"}}
    chore = task("2", "Clean gutters", dt(2026, 6, 10))

    on = filt("all", {"exclude_shopping": True})
    assert not p.matches_filter(buy, on, now=now)
    # Only the buy reminders go — everything else the profile selected stays.
    assert p.matches_filter(chore, on, now=now)


def test_exclude_shopping_alone_makes_a_group_active():
    # Nothing else in the group carries a value, so an "is anything set" check that
    # forgot this switch would ignore the group and keep the buy reminders.
    now = dt(2026, 6, 13, 12)
    buy = task("1", "Buy softener", dt(2026, 6, 10))
    buy["source"] = {"buy": {"asset_id": "a1", "part_id": "p1"}}
    assert not p.matches_filter(buy, filt("all", {"exclude_shopping": True}), now=now)


def test_exclude_shopping_is_off_unless_asked_for():
    # A group that does not ask for it must keep every task it had. An inverted check
    # here would silently empty a digest.
    now = dt(2026, 6, 13, 12)
    buy = task("1", "Buy softener", dt(2026, 6, 10))
    buy["source"] = {"buy": {"asset_id": "a1", "part_id": "p1"}}
    assert p.matches_filter(buy, {"status": "all"}, now=now)
    assert p.matches_filter(
        buy, filt("all", {"labels": [], "exclude_shopping": False}), now=now
    )


def test_exclude_shopping_reads_a_real_buy_source_only():
    # buy_source wants both ids; a half-formed source is not a buy reminder, and a
    # wear-part task is a different mechanism entirely.
    now = dt(2026, 6, 13, 12)
    on = filt("all", {"exclude_shopping": True})
    half = task("1", "A", dt(2026, 6, 10))
    half["source"] = {"buy": {"asset_id": "a1"}}
    wear = task("2", "B", dt(2026, 6, 10))
    wear["source"] = {"part": {"asset_id": "a1", "part_id": "p1"}}
    assert p.matches_filter(half, on, now=now)
    assert p.matches_filter(wear, on, now=now)


def test_exclude_shopping_is_per_group_like_every_other_exclusion():
    now = dt(2026, 6, 13, 12)
    buy = task("1", "Buy softener", dt(2026, 6, 10), labels=["dog"])
    buy["source"] = {"buy": {"asset_id": "a1", "part_id": "p1"}}
    f = filt("all", {"exclude_shopping": True}, {"labels": ["dog"]})
    assert p.matches_filter(buy, f, now=now)


def test_empty_exclusions_exclude_nothing():
    # The failure that would hurt most: an inverted check turning "no exclusions" into
    # "exclude everything" empties every profile at once.
    now = dt(2026, 6, 13, 12)
    t = task(
        "1", "A", dt(2026, 6, 10), labels=["mine"], area_id="kitchen", device_id="dev1"
    )
    assert p.matches_filter(
        t,
        filt(
            "all",
            {
                "labels": ["mine"],
                "exclude_labels": [],
                "exclude_areas": [],
                "exclude_devices": [],
            },
        ),
        now=now,
    )
    # A filter block with no groups at all omits the key entirely.
    assert p.matches_filter(t, {"status": "all"}, now=now)


def test_an_exclusion_beats_a_satisfied_include_in_the_same_group():
    now = dt(2026, 6, 13, 12)
    t = task("1", "A", dt(2026, 6, 10), labels=["mine", "pro"], area_id="kitchen")
    assert p.matches_filter(t, filt("all", {"labels": ["mine"]}), now=now)
    assert not p.matches_filter(
        t, filt("all", {"labels": ["mine"], "exclude_labels": ["pro"]}), now=now
    )
    assert not p.matches_filter(
        t, filt("all", {"areas": ["kitchen"], "exclude_areas": ["kitchen"]}), now=now
    )


def test_an_unset_area_or_device_survives_an_exclusion():
    # A task with no area must not be dropped by "exclude the garage" — it isn't there.
    now = dt(2026, 6, 13, 12)
    t = task("1", "A", dt(2026, 6, 10))
    assert p.matches_filter(t, filt("all", {"exclude_areas": ["garage"]}), now=now)
    assert p.matches_filter(t, filt("all", {"exclude_devices": ["dev1"]}), now=now)


# ── active and inactive groups ──────────────────────────────────────────────


def test_an_empty_group_beside_an_active_one_is_ignored():
    # The panel always keeps one group on the form, so a blank row is ordinary. Read as
    # a rule it would match everything and swallow its filled-in sibling.
    now = dt(2026, 6, 13, 12)
    mine = task("1", "A", dt(2026, 6, 10), labels=["mine"])
    hers = task("2", "B", dt(2026, 6, 10), labels=["hers"])
    f = filt("all", {"labels": ["mine"]}, {})
    assert p.matches_filter(mine, f, now=now)
    assert not p.matches_filter(hers, f, now=now)
    # Order does not matter: the blank row is ignored wherever it sits.
    assert not p.matches_filter(hers, filt("all", {}, {"labels": ["mine"]}), now=now)


def test_groups_that_are_all_empty_select_every_live_task():
    # No active group means no include gate: the status tier is the whole filter.
    now = dt(2026, 6, 13, 12)
    t = task("1", "A", dt(2026, 6, 10), labels=["hers"], area_id="garage")
    assert p.matches_filter(t, filt("all", {}, {}), now=now)
    assert p.matches_filter(t, filt("all"), now=now)
    assert p.matches_filter(t, {"status": "all", "groups": None}, now=now)
    assert p.matches_filter(t, {"status": "all"}, now=now)


def test_a_group_entry_that_is_not_an_object_is_ignored():
    # The matcher reads what it is handed — only normalize_groups drops these — so a
    # stray entry must not decide the answer or raise.
    now = dt(2026, 6, 13, 12)
    mine = task("1", "A", dt(2026, 6, 10), labels=["mine"])
    hers = task("2", "B", dt(2026, 6, 10), labels=["hers"])
    f = {"status": "all", "groups": ["nonsense", {"labels": ["mine"]}]}
    assert p.matches_filter(mine, f, now=now)
    assert not p.matches_filter(hers, f, now=now)


def test_the_profile_gates_beat_a_matching_group():
    # Status, enabled and next_due are profile-level and run first. A group can only
    # ever narrow what they left, never widen it.
    now = dt(2026, 6, 13, 12)
    group = {"labels": ["mine"]}
    future = task("1", "A", dt(2026, 6, 30), labels=["mine"])
    off = task("2", "B", dt(2026, 6, 10), labels=["mine"], enabled=False)
    dormant = task("3", "C", None, labels=["mine"])
    assert not p.matches_filter(future, filt("overdue", group), now=now)
    assert p.matches_filter(future, filt("all", group), now=now)
    assert not p.matches_filter(off, filt("all", group), now=now)
    assert not p.matches_filter(dormant, filt("all", group), now=now)


def test_due_queue_applies_the_groups():
    # The queue is what a notification actually sends, so the groups have to survive
    # the trip through due_queue, not just the bare predicate.
    now = dt(2026, 6, 13, 12)
    tasks = [
        task("1", "Mine", dt(2026, 6, 1), labels=["mine"]),
        task("2", "Call someone", dt(2026, 6, 8), labels=["pro"]),
    ]
    q = p.due_queue(tasks, filt("overdue", {"exclude_labels": ["pro"]}), now=now)
    assert [t["name"] for t in q] == ["Mine"]


def test_due_queue_takes_from_either_group():
    now = dt(2026, 6, 13, 12)
    tasks = [
        task("1", "Kitchen", dt(2026, 6, 1), area_id="kitchen"),
        task("2", "Boiler", dt(2026, 6, 8), device_id="dev1"),
        task("3", "Garage", dt(2026, 6, 4), area_id="garage"),
    ]
    q = p.due_queue(
        tasks, filt("overdue", {"areas": ["kitchen"]}, {"devices": ["dev1"]}), now=now
    )
    assert [t["name"] for t in q] == ["Kitchen", "Boiler"]


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
    f = filt("all", {"companions": ["battery_notes"]})
    assert p.matches_filter(_owned(), f, now=now)
    assert not p.matches_filter(_owned(integration="printer_glue"), f, now=now)


def test_companions_matches_any_of_several():
    now = dt(2026, 6, 13, 12)
    f = filt("all", {"companions": ["battery_notes", "dog_glue"]})
    assert p.matches_filter(_owned(integration="dog_glue"), f, now=now)
    assert not p.matches_filter(_owned(integration="printer_glue"), f, now=now)


def test_an_unowned_task_is_never_selected_by_a_companions_list():
    # A task the user made in the panel has no managed_by block, so it belongs to no
    # companion. It must not leak into "just the battery tasks".
    now = dt(2026, 6, 13, 12)
    hand_made = task("2", "Water plants", dt(2026, 6, 10))
    assert not p.matches_filter(
        hand_made, filt("all", {"companions": ["battery_notes"]}), now=now
    )
    # ...and the same task is untouched by an exclude list, which is the other half of
    # the rule: excluding a companion must not sweep up everything unowned.
    assert p.matches_filter(
        hand_made, filt("all", {"exclude_companions": ["battery_notes"]}), now=now
    )


def test_an_explicitly_null_managed_by_owns_nothing():
    # `managed_by: None` is not the same shape as an absent key, and both reach the
    # matcher: `add_task` stores what it is given. They must read the same.
    now = dt(2026, 6, 13, 12)
    t = task("5", "Nulled", dt(2026, 6, 10), managed_by=None)
    assert not p.matches_filter(
        t, filt("all", {"companions": ["battery_notes"]}), now=now
    )
    assert p.matches_filter(
        t, filt("all", {"exclude_companions": ["battery_notes"]}), now=now
    )


def test_a_managed_by_without_an_integration_key_owns_nothing():
    # managed_by is a free-form dict at the service boundary, so a block missing the
    # required key must read as "unowned" rather than crash or match everything.
    now = dt(2026, 6, 13, 12)
    t = task("3", "Odd", dt(2026, 6, 10), managed_by={"display_name": "Nameless"})
    assert not p.matches_filter(
        t, filt("all", {"companions": ["battery_notes"]}), now=now
    )
    assert p.matches_filter(
        t, filt("all", {"exclude_companions": ["battery_notes"]}), now=now
    )


def test_exclude_companions_drops_the_owner_and_wins_over_an_include():
    now = dt(2026, 6, 13, 12)
    f = filt("all", {"exclude_companions": ["battery_notes"]})
    assert not p.matches_filter(_owned(), f, now=now)
    assert p.matches_filter(_owned(integration="dog_glue"), f, now=now)
    # Exclusions are applied last and win, exactly as they do for labels/areas/devices.
    assert not p.matches_filter(
        _owned(),
        filt(
            "all",
            {
                "companions": ["battery_notes"],
                "exclude_companions": ["battery_notes"],
            },
        ),
        now=now,
    )


def test_an_empty_companions_list_selects_every_owner():
    now = dt(2026, 6, 13, 12)
    assert p.matches_filter(_owned(), filt("all", {"companions": []}), now=now)
    assert p.matches_filter(_owned(integration="dog_glue"), {"status": "all"}, now=now)


def test_companions_is_anded_with_the_other_axes_inside_a_group():
    # Each axis narrows: the right owner in the wrong area is still dropped...
    now = dt(2026, 6, 13, 12)
    t = task(
        "4",
        "Replace battery",
        dt(2026, 6, 10),
        area_id="kitchen",
        managed_by={"integration": "battery_notes", "display_name": "Battery Notes"},
    )
    group = {"companions": ["battery_notes"], "areas": ["garage"]}
    assert not p.matches_filter(t, filt("all", group), now=now)
    assert p.matches_filter(t, filt("all", {**group, "areas": ["kitchen"]}), now=now)
    # ...and a second group is how the user asks for the owner anywhere instead.
    assert p.matches_filter(
        t, filt("all", group, {"companions": ["battery_notes"]}), now=now
    )


# ── rejecting a pre-groups filter on write ──────────────────────────────────


def test_check_profiles_use_groups_raises_for_each_legacy_key():
    import pytest

    for key, value in (
        ("labels", ["dog"]),
        ("areas", ["kitchen"]),
        ("devices", ["dev1"]),
        ("companions", ["battery_notes"]),
        ("exclude_labels", ["pro"]),
        ("exclude_areas", ["garage"]),
        ("exclude_devices", ["dev2"]),
        ("exclude_companions", ["dog_glue"]),
        ("exclude_shopping", True),
    ):
        raw = [{"id": "p1", "name": "X", "filter": {"status": "all", key: value}}]
        with pytest.raises(ValueError) as err:
            p.check_profiles_use_groups(raw)
        assert "filter.groups" in str(err.value), key
        assert "0.22.0b4" in str(err.value), key
    # An empty legacy list is still a legacy key: the caller is on the old shape and
    # its next save would carry a real list.
    with pytest.raises(ValueError):
        p.check_profiles_use_groups([{"filter": {"labels": []}}])


def test_check_profiles_use_groups_passes_a_groups_filter_through_unchanged():
    raw = [
        {"id": "p1", "name": "X", "filter": {"status": "all", "groups": [{}]}},
        {"id": "p2", "name": "Y", "filter": {"status": "overdue"}},
        {"id": "p3", "name": "Z"},
        {"id": "p4", "name": "W", "filter": "nonsense"},
        "not a profile",
    ]
    assert p.check_profiles_use_groups(raw) is raw
    # A legacy key *inside* a group is the shape we want, not the one we refuse.
    nested = [{"filter": {"groups": [{"exclude_labels": ["pro"]}]}}]
    assert p.check_profiles_use_groups(nested) is nested
    assert p.check_profiles_use_groups([]) == []
    assert p.check_profiles_use_groups("nonsense") == "nonsense"


def test_check_profiles_use_groups_keeps_looking_past_a_non_dict_entry():
    # A junk entry must not end the scan: the legacy filter after it is still refused.
    with pytest.raises(ValueError):
        p.check_profiles_use_groups(["junk", {"filter": {"labels": ["dog"]}}])


# ── migration to groups ─────────────────────────────────────────────────────


def test_migrate_filter_v1_wraps_the_flat_keys_in_one_group():
    out = p.migrate_filter_v1(
        {
            "status": "due_soon",
            "labels": ["dog"],
            "areas": ["kitchen"],
            "devices": ["dev1"],
            "companions": ["battery_notes"],
            "exclude_labels": ["pro"],
            "exclude_areas": ["garage"],
            "exclude_devices": ["dev2"],
            "exclude_companions": ["dog_glue"],
            "exclude_shopping": True,
        }
    )
    assert out == {
        "groups": [
            {
                "labels": ["dog"],
                "labels_match": "any",
                "areas": ["kitchen"],
                "devices": ["dev1"],
                "companions": ["battery_notes"],
                "exclude_labels": ["pro"],
                "exclude_areas": ["garage"],
                "exclude_devices": ["dev2"],
                "exclude_companions": ["dog_glue"],
                "exclude_shopping": True,
            }
        ],
        "status": "due_soon",
    }


def test_migrate_filter_v1_selects_the_same_tasks_as_the_flat_filter_did():
    # The migration's whole promise, asserted on tasks rather than on a shape.
    now = dt(2026, 6, 13, 12)
    migrated = p.migrate_filter_v1(
        {"status": "all", "labels": ["dog"], "exclude_areas": ["garage"]}
    )
    kitchen_dog = task("1", "A", dt(2026, 6, 10), labels=["dog"], area_id="kitchen")
    garage_dog = task("2", "B", dt(2026, 6, 10), labels=["dog"], area_id="garage")
    kitchen_cat = task("3", "C", dt(2026, 6, 10), labels=["cat"], area_id="kitchen")
    assert p.matches_filter(kitchen_dog, migrated, now=now)
    assert not p.matches_filter(garage_dog, migrated, now=now)
    assert not p.matches_filter(kitchen_cat, migrated, now=now)


def test_migrate_filter_v1_is_idempotent():
    once = p.migrate_filter_v1({"status": "all", "labels": ["dog"]})
    assert p.migrate_filter_v1(once) == once
    assert p.migrate_filter_v1(p.migrate_filter_v1(once)) == once


def test_migrate_filter_v1_keeps_existing_groups_and_drops_stray_flat_keys():
    # Half-converted input: the groups are the truth, and the flat keys beside them are
    # residue that must not be lifted into a second group.
    out = p.migrate_filter_v1(
        {
            "status": "all",
            "labels": ["stray"],
            "exclude_shopping": True,
            "groups": [{"areas": ["kitchen"]}, {"devices": ["dev1"]}],
        }
    )
    assert [g["areas"] for g in out["groups"]] == [["kitchen"], []]
    assert [g["devices"] for g in out["groups"]] == [[], ["dev1"]]
    assert all(g["labels"] == [] for g in out["groups"])
    assert all(g["exclude_shopping"] is False for g in out["groups"])


def test_migrate_filter_v1_turns_garbage_into_one_empty_group():
    canonical = {"groups": [EMPTY_GROUP], "status": "overdue"}
    assert p.migrate_filter_v1(None) == canonical
    assert p.migrate_filter_v1("nonsense") == canonical
    assert p.migrate_filter_v1({}) == canonical
    assert p.migrate_filter_v1({"groups": "nonsense"}) == canonical
    assert p.migrate_filter_v1({"status": "nope", "labels": "nonsense"}) == canonical


def test_migrate_options_v1_migrates_every_profile_filter():
    options = {
        "profiles": [
            {"id": "p1", "name": "Dog", "filter": {"status": "all", "labels": ["dog"]}},
            {
                "id": "p2",
                "name": "Kitchen",
                "filter": {"status": "overdue", "areas": ["kitchen"]},
            },
        ]
    }
    out = p.migrate_options_v1(options)
    assert out["profiles"][0]["filter"] == {
        "groups": [{**EMPTY_GROUP, "labels": ["dog"]}],
        "status": "all",
    }
    assert out["profiles"][1]["filter"] == {
        "groups": [{**EMPTY_GROUP, "areas": ["kitchen"]}],
        "status": "overdue",
    }
    # The input is left alone: a migration that mutated the entry's own options would
    # make async_update_entry see no change.
    assert options["profiles"][0]["filter"] == {"status": "all", "labels": ["dog"]}


def test_migrate_options_v1_keeps_every_other_option_byte_identical():
    options = {
        "sync_problem_sensors": True,
        "one_off_retention_days": 30,
        "shopping_list_entity": "todo.shopping",
        "dismissed_companions": ["dog_glue"],
        "notifications": [{"id": "n1", "profile_id": "p1"}],
        "profiles": [{"id": "p1", "name": "Dog", "filter": {"labels": ["dog"]}}],
    }
    out = p.migrate_options_v1(options)
    for key in (
        "sync_problem_sensors",
        "one_off_retention_days",
        "shopping_list_entity",
        "dismissed_companions",
        "notifications",
    ):
        assert out[key] == options[key], key
    assert set(out) == set(options)


def test_migrate_options_v1_keeps_a_profiles_id_name_and_sync():
    sync = {"entity_id": "todo.family", "two_way": False, "vanish_as_completed": True}
    out = p.migrate_options_v1(
        {"profiles": [{"id": "p1", "name": "Dog", "sync": sync, "filter": {}}]}
    )
    profile = out["profiles"][0]
    assert profile["id"] == "p1"
    assert profile["name"] == "Dog"
    assert profile["sync"] == sync


def test_migrate_options_v1_survives_options_without_usable_profiles():
    assert p.migrate_options_v1({}) == {}
    assert p.migrate_options_v1({"profiles": "nonsense"}) == {"profiles": "nonsense"}
    # A non-dict profile is passed through, and normalize_profiles drops it later.
    out = p.migrate_options_v1({"profiles": ["nonsense", {"id": "p1"}]})
    assert out["profiles"][0] == "nonsense"
    canonical = {"groups": [EMPTY_GROUP], "status": "overdue"}
    assert out["profiles"][1]["filter"] == canonical
    assert p.normalize_profiles(out["profiles"])[0]["id"] == "p1"
    assert len(p.normalize_profiles(out["profiles"])) == 1


# ── the service-only "none" status ──────────────────────────────────────────


def test_with_status_replaces_the_status_and_leaves_the_original_alone():
    # A per-call override must not reach the stored profile: `resolve_profile` hands
    # back the live options entry, so mutating in place would leak "everything" into
    # a profile the user saved as "overdue".
    f = p.normalize_filter({"status": "overdue", "groups": [{"labels": ["dog"]}]})
    widened = p.with_status(f, "all")
    assert widened["status"] == "all"
    assert f["status"] == "overdue"
    assert widened["groups"] == f["groups"]
    assert widened["groups"][0]["labels"] == ["dog"]


def test_with_status_accepts_every_service_status():
    f = p.normalize_filter({"status": "overdue"})
    for status in p.SERVICE_STATUSES:
        assert p.with_status(f, status)["status"] == status
    assert p.STATUS_NONE in p.SERVICE_STATUSES


def test_with_status_leaves_the_filter_alone_for_no_override():
    # The ordinary case: a call that did not ask for one. An unknown value falls back
    # the same way rather than raising, matching every other clamp in this module.
    f = p.normalize_filter({"status": "due_soon"})
    for value in (None, "", "sometimes", 3):
        assert p.with_status(f, value)["status"] == "due_soon"


def test_status_none_matches_nothing_that_every_other_status_would():
    now = dt(2026, 6, 13, 12)
    overdue = task("t", "X", dt(2026, 6, 1))
    assert p.matches_filter(overdue, p.normalize_filter({"status": "all"}), now=now)
    none = p.with_status(p.normalize_filter({"status": "all"}), p.STATUS_NONE)
    assert p.matches_filter(overdue, none, now=now) is False
    assert p.due_queue([overdue], none, now=now) == []


def test_a_stored_none_status_reads_back_as_overdue():
    # The boundary that keeps "match nothing" a per-call option and never a saved
    # profile. `STATUSES` stays three-valued so this clamp does the work; widening it
    # "for symmetry" would let a user save a profile that can never select anything.
    assert p.normalize_filter({"status": "none"})["status"] == "overdue"
    assert p.normalize_profile({"filter": {"status": "none"}})["filter"]["status"] == (
        "overdue"
    )
    assert p.STATUS_NONE not in p.STATUSES
