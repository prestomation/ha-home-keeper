"""Unit tests for ``ci/wait_for_checks.py`` (X06-1).

``dependabot-auto-merge.yml`` waited with ``gh pr checks --watch``, which counted
the job's own check as pending, so the job timed out and no Dependabot pull
request ever merged. The verdict is pure and tested here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "ci" / "wait_for_checks.py"


def _load():
    spec = importlib.util.spec_from_file_location("wait_for_checks", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wfc = _load()
IGNORE = ["Dependabot auto-merge", "Discord Notify"]


def _c(workflow: str, bucket: str, name: str = "job") -> dict:
    return {"workflow": workflow, "name": name, "bucket": bucket}


def test_x06_1_own_pending_check_does_not_block_a_pass() -> None:
    checks = [
        _c("Test", "pass"),
        _c("Lint", "skipping"),
        _c("Dependabot auto-merge", "pending", "dependabot"),
    ]
    assert wfc.verdict(checks, IGNORE) == wfc.PASS


def test_x06_1_a_failed_discord_notify_does_not_fail_the_wait() -> None:
    checks = [_c("Test", "pass"), _c("Discord Notify", "fail", "notify / notify")]
    assert wfc.verdict(checks, IGNORE) == wfc.PASS


def test_x06_1_a_failed_or_cancelled_check_fails() -> None:
    assert wfc.verdict([_c("Test", "fail"), _c("Lint", "pass")], IGNORE) == wfc.FAIL
    assert wfc.verdict([_c("Test", "cancel"), _c("Lint", "pass")], IGNORE) == wfc.FAIL
    # A failure wins over a pending check: there is no need to wait.
    assert wfc.verdict([_c("Test", "fail"), _c("E2E", "pending")], IGNORE) == wfc.FAIL


def test_x06_1_a_pending_check_keeps_the_wait_going() -> None:
    assert (
        wfc.verdict([_c("Test", "pass"), _c("E2E", "pending")], IGNORE) == wfc.PENDING
    )


def test_x06_1_no_check_left_is_pending_not_pass() -> None:
    assert wfc.verdict([], IGNORE) == wfc.PENDING
    only_own = [_c("Dependabot auto-merge", "pending")]
    assert wfc.verdict(only_own, IGNORE) == wfc.PENDING


def test_x06_1_ignore_matches_the_workflow_not_the_job_name() -> None:
    checks = [_c("Test", "fail", "Dependabot auto-merge")]
    assert wfc.verdict(checks, IGNORE) == wfc.FAIL


def test_x06_1_main_merges_only_on_pass(monkeypatch) -> None:
    reads = iter(
        [
            [_c("Test", "pending"), _c("Dependabot auto-merge", "pending")],
            [_c("Test", "pass"), _c("Dependabot auto-merge", "pending")],
        ]
    )
    monkeypatch.setattr(wfc, "_read", lambda pr: next(reads))
    monkeypatch.setattr(wfc.time, "sleep", lambda s: None)
    argv = ["https://x/pull/1", "--ignore-workflow", "Dependabot auto-merge"]
    assert wfc.main(argv) == 0


def test_x06_1_main_fails_on_a_failed_check(monkeypatch) -> None:
    monkeypatch.setattr(wfc, "_read", lambda pr: [_c("Test", "fail")])
    assert wfc.main(["1"]) == 1


def test_x06_1_main_fails_at_the_timeout(monkeypatch) -> None:
    monkeypatch.setattr(wfc, "_read", lambda pr: [_c("Test", "pending")])
    monkeypatch.setattr(wfc.time, "sleep", lambda s: None)
    assert wfc.main(["1", "--timeout", "0"]) == 1
