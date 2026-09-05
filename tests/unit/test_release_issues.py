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
import re
import subprocess
import textwrap
from pathlib import Path
from typing import ClassVar

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
version_key = _mod.version_key
previous_tags = _mod.previous_tags


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


class TestFencedCode:
    """A `Fixes #N` in a code sample is not a claim that this release fixed it."""

    def test_reference_inside_a_fence_is_ignored(self):
        text = "- **A.** Example:\n\n```\ngit commit -m 'Fixes #4'\n```\n"
        assert _numbers(text) == []

    def test_indented_fence_inside_a_bullet_is_ignored(self):
        text = (
            "- **A.** Example:\n  ```bash\n  # Fixes #4\n  ```\n  Real text. (Fixes #5)"
        )
        assert _numbers(text) == [5]

    def test_text_after_a_closed_fence_is_read_again(self):
        text = "- **A.**\n```\nnoise\n```\n- **B.** (Fixes #6)"
        assert _numbers(text) == [6]

    def test_tilde_fences_are_dropped_too(self):
        # CommonMark accepts ~~~ as well as ```. A ~~~ block used to sail straight
        # through and close whatever issue the code sample happened to mention.
        assert _numbers("- **A.**\n~~~\nFixes #4\n~~~\n") == []

    def test_a_longer_fence_run_is_still_a_fence(self):
        assert _numbers("- **A.**\n````\nFixes #4\n````\n") == []

    def test_an_unclosed_fence_swallows_the_rest(self):
        # Erring toward dropping beats erring toward closing someone's issue.
        assert _numbers("- **A.** (Fixes #1)\n```\nFixes #2\n- **B.** (Fixes #3)") == [
            1
        ]


class TestThematicBreaks:
    """`* * *` and `- - -` are horizontal rules, not bullets."""

    @pytest.mark.parametrize("rule", ["---", "--- ", "***", "* * *", "- - -", "___"])
    def test_rules_are_not_bullets(self, rule):
        assert bullets(rule) == []

    def test_a_rule_does_not_swallow_the_prose_below_it(self):
        # `* * *` used to parse as a bullet with the text "* *", absorb the line
        # under it, and quote that back at the reporter as the summary.
        assert bullets("* * *\ncontinuation (Fixes #7)") == []

    def test_a_rule_separates_two_bullets(self):
        assert _numbers("- **A.** (Fixes #1)\n\n---\n\n- **B.** (Fixes #2)") == [1, 2]

    def test_a_real_bullet_starting_with_a_dash_still_parses(self):
        assert bullets("- - is a dash") == ["- is a dash"]


class TestOrderedLists:
    """A `Fixes #N` in a numbered item must not be silently dropped."""

    def test_numbered_items_are_bullets(self):
        assert bullets("1. one\n2. two") == ["one", "two"]

    def test_a_reference_in_a_numbered_item_is_found(self):
        assert issues("1. **First.** (Fixes #5)") == [
            {"number": 5, "summary": "First."}
        ]

    def test_multi_digit_numbering(self):
        assert bullets("10. ten") == ["ten"]

    def test_a_version_number_is_not_a_bullet(self):
        assert bullets("0.16.0b1 shipped this") == []

    def test_a_decimal_in_prose_is_not_a_bullet(self):
        # "2.5 seconds" must not start a list: the marker needs whitespace after it.
        assert bullets("  it took 2.5 seconds") == []

    def test_a_numeric_continuation_line_splits_but_keeps_the_reference(self):
        # Known boundary, pinned deliberately. A wrapped line that begins with a
        # number and a period ("30. Then …") is indistinguishable from an ordered
        # list item, so it starts a new bullet and the quoted summary shifts to it.
        # The reference is still found, so the issue still closes correctly — the
        # cost is a less apt sentence in the comment, not a missed fix. Tracking
        # indentation to tell the two apart would add more risk than the case is
        # worth: the changelog has no ordered lists and no numeric continuations.
        found = issues("- **Parent.** It takes\n  30. Then the rest. (Fixes #9)")
        assert [entry["number"] for entry in found] == [9]
        assert found[0]["summary"] == "Then the rest."


class TestNestedBullets:
    """A nested bullet is its own entry, so its ref gets its own summary."""

    def test_nested_bullet_is_separate(self):
        assert bullets("- parent\n  - child") == ["parent", "child"]

    def test_nested_reference_gets_its_own_summary(self):
        text = "- **Parent headline.** Prose.\n  - **Child headline.** (Fixes #8)"
        assert issues(text) == [{"number": 8, "summary": "Child headline."}]

    def test_parent_reference_is_unaffected_by_a_nested_bullet(self):
        text = "- **Parent headline.** (Fixes #9)\n  - **Child headline.** Detail."
        assert issues(text) == [{"number": 9, "summary": "Parent headline."}]

    def test_continuation_lines_still_join(self):
        # An indented line that is *not* a bullet remains part of the bullet above it.
        assert bullets("- parent\n  wrapped prose\n  - child") == [
            "parent wrapped prose",
            "child",
        ]

    def test_real_changelog_nested_bullets_do_not_change_the_issue_list(self):
        # The 0.14.0 section is the one with nested bullets; splitting them must not
        # drop or move the reference the release actually closes.
        text = _CHANGELOG.read_text(encoding="utf-8")
        assert _numbers(section(text, "0.14.0")) == [204]


class TestVersionKey:
    """PEP 440 ordering, which `git tag --sort=-v:refname` does not provide."""

    def test_a_final_release_outranks_its_own_prereleases(self):
        # This is the bug: git sorts v0.16.0 *below* v0.16.0rc1.
        assert version_key("v0.16.0") > version_key("v0.16.0rc1")
        assert version_key("v0.16.0rc1") > version_key("v0.16.0b2")
        assert version_key("v0.16.0b2") > version_key("v0.16.0a1")

    def test_beta_serials_order_numerically(self):
        assert version_key("v0.16.0b10") > version_key("v0.16.0b2")

    def test_across_versions(self):
        assert version_key("v0.16.0b1") > version_key("v0.15.0")

    @pytest.mark.parametrize("tag", ["v0.16", "0.16.0", "v0.16.0.dev1", "vX.Y.Z", ""])
    def test_non_release_tags_are_rejected(self, tag):
        assert version_key(tag) is None


class TestPreviousTags:
    ALL: ClassVar[list[str]] = [
        "v0.17.0b1",
        "v0.16.0",
        "v0.16.0rc1",
        "v0.16.0b10",
        "v0.16.0b2",
        "v0.16.0b1",
        "v0.15.0",
        "v0.15.0b1",
        "not-a-tag",
    ]

    def test_a_stable_only_considers_stables(self):
        # A stable's section rolls up its betas, so it is measured from the last stable.
        assert previous_tags(self.ALL, "0.16.0") == ["v0.15.0"]

    def test_a_beta_considers_any_kind(self):
        # The regression this fixes: git ranked v0.16.0rc1 above v0.16.0, so a beta
        # measured from the rc and flagged everything v0.16.0 shipped as missing.
        assert previous_tags(self.ALL, "0.17.0b1")[0] == "v0.16.0"

    def test_ordering_is_newest_first(self):
        assert previous_tags(self.ALL, "0.17.0b1") == [
            "v0.16.0",
            "v0.16.0rc1",
            "v0.16.0b10",
            "v0.16.0b2",
            "v0.16.0b1",
            "v0.15.0",
            "v0.15.0b1",
        ]

    def test_the_version_itself_is_excluded(self):
        assert "v0.16.0" not in previous_tags(self.ALL, "0.16.0")

    def test_newer_tags_are_excluded(self):
        assert "v0.17.0b1" not in previous_tags(self.ALL, "0.16.0")

    def test_a_beta_excludes_its_own_line_above_it(self):
        assert previous_tags(self.ALL, "0.16.0b2")[0] == "v0.16.0b1"

    def test_unparseable_tags_are_dropped(self):
        assert "not-a-tag" not in previous_tags(self.ALL, "0.17.0b1")

    def test_no_candidates(self):
        assert previous_tags(["v0.1.0"], "0.1.0") == []

    def test_a_malformed_version_yields_nothing(self):
        assert previous_tags(self.ALL, "garbage") == []


class TestOutputSafety:
    """The JSON reaches $GITHUB_OUTPUT as `issues=<json>`, so it must stay one line."""

    def test_json_is_single_line_even_with_hostile_prose(self):
        text = "- **A line\nbreak and a `backtick`.** (Fixes #5)"
        assert "\n" not in json.dumps(issues(text))

    def test_a_forged_output_line_in_prose_cannot_escape_the_json(self):
        # A changelog line that looks like a workflow output must stay inert data.
        text = "- Evil stuff\n  prerelease=false\n  more (Fixes #5)"
        encoded = json.dumps(issues(text))
        assert "\n" not in encoded
        summary = json.loads(encoded)[0]["summary"]
        assert summary == "Evil stuff prerelease=false more (Fixes #5)"


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


def _released_versions() -> list[str]:
    """Every version with a section in the real CHANGELOG."""
    text = _CHANGELOG.read_text(encoding="utf-8")
    return re.findall(r"^## \[([^\]]+)\]", text, re.MULTILINE)


@pytest.mark.parametrize("version", _released_versions())
def test_notes_are_byte_identical_to_the_awk_it_replaced(version):
    """Every shipped release's notes must come out unchanged.

    Parametrized over the whole file rather than a sample: a hand-picked list can't
    fail for a section nobody thought to add to it, and this test is the only thing
    standing between a parser change and silently rewritten release bodies.
    """
    expected = subprocess.run(
        ["awk", "-v", f"ver={version}", _AWK, str(_CHANGELOG)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert expected, f"the awk baseline found no section for {version}"
    assert section(_CHANGELOG.read_text(encoding="utf-8"), version) == expected


# The complete set of issues the real CHANGELOG claims to close. Pinned rather than
# recomputed: this is the list that decides whose issue gets closed, so a parser change
# that quietly adds or drops one has to show up as a failing test, not a silent diff.
_KNOWN_ISSUES = frozenset(
    {
        104,
        105,
        118,
        119,
        143,
        144,
        145,
        150,
        159,
        160,
        163,
        164,
        173,
        182,
        183,
        204,
        211,
        214,
        215,
        216,
        220,
        221,
        228,
        230,
        231,
        235,
        239,
        242,
        247,
        248,
        250,
        253,
        255,
        262,
        279,
    }
)


def test_real_changelog_yields_exactly_the_known_issue_set():
    text = _CHANGELOG.read_text(encoding="utf-8")
    found = set()
    for version in _released_versions():
        found.update(_numbers(section(text, version)))
    assert found == _KNOWN_ISSUES


def test_real_changelog_never_yields_a_pull_request_number():
    """No PR number, and no soft reference, may be read as something to close."""
    # 189/219/222 appear as "(#N)" in the same prose; 161 is "(Related to #161)".
    assert _KNOWN_ISSUES.isdisjoint({161, 189, 219, 222})
