"""The quality scale ledger agrees with the manifest and with the setup (B20-4).

``manifest.json`` requires Babel, so the 2 dependency rules must name it. Babel
opens its locale data files on the first lookup, so ``async_setup_entry`` must do
that lookup in the executor before the shopping-list sync calls it on the loop.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
import yaml

_COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "home_keeper"


def _requirements() -> list[str]:
    manifest = json.loads((_COMPONENT / "manifest.json").read_text())
    return [
        re.split(r"[<>=!~\[]", req, maxsplit=1)[0] for req in manifest["requirements"]
    ]


def test_b20_4_the_manifest_has_a_requirement():
    assert _requirements() == ["Babel"]


@pytest.mark.parametrize("rule", ["dependency-transparency", "async-dependency"])
def test_b20_4_the_dependency_rules_name_each_requirement(rule):
    ledger = yaml.safe_load((_COMPONENT / "quality_scale.yaml").read_text())
    comment = ledger["rules"][rule]["comment"]
    for name in _requirements():
        assert name in comment
    assert "No external" not in comment


def test_b20_4_setup_warms_the_decimal_mark_in_the_executor():
    tree = ast.parse((_COMPONENT / "__init__.py").read_text())
    setup = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup_entry"
    )
    calls = [
        ast.unparse(node) for node in ast.walk(setup) if isinstance(node, ast.Await)
    ]
    assert (
        "await hass.async_add_executor_job(assets.decimal_mark, hass.config.language)"
        in calls
    )
