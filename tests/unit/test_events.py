"""Unit tests for the shared completion-event payload builder.

This is the single source of the ``home_keeper_task_completed`` payload, used by
both the real store and the test fake, so the contract can't drift.
"""

from datetime import datetime, timedelta, timezone

import hk_events as ev

TZ = timezone(timedelta(hours=-4))
WHEN = datetime(2026, 6, 14, 10, tzinfo=TZ)


def test_payload_has_contract_fields():
    task = {
        "id": "t1",
        "name": "Medicine",
        "source": {"pawsistant": {"schedule_id": "s1"}},
    }
    data = ev.completion_event_data(task, WHEN, origin="pawsistant")
    assert data == {
        "task_id": "t1",
        "name": "Medicine",
        "source": {"pawsistant": {"schedule_id": "s1"}},
        "completed_at": WHEN.isoformat(),
        "origin": "pawsistant",
    }


def test_source_defaults_to_none_and_origin_passthrough():
    data = ev.completion_event_data({"id": "t2", "name": "X"}, WHEN, origin=None)
    assert data["source"] is None
    assert data["origin"] is None


def test_accepts_iso_string_when():
    iso = WHEN.isoformat()
    data = ev.completion_event_data({"id": "t3", "name": "X"}, iso, origin=None)
    assert data["completed_at"] == iso
