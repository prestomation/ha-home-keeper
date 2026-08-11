#!/usr/bin/env python3
"""Map a branch's diff onto the mutation-testing surface.

Mutation testing is expensive, and judging a pull request on a whole file's
score would fail it for debt it did not create. So the PR check mutates only
what the branch actually touched:

* **Python** — changed lines are mapped, via ``ast``, to the enclosing top-level
  function or method (decorators included), and printed as mutmut mutant-name
  filters (``package.module.x_func*``). mutmut only builds mutants for top-level
  functions and methods, so a changed line outside one — module-level code, a
  nested closure — contributes no filter. There is nothing to run for those, but
  it does mean the surface should stay free of significant module-level logic.
* **TypeScript** — changed hunks are printed directly as Stryker ``--mutate``
  line ranges (``path/to/file.ts:12-40``).

Either way, only files already on the configured surface are considered: the
``only_mutate`` list in ``[tool.mutmut]`` for Python and ``mutate`` in
``stryker.conf.json`` for TypeScript. Those two lists are the single definition
of what is worth mutating; this script never widens them.

Prints one filter/range per line to stdout. Empty output means "the diff touched
nothing mutable" — callers should treat that as a pass, not an error.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# mutmut mangles a method into ``xǁClassǁmethod`` and a bare function into
# ``x_function`` (mutmut.mutation.trampoline_templates.CLASS_NAME_SEPARATOR).
CLASS_NAME_SEPARATOR = "ǁ"

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _git(*args: str) -> str:
    """Run git in the repo root and return stdout, or fail loudly."""
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        sys.exit(
            f"[mutation-scope] git {' '.join(args)} failed: {result.stderr.strip()}"
        )
    return result.stdout


def python_surface() -> list[str]:
    """The ``only_mutate`` globs from ``[tool.mutmut]``."""
    try:
        with (ROOT / "pyproject.toml").open("rb") as handle:
            config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        sys.exit(f"[mutation-scope] cannot read pyproject.toml: {exc}")
    return list(config.get("tool", {}).get("mutmut", {}).get("only_mutate", []))


def typescript_surface() -> list[str]:
    """The ``mutate`` globs from ``stryker.conf.json``."""
    try:
        config = json.loads((ROOT / "stryker.conf.json").read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"[mutation-scope] cannot read stryker.conf.json: {exc}")
    return list(config.get("mutate", []))


def _on_surface(path: str, surface: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in surface)


def changed_hunks(base: str, surface: list[str]) -> dict[str, list[tuple[int, int]]]:
    """Return ``{path: [(start, end), ...]}`` for surface files changed since *base*.

    Line numbers are in the *new* file. ``--unified=0`` keeps each hunk tight
    around the real edit instead of dragging in three lines of context either
    side, which would pull untouched neighbouring functions into scope.
    """
    merge_base = _git("merge-base", base, "HEAD").strip()
    if not merge_base:
        sys.exit(f"[mutation-scope] could not find a merge base with {base}")
    diff = _git(
        "diff",
        "--unified=0",
        "--diff-filter=ACMR",  # skip deletions: there is nothing left to mutate
        merge_base,
        "HEAD",
    )

    hunks: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:].strip()
            # "+++ b/path/to/file" — or "/dev/null" for a deleted file.
            path = target[2:] if target.startswith("b/") else target
            current = path if _on_surface(path, surface) else None
            continue
        if current is None or not line.startswith("@@"):
            continue
        match = _HUNK_RE.match(line)
        if not match:
            # Never silently narrow the scope: an unrecognised header would drop
            # a real change and quietly turn the gate green.
            sys.exit(f"[mutation-scope] unparseable hunk header in {current}: {line}")
        start = int(match.group(1))
        count = 1 if match.group(2) is None else int(match.group(2))
        if count == 0:
            # A pure deletion. `start` is the line *before* the removed block, so
            # cover both it and the line that followed it — the deleted code sat
            # between them, and either neighbour may be the enclosing function.
            hunks.setdefault(current, []).append((start, start + 1))
            continue
        hunks.setdefault(current, []).append((start, start + count - 1))
    return hunks


def _module_name(path: str) -> str:
    return path[: -len(".py")].replace("/", ".")


def _definition_span(node: ast.AST) -> tuple[int, int]:
    """First-to-last line of a definition, decorators included."""
    start = node.lineno  # type: ignore[attr-defined]
    for decorator in getattr(node, "decorator_list", []):
        start = min(start, decorator.lineno)
    return start, node.end_lineno  # type: ignore[attr-defined]


def _overlaps(span: tuple[int, int], ranges: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(
        hunk_start <= end and hunk_end >= start for hunk_start, hunk_end in ranges
    )


def python_filters(hunks: dict[str, list[tuple[int, int]]]) -> list[str]:
    """Turn changed line ranges into mutmut mutant-name filters."""
    filters: list[str] = []
    for path, ranges in sorted(hunks.items()):
        module = _module_name(path)
        try:
            tree = ast.parse((ROOT / path).read_text("utf-8"), filename=path)
        except (OSError, SyntaxError) as exc:
            # Failing loudly beats silently emitting no filter for the file:
            # an empty scope reads as "nothing to test" and would pass the gate.
            sys.exit(f"[mutation-scope] cannot parse {path}: {exc}")
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if _overlaps(_definition_span(node), ranges):
                    filters.append(f"{module}.x_{node.name}*")
            elif isinstance(node, ast.ClassDef):
                for child in node.body:
                    if not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                        continue
                    if _overlaps(_definition_span(child), ranges):
                        sep = CLASS_NAME_SEPARATOR
                        filters.append(f"{module}.x{sep}{node.name}{sep}{child.name}*")
    return filters


def typescript_ranges(hunks: dict[str, list[tuple[int, int]]]) -> list[str]:
    """Turn changed line ranges into Stryker ``--mutate`` arguments."""
    return [
        f"{path}:{start}-{end}"
        for path, ranges in sorted(hunks.items())
        for start, end in ranges
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", required=True, choices=("python", "typescript"))
    parser.add_argument(
        "--base",
        default="origin/main",
        help="branch to diff against (default: origin/main)",
    )
    args = parser.parse_args()

    if args.language == "python":
        surface = python_surface()
        hunks = changed_hunks(args.base, surface)
        scope = python_filters(hunks)
    else:
        surface = typescript_surface()
        hunks = changed_hunks(args.base, surface)
        scope = typescript_ranges(hunks)

    for entry in scope:
        print(entry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
