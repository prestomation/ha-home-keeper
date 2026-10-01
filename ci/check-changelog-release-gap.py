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

A second check reads ``manifest.json`` and ``const.py`` at ``HEAD`` (X06-3). A PR
that opens a new top section but leaves ``manifest.json`` at the released version
passed the first check, and ``release.yml`` stops at "tag already exists" before it
compares the CHANGELOG, so the section never shipped. So:

* ``manifest.json`` and ``PANEL_VERSION`` differ -> fail.
* The top section names a version that is not ``manifest.json``'s and is not a
  published tag -> fail. Nothing will release it.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_TOP_VERSION = re.compile(r"^## \[([^\]]+)\]", re.MULTILINE)
_RELEASE_VERSION = re.compile(r"^\d+\.\d+\.\d+((a|b|rc)\d+)?$")
_PANEL_VERSION = re.compile(r'^PANEL_VERSION\s*=\s*"([^"]+)"', re.MULTILINE)


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
    """Return a failure message, or None if the PR's changelog top section is clean.

    A version bump always short-circuits here: once the top heading itself changes,
    ``base_version`` and ``head_version`` name two different sections, so there is
    nothing to compare them for and ``release.yml`` will see a new tag to cut.
    """
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


def check_versions(
    head_changelog: str,
    manifest_version: str | None,
    panel_version: str | None,
    tag_exists: Callable[[str], bool],
) -> str | None:
    """Return a failure message when the versions at HEAD cannot release the top.

    A top heading that is not a version (``## [Unreleased]``) is not checked.
    """
    if manifest_version != panel_version:
        return (
            f"manifest.json is at {manifest_version} but const.py PANEL_VERSION is "
            f"at {panel_version}. Bump both in the same PR."
        )
    top = top_version(head_changelog)
    if top is None or not _RELEASE_VERSION.match(top) or top == manifest_version:
        return None
    if tag_exists(top):
        return None
    return (
        f"CHANGELOG.md's top section is '## [{top}]', but manifest.json is at "
        f"{manifest_version} and v{top} is not a published release. release.yml "
        "releases manifest.json's version only, so this section will never ship. "
        f"Bump manifest.json + const.py (PANEL_VERSION) to {top}."
    )


def manifest_version(manifest: str | None) -> str | None:
    """The ``version`` in a ``manifest.json`` text, or None."""
    if manifest is None:
        return None
    value = json.loads(manifest).get("version")
    return str(value) if value is not None else None


def panel_version(const: str | None) -> str | None:
    """The ``PANEL_VERSION`` string in a ``const.py`` text, or None."""
    match = _PANEL_VERSION.search(const or "")
    return match.group(1) if match else None


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

    messages = [
        check(
            base_changelog, head_changelog, _tag_exists, _load_release_issues().section
        ),
        check_versions(
            head_changelog,
            manifest_version(
                _file_at("HEAD", "custom_components/home_keeper/manifest.json")
            ),
            panel_version(_file_at("HEAD", "custom_components/home_keeper/const.py")),
            _tag_exists,
        ),
    ]
    failed = [m for m in messages if m is not None]
    for message in failed:
        print(f"::error::{message}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
