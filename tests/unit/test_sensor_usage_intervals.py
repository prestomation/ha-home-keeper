"""Usage between completions on a meter task (issue #305).

``sensor_tasks.usage_intervals`` turns the readings a usage task already logs into the
usage each service interval ran, and ``usage_interval_stats`` summarizes them. The
panel has the same rule in ``utils.usageIntervalStats``; the two are tested to the same
edge cases on purpose, so a change on one side that the other does not follow shows up
as a red test rather than as two screens disagreeing.
"""

from __future__ import annotations

from typing import Any

import hk_sensor_tasks as st


def usage_task(*completions: tuple[str, Any], mode: str = "usage") -> dict[str, Any]:
    """A sensor task carrying ``(ts, reading)`` completions, in the order given."""
    return {
        "id": "t1",
        "recurrence_type": "sensor",
        "sensor": {
            "entity_id": "sensor.odometer",
            "mode": mode,
            "target": 10000.0,
            "baseline": 163900.0,
        },
        "completions": [
            {"ts": ts} if reading is None else {"ts": ts, "reading": reading}
            for ts, reading in completions
        ],
    }


def test_intervals_are_the_gaps_between_consecutive_readings() -> None:
    task = usage_task(
        ("2023-03-12T09:00:00+00:00", 120000.0),
        ("2024-02-04T09:00:00+00:00", 134800.0),
        ("2024-11-19T09:00:00+00:00", 150200.0),
        ("2025-08-28T09:00:00+00:00", 163900.0),
    )
    assert st.usage_intervals(task) == [14800.0, 15400.0, 13700.0]


def test_a_single_reading_has_no_interval() -> None:
    assert st.usage_intervals(usage_task(("2025-08-28T09:00:00+00:00", 163900.0))) == []


def test_no_completions_has_no_interval() -> None:
    assert st.usage_intervals(usage_task()) == []


def test_a_task_with_no_completions_key_at_all_has_no_interval() -> None:
    """A task built before the key existed, or a caller passing a partial dict."""
    task = usage_task()
    del task["completions"]
    assert st.usage_intervals(task) == []
    assert st.usage_interval_stats(task) == {}


def test_a_back_dated_completion_is_ordered_by_its_timestamp() -> None:
    """``completions`` keeps insertion order, so the newest entry can be the oldest.

    Subtracting in list order here would report 15400 and then -1400, and the negative
    would then be dropped — losing a real interval and reporting a wrong one.
    """
    task = usage_task(
        ("2024-02-04T09:00:00+00:00", 134800.0),
        ("2024-11-19T09:00:00+00:00", 150200.0),
        ("2023-03-12T09:00:00+00:00", 120000.0),
    )
    assert st.usage_intervals(task) == [14800.0, 15400.0]


def test_mixed_utc_offsets_are_compared_as_instants() -> None:
    """A store that has seen a timezone change holds mixed offsets.

    Lexicographically ``2024-02-04T23:00:00-05:00`` sorts after
    ``2024-02-05T02:00:00+00:00``, but they are the same instant three hours apart the
    other way, so a string sort puts these two in the wrong order.
    """
    task = usage_task(
        ("2024-02-05T02:00:00+00:00", 134800.0),
        ("2024-02-04T23:00:00-05:00", 150200.0),
    )
    assert st.usage_intervals(task) == [15400.0]


def test_a_completion_without_a_reading_is_skipped() -> None:
    """History predating #235 has no reading, and a task can be completed while its
    sensor is unavailable. Neither entry can take part in a subtraction."""
    task = usage_task(
        ("2024-02-04T09:00:00+00:00", 134800.0),
        ("2024-11-19T09:00:00+00:00", None),
        ("2025-08-28T09:00:00+00:00", 163900.0),
    )
    assert st.usage_intervals(task) == [29100.0]


def test_a_non_numeric_reading_is_skipped() -> None:
    task = usage_task(
        ("2024-02-04T09:00:00+00:00", 134800.0),
        ("2024-11-19T09:00:00+00:00", "150200"),
        ("2025-08-28T09:00:00+00:00", 163900.0),
    )
    assert st.usage_intervals(task) == [29100.0]


def test_a_boolean_reading_is_not_a_number() -> None:
    """``True`` is an ``int`` in Python, and would silently subtract as 1."""
    task = usage_task(
        ("2024-02-04T09:00:00+00:00", 134800.0),
        ("2024-11-19T09:00:00+00:00", True),
        ("2025-08-28T09:00:00+00:00", 163900.0),
    )
    assert st.usage_intervals(task) == [29100.0]


def test_an_infinite_reading_is_skipped() -> None:
    task = usage_task(
        ("2024-02-04T09:00:00+00:00", 134800.0),
        ("2024-11-19T09:00:00+00:00", float("inf")),
        ("2025-08-28T09:00:00+00:00", 163900.0),
    )
    assert st.usage_intervals(task) == [29100.0]


def test_a_completion_without_a_timestamp_is_skipped() -> None:
    task = usage_task(
        ("2024-02-04T09:00:00+00:00", 134800.0),
        ("2025-08-28T09:00:00+00:00", 163900.0),
    )
    task["completions"].insert(1, {"ts": "", "reading": 150200.0})
    assert st.usage_intervals(task) == [29100.0]


def test_text_that_ends_in_an_offset_but_is_not_a_date_is_skipped() -> None:
    """The panel tests the tail of the stamp, so this gets past its offset check and is
    caught by the parse instead. Here it is the ``ValueError`` that catches it, and the
    two sides drop the same string."""
    task = usage_task(
        ("not a date+00:00", 120000.0),
        ("2025-08-28T09:00:00+00:00", 163900.0),
    )
    assert st.usage_intervals(task) == []


def test_an_unparseable_timestamp_is_skipped() -> None:
    task = usage_task(
        ("2024-02-04T09:00:00+00:00", 134800.0),
        ("not a date", 150200.0),
        ("2025-08-28T09:00:00+00:00", 163900.0),
    )
    assert st.usage_intervals(task) == [29100.0]


def test_two_completions_at_the_same_instant_keep_their_stored_order() -> None:
    """Ordering is by instant alone, so entries that tie keep the order they are in.

    A tie is reachable: two different timestamp strings can name the same instant when
    the store holds mixed offsets, and the entries are keyed by string. Sorting the
    whole record instead would order the tie by reading, which is the store inventing
    a sequence it was never told.
    """
    task = usage_task(
        ("2024-02-05T02:00:00+00:00", 150200.0),
        ("2024-02-04T21:00:00-05:00", 134800.0),
    )
    assert st.usage_intervals(task) == []


def test_every_offset_shape_home_assistant_writes_is_accepted() -> None:
    """``Z``, ``+00:00`` and a real offset all name an instant and all take part."""
    task = usage_task(
        ("2024-02-04T09:00:00Z", 134800.0),
        ("2024-11-19T09:00:00+00:00", 150200.0),
        ("2025-08-28T04:00:00-05:00", 163900.0),
    )
    assert st.usage_intervals(task) == [15400.0, 13700.0]


def test_a_stamp_with_no_offset_is_skipped() -> None:
    """Naive beside aware is not an ordering, it is a ``TypeError``.

    Python refuses to compare the two, which would raise out of the next-due sensor's
    attributes, and the panel's ``new Date`` would read the offset-free one as the
    viewer's own zone instead — so the same history would sort differently in Berlin
    and in Seattle. Neither is an answer, so both sides drop it. Nothing Home Keeper
    writes is offset-free; hand-edited storage can be.
    """
    task = usage_task(
        ("2024-02-04T09:00:00+00:00", 134800.0),
        ("2024-11-19T09:00:00", 150200.0),
        ("2025-08-28T09:00:00+00:00", 163900.0),
    )
    assert st.usage_intervals(task) == [29100.0]


def test_a_meter_reset_drops_the_negative_interval() -> None:
    """A replaced controller reads lower than the completion before it, so the
    difference is not usage. The interval after the reset is real and is kept."""
    task = usage_task(
        ("2024-02-04T09:00:00+00:00", 134800.0),
        ("2024-11-19T09:00:00+00:00", 200.0),
        ("2025-08-28T09:00:00+00:00", 14000.0),
    )
    assert st.usage_intervals(task) == [13800.0]


def test_a_zero_interval_is_kept() -> None:
    """Two completions at the same reading are 0 units apart, which is an answer."""
    task = usage_task(
        ("2024-02-04T09:00:00+00:00", 134800.0),
        ("2024-11-19T09:00:00+00:00", 134800.0),
    )
    assert st.usage_intervals(task) == [0.0]


def test_skips_never_count_toward_an_interval() -> None:
    """A skip resets the meter, but it records work that was not done, so the interval
    it sits inside is still one service interval."""
    task = usage_task(
        ("2024-02-04T09:00:00+00:00", 134800.0),
        ("2025-08-28T09:00:00+00:00", 163900.0),
    )
    task["skips"] = [{"ts": "2024-11-19T09:00:00+00:00", "reading": 145000.0}]
    assert st.usage_intervals(task) == [29100.0]


# ── The summary ──────────────────────────────────────────────────────────────


def test_stats_report_the_last_average_and_range() -> None:
    task = usage_task(
        ("2023-03-12T09:00:00+00:00", 120000.0),
        ("2024-02-04T09:00:00+00:00", 134800.0),
        ("2024-11-19T09:00:00+00:00", 150200.0),
        ("2025-08-28T09:00:00+00:00", 163900.0),
    )
    stats = st.usage_interval_stats(task)
    assert stats["last"] == 13700.0
    assert stats["average"] == (14800.0 + 15400.0 + 13700.0) / 3
    assert stats["shortest"] == 13700.0
    assert stats["longest"] == 15400.0


def test_stats_over_one_interval_are_that_interval() -> None:
    task = usage_task(
        ("2024-02-04T09:00:00+00:00", 134800.0),
        ("2025-08-28T09:00:00+00:00", 150200.0),
    )
    assert st.usage_interval_stats(task) == {
        "last": 15400.0,
        "average": 15400.0,
        "shortest": 15400.0,
        "longest": 15400.0,
    }


def test_stats_are_empty_without_an_interval() -> None:
    assert st.usage_interval_stats(usage_task(("2025-08-28T09:00:00+00:00", 1.0))) == {}


def test_stats_are_empty_for_a_threshold_task() -> None:
    """A threshold task logs a reading too, but that reading is a measurement and not
    a meter that only climbs, so the difference between two of them is not usage."""
    task = usage_task(
        ("2024-02-04T09:00:00+00:00", 58.0),
        ("2025-08-28T09:00:00+00:00", 55.0),
        mode="threshold",
    )
    assert st.usage_interval_stats(task) == {}


def test_stats_are_empty_for_a_task_with_no_sensor_binding() -> None:
    assert st.usage_interval_stats({"id": "t1", "recurrence_type": "floating"}) == {}


def test_the_last_stat_is_the_newest_surviving_interval() -> None:
    """After a meter reset the newest interval is the one after it, not the drop."""
    task = usage_task(
        ("2023-03-12T09:00:00+00:00", 120000.0),
        ("2024-02-04T09:00:00+00:00", 134800.0),
        ("2024-11-19T09:00:00+00:00", 500.0),
    )
    assert st.usage_interval_stats(task)["last"] == 14800.0
