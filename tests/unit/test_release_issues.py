"""Unit tests for ``ci/release-issues.py``.

The script decides which issues a release closes. A false positive closes an issue
that was never fixed, on someone else's thread, irreversibly enough to be rude — so
the exclusions matter as much as the matches, and both are pinned here.

The parity test is the other half: ``release.yml`` used an inline ``awk`` to cut the
release-notes section for every release this project has shipped, and the script has
to reproduce it byte for byte or the switch silently changes release bodies.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import textwrap
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "ci" / "release-issues.py"
_CHANGELOG = _ROOT / "CHANGELOG.md"

# The awk program release.yml carried before this script replaced it.
_AWK = r"""
$0 ~ "^## \\[" ver "\\]" { found=1; print; next }
found && /^## \[/ { exit }
found { print }
"""


def _load():
    # The filename has a hyphen, so it is not importable as a module name.
    spec = importlib.util.spec_from_file_location("release_issues", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_mod = _load()
section = _mod.section
issues = _mod.issues
bullets = _mod.bullets
summarize = _mod.summarize
scan = _mod.scan


def _numbers(text: str) -> list[int]:
    return [entry["number"] for entry in issues(text)]


CHANGELOG = textwrap.dedent(
    """\
    # Changelog

    Preamble prose that mentions Fixes #999 and must never be read.

    ## [0.16.0b1] - 2026-08-21

    ### Fixed

    - **A wrapped bullet.** The description runs across several lines, and the
      issue reference lands on a line of its own rather than the one carrying
      the summary. (Fixes #214)

    ### Changed

    - **Something softer.** This one only nods at an issue. (Related to #161)

    ## [0.15.0] - 2026-08-20

    ### Added

    - **First fix.** (Fixes #211)
    - **Second fix.** (Closes #212) and also (Resolves #213)

    ## [0.14.0]

    ### Fixed

    - **No refs at all.** Nothing to notify here.
    """
)


class TestSection:
    def test_returns_heading_and_body(self):
        body = section(CHANGELOG, "0.15.0")
        assert body.startswith("## [0.15.0] - 2026-08-20")
        assert "First fix" in body

    def test_stops_at_the_next_version(self):
        body = section(CHANGELOG, "0.15.0")
        assert "0.14.0" not in body
        assert "No refs at all" not in body

    def test_excludes_earlier_sections(self):
        assert "0.16.0b1" not in section(CHANGELOG, "0.15.0")

    def test_dateless_heading_is_found(self):
        # Most beta sections in the real changelog carry no date.
        assert section(CHANGELOG, "0.14.0").startswith("## [0.14.0]")

    def test_unknown_version_is_empty(self):
        assert section(CHANGELOG, "9.9.9") == ""

    def test_prefix_of_a_real_version_does_not_match(self):
        # "0.15" must not match "## [0.15.0]" — a truncated version would ship the
        # wrong notes and notify the wrong issues.
        assert section(CHANGELOG, "0.15") == ""

    def test_ends_with_a_newline(self):
        assert section(CHANGELOG, "0.15.0").endswith("\n")


class TestIssues:
    def test_reference_on_a_continuation_line_is_found(self):
        assert _numbers(section(CHANGELOG, "0.16.0b1")) == [214]

    def test_related_to_is_not_a_closing_reference(self):
        assert 161 not in _numbers(section(CHANGELOG, "0.16.0b1"))

    @pytest.mark.parametrize(
        "keyword",
        ["Fixes", "fixes", "Fixed", "fix", "Closes", "closed", "Resolves", "resolve"],
    )
    def test_closing_keywords_and_case(self, keyword):
        assert _numbers(f"- **X.** ({keyword} #7)") == [7]

    def test_bare_reference_is_ignored(self):
        # "(#189)" is the squash-merge PR number in this repo's commit subjects and
        # is indistinguishable from an issue ref. Reading it would close random PRs.
        assert _numbers("- **X.** Something happened (#189)") == []

    def test_multiple_references_in_one_section(self):
        assert _numbers(section(CHANGELOG, "0.15.0")) == [211, 212, 213]

    def test_order_is_first_mention(self):
        assert _numbers("- **B.** (Fixes #9)\n- **A.** (Fixes #2)") == [9, 2]

    def test_deduped_across_bullets(self):
        # The stable section repeats its betas' refs, so duplicates are routine.
        assert _numbers("- **A.** (Fixes #5)\n- **B.** (Fixes #5)") == [5]

    def test_first_mention_wins_the_summary(self):
        found = issues("- **First.** (Fixes #5)\n- **Second.** (Fixes #5)")
        assert found == [{"number": 5, "summary": "First."}]

    def test_summary_travels_with_its_own_bullet(self):
        found = issues(section(CHANGELOG, "0.15.0"))
        assert found[0]["summary"] == "First fix."
        assert found[1]["summary"] == "Second fix."

    def test_section_without_references(self):
        assert _numbers(section(CHANGELOG, "0.14.0")) == []


class TestBullets:
    def test_continuation_lines_are_joined_and_unwrapped(self):
        assert bullets("- one\n  two\n  three") == ["one two three"]

    def test_bullets_are_separate(self):
        assert bullets("- one\n- two") == ["one", "two"]

    def test_headings_end_a_bullet(self):
        assert bullets("- one\n### Fixed\n- two") == ["one", "two"]

    def test_asterisk_bullets(self):
        assert bullets("* one") == ["one"]

    def test_prose_outside_a_bullet_is_dropped(self):
        assert bullets("Loose prose.\n\n- one") == ["one"]


class TestSummarize:
    def test_bold_lead_wins(self):
        assert summarize("**The headline.** Then detail. And more.") == "The headline."

    def test_falls_back_to_the_first_sentence(self):
        assert summarize("No bold here. Second sentence.") == "No bold here."

    def test_long_unpunctuated_text_is_truncated(self):
        assert summarize("word " * 100).endswith("…")
        assert len(summarize("word " * 100)) <= 200


class TestScan:
    def test_reads_refs_and_closing_keywords(self):
        assert scan("Refs #300\nFixes #216\nCloses #7") == [300, 216, 7]

    def test_ignores_bare_pr_suffixes(self):
        assert scan("feat: a thing (#222)") == []

    def test_deduped_in_first_mention_order(self):
        assert scan("Refs #4 Fixes #4 Refs #1") == [4, 1]


class TestMissing:
    """The cross-check that catches a forgotten changelog reference."""

    def test_referenced_but_not_listed_is_reported(self):
        commits = "feat: a thing (#219)\n\nRefs #214\nRefs #999\n"
        assert _mod.missing(commits, section(CHANGELOG, "0.16.0b1")) == [999]

    def test_listed_issues_are_not_reported(self):
        assert _mod.missing("Refs #214", section(CHANGELOG, "0.16.0b1")) == []

    def test_pr_suffix_is_not_reported(self):
        # Every squash-merged commit ends in "(#N)". Flagging those would make the
        # warning noise and get it ignored.
        commits = "feat(profiles): exclude tasks (#219)"
        assert _mod.missing(commits, section(CHANGELOG, "0.16.0b1")) == []

    def test_a_commit_closing_keyword_still_counts_as_a_reference(self):
        assert _mod.missing("Fixes #99", section(CHANGELOG, "0.16.0b1")) == [99]

    def test_empty_commit_range(self):
        assert _mod.missing("", section(CHANGELOG, "0.16.0b1")) == []


class TestCli:
    def _run(self, *args, stdin=""):
        return subprocess.run(
            ["python3", str(_SCRIPT), *args],
            capture_output=True,
            text=True,
            input=stdin,
            cwd=_ROOT,
        )

    def test_notes_prints_the_section(self):
        result = self._run("--version", "0.15.0", "--notes")
        assert result.returncode == 0
        assert result.stdout.startswith("## [0.15.0]")

    def test_json_is_parseable(self):
        result = self._run("--version", "0.15.0", "--json")
        assert result.returncode == 0
        assert json.loads(result.stdout) == [
            {"number": 211, "summary": "Complete a task by scanning an NFC/RFID tag."}
        ]

    def test_missing_section_fails(self):
        result = self._run("--version", "9.9.9", "--notes")
        assert result.returncode == 1
        assert "9.9.9" in result.stderr

    def test_scan_reads_stdin(self):
        result = self._run("--scan", stdin="Refs #12\nFixes #34\n")
        assert result.returncode == 0
        assert result.stdout.split() == ["12", "34"]

    def test_missing_is_json(self):
        result = self._run(
            "--version", "0.15.0", "--missing", stdin="Refs #211\nRefs #998\n"
        )
        assert result.returncode == 0
        assert json.loads(result.stdout) == [998]

    def test_a_mode_is_required(self):
        assert self._run("--version", "0.15.0").returncode != 0


@pytest.mark.parametrize(
    "version",
    [
        "0.16.0b2",
        "0.16.0b1",
        "0.15.0",
        "0.14.0",
        "0.13.0",
        "0.12.0",
        "0.8.0",
        "0.8.0b5",
    ],
)
def test_notes_are_byte_identical_to_the_awk_it_replaced(version):
    """Every shipped release's notes must come out unchanged."""
    expected = subprocess.run(
        ["awk", "-v", f"ver={version}", _AWK, str(_CHANGELOG)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert expected, f"the awk baseline found no section for {version}"
    assert section(_CHANGELOG.read_text(encoding="utf-8"), version) == expected


def test_real_changelog_never_yields_a_pull_request_number():
    """A sweep of the whole file: no PR number may leak in as an issue."""
    text = _CHANGELOG.read_text(encoding="utf-8")
    found = set()
    for line in text.splitlines():
        if line.startswith("## ["):
            found.update(_numbers(section(text, line[4:].split("]")[0])))
    # These are PR numbers appearing as "(#N)" in the same prose, plus the one
    # "Related to" reference. None may be read as something to close.
    assert found.isdisjoint({161, 189, 219, 222})
    assert {214, 216, 211} <= found
