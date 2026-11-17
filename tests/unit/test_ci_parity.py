"""``ci/parity.py check``: the parity registry and its markers.

Each test copies the real registry, sources and case files into a temporary tree,
breaks 1 thing, and checks that the error names it. The first test runs the check on
the real repository.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "ci" / "parity.py"


def _load():
    spec = importlib.util.spec_from_file_location("parity", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parity = _load()
ROOT = parity.ROOT


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A copy of the parts of the repository that the check reads."""
    for rel in (parity.PY_DIR, "tests/fixtures"):
        src = ROOT / rel
        ignore = shutil.ignore_patterns("node_modules", "dist", "__pycache__", "*.png")
        shutil.copytree(src, tmp_path / rel, ignore=ignore)
    return tmp_path


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _registry(tree: Path) -> dict:
    return json.loads((tree / parity.REGISTRY).read_text())


def _save(tree: Path, data: dict) -> None:
    (tree / parity.REGISTRY).write_text(json.dumps(data))


def test_the_repository_holds() -> None:
    assert parity.check() == []


def test_the_copy_holds(tree: Path) -> None:
    assert parity.check(tree) == []


def test_a_marker_on_one_side_only_fails(tree: Path) -> None:
    _edit(tree / parity.TS_DIR / "parts-overview.ts", "// parity: part_low\n", "")
    assert parity.check(tree) == ["part_low: 0 TypeScript markers, expected 1"]


def test_a_python_marker_that_is_gone_fails(tree: Path) -> None:
    _edit(tree / parity.PY_DIR / "assets.py", "# parity: part_low\n", "")
    assert parity.check(tree) == ["part_low: 0 Python markers, expected 1"]


def test_a_marker_for_an_unregistered_rule_fails(tree: Path) -> None:
    _edit(
        tree / parity.PY_DIR / "assets.py",
        "def part_has_reorder(",
        "# parity: reorder\ndef part_has_reorder(",
    )
    (error,) = parity.check(tree)
    assert error.startswith(f"{parity.PY_DIR}/assets.py:")
    assert error.endswith(
        "marker for 'reorder', which tests/fixtures/parity.json does not list"
    )


def test_a_marker_above_the_wrong_definition_fails(tree: Path) -> None:
    path = tree / parity.PY_DIR / "assets.py"
    _edit(path, "# parity: part_low\n", "")
    _edit(path, "def part_has_reorder(", "# parity: part_low\ndef part_has_reorder(")
    (error,) = parity.check(tree)
    assert error.endswith(
        f"the part_low marker must sit above {parity.PY_DIR}/assets.py::part_is_low"
    )


def test_a_marker_may_sit_above_a_decorator_or_a_doc_comment(tree: Path) -> None:
    # decimal_mark has @functools.cache, and profileMatches has a JSDoc block.
    assert "@functools.cache" in (tree / parity.PY_DIR / "assets.py").read_text()
    assert parity.check(tree) == []


def test_a_second_marker_fails(tree: Path) -> None:
    _edit(
        tree / parity.TS_DIR / "parts-overview.ts",
        "// parity: part_low\n",
        "// parity: part_low\n// parity: part_low\n",
    )
    assert "part_low: 2 TypeScript markers, expected 1" in parity.check(tree)


def test_a_function_that_is_gone_fails(tree: Path) -> None:
    data = _registry(tree)
    data["rules"][0]["python"] = f"{parity.PY_DIR}/profiles.py::no_such_function"
    _save(tree, data)
    assert (
        f"profile_filter: {parity.PY_DIR}/profiles.py does not define no_such_function"
        in (parity.check(tree))
    )


def test_a_file_that_is_gone_fails(tree: Path) -> None:
    data = _registry(tree)
    data["rules"][0]["typescript"] = f"{parity.TS_DIR}/gone.ts::profileMatches"
    _save(tree, data)
    assert f"profile_filter: {parity.TS_DIR}/gone.ts does not exist" in parity.check(
        tree
    )


def test_a_case_file_that_is_gone_fails(tree: Path) -> None:
    (tree / "tests/fixtures/part_low_cases.json").unlink()
    assert parity.check(tree) == [
        "part_low: the case file tests/fixtures/part_low_cases.json does not exist"
    ]


def test_an_empty_case_file_fails(tree: Path) -> None:
    (tree / "tests/fixtures/part_low_cases.json").write_text('{"cases": []}')
    assert parity.check(tree) == [
        "part_low: tests/fixtures/part_low_cases.json has no cases"
    ]


def test_cases_with_the_same_name_fail(tree: Path) -> None:
    case = {"name": "x", "input": {}, "expected": False}
    (tree / "tests/fixtures/part_low_cases.json").write_text(
        json.dumps({"cases": [case, case]})
    )
    assert parity.check(tree) == [
        "part_low: tests/fixtures/part_low_cases.json has 2 cases with the same name"
    ]


def test_a_rule_registered_2_times_fails(tree: Path) -> None:
    data = _registry(tree)
    data["rules"].append(dict(data["rules"][0]))
    _save(tree, data)
    assert "profile_filter: registered 2 times" in parity.check(tree)


def test_a_corpus_rule_with_no_entries_fails(tree: Path) -> None:
    data = _registry(tree)
    data["rules"][1]["corpus"] = True
    _save(tree, data)
    assert parity.check(tree) == [
        "companion_keys: marked corpus, but tests/fixtures/parity_corpus.json "
        "has no entries for it"
    ]


def test_corpus_entries_for_an_unmarked_rule_fail(tree: Path) -> None:
    data = _registry(tree)
    data["rules"][0].pop("corpus")
    _save(tree, data)
    assert parity.check(tree) == [
        "profile_filter: in tests/fixtures/parity_corpus.json, "
        "but not marked corpus in tests/fixtures/parity.json"
    ]


def test_main_exit_codes(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert parity.main(["check"]) == 0
    monkeypatch.setattr(parity, "ROOT", tree)
    monkeypatch.setattr(parity.check, "__defaults__", (tree,))
    _edit(tree / parity.PY_DIR / "assets.py", "# parity: part_low\n", "")
    assert parity.main(["check"]) == 1
