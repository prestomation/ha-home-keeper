"""The arm and dormant gates of a task, 1 row for each recurrence type and phase."""

from __future__ import annotations

import hk_lifecycle as lc
import pytest
from hk_const import RECURRENCE_TYPES

_BASE = {"complete", "skip"}
_DEFER = {"snooze", "due_today"}

# The table written out by hand, so that a change to a gate is a change here too.
_EXPECTED = {
    ("floating", "armed"): _BASE | _DEFER,
    ("floating", "dormant"): _BASE,
    ("fixed", "armed"): _BASE | _DEFER | {"move_occurrence"},
    ("fixed", "dormant"): _BASE | {"move_occurrence"},
    ("one-off", "armed"): _BASE | _DEFER,
    ("one-off", "dormant"): _BASE,
    ("triggered", "armed"): _BASE | _DEFER | {"trigger"},
    ("triggered", "dormant"): _BASE | {"trigger"},
    ("sensor", "armed"): _BASE | _DEFER | {"trigger"},
    ("sensor", "dormant"): _BASE | {"trigger"},
    ("use", "armed"): _BASE | _DEFER,
    ("use", "dormant"): _BASE,
}


def test_the_table_has_1_row_for_each_type_and_phase():
    assert set(RECURRENCE_TYPES) == {rec_type for rec_type, _ in _EXPECTED}
    assert {key: set(value) for key, value in lc.ALLOWED.items()} == _EXPECTED


def test_phase_follows_next_due():
    assert lc.phase({"next_due": "2026-03-01T09:00:00+00:00"}) == "armed"
    assert lc.phase({"next_due": None}) == "dormant"
    assert lc.phase({}) == "dormant"


@pytest.mark.parametrize(("rec_type", "phase"), sorted(_EXPECTED))
def test_allows_reads_the_row_of_the_task(rec_type, phase):
    task = {
        "recurrence_type": rec_type,
        "next_due": "2026-03-01T09:00:00+00:00" if phase == "armed" else None,
    }
    for action in _BASE | _DEFER | {"trigger", "move_occurrence"}:
        assert lc.allows(task, action) is (action in _EXPECTED[(rec_type, phase)])


def test_a_task_with_no_type_is_floating():
    assert lc.allows({"next_due": "2026-03-01T09:00:00+00:00"}, "snooze") is True
    assert lc.allows({"next_due": "2026-03-01T09:00:00+00:00"}, "trigger") is False


def test_an_unknown_type_accepts_no_action():
    assert (
        lc.allows({"recurrence_type": "weekly", "next_due": None}, "complete") is False
    )
