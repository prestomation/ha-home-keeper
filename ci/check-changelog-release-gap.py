#!/usr/bin/env python3
"""Fail a PR that edits an already-released CHANGELOG section without a version bump.

``release.yml`` cuts a release by reading ``manifest.json``'s version and tagging it
— but only if that tag doesn't already exist; if it does, the job skips silently (see
RELEASE.md). A PR that adds a new entry under the *current* top ``## [X.Y.Z]``
CHANGELOG section without bumping ``manifest.json``/``const.py`` therefore merges
clean, and then goes nowhere: the entry documents a change that will never actually
ship, because nothing about the merge told ``release.yml`` there was anything new to
publish.

This happened for real: PR #236 folded a feature into the just-released
``## [0.16.0b7]`` section instead of opening a new beta. ``release.yml`` read the
unchanged version, saw ``v0.16.0b7`` already tagged, and skipped — the feature sat on
``main`` unreleased until PR #237 caught it and cut ``0.16.0b8``. See AGENTS.md,
"Always cut a beta release for a new feature."

The check compares ``CHANGELOG.md``'s *top* section between the PR's merge-base and
``HEAD``:

* Version unchanged, section content unchanged  -> fine, nothing new to ship.
* Version bumped                                -> fine, ``release.yml`` will see a
  new tag to cut.
* Version unchanged, section content changed, and that version is not yet a
  published tag -> fine, the beta is still being iterated (AGENTS.md: "fold the
  feature into it").
* Version unchanged, section content changed, and that version *is* already a
  published tag -> fail. The new content will never ship as written.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_TOP_VERSION = re.compile(r"^## \[([^\]]+)\]", re.MULTILINE)


def _load_release_issues():
    # The filename has a hyphen, so it is not importable as a module name.
    spec = importlib.util.spec_from_file_location(
        "release_issues", ROOT / "ci" / "release-issues.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def top_version(changelog: str) -> str | None:
    """The version in *changelog*'s first ``## [X.Y.Z]`` heading, or None."""
    match = _TOP_VERSION.search(changelog)
    return match.group(1) if match else None


def check(
    base_changelog: str,
    head_changelog: str,
    tag_exists: Callable[[str], bool],
    section: Callable[[str, str], str],
) -> str | None:
    """Return a failure message, or None if the PR's changelog top section is clean."""
    base_version = top_version(base_changelog)
    head_version = top_version(head_changelog)
    if base_version is None or head_version is None or base_version != head_version:
        return None

    if section(base_changelog, base_version) == section(head_changelog, head_version):
        return None

    if not tag_exists(base_version):
        return None

    return (
        f"CHANGELOG.md's '## [{base_version}]' section changed, but v{base_version} "
        "is already a published release. release.yml keys off an unchanged "
        "manifest.json/const.py version and will skip re-publishing it, so this "
        "entry will never ship. Bump manifest.json + const.py (PANEL_VERSION) to the "
        "next beta and open a new '## [X.Y.ZbN]' CHANGELOG section for it -- see "
        "AGENTS.md, 'Always cut a beta release for a new feature.'"
    )


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        sys.exit(
            f"[changelog-release-gap] git {' '.join(args)} failed: "
            f"{result.stderr.strip()}"
        )
    return result.stdout


def _file_at(ref: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def _tag_exists(version: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/v{version}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default="origin/main",
        help="branch to diff against (default: origin/main)",
    )
    args = parser.parse_args()

    merge_base = _git("merge-base", args.base, "HEAD").strip()
    if not merge_base:
        sys.exit(
            f"[changelog-release-gap] could not find a merge base with {args.base}"
        )

    base_changelog = _file_at(merge_base, "CHANGELOG.md")
    head_changelog = _file_at("HEAD", "CHANGELOG.md")
    if base_changelog is None or head_changelog is None:
        # No CHANGELOG.md on one side -- nothing for this guard to compare.
        return 0

    message = check(
        base_changelog, head_changelog, _tag_exists, _load_release_issues().section
    )
    if message is None:
        return 0

    print(f"::error::{message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
