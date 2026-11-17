#!/usr/bin/env python3
"""Check the parity registry: the rules that exist in Python and in TypeScript.

``tests/fixtures/parity.json`` lists each such rule with its Python function, its
TypeScript function and its shared case file. Each side carries a marker comment just
above its definition: ``# parity: <id>`` in Python, ``// parity: <id>`` in TypeScript.

``python3 ci/parity.py check`` fails when:

* a registered file, function or case file is missing, or a case file has no cases;
* a marker names an id that is not registered, or sits above the wrong definition;
* a registered rule has no marker, or more than 1, on either side. A rule marked on 1
  side only is a twin that nothing holds to the other;
* the corpus (``parity_corpus.json``) does not cover exactly the ``corpus`` rules.

It reads files only and needs the standard library only. The tests that run the cases
are ``tests/unit/test_shared_cases.py`` and ``frontend/test/shared-cases.test.js``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = "tests/fixtures/parity.json"
CORPUS = "tests/fixtures/parity_corpus.json"
PY_DIR = "custom_components/home_keeper"
TS_DIR = "custom_components/home_keeper/frontend/src"

_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_PY_MARK = re.compile(r"^#\s*parity:\s*(\S+)\s*$")
_TS_MARK = re.compile(r"^//\s*parity:\s*(\S+)\s*$")


def _py_defines(line: str, name: str) -> bool:
    return (
        re.match(
            rf"(async\s+)?def\s+{re.escape(name)}\b|{re.escape(name)}\s*[:=]", line
        )
        is not None
    )


def _ts_defines(line: str, name: str) -> bool:
    pattern = rf"(export\s+)?(async\s+)?(function|const|let)\s+{re.escape(name)}\b"
    return re.match(pattern, line) is not None


def _is_lead_in(line: str, python: bool) -> bool:
    """A line that may stand between a marker and its definition."""
    text = line.strip()
    if python:
        return text.startswith("@")
    return text.startswith(("/*", "*", "//"))


def _markers(path: Path, python: bool) -> list[tuple[str, int, str | None]]:
    """Each marker in *path*: its id, its line number and the next code line."""
    lines = path.read_text(encoding="utf-8").splitlines()
    mark = _PY_MARK if python else _TS_MARK
    found = []
    for index, line in enumerate(lines):
        match = mark.match(line.strip())
        if not match:
            continue
        nxt = index + 1
        while nxt < len(lines) and _is_lead_in(lines[nxt], python):
            nxt += 1
        found.append(
            (match.group(1), index + 1, lines[nxt] if nxt < len(lines) else None)
        )
    return found


def _source_files(root: Path) -> list[tuple[Path, bool]]:
    py = sorted((root / PY_DIR).rglob("*.py"))
    ts = sorted((root / TS_DIR).rglob("*.ts"))
    return [(p, True) for p in py] + [(p, False) for p in ts]


def _check_cases(root: Path, rule_id: str, rel: str) -> list[str]:
    path = root / rel
    if not path.is_file():
        return [f"{rule_id}: the case file {rel} does not exist"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        return [f"{rule_id}: {rel} is not valid JSON ({err})"]
    cases = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(cases, list) or not cases:
        return [f"{rule_id}: {rel} has no cases"]
    names = [case.get("name") for case in cases if isinstance(case, dict)]
    if len(names) != len(cases) or not all(names):
        return [f"{rule_id}: each case in {rel} needs a name"]
    if len(set(names)) != len(names):
        return [f"{rule_id}: {rel} has 2 cases with the same name"]
    return []


def check(root: Path = ROOT) -> list[str]:
    """Return 1 line for each problem. An empty list means the registry holds."""
    errors: list[str] = []
    try:
        registry = json.loads((root / REGISTRY).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        return [f"cannot read {REGISTRY}: {err}"]
    rules = registry.get("rules") or []
    by_id: dict[str, dict] = {}
    for rule in rules:
        rule_id = rule.get("id", "")
        if not _ID.match(rule_id):
            errors.append(f"{rule_id!r}: an id is lower case, digits and underscores")
            continue
        if rule_id in by_id:
            errors.append(f"{rule_id}: registered 2 times")
            continue
        by_id[rule_id] = rule
        for side, base, suffix in (
            ("python", PY_DIR, ".py"),
            ("typescript", TS_DIR, ".ts"),
        ):
            rel, _, name = str(rule.get(side, "")).partition("::")
            if not rel.startswith(base + "/") or not rel.endswith(suffix) or not name:
                errors.append(
                    f"{rule_id}: {side} must be '{base}/<file>{suffix}::<name>'"
                )
                continue
            path = root / rel
            if not path.is_file():
                errors.append(f"{rule_id}: {rel} does not exist")
                continue
            defines = _py_defines if side == "python" else _ts_defines
            text = path.read_text(encoding="utf-8").splitlines()
            if not any(defines(line, name) for line in text):
                errors.append(f"{rule_id}: {rel} does not define {name}")
        errors.extend(_check_cases(root, rule_id, str(rule.get("cases", ""))))

    seen: dict[tuple[str, bool], int] = {}
    for path, python in _source_files(root):
        rel = path.relative_to(root).as_posix()
        for rule_id, line_no, code in _markers(path, python):
            where = f"{rel}:{line_no}"
            rule = by_id.get(rule_id)
            if rule is None:
                errors.append(
                    f"{where}: marker for {rule_id!r}, which {REGISTRY} does not list"
                )
                continue
            seen[(rule_id, python)] = seen.get((rule_id, python), 0) + 1
            want_rel, _, name = rule["python" if python else "typescript"].partition(
                "::"
            )
            defines = _py_defines if python else _ts_defines
            if rel != want_rel or code is None or not defines(code, name):
                errors.append(
                    f"{where}: the {rule_id} marker must sit above {want_rel}::{name}"
                )

    for rule_id in by_id:
        for python, label in ((True, "Python"), (False, "TypeScript")):
            count = seen.get((rule_id, python), 0)
            if count != 1:
                errors.append(f"{rule_id}: {count} {label} markers, expected 1")

    corpus_ids = {rule_id for rule_id, rule in by_id.items() if rule.get("corpus")}
    if corpus_ids:
        try:
            corpus = json.loads((root / CORPUS).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as err:
            errors.append(f"cannot read {CORPUS}: {err}")
        else:
            have = set(corpus.get("rules") or {})
            for rule_id in sorted(corpus_ids - have):
                errors.append(
                    f"{rule_id}: marked corpus, but {CORPUS} has no entries for it"
                )
            for rule_id in sorted(have - corpus_ids):
                errors.append(
                    f"{rule_id}: in {CORPUS}, but not marked corpus in {REGISTRY}"
                )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["check"])
    parser.parse_args(argv)
    errors = check()
    for error in errors:
        print(f"parity: {error}", file=sys.stderr)
    if errors:
        return 1
    print(
        f"parity: {len(json.loads((ROOT / REGISTRY).read_text())['rules'])} rules hold"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
