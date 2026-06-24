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
    assert prof["filter"]["status"] == p.STATUS_OVERDUE
    assert prof["filter"] == {
        "labels": [],
        "areas": [],
        "devices": [],
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


def test_matches_filter_excludes_disabled_dormant_and_problem():
    now = dt(2026, 6, 13, 12)
    f = {"status": "all"}
    assert not p.matches_filter(
        task("1", "A", dt(2026, 6, 10), enabled=False), f, now=now
    )
    assert not p.matches_filter(task("2", "B", None), f, now=now)
    assert not p.matches_filter(
        task("3", "C", dt(2026, 6, 10), source={"problem_sensor": {"entity_id": "x"}}),
        f,
        now=now,
    )


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
        assert got is case["expected"], f"{case['name']}: expected {case['expected']}, got {got}"
