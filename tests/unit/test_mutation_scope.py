"""Unit tests for ``ci/mutation_scope.py``'s mutmut filters (X06-7).

A filter of ``<module>.x_<name>*`` also matched every function whose name starts
with ``<name>``, so a change in ``recurrence._parse`` scored the mutants of the
untouched ``_parse_mmdd`` as well. The filter must end in mutmut's own
``__mutmut_*`` suffix.
"""

from __future__ import annotations

import ast
import importlib.util
from fnmatch import fnmatch
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "ci" / "mutation_scope.py"
_RECURRENCE = "custom_components/home_keeper/recurrence.py"
_MOD = "custom_components.home_keeper.recurrence"


def _load():
    spec = importlib.util.spec_from_file_location("mutation_scope", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scope = _load()


def _line_of(path: str, name: str) -> int:
    tree = ast.parse((_ROOT / path).read_text("utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and (
            node.name == name
        ):
            return node.body[-1].lineno
    raise AssertionError(f"{name} not in {path}")


def test_x06_7_a_change_in_parse_does_not_match_parse_mmdd() -> None:
    line = _line_of(_RECURRENCE, "_parse")
    filters = scope.python_filters({_RECURRENCE: [(line, line)]})
    assert filters == [f"{_MOD}.x__parse__mutmut_*"]
    assert fnmatch(f"{_MOD}.x__parse__mutmut_1", filters[0])
    assert fnmatch(f"{_MOD}.x__parse__mutmut_12", filters[0])
    assert not fnmatch(f"{_MOD}.x__parse_mmdd__mutmut_1", filters[0])


def test_x06_7_a_method_filter_ends_in_the_mutmut_suffix(tmp_path, monkeypatch) -> None:
    source = (
        "class Store:\n"
        "    def save(self):\n"
        "        return 1\n"
        "\n"
        "    def save_all(self):\n"
        "        return 2\n"
    )
    pkg = tmp_path / "custom_components" / "home_keeper"
    pkg.mkdir(parents=True)
    (pkg / "fake.py").write_text(source)
    monkeypatch.setattr(scope, "ROOT", tmp_path)
    filters = scope.python_filters({"custom_components/home_keeper/fake.py": [(3, 3)]})
    sep = scope.CLASS_NAME_SEPARATOR
    expected = f"custom_components.home_keeper.fake.x{sep}Store{sep}save__mutmut_*"
    assert filters == [expected]
    assert fnmatch(
        f"custom_components.home_keeper.fake.x{sep}Store{sep}save__mutmut_3", expected
    )
    assert not fnmatch(
        f"custom_components.home_keeper.fake.x{sep}Store{sep}save_all__mutmut_3",
        expected,
    )
