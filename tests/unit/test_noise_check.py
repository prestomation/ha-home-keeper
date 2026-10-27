"""The budget check of the noise tier (tests/noise/conftest.py).

The tier itself needs a Docker Home Assistant. Its check is pure, so the unit lane
tests it: a test that cannot fail would let any noise through.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

_PATH = Path(__file__).resolve().parents[1] / "noise" / "conftest.py"
_SPEC = importlib.util.spec_from_file_location("hk_noise_conftest", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
noise = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(noise)

ZERO = dict.fromkeys(noise.COUNTERS, 0)


def _baseline(entry: dict[str, Any]) -> Any:
    data = object.__new__(noise.Baseline)
    data.data = {"scenarios": {"s": entry}}
    data.changed = False
    return data


def _check(entry: dict[str, Any], **counts: int) -> None:
    measured = {
        "counts": {**ZERO, **counts},
        "snapshot": {"detail": {}, "logbook": {}},
    }
    noise.check(_baseline(entry), "s", measured)


KNOWN = {
    "budget": {**ZERO, "logbook_rows": 1},
    "known": {
        "bug": "R9",
        "reason": "a test bug",
        "counters": {
            "logbook_rows": {"target": 1, "now": 63},
            "entry_reloads": {"target": 0, "now": 1},
        },
    },
}


def test_a_count_at_its_budget_passes() -> None:
    _check({"budget": {**ZERO, "events": 2}}, events=2)


def test_a_count_over_its_budget_fails_and_names_the_counter() -> None:
    with pytest.raises(pytest.fail.Exception, match=r"events\s+3\s+2\s+<-- over"):
        _check({"budget": {**ZERO, "events": 2}}, events=3)


def test_a_scenario_with_no_budget_fails() -> None:
    with pytest.raises(AssertionError, match="has no budget"):
        noise.check(_baseline(KNOWN), "other", {"counts": ZERO, "snapshot": {}})


def test_a_known_bug_at_its_now_value_is_an_expected_failure() -> None:
    with pytest.raises(pytest.xfail.Exception, match="R9: a test bug"):
        _check(KNOWN, logbook_rows=63, entry_reloads=1)


def test_a_known_bug_that_got_worse_fails() -> None:
    with pytest.raises(pytest.fail.Exception, match="exceeded"):
        _check(KNOWN, logbook_rows=64, entry_reloads=1)


def test_a_known_bug_fixed_in_part_fails_until_now_is_lowered() -> None:
    # Amazon Q on #503: with a range, 40 rows would read as the known bug, and a
    # later regression from 40 back to 63 would stay hidden.
    with pytest.raises(pytest.fail.Exception, match=r"fixed in part.*logbook_rows=40"):
        _check(KNOWN, logbook_rows=40, entry_reloads=1)


def test_a_fixed_bug_fails_until_its_entry_is_deleted() -> None:
    with pytest.raises(pytest.fail.Exception, match="Delete the 'known' entry"):
        _check(KNOWN, logbook_rows=1, entry_reloads=0)


def test_a_bug_fixed_for_one_counter_names_that_counter() -> None:
    with pytest.raises(pytest.fail.Exception, match="Take entry_reloads out"):
        _check(KNOWN, logbook_rows=63, entry_reloads=0)


def test_a_counter_outside_the_known_entry_is_still_gated() -> None:
    with pytest.raises(pytest.fail.Exception, match=r"storage_writes\s+1\s+0\s+<--"):
        _check(KNOWN, logbook_rows=63, entry_reloads=1, storage_writes=1)
