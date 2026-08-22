#!/usr/bin/env python3
"""Extract a CHANGELOG section and the GitHub issues it says it fixes.

``release.yml`` uses this twice. Once to pull the ``## [X.Y.Z]`` section out of
``CHANGELOG.md`` for the GitHub Release body, and once to work out which issues that
release ships a fix for, so ``notify-issues`` can tell each reporter which version
carries it (and close the issue when that version is stable).

That second use is why the parsing is strict. An issue only closes because its number
appeared here, so a false positive closes something that isn't fixed:

* Only ``Fixes|Closes|Resolves #N`` counts. The CHANGELOG also carries softer refs
  like ``(Related to #161)``, which must *not* close anything.
* A bare ``(#N)`` never counts. This repo overloads it — ``(#189)`` in a commit
  subject is the PR number appended by squash-merge, while ``(#183)`` in the same
  subject is the issue. There is no way to tell them apart, so neither is read.

Usage:
    python3 ci/release-issues.py --version 0.16.0 --notes   # the section, verbatim
    python3 ci/release-issues.py --version 0.16.0 --json    # [{"number":…,"summary":…}]
    git log --format=%B a..b | python3 ci/release-issues.py --scan  # refs, one per line

``--notes`` and ``--json`` exit 1 when the version has no section — a release must
not ship with empty notes, and ``release.yml`` already treated that as fatal.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_DEFAULT_CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"

# Closing keywords only. ``Related to #N`` and bare ``(#N)`` are deliberately absent —
# see the module docstring.
_CLOSING_WORDS = r"fix(?:es|ed)?|close[sd]?|resolve[sd]?"
_CLOSES = re.compile(rf"\b(?:{_CLOSING_WORDS})\s+#(\d+)\b", re.IGNORECASE)

# ``--scan`` reads commit messages, where the new convention is ``Refs #N`` (the PR
# links the issue without closing it). Anything that mentions an issue at all is worth
# cross-checking against the changelog, so this is the looser pattern.
_MENTIONS = re.compile(rf"\b(?:{_CLOSING_WORDS}|refs?)\s+#(\d+)\b", re.IGNORECASE)

_BULLET = re.compile(r"^[-*] ")
_HEADING = re.compile(r"^#")
_BOLD_LEAD = re.compile(r"^\*\*(.+?)\*\*")


def section(changelog: str, version: str) -> str:
    """Return the ``## [version]`` section of *changelog*, heading line included.

    Everything from the heading up to (not including) the next ``## [`` heading, which
    is what the release body has always contained. Returns "" when there is no such
    section.
    """
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
    if not found:
        return ""
    return "\n".join(out) + "\n"


def bullets(text: str) -> list[str]:
    """Split *text* into its top-level Markdown bullets, each flattened to one line.

    A bullet runs from a ``- `` at column zero until the next bullet, heading or blank
    line. The changelog wraps prose across several indented continuation lines, and a
    ``Fixes #N`` often lands on a different line from the sentence that describes it,
    so the whole bullet has to be reassembled before either can be read.
    """
    out: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            out.append(re.sub(r"\s+", " ", " ".join(current)).strip())
            current.clear()

    for line in text.splitlines():
        if _BULLET.match(line):
            flush()
            current.append(_BULLET.sub("", line))
        elif not line.strip() or _HEADING.match(line):
            flush()
        elif current:
            current.append(line.strip())
    flush()
    return out


def summarize(bullet: str) -> str:
    """The bullet's lead sentence, for quoting back at the issue reporter.

    Changelog bullets open with a bolded one-line summary — exactly the sentence a
    reporter wants to see. Fall back to the first sentence when a bullet doesn't
    follow the convention.
    """
    bold = _BOLD_LEAD.match(bullet)
    if bold:
        return bold.group(1).strip()
    first = re.split(r"(?<=\.)\s", bullet, maxsplit=1)[0].strip()
    return first if len(first) <= 200 else first[:197].rstrip() + "…"


def issues(text: str) -> list[dict[str, object]]:
    """Issues *text* claims to fix, in first-mention order, deduped.

    A number can legitimately appear in more than one bullet (a fix split across two
    entries), and the stable section repeats the refs from its betas, so dedupe is not
    optional.
    """
    seen: dict[int, dict[str, object]] = {}
    for bullet in bullets(text):
        summary = summarize(bullet)
        for match in _CLOSES.finditer(bullet):
            number = int(match.group(1))
            seen.setdefault(number, {"number": number, "summary": summary})
    return list(seen.values())


def scan(text: str) -> list[int]:
    """Every issue number *text* mentions, deduped, in first-mention order."""
    seen: list[int] = []
    for match in _MENTIONS.finditer(text):
        number = int(match.group(1))
        if number not in seen:
            seen.append(number)
    return seen


def missing(commits: str, section_body: str) -> list[int]:
    """Issues the shipped commits reference but the release notes never mention.

    The one silent failure of shipping-closes-the-issue: forget the ``Fixes #N`` line
    in the changelog and the issue is never notified and never closed — it just sits
    open forever with no signal that anything went wrong. ``release.yml`` turns this
    into a warning (never a failure: the release is already tagged and published by
    the time it runs, and changelog bookkeeping must not look like a broken release).
    """
    listed = {entry["number"] for entry in issues(section_body)}
    return [number for number in scan(commits) if number not in listed]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="release version, e.g. 0.16.0 or 0.16.0b1")
    parser.add_argument("--changelog", type=Path, default=_DEFAULT_CHANGELOG)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--notes", action="store_true", help="print the section verbatim")
    mode.add_argument("--json", action="store_true", help="print the issues as JSON")
    mode.add_argument(
        "--scan", action="store_true", help="print issue refs read from stdin"
    )
    mode.add_argument(
        "--missing",
        action="store_true",
        help="print, as JSON, the issues stdin references that the section omits",
    )
    args = parser.parse_args(argv)

    if args.scan:
        for number in scan(sys.stdin.read()):
            print(number)
        return 0

    if not args.version:
        parser.error("--version is required for --notes, --json and --missing")

    body = section(args.changelog.read_text(encoding="utf-8"), args.version)
    if not body.strip():
        print(
            f"::error::CHANGELOG.md has no '## [{args.version}]' section "
            "(or it is empty).",
            file=sys.stderr,
        )
        return 1

    if args.notes:
        sys.stdout.write(body)
    elif args.missing:
        json.dump(missing(sys.stdin.read(), body), sys.stdout)
        sys.stdout.write("\n")
    else:
        json.dump(issues(body), sys.stdout)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
