#!/usr/bin/env python3
"""Score a mutation-testing run, summarise it, and gate on a threshold.

Two input formats, one output shape:

* ``--format mutmut`` reads ``mutmut results --all=1`` on **stdin**. mutmut has
  no threshold of its own and exits 0 whether or not mutants survived, so this
  script owns the Python gate.
* ``--format stryker`` reads Stryker's JSON report. Stryker already gates via
  ``thresholds.break``; here the script only renders the summary, and the
  caller propagates Stryker's exit code.

A mutant counts as **detected** when the suite noticed it (killed, timed out, or
was rejected by the type checker) and **undetected** when it did not (survived,
or no test covered it at all). Mutants that were never run — the ones outside a
diff-scoped filter — are excluded from the score rather than counted as
failures.

The markdown summary is appended to ``$GITHUB_STEP_SUMMARY`` when that is set,
and always printed to stdout.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_THRESHOLD = 80.0

# How mutmut's own status strings map onto detected / undetected. "suspicious"
# means mutmut got an exit code it could not classify; counting it as undetected
# keeps the gate honest instead of quietly discarding an unknown.
MUTMUT_DETECTED = {"killed", "timeout", "caught by type check"}
MUTMUT_UNDETECTED = {"survived", "no tests", "suspicious"}
MUTMUT_IGNORED = {"not checked", "skipped", "check was interrupted by user"}

# Stryker statuses, from the mutation-testing-elements schema.
STRYKER_DETECTED = {"Killed", "Timeout"}
STRYKER_UNDETECTED = {"Survived", "NoCoverage"}
STRYKER_IGNORED = {"CompileError", "RuntimeError", "Ignored", "Pending"}

MAX_LISTED = 40


def configured_threshold() -> float:
    """Read ``[tool.mutation-gate] break`` from pyproject.toml.

    An unreadable pyproject.toml is fatal rather than a quiet fall back to
    ``DEFAULT_THRESHOLD``: silently substituting a threshold nobody configured is
    how a gate stops meaning anything.
    """
    try:
        with (ROOT / "pyproject.toml").open("rb") as handle:
            config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        sys.exit(f"[mutation] cannot read the threshold from pyproject.toml: {exc}")
    section = config.get("tool", {}).get("mutation-gate", {})
    return float(section.get("break", DEFAULT_THRESHOLD))


def check_thresholds_agree(threshold: float) -> None:
    """Fail if pyproject.toml and stryker.conf.json disagree on the gate.

    The two live apart because each tool reads its own config, so nothing stops
    them drifting — and a drift means Python and TypeScript are quietly held to
    different standards. Cheap to check, so check it every run.
    """
    try:
        config = json.loads((ROOT / "stryker.conf.json").read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"[mutation] cannot read stryker.conf.json: {exc}")
    stryker = config.get("thresholds", {}).get("break")
    if stryker is None or float(stryker) != threshold:
        sys.exit(
            f"[mutation] threshold mismatch: [tool.mutation-gate] break = "
            f"{threshold:g} but stryker.conf.json thresholds.break = {stryker}. "
            "Keep them equal."
        )


def parse_mutmut(
    stream: list[str], scope: list[str]
) -> tuple[dict[str, int], list[str]]:
    """Parse ``mutmut results --all=1`` lines into a status tally and survivor list.

    Each line looks like ``    package.module.x_func__mutmut_3: survived``.
    When *scope* is non-empty only mutants matching one of its glob filters are
    counted, so a diff-scoped run is not dragged down by the rest of the file.
    """
    tally: dict[str, int] = {}
    undetected: list[str] = []
    for raw in stream:
        line = raw.strip()
        if not line or ": " not in line:
            continue
        name, _, status = line.rpartition(": ")
        name = name.strip()
        status = status.strip()
        if scope and not any(fnmatch.fnmatch(name, pattern) for pattern in scope):
            continue
        tally[status] = tally.get(status, 0) + 1
        if status in MUTMUT_UNDETECTED:
            undetected.append(f"{name} ({status})")
    return tally, undetected


def parse_stryker(path: Path) -> tuple[dict[str, int], list[str]]:
    """Parse Stryker's JSON report into a status tally and survivor list."""
    try:
        report = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # A truncated report means the run died mid-write. Say so; do not let a
        # half-read file be scored as if it were the whole run.
        sys.exit(f"[mutation] cannot read the Stryker report at {path}: {exc}")
    tally: dict[str, int] = {}
    undetected: list[str] = []
    for file_path, entry in sorted(report.get("files", {}).items()):
        for mutant in entry.get("mutants", []):
            status = mutant.get("status", "Pending")
            tally[status] = tally.get(status, 0) + 1
            if status in STRYKER_UNDETECTED:
                line = mutant.get("location", {}).get("start", {}).get("line", "?")
                undetected.append(
                    f"{file_path}:{line} {mutant.get('mutatorName', '?')} ({status})"
                )
    return tally, undetected


def score(
    tally: dict[str, int], detected: set[str], undetected: set[str]
) -> tuple[float, int, int]:
    """Mutation score as a percentage, plus the two counts behind it."""
    hits = sum(count for status, count in tally.items() if status in detected)
    misses = sum(count for status, count in tally.items() if status in undetected)
    total = hits + misses
    return (100.0 if total == 0 else 100.0 * hits / total), hits, misses


def render(
    title: str,
    tally: dict[str, int],
    survivors: list[str],
    percent: float,
    hits: int,
    misses: int,
    threshold: float,
    passed: bool,
) -> str:
    verdict = "✅ pass" if passed else "❌ below threshold"
    lines = [
        f"## {title}",
        "",
        f"**Mutation score: {percent:.2f}%** ({hits} detected / {hits + misses} scored)"
        f" — threshold {threshold:.0f}% — {verdict}",
        "",
    ]
    if tally:
        lines += ["| Outcome | Mutants |", "| --- | ---: |"]
        lines += [f"| {status} | {count} |" for status, count in sorted(tally.items())]
        lines.append("")
    if survivors:
        shown = survivors[:MAX_LISTED]
        lines.append(
            f"<details><summary>Undetected mutants ({len(survivors)})</summary>"
        )
        lines.append("")
        lines += [f"- `{entry}`" for entry in shown]
        if len(survivors) > len(shown):
            lines.append(f"- …and {len(survivors) - len(shown)} more")
        lines += ["", "</details>", ""]
    return "\n".join(lines)


def emit(markdown: str) -> None:
    print(markdown)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", required=True, choices=("mutmut", "stryker"))
    parser.add_argument(
        "--input", type=Path, help="Stryker JSON report (stryker format)"
    )
    parser.add_argument(
        "--scope-file", type=Path, help="mutant-name filters, one per line"
    )
    parser.add_argument("--title", default="Mutation testing")
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument(
        "--gate",
        action="store_true",
        help="exit non-zero when the score is below the threshold",
    )
    parser.add_argument(
        "--require-mutants",
        action="store_true",
        help="exit non-zero when nothing was scored at all",
    )
    args = parser.parse_args()

    # Always compare what the *configs* say, even when --threshold overrides the
    # value used for this run — the point is to catch the two drifting apart.
    check_thresholds_agree(configured_threshold())
    threshold = configured_threshold() if args.threshold is None else args.threshold

    if args.format == "mutmut":
        scope = []
        if args.scope_file and args.scope_file.exists():
            scope = [
                ln.strip()
                for ln in args.scope_file.read_text("utf-8").splitlines()
                if ln.strip()
            ]
        tally, survivors = parse_mutmut(sys.stdin.readlines(), scope)
        percent, hits, misses = score(tally, MUTMUT_DETECTED, MUTMUT_UNDETECTED)
    else:
        if not args.input or not args.input.exists():
            emit(
                f"## {args.title}\n\n"
                "⚠️ No Stryker report was produced — the run failed before reporting.\n"
            )
            # The caller propagates Stryker's own exit code, so this is already
            # a failure there; return non-zero anyway so the script is honest
            # when read on its own.
            return 1 if args.require_mutants else 0
        tally, survivors = parse_stryker(args.input)
        percent, hits, misses = score(tally, STRYKER_DETECTED, STRYKER_UNDETECTED)

    known = (
        MUTMUT_DETECTED | MUTMUT_UNDETECTED | MUTMUT_IGNORED
        if args.format == "mutmut"
        else STRYKER_DETECTED | STRYKER_UNDETECTED | STRYKER_IGNORED
    )
    unknown = sorted(set(tally) - known)
    if unknown:
        # A status this script does not classify is silently absent from the
        # score, which would quietly weaken the gate. Say so loudly instead.
        print(
            f"[mutation] unclassified outcome(s) {unknown} — not counted in the "
            "score; teach ci/mutation_report.py about them.",
            file=sys.stderr,
        )

    scored = hits + misses
    passed = scored == 0 or percent >= threshold
    emit(render(args.title, tally, survivors, percent, hits, misses, threshold, passed))

    if scored == 0 and tally and args.require_mutants:
        # Mutants existed and not one of them was scored: they all errored out,
        # or the filters matched nothing runnable. That is a run which tested
        # nothing while looking like a pass — the one failure mode worse than a
        # false red.
        #
        # An empty tally is the *opposite* case and must pass: the scoped lines
        # genuinely hold no mutants. A comment-only edit inside a mutable file
        # produces exactly that — real changed line ranges, nothing to mutate.
        print(
            f"[mutation] {sum(tally.values())} mutant(s) were reported but none "
            "could be scored — the run did not test anything.",
            file=sys.stderr,
        )
        return 1

    if scored == 0:
        print("[mutation] no mutants in scope — nothing to gate on.", file=sys.stderr)
    return 0 if passed or not args.gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
