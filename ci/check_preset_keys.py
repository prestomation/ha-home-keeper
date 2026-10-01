#!/usr/bin/env python3
"""Check the integration presets against their upstream sources.

An integration preset selects entities by their ``translation_key``. An integration
can rename or remove a key in a new release, and a preset that names that key then
matches nothing, with no error. An integration can also add a key for a part or a
supply that no preset uses yet.

Each entry in ``declarative_presets_catalog.INTEGRATIONS`` names its English
translation file (``source``, a raw GitHub URL on a branch) and the commit of that
branch we last read (``verified.ref``). This script reads the file at the branch head
and at the pinned commit, and reports:

* the catalog keys that are gone at the head (a break), and
* the keys added and removed since the pinned commit, per entity platform, with the
  added keys whose names look like a maintenance duty listed first as hints.

It decides nothing. The preset-upkeep skill (``.claude/skills/preset-upkeep``) reads
the report and decides what to fix or add. The branch head comes from
``git ls-remote``, not the GitHub API, so the script needs no token and runs where only
git and raw file reads reach GitHub.

Standard library and the ``git`` command only. Exit status: 0 when every key is found
and every source can be read, 1 otherwise. It is not a pull request gate: a change in
another project must not stop a merge here.

Usage:
    python ci/check_preset_keys.py                    # check every integration
    python ci/check_preset_keys.py roborock zha       # only the named domains
    python ci/check_preset_keys.py --report out.json  # also write the full report
    python ci/check_preset_keys.py --pin              # pin every clean entry to head
    python ci/check_preset_keys.py --pin roborock     # pin only the named domains
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

_CATALOG = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "home_keeper"
    / "declarative_presets_catalog.py"
)
_TIMEOUT = 30
_HEADERS = {"User-Agent": "home-keeper-preset-key-check"}
_RAW = re.compile(
    r"^https://raw\.githubusercontent\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/"
    r"(?P<branch>[^/]+)/(?P<path>.+)$"
)
# Parts of a key name that a maintenance duty usually has. A word matches the start
# of a part of the key between underscores ("descal" matches "descaling", "ink" does
# not match "link"), and a word with an underscore matches parts in a row. A key with
# a match is listed first in the report. It is a hint for the person or the skill that
# reads the report, not a decision.
DUTY_WORDS = (
    "filter",
    "brush",
    "life",
    "remain",
    "time_left",
    "wear",
    "service",
    "maint",
    "descal",
    "limescale",
    "salt",
    "toner",
    "ink",
    "drum",
    "cartridge",
    "blade",
    "bag",
    "pad",
    "mop",
    "clean",
    "consumable",
    "replace",
    "run_time",
    "runtime",
    "hours",
    "strainer",
    "desiccant",
    "odor",
    "saturation",
)

Fetch = Callable[[str], "dict[str, Any] | None"]
HeadRef = Callable[[str, str, str], "str | None"]


def parse_source(url: str) -> dict[str, str] | None:
    """The owner, repository, branch and path of a raw GitHub *url*, or ``None``."""
    match = _RAW.match(url)
    return match.groupdict() if match else None


def raw_url(source: dict[str, str], ref: str) -> str:
    """The raw URL of *source*'s file at *ref*, a branch or a commit."""
    return (
        f"https://raw.githubusercontent.com/{source['owner']}/{source['repo']}/"
        f"{ref}/{source['path']}"
    )


def entity_keys(translations: dict[str, Any]) -> dict[str, set[str]]:
    """The entity keys of a translation file, by platform."""
    entities = translations.get("entity") or {}
    return {
        platform: set(keys)
        for platform, keys in entities.items()
        if isinstance(keys, dict)
    }


def missing_keys(
    entry: dict[str, Any], translations: dict[str, Any]
) -> list[tuple[str, str]]:
    """The ``(platform, key)`` pairs of *entry* not in *translations*."""
    known = entity_keys(translations)
    missing = []
    for duty in entry["duties"]:
        platform = duty.get("platform", "sensor")
        missing += [
            (platform, key)
            for key in duty["keys"]
            if key not in known.get(platform, set())
        ]
    return missing


def key_diff(
    old: dict[str, set[str]], new: dict[str, set[str]]
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """The keys added and removed from *old* to *new*, by platform, sorted."""
    added: dict[str, list[str]] = {}
    removed: dict[str, list[str]] = {}
    for platform in sorted(set(old) | set(new)):
        plus = sorted(new.get(platform, set()) - old.get(platform, set()))
        minus = sorted(old.get(platform, set()) - new.get(platform, set()))
        if plus:
            added[platform] = plus
        if minus:
            removed[platform] = minus
    return added, removed


def has_duty_word(key: str) -> bool:
    """Whether *key* has a part that starts with a word of ``DUTY_WORDS``."""
    parts = key.lower().split("_")
    for word in DUTY_WORDS:
        wanted = word.split("_")
        for start in range(len(parts) - len(wanted) + 1):
            window = parts[start : start + len(wanted)]
            if all(p.startswith(w) for p, w in zip(window, wanted, strict=True)):
                return True
    return False


def duty_hints(added: dict[str, list[str]]) -> list[str]:
    """The added keys, as ``platform.key``, whose names have a duty word."""
    return [
        f"{platform}.{key}"
        for platform, keys in added.items()
        for key in keys
        if has_duty_word(key)
    ]


def check_entry(
    entry: dict[str, Any], fetch: Fetch, head_ref: str | None
) -> dict[str, Any]:
    """The report record of one catalog *entry*.

    *head_ref* is the commit at the head of the entry's branch, or ``None`` when it
    could not be read. The head file is read at that commit, so the record and a pin
    written from it describe the same file.
    """
    source = parse_source(entry["source"])
    pinned = (entry.get("verified") or {}).get("ref")
    record: dict[str, Any] = {
        "domain": entry["domain"],
        "source": entry["source"],
        "pinned_ref": pinned,
        "head_ref": head_ref,
        "missing": [],
        "added": {},
        "removed": {},
        "hints": [],
        "fetch_error": None,
        "pin_error": None,
    }
    if source is None:
        record["fetch_error"] = "source is not a raw GitHub URL"
        return record
    if head_ref is None:
        record["fetch_error"] = "cannot reach the repository: git ls-remote failed"
        return record
    if not head_ref:
        record["fetch_error"] = (
            f"branch {source['branch']} not found: the default branch may have changed"
        )
        return record
    head = fetch(raw_url(source, head_ref))
    if head is None:
        record["fetch_error"] = "cannot read the source at the branch head"
        return record
    record["missing"] = [f"{p}.{k}" for p, k in missing_keys(entry, head)]
    if pinned and pinned != head_ref:
        old = fetch(raw_url(source, pinned))
        if old is None:
            # The pinned commit is gone (a force push) or the file was not there
            # then. The head is still checked, so the entry can be pinned again.
            record["pin_error"] = (
                f"cannot read the source at the pinned commit {pinned}"
            )
            return record
        added, removed = key_diff(entity_keys(old), entity_keys(head))
        record["added"], record["removed"] = added, removed
        record["hints"] = duty_hints(added)
    return record


def pin_text(text: str, domain: str, ref: str, date: str) -> str:
    """*text* (the catalog source) with *domain*'s ``verified`` set to *ref* and *date*.

    The block goes on the line after the entry's ``source`` and replaces an older
    ``verified`` block there. Raises ``ValueError`` when the entry is not found.
    """
    pattern = re.compile(
        r'(?P<head>        "domain": "' + re.escape(domain) + r'",\n'
        r'(?:        (?!"domain").*\n)*?'
        r'        "source": "[^"]*",\n)'
        r'(?:        "verified": \{\n(?:            .*\n)*?        \},\n)?'
    )
    block = (
        '        "verified": {\n'
        f'            "ref": "{ref}",\n'
        f'            "date": "{date}",\n'
        "        },\n"
    )
    new, count = pattern.subn(lambda m: m.group("head") + block, text, count=1)
    if count != 1:
        raise ValueError(f"no catalog entry for domain {domain!r}")
    return new


def _integrations() -> list[dict[str, Any]]:
    """The catalog, loaded by path: it imports nothing from Home Assistant."""
    spec = importlib.util.spec_from_file_location("preset_catalog", _CATALOG)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.INTEGRATIONS)


def _fetch(url: str) -> dict[str, Any] | None:
    try:
        request = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as err:
        print(f"  FETCH FAILED: {url} ({err})")
        return None


def _ls_remote(owner: str, repo: str, branch: str) -> str | None:
    """The commit at the head of *branch*, from ``git ls-remote``.

    ``""`` when the repository answers and has no such branch, ``None`` when it
    cannot be reached, so a renamed branch and a network error are told apart.
    """
    try:
        out = subprocess.run(
            [
                "git",
                "ls-remote",
                f"https://github.com/{owner}/{repo}",
                f"refs/heads/{branch}",
            ],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT * 2,
            check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError) as err:
        print(f"  LS-REMOTE FAILED: {owner}/{repo} {branch} ({err})")
        return None
    first = out.split()
    return first[0] if first else ""


def head_refs(
    entries: Iterable[dict[str, Any]], head_ref: HeadRef
) -> dict[str, str | None]:
    """The branch head commit for each entry's source, by domain.

    One ``ls-remote`` per repository branch: 91 entries share about 50 of them.
    """
    branches: dict[tuple[str, str, str], list[str]] = {}
    for entry in entries:
        source = parse_source(entry["source"])
        if source is None:
            continue
        key = (source["owner"], source["repo"], source["branch"])
        branches.setdefault(key, []).append(entry["domain"])
    with ThreadPoolExecutor(max_workers=8) as pool:
        refs = dict(
            zip(branches, pool.map(lambda k: head_ref(*k), branches), strict=True)
        )
    return {
        domain: refs[key] for key, domains in branches.items() for domain in domains
    }


def run(
    entries: list[dict[str, Any]], fetch: Fetch = _fetch, head_ref: HeadRef = _ls_remote
) -> list[dict[str, Any]]:
    """The report records for *entries*."""
    heads = head_refs(entries, head_ref)
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(
            pool.map(lambda e: check_entry(e, fetch, heads.get(e["domain"])), entries)
        )


def _print(records: list[dict[str, Any]]) -> int:
    problems = 0
    for record in records:
        domain = record["domain"]
        if record["fetch_error"]:
            print(f"[FAIL] {domain}: {record['fetch_error']}")
            problems += 1
            continue
        if record["missing"]:
            print(
                f"[DRIFT] {domain}: {', '.join(record['missing'])} not found upstream"
            )
            problems += 1
        else:
            print(f"[OK] {domain}")
        if record["hints"]:
            print(f"  new keys that may be a duty: {', '.join(record['hints'])}")
        elif record["added"]:
            count = sum(len(keys) for keys in record["added"].values())
            print(f"  {count} new keys since the pinned commit")
        if not record["pinned_ref"]:
            print("  no pinned commit")
        if record["pin_error"]:
            print(f"  no diff: {record['pin_error']}")
    print(f"\n{len(records)} integrations checked, {problems} with a problem.")
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("domains", nargs="*", help="only these integration domains")
    parser.add_argument("--report", type=Path, help="write the full report as JSON")
    parser.add_argument(
        "--pin",
        action="store_true",
        help="pin each checked entry with no problem to its branch head commit",
    )
    args = parser.parse_args(argv)
    entries = _integrations()
    if args.domains:
        unknown = set(args.domains) - {e["domain"] for e in entries}
        if unknown:
            parser.error(f"unknown domains: {', '.join(sorted(unknown))}")
        entries = [e for e in entries if e["domain"] in args.domains]
    records = run(entries)
    problems = _print(records)
    if args.report:
        args.report.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        print(f"Report written to {args.report}")
    if args.pin:
        today = dt.datetime.now(dt.UTC).date().isoformat()
        text = _CATALOG.read_text(encoding="utf-8")
        pinned = 0
        for record in records:
            if record["fetch_error"] or record["missing"]:
                print(f"  not pinned: {record['domain']} (fix it first)")
                continue
            text = pin_text(text, record["domain"], record["head_ref"], today)
            pinned += 1
        _CATALOG.write_text(text, encoding="utf-8")
        print(f"Pinned {pinned} entries to their branch head on {today}.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
