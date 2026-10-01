#!/usr/bin/env python3
"""List the integrations that may need a new preset.

Two sources, both read with no GitHub API:

* **Home Assistant core.** Every integration in a local sparse clone of core whose
  ``strings.json`` names an entity key that looks like a maintenance duty (the same
  word list as ``check_preset_keys.DUTY_WORDS``), and that has no catalog entry.
* **HACS default list.** The integration repositories added to
  ``hacs/default``'s ``integration`` file since the commit in the state file, that no
  catalog entry reads from.

The state file, ``ci/preset_candidates.json``, records each candidate that a person
or the preset-upkeep skill already reviewed, with the duty keys it had then and the
reason. A reviewed core integration comes back only when it gains a new duty key, so
a weekly run lists what changed, not the same integrations again. The script decides
nothing; the skill reads its output and decides.

Usage:
    git clone -q --depth 1 --filter=blob:none --sparse \\
        https://github.com/home-assistant/core /tmp/ha-core
    git -C /tmp/ha-core sparse-checkout set --no-cone \\
        '/homeassistant/components/*/strings.json'
    python ci/find_preset_candidates.py --core /tmp/ha-core
    python ci/find_preset_candidates.py --core /tmp/ha-core --json out.json
    python ci/find_preset_candidates.py --mark core:balboa "filter cycle is a schedule"
    python ci/find_preset_candidates.py --pin-hacs
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_STATE = _ROOT / "ci" / "preset_candidates.json"
_HACS = ("hacs", "default", "master", "integration")


def _check_module() -> Any:
    """``check_preset_keys``, loaded by path so this script needs no package."""
    spec = importlib.util.spec_from_file_location(
        "check_preset_keys", _ROOT / "ci" / "check_preset_keys.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _check_module()


def load_state(path: Path = _STATE) -> dict[str, Any]:
    """The state file, or an empty state when there is none."""
    if not path.exists():
        return {"hacs_default_ref": None, "reviewed": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any], path: Path = _STATE) -> None:
    """Write *state* with sorted keys, so a diff of the file stays small."""
    state["reviewed"] = dict(sorted(state["reviewed"].items()))
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def catalog_domains_and_repos(
    entries: list[dict[str, Any]],
) -> tuple[set[str], set[str]]:
    """The catalog's domains, and the ``owner/repo`` of every source."""
    repos = set()
    for entry in entries:
        source = check.parse_source(entry["source"])
        if source:
            repos.add(f"{source['owner']}/{source['repo']}".lower())
    return {e["domain"] for e in entries}, repos


def core_candidates(
    strings: dict[str, dict[str, Any]],
    catalog: set[str],
    reviewed: dict[str, Any],
) -> dict[str, list[str]]:
    """The core integrations to look at, with their duty keys.

    *strings* maps a domain to its ``strings.json``. An integration in the catalog is
    left out. A reviewed one is left out unless it now has a duty key that it did not
    have when it was reviewed; then only the new keys are listed.
    """
    found: dict[str, list[str]] = {}
    for domain in sorted(strings):
        if domain in catalog:
            continue
        keys = check.entity_keys(strings[domain])
        hints = check.duty_hints({p: sorted(k) for p, k in sorted(keys.items())})
        seen = set(reviewed.get(f"core:{domain}", {}).get("keys", []))
        new = [h for h in hints if h not in seen]
        if new:
            found[domain] = new
    return found


def hacs_candidates(
    old: list[str], new: list[str], catalog_repos: set[str], reviewed: dict[str, Any]
) -> list[str]:
    """The repositories added to the HACS list from *old* to *new* to look at."""
    before = {r.lower() for r in old}
    return [
        repo
        for repo in new
        if repo.lower() not in before
        and repo.lower() not in catalog_repos
        and f"hacs:{repo.lower()}" not in reviewed
    ]


def read_core(path: Path) -> dict[str, dict[str, Any]]:
    """Each core integration's ``strings.json`` from a sparse clone at *path*."""
    out = {}
    for file in sorted((path / "homeassistant" / "components").glob("*/strings.json")):
        try:
            out[file.parent.name] = json.loads(file.read_text(encoding="utf-8"))
        except ValueError:
            print(f"  cannot parse {file}")
    return out


def _hacs_list(ref: str) -> list[str] | None:
    owner, repo, _branch, path = _HACS
    data = check._fetch(
        f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
    )
    return data if isinstance(data, list) else None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--core", type=Path, help="a sparse clone of core")
    parser.add_argument("--json", type=Path, help="write the candidates as JSON")
    parser.add_argument(
        "--mark",
        nargs=2,
        metavar=("ID", "REASON"),
        help="record core:<domain> or hacs:<owner/repo> as reviewed",
    )
    parser.add_argument(
        "--pin-hacs",
        action="store_true",
        help="record the head of the HACS list as reviewed",
    )
    args = parser.parse_args(argv)
    state = load_state()
    catalog, repos = catalog_domains_and_repos(check._integrations())

    if args.mark:
        ident, reason = args.mark
        keys: list[str] = []
        if ident.startswith("core:") and args.core:
            strings = read_core(args.core).get(ident.removeprefix("core:"), {})
            entity = check.entity_keys(strings)
            keys = check.duty_hints({p: sorted(k) for p, k in sorted(entity.items())})
        elif not ident.startswith(("core:", "hacs:")):
            parser.error("ID must start with core: or hacs:")
        state["reviewed"][ident.lower()] = {"keys": keys, "reason": reason}
        save_state(state)
        print(f"Marked {ident} as reviewed.")
        return 0

    head = check._ls_remote(*_HACS[:3])
    if args.pin_hacs:
        if head is None:
            print("Cannot read the head of the HACS list.")
            return 1
        state["hacs_default_ref"] = head
        save_state(state)
        print(f"Pinned the HACS list at {head}.")
        return 0

    result: dict[str, Any] = {"core": {}, "hacs": [], "hacs_head_ref": head}
    if args.core:
        result["core"] = core_candidates(
            read_core(args.core), catalog, state["reviewed"]
        )
    pinned = state.get("hacs_default_ref")
    if head and pinned and head != pinned:
        old, new = _hacs_list(pinned), _hacs_list(head)
        if old is not None and new is not None:
            result["hacs"] = hacs_candidates(old, new, repos, state["reviewed"])
    for domain, hints in result["core"].items():
        print(f"core:{domain}: {', '.join(hints)}")
    for repo in result["hacs"]:
        print(f"hacs:{repo}")
    print(f"\n{len(result['core'])} core and {len(result['hacs'])} HACS candidates.")
    if args.json:
        args.json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
