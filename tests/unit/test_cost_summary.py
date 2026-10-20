"""The spend and purchase totals (#460)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from custom_components.home_keeper import cost_summary as cs

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def _ts(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def _task(tid: str, *entries: dict) -> dict:
    return {"id": tid, "name": f"Task {tid}", "completions": list(entries)}


# ── normalize_windows ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ([60, 30], [30, 60]),
        ([30, 30, "30"], [30]),
        (["7", 90.0], [7, 90]),
        ([0, -1, 3651, "x", None, 5], [5]),
        ([1, 3650], [1, 3650]),
        ([5, 4, 3, 2, 1], [1, 2, 3, 4]),
        ([], [30, 60]),
        (["bad"], [30, 60]),
        (None, [30, 60]),
        ("30", [30, 60]),
        ((14,), [14]),
        ([float("inf")], [30, 60]),
        ([True, 7], [7]),
    ],
)
def test_normalize_windows(value, expected) -> None:
    assert cs.normalize_windows(value) == expected


def test_normalize_windows_returns_a_new_default_list() -> None:
    first = cs.normalize_windows(None)
    first.append(1)
    assert cs.normalize_windows(None) == [30, 60]


# ── spend_records ────────────────────────────────────────────────────────────


def test_records_keep_only_completions_with_a_cost() -> None:
    tasks = [
        _task(
            "a",
            {"ts": _ts(1), "cost": 3.19, "who": "Kay"},
            {"ts": _ts(2)},
            {"ts": _ts(3), "cost": None},
            {"ts": _ts(4), "cost": 0},
        )
    ]
    records = cs.spend_records(tasks, [], tz=UTC)
    assert records == [
        {
            "ts": _ts(1),
            "cost": 3.19,
            "who": "Kay",
            "task_id": "a",
            "task_name": "Task a",
            "asset_id": None,
            "archived": False,
        },
        {
            "ts": _ts(4),
            "cost": 0.0,
            "who": None,
            "task_id": "a",
            "task_name": "Task a",
            "asset_id": None,
            "archived": False,
        },
    ]


def test_records_skip_a_bad_time_and_read_a_bad_cost_as_zero() -> None:
    tasks = [
        _task(
            "a",
            {"ts": "not a time", "cost": 5},
            {"ts": None, "cost": 5},
            {"ts": _ts(1), "cost": "nan"},
        )
    ]
    records = cs.spend_records(tasks, [], tz=UTC)
    assert [r["cost"] for r in records] == [0.0]


def test_records_give_a_naive_time_the_zone() -> None:
    zone = timezone(timedelta(hours=-7))
    tasks = [_task("a", {"ts": "2026-10-01T08:00:00", "cost": 1})]
    records = cs.spend_records(tasks, [], tz=zone)
    assert records[0]["ts"] == "2026-10-01T08:00:00-07:00"


def test_records_include_archived_appliance_history() -> None:
    assets = [
        {
            "id": "heater",
            "task_history": [
                {
                    "task_id": "gone",
                    "task_name": "Flush heater",
                    "completions": [{"ts": _ts(10), "cost": 50}, {"ts": _ts(11)}],
                },
                {"task_id": "empty", "completions": []},
            ],
        },
        {"id": "no-history"},
    ]
    records = cs.spend_records([], assets, tz=UTC)
    assert records == [
        {
            "ts": _ts(10),
            "cost": 50.0,
            "who": None,
            "task_id": "gone",
            "task_name": "Flush heater",
            "asset_id": "heater",
            "archived": True,
        }
    ]


def test_records_are_newest_first_across_zones() -> None:
    # 10:00+02:00 is 08:00 UTC, which is before 09:00 UTC. A text sort puts it
    # after, so this pins the sort to the real time.
    tasks = [
        _task("a", {"ts": "2026-10-01T10:00:00+02:00", "cost": 1}),
        _task("b", {"ts": "2026-10-01T09:00:00+00:00", "cost": 2}),
        _task("c", {"ts": "2026-09-01T09:00:00+00:00", "cost": 3}),
    ]
    records = cs.spend_records(tasks, [], tz=UTC)
    assert [r["task_id"] for r in records] == ["b", "a", "c"]


def test_records_with_no_tasks_and_no_assets() -> None:
    assert cs.spend_records([], [], tz=UTC) == []
    assert (
        cs.spend_records([{"id": "x"}], [{"id": "y", "task_history": None}], tz=UTC)
        == []
    )


def test_a_task_with_no_name_gives_an_empty_name() -> None:
    records = cs.spend_records(
        [{"id": "a", "completions": [{"ts": _ts(1), "cost": 1}]}], [], tz=UTC
    )
    assert records[0]["task_name"] == ""


# ── spend_summary ────────────────────────────────────────────────────────────


def _records(*pairs: tuple[float, float]) -> list[dict]:
    tasks = [_task(str(i), {"ts": _ts(d), "cost": c}) for i, (d, c) in enumerate(pairs)]
    return cs.spend_records(tasks, [], tz=UTC)


def test_summary_windows_and_all_time() -> None:
    records = _records((5, 3.19), (19, 24.99), (48, 180), (137, 215), (349, 49.25))
    summary = cs.spend_summary(records, now=NOW, windows=[30, 60])
    assert summary == {
        "windows": [
            {"days": 30, "total": 28.18, "count": 2, "since": _ts(30)},
            {"days": 60, "total": 208.18, "count": 3, "since": _ts(60)},
        ],
        "all_time": {"total": 472.43, "count": 5, "first": _ts(349)},
    }


def test_summary_window_start_is_inclusive() -> None:
    records = _records((30, 10), (30.0001, 20))
    summary = cs.spend_summary(records, now=NOW, windows=[30])
    assert summary["windows"][0]["total"] == 10
    assert summary["windows"][0]["count"] == 1


def test_summary_counts_a_future_record_in_every_window() -> None:
    records = _records((-1, 7))
    summary = cs.spend_summary(records, now=NOW, windows=[1])
    assert summary["windows"][0]["total"] == 7


def test_summary_rounds_once() -> None:
    records = _records(*[(1, 0.1)] * 3)
    summary = cs.spend_summary(records, now=NOW, windows=[30])
    assert summary["windows"][0]["total"] == 0.3
    assert summary["all_time"]["total"] == 0.3


def test_summary_with_no_records() -> None:
    summary = cs.spend_summary([], now=NOW, windows=[30])
    assert summary == {
        "windows": [{"days": 30, "total": 0, "count": 0, "since": _ts(30)}],
        "all_time": {"total": 0, "count": 0, "first": None},
    }


def test_summary_with_no_windows() -> None:
    summary = cs.spend_summary(_records((1, 2)), now=NOW, windows=[])
    assert summary["windows"] == []
    assert summary["all_time"]["total"] == 2


# ── purchase_total ───────────────────────────────────────────────────────────


def test_purchase_total() -> None:
    assets = [
        {"id": "a", "cost": 899.99},
        {"id": "b", "cost": 100.01},
        {"id": "c"},
        {"id": "d", "cost": None},
        {"id": "e", "cost": 0},
    ]
    assert cs.purchase_total(assets) == {"total": 1000.0, "count": 3}


def test_purchase_total_empty() -> None:
    assert cs.purchase_total([]) == {"total": 0, "count": 0}


def test_archived_history_gives_a_naive_time_the_zone() -> None:
    zone = timezone(timedelta(hours=2))
    assets = [
        {
            "id": "heater",
            "task_history": [
                {
                    "task_id": "gone",
                    "completions": [{"ts": "2026-01-01T10:00:00", "cost": 1}],
                }
            ],
        }
    ]
    records = cs.spend_records([], assets, tz=zone)
    assert records[0]["ts"] == "2026-01-01T10:00:00+02:00"


def test_totals_round_to_cents() -> None:
    records = _records((1, 1.234), (2, 1.0))
    summary = cs.spend_summary(records, now=NOW, windows=[30])
    assert summary["windows"][0]["total"] == 2.23
    assert summary["all_time"]["total"] == 2.23
    assert cs.purchase_total([{"cost": 1.234}, {"cost": 0.5}]) == {
        "total": 1.73,
        "count": 2,
    }
