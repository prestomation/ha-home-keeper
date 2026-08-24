"""Unit tests for ``ci/check-changelog-release-gap.py``.

The script exists to catch exactly the bug PR #236 shipped: a feature folded into a
CHANGELOG section whose version had already been tagged and released, so
``release.yml`` saw nothing new and silently skipped publishing it. ``check()`` is
pure — the git/tag lookups are injected — so the four cases it has to tell apart are
pinned here without touching a real repository.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "ci" / "check-changelog-release-gap.py"


def _load():
    # The filename has a hyphen, so it is not importable as a module name.
    spec = importlib.util.spec_from_file_location(
        "check_changelog_release_gap", _SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_mod = _load()
top_version = _mod.top_version
check = _mod.check


def _section(changelog: str, version: str) -> str:
    """A minimal stand-in for release-issues.section(): the heading's own text."""
    heading = f"## [{version}]"
    out: list[str] = []
    found = False
    for line in changelog.splitlines():
        if not found:
            if line.startswith(heading):
                found = True
                out.append(line)
            continue
        if line.startswith("## ["):
            break
        out.append(line)
    return "\n".join(out) + "\n" if found else ""


class TestTopVersion:
    def test_reads_the_first_heading(self):
        text = "# Changelog\n\n## [0.16.0b8]\n\nstuff\n\n## [0.16.0b7]\n\nolder\n"
        assert top_version(text) == "0.16.0b8"

    def test_ignores_a_version_mentioned_in_prose(self):
        text = "# Changelog\n\nSee 0.15.0 for history.\n\n## [0.16.0]\n\nstuff\n"
        assert top_version(text) == "0.16.0"

    def test_no_heading_at_all(self):
        assert top_version("# Changelog\n\nnothing here\n") is None


class TestCheck:
    def test_version_bumped_is_always_clean(self):
        base = "## [0.16.0b7]\n\nold entry\n"
        head = "## [0.16.0b8]\n\nnew entry\n"
        message = check(base, head, tag_exists=lambda v: True, section=_section)
        assert message is None

    def test_unchanged_section_on_a_released_version_is_clean(self):
        text = "## [0.16.0b7]\n\nsame entry\n"
        message = check(text, text, tag_exists=lambda v: True, section=_section)
        assert message is None

    def test_new_entry_folded_into_an_unreleased_beta_is_clean(self):
        # AGENTS.md's normal workflow: several PRs land into the same unreleased
        # beta section before it's ever tagged.
        base = "## [0.16.0b7]\n\nfirst entry\n"
        head = "## [0.16.0b7]\n\nfirst entry\nsecond entry\n"
        message = check(base, head, tag_exists=lambda v: False, section=_section)
        assert message is None

    def test_new_entry_folded_into_an_already_released_beta_fails(self):
        # This is PR #236's bug: v0.16.0b7 already tagged, entry added anyway.
        base = "## [0.16.0b7]\n\nfirst entry\n"
        head = "## [0.16.0b7]\n\nfirst entry\nsecond entry\n"
        message = check(base, head, tag_exists=lambda v: True, section=_section)
        assert message is not None
        assert "0.16.0b7" in message
        assert "next beta" in message

    def test_checks_the_version_that_was_actually_edited(self):
        calls: list[str] = []

        def tag_exists(version: str) -> bool:
            calls.append(version)
            return True

        base = "## [0.16.0b7]\n\nfirst entry\n"
        head = "## [0.16.0b7]\n\nfirst entry\nsecond entry\n"
        check(base, head, tag_exists=tag_exists, section=_section)
        assert calls == ["0.16.0b7"]

    def test_missing_top_heading_on_either_side_is_clean(self):
        head = "## [0.16.0]\n\nx\n"
        assert check("no heading", head, lambda v: True, _section) is None
        assert check(head, "no heading", lambda v: True, _section) is None

    def test_a_stable_release_is_covered_too(self):
        # The guard isn't beta-specific -- a stable's top section can hit the same bug.
        base = "## [0.16.0]\n\nfirst entry\n"
        head = "## [0.16.0]\n\nfirst entry\nsneaked-in entry\n"
        message = check(base, head, tag_exists=lambda v: True, section=_section)
        assert message is not None
