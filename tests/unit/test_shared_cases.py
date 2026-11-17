"""Run every shared case file in the parity registry through the Python side.

``tests/fixtures/parity.json`` lists each rule that exists in Python and in
TypeScript, and the case file that pins it. This module runs each case against the
Python function; ``frontend/test/shared-cases.test.js`` runs the same file against the
TypeScript function. When the 2 sides disagree, 1 of the 2 tests fails.

``parity_adapters.ADAPTERS`` maps a rule id to a call of the shipped function.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from parity_adapters import ADAPTERS, REGISTRY, ROOT


def _cases() -> list[Any]:
    params = []
    for rule in REGISTRY["rules"]:
        data = json.loads((ROOT / rule["cases"]).read_text())
        for case in data["cases"]:
            params.append(
                pytest.param(rule["id"], case, data, id=f"{rule['id']}: {case['name']}")
            )
    return params


def test_every_registered_rule_has_an_adapter() -> None:
    """A new registry entry fails here until this module can run its cases."""
    assert set(ADAPTERS) == {rule["id"] for rule in REGISTRY["rules"]}


@pytest.mark.parametrize(("rule_id", "case", "data"), _cases())
def test_shared_case(rule_id: str, case: dict[str, Any], data: dict[str, Any]) -> None:
    got = ADAPTERS[rule_id](case, data)
    assert got == case["expected"]
    # `==` holds for True == 1 too; the 2 languages must agree on the type as well.
    assert type(got) is type(case["expected"])
