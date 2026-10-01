"""Unit tests for ``ci/mutation_scope.py``'s mutmut filters (X06-7).

A filter of ``<module>.x_<name>*`` also matched every function whose name starts
with ``<name>``, so a change in ``recurrence._parse`` scored the mutants of the
untouched ``_parse_mmdd`` as well. The filter must end in mutmut's own
``__mutmut_*`` suffix.

The tests parse a small module in a temporary root, not the real source: under
mutmut the real source is the rewritten, mutated copy.
"""

from __future__ import annotations

import importlib.util
from fnmatch import fnmatch
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "ci" / "mutation_scope.py"
_PATH = "custom_components/home_keeper/fake.py"
_MOD = "custom_components.home_keeper.fake"

_SOURCE = (
    "def _parse_mmdd(value):\n"  # 1
    "    return value\n"  # 2
    "\n"  # 3
    "\n"  # 4
    "def _parse(value):\n"  # 5
    "    return value\n"  # 6
    "\n"  # 7
    "\n"  # 8
    "class Store:\n"  # 9
    "    def save(self):\n"  # 10
    "        return 1\n"  # 11
    "\n"  # 12
    "    def save_all(self):\n"  # 13
    "        return 2\n"  # 14
)


def _load():
    spec = importlib.util.spec_from_file_location("mutation_scope", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scope = _load()


def _filters(tmp_path, monkeypatch, line: int) -> list[str]:
    pkg = tmp_path / "custom_components" / "home_keeper"
    pkg.mkdir(parents=True)
    (pkg / "fake.py").write_text(_SOURCE)
    monkeypatch.setattr(scope, "ROOT", tmp_path)
    return scope.python_filters({_PATH: [(line, line)]})


def test_x06_7_a_change_in_parse_does_not_match_parse_mmdd(
    tmp_path, monkeypatch
) -> None:
    filters = _filters(tmp_path, monkeypatch, 6)
    assert filters == [f"{_MOD}.x__parse__mutmut_*"]
    assert fnmatch(f"{_MOD}.x__parse__mutmut_1", filters[0])
    assert fnmatch(f"{_MOD}.x__parse__mutmut_12", filters[0])
    assert not fnmatch(f"{_MOD}.x__parse_mmdd__mutmut_1", filters[0])


def test_x06_7_a_method_filter_ends_in_the_mutmut_suffix(tmp_path, monkeypatch) -> None:
    filters = _filters(tmp_path, monkeypatch, 11)
    sep = scope.CLASS_NAME_SEPARATOR
    expected = f"{_MOD}.x{sep}Store{sep}save__mutmut_*"
    assert filters == [expected]
    assert fnmatch(f"{_MOD}.x{sep}Store{sep}save__mutmut_3", expected)
    assert not fnmatch(f"{_MOD}.x{sep}Store{sep}save_all__mutmut_3", expected)
