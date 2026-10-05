"""Wait until every check on a pull request ends, then report pass or fail.

``dependabot-auto-merge.yml`` runs this before it merges. ``gh pr checks --watch``
could not do the job (X06-1): the job that runs the wait is itself a check on the
pull request, so it stays pending until the job times out, and the merge never
runs. And ``notify-discord.yml`` fails on every Dependabot pull request, because
such a run gets no secrets, so ``--fail-fast`` stopped at once.

This script reads ``gh pr checks --json`` in a loop and leaves out the checks of
the workflows named in ``--ignore-workflow``. It exits 0 when every other check
passed or was skipped, and 1 when one failed or was cancelled, or at the timeout.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Iterable

PASS = "pass"
FAIL = "fail"
PENDING = "pending"

# ``gh pr checks`` puts each check in one of these buckets.
_DONE_OK = {"pass", "skipping"}
_DONE_BAD = {"fail", "cancel"}


def verdict(checks: Iterable[dict], ignore: Iterable[str]) -> str:
    """Return PASS, FAIL or PENDING for *checks*, without the *ignore* workflows.

    No check left is PENDING, not PASS: the other workflows can be still to start.
    """
    ignored = set(ignore)
    left = [c for c in checks if c.get("workflow") not in ignored]
    if any(c.get("bucket") in _DONE_BAD for c in left):
        return FAIL
    if left and all(c.get("bucket") in _DONE_OK for c in left):
        return PASS
    return PENDING


def _read(pr: str) -> list[dict]:
    out = subprocess.run(
        ["gh", "pr", "checks", pr, "--json", "name,workflow,bucket"],
        capture_output=True,
        text=True,
        check=False,
    )
    # ``gh pr checks`` exits 8 while a check is pending, and still prints the JSON.
    if not out.stdout.strip():
        return []
    return list(json.loads(out.stdout))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr", help="pull request URL or number")
    parser.add_argument("--ignore-workflow", action="append", default=[])
    parser.add_argument("--interval", type=float, default=15)
    parser.add_argument("--timeout", type=float, default=45 * 60)
    args = parser.parse_args(argv)

    end = time.monotonic() + args.timeout
    while True:
        checks = _read(args.pr)
        result = verdict(checks, args.ignore_workflow)
        if result != PENDING:
            for c in checks:
                print(f"{c.get('bucket')}\t{c.get('workflow')} / {c.get('name')}")
            print(f"checks: {result}")
            return 0 if result == PASS else 1
        if time.monotonic() >= end:
            print("checks: timed out while a check was pending")
            return 1
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
