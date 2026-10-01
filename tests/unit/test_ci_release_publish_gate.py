"""The release workflow publishes only from main, and never on a dry run (X06-2).

A ``notify_dry_run`` dispatch on a branch whose manifest version had no tag ran
the full release job: it tagged the branch head, published a GitHub Release and
deployed the docs. The publish decision is now one step, run here with bash, and
every publishing step and job must read it.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

_WORKFLOW = (
    Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml"
)


def _doc() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _doc()["jobs"]["release"]["steps"]


def _step(step_id: str) -> dict:
    return next(s for s in _steps() if s.get("id") == step_id)


def _publish(tmp_path: Path, event: str, ref: str, dry_run: str) -> str:
    out = tmp_path / "out"
    out.write_text("")
    env = {
        **os.environ,
        "EVENT": event,
        "REF": ref,
        "DRY_RUN": dry_run,
        "GITHUB_OUTPUT": str(out),
    }
    subprocess.run(
        ["bash", "-c", _step("publish")["run"]],
        env=env,
        check=True,
        capture_output=True,
    )
    return out.read_text().strip()


@pytest.mark.parametrize(
    ("event", "ref", "dry_run", "expected"),
    [
        ("push", "refs/heads/main", "", "publish=true"),
        ("workflow_dispatch", "refs/heads/main", "false", "publish=true"),
        ("workflow_dispatch", "refs/heads/main", "true", "publish=false"),
        ("workflow_dispatch", "refs/heads/release-0.27.0", "true", "publish=false"),
        ("workflow_dispatch", "refs/heads/release-0.27.0", "false", "publish=false"),
        ("pull_request", "refs/pull/1/merge", "", "publish=false"),
        ("push", "refs/heads/feature", "", "publish=false"),
    ],
)
def test_x06_2_publish_decision(tmp_path, event, ref, dry_run, expected) -> None:
    assert _publish(tmp_path, event, ref, dry_run) == expected


def test_x06_2_tag_and_release_steps_read_the_decision() -> None:
    by_name = {s.get("name"): s for s in _steps()}
    for name in ("Create and push tag", "Create GitHub Release"):
        cond = by_name[name]["if"]
        assert "steps.publish.outputs.publish == 'true'" in cond, name
        assert "github.event_name != 'pull_request'" not in cond, name


def test_x06_2_jobs_read_the_decision() -> None:
    jobs = _doc()["jobs"]
    assert (
        jobs["release"]["outputs"]["publish"] == "${{ steps.publish.outputs.publish }}"
    )
    assert "needs.release.outputs.publish == 'true'" in jobs["deploy-docs"]["if"]
    assert "needs.release.outputs.publish == 'true'" in jobs["notify-issues"]["if"]
