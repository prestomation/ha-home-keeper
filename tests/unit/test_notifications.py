"""Unit tests for the pure actionable-notification helpers."""

from datetime import datetime, timedelta, timezone

import hk_notifications as n

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


# ── action encode / decode ──────────────────────────────────────────────────


def test_encode_decode_roundtrip():
    a = n.encode_action(n.ACTION_SNOOZE, "task123", "prof456")
    assert n.decode_action(a) == (n.ACTION_SNOOZE, "task123", "prof456")


def test_decode_rejects_foreign_and_malformed():
    assert n.decode_action(None) is None
    assert n.decode_action("") is None
    assert n.decode_action("OTHER_APP::complete::t::p") is None
    assert n.decode_action("home_keeper::complete::t") is None  # too few parts
    assert n.decode_action("home_keeper::bogus::t::p") is None  # unknown verb
    assert n.decode_action("home_keeper::complete::::p") is None  # empty task id


# ── profile normalization ───────────────────────────────────────────────────


def test_normalize_profile_defaults_and_id():
    p = n.normalize_profile({"name": "Me"})
    assert p["name"] == "Me"
    assert p["id"]  # generated
    assert p["actions"] == n.DEFAULT_ACTIONS
    assert p["style"] == n.STYLE_WALK
    assert p["snooze_hours"] == n.DEFAULT_SNOOZE_HOURS
    assert p["filter"]["status"] == n.STATUS_OVERDUE
    assert p["auto"] == {"overdue": False, "due_soon": False}


def test_normalize_profile_clamps_actions_and_dedupes_preserving_order():
    p = n.normalize_profile(
        {"id": "x", "actions": ["skip", "bogus", "complete", "skip"]}
    )
    assert p["actions"] == ["skip", "complete"]
    assert p["id"] == "x"


def test_normalize_profile_bad_snooze_falls_back():
    assert n.normalize_profile({"snooze_hours": "nope"})["snooze_hours"] == 24
    assert n.normalize_profile({"snooze_hours": 0})["snooze_hours"] == 24
    assert n.normalize_profile({"snooze_hours": 6})["snooze_hours"] == 6


def test_resolve_profile_by_id_then_name():
    profiles = [n.normalize_profile({"id": "a", "name": "Me"})]
    assert n.resolve_profile(profiles, "a")["name"] == "Me"
    assert n.resolve_profile(profiles, "Me")["id"] == "a"
    assert n.resolve_profile(profiles, "nope") is None
    assert n.resolve_profile(profiles, None) is None


# ── filtering & queue ───────────────────────────────────────────────────────


def test_matches_filter_status_overdue_vs_due_soon():
    now = dt(2026, 6, 13, 12)
    overdue = task("1", "A", dt(2026, 6, 10))
    soon = task("2", "B", dt(2026, 6, 14))
    far = task("3", "C", dt(2026, 9, 1))
    f_over = {"status": "overdue"}
    f_soon = {"status": "due_soon"}
    f_all = {"status": "all"}
    assert n.matches_filter(overdue, f_over, now=now)
    assert not n.matches_filter(soon, f_over, now=now)
    assert n.matches_filter(soon, f_soon, now=now)
    assert n.matches_filter(overdue, f_soon, now=now)  # overdue counts as due_soon
    assert not n.matches_filter(far, f_soon, now=now)
    assert n.matches_filter(far, f_all, now=now)  # all -> any active task


def test_matches_filter_excludes_disabled_dormant_and_problem():
    now = dt(2026, 6, 13, 12)
    f = {"status": "all"}
    assert not n.matches_filter(
        task("1", "A", dt(2026, 6, 10), enabled=False), f, now=now
    )
    assert not n.matches_filter(task("2", "B", None), f, now=now)
    assert not n.matches_filter(
        task("3", "C", dt(2026, 6, 10), source={"problem_sensor": {"entity_id": "x"}}),
        f,
        now=now,
    )


def test_matches_filter_labels_areas_devices():
    now = dt(2026, 6, 13, 12)
    t = task(
        "1", "A", dt(2026, 6, 10), labels=["mine"], area_id="kitchen", device_id="dev1"
    )
    assert n.matches_filter(t, {"status": "all", "labels": ["mine"]}, now=now)
    assert not n.matches_filter(t, {"status": "all", "labels": ["hers"]}, now=now)
    assert n.matches_filter(t, {"status": "all", "areas": ["kitchen"]}, now=now)
    assert not n.matches_filter(t, {"status": "all", "areas": ["garage"]}, now=now)
    assert n.matches_filter(t, {"status": "all", "devices": ["dev1"]}, now=now)
    assert not n.matches_filter(t, {"status": "all", "devices": ["dev2"]}, now=now)


def test_due_queue_orders_most_overdue_first():
    now = dt(2026, 6, 13, 12)
    tasks = [
        task("1", "Later", dt(2026, 6, 12)),
        task("2", "Earliest", dt(2026, 6, 1)),
        task("3", "Middle", dt(2026, 6, 8)),
        task("4", "Future", dt(2026, 12, 1)),  # filtered out by overdue
    ]
    q = n.due_queue(tasks, {"status": "overdue"}, now=now)
    assert [t["name"] for t in q] == ["Earliest", "Middle", "Later"]


# ── payload building ────────────────────────────────────────────────────────


def test_build_notification_walk_actions_and_tag():
    now = dt(2026, 6, 13, 12)
    profile = n.normalize_profile(
        {
            "id": "p1",
            "name": "Me",
            "actions": ["complete", "snooze", "open"],
            "snooze_hours": 6,
        }
    )
    t = task("t1", "Furnace filter", dt(2026, 6, 10))
    payload = n.build_notification(t, profile=profile, now=now)
    assert payload["title"] == "Furnace filter"
    assert "Overdue by 3 days" in payload["message"]
    assert payload["data"]["tag"] == "home_keeper_p1"
    actions = payload["data"]["actions"]
    assert [a["title"] for a in actions] == ["Mark done", "Snooze 6h", "Open"]
    assert actions[0]["action"] == "home_keeper::complete::t1::p1"
    # The open button carries a panel deep-link URI.
    assert actions[2]["uri"] == "/home-keeper/tasks/t1"


def test_overdue_phrase_singular_and_due_now():
    now = dt(2026, 6, 13, 12)
    profile = n.normalize_profile({"id": "p", "actions": ["complete"]})
    one = n.build_notification(
        task("t", "X", dt(2026, 6, 12, 12)), profile=profile, now=now
    )
    assert "Overdue by 1 day." in one["message"]
    same = n.build_notification(
        task("t", "X", dt(2026, 6, 13, 12)), profile=profile, now=now
    )
    assert same["message"] == "Due now."


def test_build_digest_lists_and_truncates():
    now = dt(2026, 6, 13, 12)
    profile = n.normalize_profile({"id": "p", "style": "digest"})
    q = [task(str(i), f"Task {i}", dt(2026, 6, 1)) for i in range(7)]
    payload = n.build_digest(q, profile=profile, now=now)
    assert payload["title"] == "7 tasks due"
    assert "…and 2 more" in payload["message"]
    assert payload["data"]["tag"] == "home_keeper_p"
