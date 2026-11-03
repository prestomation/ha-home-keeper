#!/usr/bin/env python3
"""Fail when a Home Assistant log shows problems in one custom integration.

Usage:
    python ci/check_ha_log.py --domain home_keeper ha.log
    docker compose logs homeassistant | python ci/check_ha_log.py --domain home_keeper -

Exit codes:
    0  no findings
    1  at least one finding that is not in the allowlist
    2  bad input (no log lines, bad allowlist, unreadable file)

The script uses only the Python standard library. It knows nothing about one
integration except the domain name you give it.

What counts as a finding (a "record" is one log line plus the lines that
follow it, such as a traceback):

1. A WARNING, ERROR or CRITICAL record from the logger
   ``custom_components.<domain>`` (or any child logger).
2. A "Detected blocking call" record that names the domain.
3. A record that names the domain and has one of the known bad patterns:
   "was never awaited", "Task exception was never retrieved", a slow
   callback ("Executing <Task ... took N seconds"), "Unclosed" resources,
   or a deprecation notice.

A record "names the domain" when it contains ``custom_components/<domain>``,
``custom_components.<domain>`` or ``integration '<domain>'``.

Home Assistant's own generic warnings are ignored (see GENERIC_IGNORES).
For anything else, add an entry to the allowlist file. Each entry is a
regular expression on its own line, and the line before it must be a
comment that gives the reason. Entries without a reason are rejected.

An allowlist regex is checked against every record and hides it from all
the rules above. Keep each entry narrow: match the logger name or the full
message, not a short word like "timeout".
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ALLOWLIST = Path(__file__).with_name("ha_log_allowlist.txt")

# Home Assistant may colour its log lines, even when the output is not a
# terminal. Remove the colour codes before matching.
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# Docker compose adds "<service>-<n>  | " in front of every line.
COMPOSE_PREFIX = re.compile(r"^[\w.-]+\s*\|\s?")

# Start of a Home Assistant log record:
#   2026-11-02 10:00:00.123 WARNING (MainThread) [logger.name] message
# The date and time may be split by "T" and may end with a time zone.
RECORD_START = re.compile(
    r"^\s*"
    r"(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?)\s+"
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+"
    r"(?:\((?P<thread>[^)]*)\)\s+)?"
    r"\[(?P<logger>[^\]]+)\]"
)

# Longest message shape that is used to group findings.
SHAPE_WIDTH = 140

BAD_LEVELS = {"WARNING", "ERROR", "CRITICAL"}

# Patterns that are a problem when the record also names the domain.
BAD_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("coroutine was never awaited", re.compile(r"was never awaited")),
    (
        "task exception was never retrieved",
        re.compile(r"Task exception was never retrieved"),
    ),
    ("slow callback", re.compile(r"Executing <(?:Task|Handle)\b")),
    ("unclosed resource", re.compile(r"\bUnclosed\b|ResourceWarning")),
    ("deprecation notice", re.compile(r"deprecat", re.IGNORECASE)),
]

BLOCKING_CALL = re.compile(r"Detected blocking call")

# Warnings that Home Assistant writes for every custom integration.
# They say nothing about the quality of our code.
GENERIC_IGNORES = [
    re.compile(r"custom integration .* has not been tested by Home Assistant"),
    re.compile(r"You are using a custom integration .*"),
]


@dataclass
class Record:
    line_no: int
    level: str | None
    logger: str | None
    text: str  # first line plus continuation lines


@dataclass
class Finding:
    line_no: int
    rule: str
    text: str

    @property
    def message(self) -> str:
        """First line of the record, without date, level and thread."""
        first = self.text.splitlines()[0] if self.text else ""
        match = RECORD_START.match(first)
        return first[match.start("logger") - 1 :].strip() if match else first.strip()

    @property
    def shape(self) -> str:
        """The message with names and numbers removed, to group like findings."""
        text = re.sub(r"'[^']*'", "'*'", self.message)
        text = re.sub(r"\d+", "N", text)
        return text[:SHAPE_WIDTH]


@dataclass
class Group:
    rule: str
    shape: str
    findings: list[Finding]


def clean_line(raw: str) -> str:
    """Remove colour codes and the compose prefix from one log line."""
    line = ANSI.sub("", raw.rstrip("\n"))
    return COMPOSE_PREFIX.sub("", line, count=1)


def parse_records(lines: list[str]) -> list[Record]:
    """Group log lines into records. Lines before the first record are kept."""
    records: list[Record] = []
    for number, raw in enumerate(lines, start=1):
        line = clean_line(raw)
        match = RECORD_START.match(line)
        if match:
            records.append(Record(number, match["level"], match["logger"], line))
        elif records:
            records[-1].text += "\n" + line
        else:
            records.append(Record(number, None, None, line))
    return records


def names_domain(text: str, domain: str) -> bool:
    d = re.escape(domain)
    return bool(
        re.search(rf"custom_components[./]{d}(?![\w])", text)
        or re.search(rf"integration '{d}'", text)
    )


def load_allowlist(path: Path) -> list[tuple[re.Pattern[str], str]]:
    """Read allowlist entries. Raise ValueError on an entry without a reason."""
    entries: list[tuple[re.Pattern[str], str]] = []
    reason: str | None = None
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            reason = None
        elif line.startswith("#"):
            reason = line.lstrip("#").strip() or None
        else:
            if not reason:
                raise ValueError(
                    f"{path}:{number}: allowlist entry has no reason comment "
                    "on the line before it"
                )
            try:
                entries.append((re.compile(line), reason))
            except re.error as err:
                raise ValueError(f"{path}:{number}: bad regex: {err}") from err
    return entries


def check_records(
    records: list[Record],
    domain: str,
    allowlist: list[tuple[re.Pattern[str], str]],
) -> list[Finding]:
    findings: list[Finding] = []
    logger_prefix = f"custom_components.{domain}"
    for record in records:
        text = record.text
        if any(p.search(text) for p in GENERIC_IGNORES):
            continue

        rules: list[str] = []
        logger = record.logger or ""
        if record.level in BAD_LEVELS and (
            logger == logger_prefix or logger.startswith(logger_prefix + ".")
        ):
            rules.append(f"{record.level} from logger {logger}")
        if BLOCKING_CALL.search(text) and names_domain(text, domain):
            rules.append("blocking call in the event loop")
        if names_domain(text, domain):
            for label, pattern in BAD_PATTERNS:
                if pattern.search(text):
                    rules.append(label)
        if not rules:
            continue
        if any(p.search(text) for p, _ in allowlist):
            continue
        findings.append(Finding(record.line_no, "; ".join(rules), text))
    return findings


def group_findings(findings: list[Finding]) -> list[Group]:
    """Group findings by rule and message shape. Biggest group first."""
    groups: dict[tuple[str, str], Group] = {}
    for finding in findings:
        key = (finding.rule, finding.shape)
        groups.setdefault(key, Group(finding.rule, finding.shape, [])).findings.append(
            finding
        )
    # sorted() is stable, so groups of the same size keep the log order.
    return sorted(groups.values(), key=lambda g: -len(g.findings))


def format_report(findings: list[Finding], example_count: int = 2) -> str:
    """Build the report: a summary of groups first, then every finding."""
    groups = group_findings(findings)
    lines = [f"Summary: {len(findings)} problem(s) in {len(groups)} group(s)", ""]
    for number, group in enumerate(groups, start=1):
        lines.append(f"{number}. {len(group.findings)} x {group.rule}")
        lines.append(f"   shape: {group.shape}")
        for example in group.findings[:example_count]:
            lines.append(f"   e.g. line {example.line_no}: {example.message[:200]}")
        lines.append("")
    lines.append("Details:")
    for finding in findings:
        lines.append(f"line {finding.line_no}: {finding.rule}")
        for text_line in finding.text.splitlines()[:6]:
            lines.append(f"    {text_line}")
    return "\n".join(lines)


def print_log_sample(lines: list[str], count: int = 15, width: int = 200) -> None:
    """Show the first and last lines, so a CI run shows the real log format."""

    def show(line: str) -> str:
        # Escape control characters, so colour codes are visible.
        return line[:width].encode("unicode_escape").decode("ascii")

    print(f"log has {len(lines)} lines. First {count}:", file=sys.stderr)
    for line in lines[:count]:
        print(f"  | {show(line)}", file=sys.stderr)
    if len(lines) > count:
        print(f"Last {count}:", file=sys.stderr)
        for line in lines[-count:]:
            print(f"  | {show(line)}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--domain", required=True, help="integration domain")
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST,
        help=f"allowlist file (default: {DEFAULT_ALLOWLIST})",
    )
    parser.add_argument(
        "log", nargs="?", default="-", help="log file, or - for stdin (default)"
    )
    args = parser.parse_args(argv)

    try:
        if args.log == "-":
            lines = sys.stdin.read().splitlines()
        else:
            lines = (
                Path(args.log)
                .read_text(encoding="utf-8", errors="replace")
                .splitlines()
            )
    except OSError as err:
        print(f"error: cannot read log: {err}", file=sys.stderr)
        return 2

    try:
        allowlist = load_allowlist(args.allowlist) if args.allowlist.exists() else []
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2

    records = parse_records(lines)
    if not any(r.level for r in records):
        # An empty or wrong log must not pass the gate.
        print("error: no Home Assistant log records found", file=sys.stderr)
        print_log_sample(lines)
        return 2

    findings = check_records(records, args.domain, allowlist)
    if findings:
        print(format_report(findings))
        # Same stream as the report, so the order of the output is stable.
        print(
            f"\n{len(findings)} problem(s) found for '{args.domain}'. "
            "Fix them, or add a reason and a pattern to the allowlist."
        )
        return 1
    print(f"OK: no problems found for '{args.domain}' in {len(records)} records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
