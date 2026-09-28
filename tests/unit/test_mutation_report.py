"""The TypeScript mutation gate fails when Stryker ran no test at all.

#384 moved the root vitest to a major the Stryker vitest runner could not drive.
Stryker then scored every mutant as "survived" without running a test against
it. ``ci/mutation_report.py`` reads ``testsCompleted`` from the report and fails
on that cause, whatever score it produced.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "ci" / "mutation_report.py"


def _load():
    spec = importlib.util.spec_from_file_location("mutation_report", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_mod = _load()


def _report(tmp_path: Path, mutants: list[dict]) -> Path:
    path = tmp_path / "mutation.json"
    path.write_text(json.dumps({"files": {"src/limits.ts": {"mutants": mutants}}}))
    return path


def _mutant(status: str, tests: int | None) -> dict:
    mutant = {"status": status, "mutatorName": "BooleanLiteral"}
    if tests is not None:
        mutant["testsCompleted"] = tests
    return mutant


def test_tests_run_sums_every_mutant(tmp_path: Path) -> None:
    path = _report(tmp_path, [_mutant("Killed", 3), _mutant("Survived", 4)])
    assert _mod.stryker_tests_run(path) == 7


def test_tests_run_is_zero_when_no_test_ran(tmp_path: Path) -> None:
    path = _report(tmp_path, [_mutant("Survived", 0), _mutant("Survived", 0)])
    assert _mod.stryker_tests_run(path) == 0


def test_tests_run_is_unknown_without_the_field(tmp_path: Path) -> None:
    path = _report(tmp_path, [_mutant("Killed", None)])
    assert _mod.stryker_tests_run(path) is None


def test_tests_run_leaves_out_uncovered_mutants(tmp_path: Path) -> None:
    # No test covers a NoCoverage mutant, so its 0 says nothing about the runner.
    path = _report(tmp_path, [_mutant("NoCoverage", 0), _mutant("Killed", 2)])
    assert _mod.stryker_tests_run(path) == 2
    only = _report(tmp_path, [_mutant("NoCoverage", 0)])
    assert _mod.stryker_tests_run(only) is None


def test_tests_run_is_unknown_for_an_unreadable_report(tmp_path: Path) -> None:
    path = tmp_path / "mutation.json"
    path.write_text("{not json")
    assert _mod.stryker_tests_run(path) is None


def _main(monkeypatch: pytest.MonkeyPatch, path: Path) -> int:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mutation_report.py",
            "--format",
            "stryker",
            "--input",
            str(path),
            "--require-mutants",
        ],
    )
    return _mod.main()


def test_gate_fails_when_scored_mutants_ran_no_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    path = _report(tmp_path, [_mutant("Survived", 0), _mutant("Survived", 0)])
    assert _main(monkeypatch, path) == 1
    assert "ran no test" in capsys.readouterr().err


def test_gate_passes_when_tests_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _report(tmp_path, [_mutant("Killed", 5), _mutant("Killed", 2)])
    assert _main(monkeypatch, path) == 0


def test_gate_ignores_a_report_without_the_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An older Stryker that does not write testsCompleted must not fail the gate.
    path = _report(tmp_path, [_mutant("Killed", None)])
    assert _main(monkeypatch, path) == 0
