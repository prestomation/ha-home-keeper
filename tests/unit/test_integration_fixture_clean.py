"""The committed integration fixture must match what the suites expect of it.

Two failure modes, both of which have happened, and neither of which shows up in a
local run:

*Extra* records — the fixture committed as the tests left it — and *missing* records,
where a hand-restore drops a seeded row the capture harnesses click on. The second one
is the sneakier of the two: it only fails in the Playwright capture, which is a soft
gate, so it lands as a "capture failed" note rather than a red check.

``tests/integration/ha_config`` is bind-mounted into the container, so running the
suite locally rewrites `.storage/home_keeper` in place. AGENTS.md says to restore it
before committing, and that instruction is easy to miss — a `git add -A` after a local
run quietly bakes in whatever the tests just created.

That is not a cosmetic problem. Several integration tests find their subject with
``next(a for a in assets if a["name"] == "…")``, so a leftover record with the same
name shadows the one the test just created and the test fails on a *pristine* checkout
while passing locally against the already-dirty container. It happened; this is the
guard so it can't happen quietly again.

Pure JSON reading, so it runs in the fast unit lane with no Home Assistant.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FIXTURE = ROOT / "tests" / "integration" / "ha_config" / ".storage" / "home_keeper"

E2E_DIR = ROOT / "tests" / "e2e"

#: `.detail-open[data-detail-id="…"]` — how the capture harnesses open a detail page.
DETAIL_ID = re.compile(r'data-detail-id="([^"]+)"')

#: The harnesses interpolate a constant rather than pasting a uuid, so the id reads
#: `${TASK.nozzleUsage}` in the source. Resolve those through `fixture-ids.ts` before
#: measuring them against the seed.
FIXTURE_IDS = E2E_DIR / "fixture-ids.ts"
CONST_REF = re.compile(r"^\$\{(\w+)\.(\w+)\}$")
CONST_DECL = re.compile(r"export const (\w+) = \{(.*?)\} as const;", re.S)
CONST_ENTRY = re.compile(r"(\w+):\s*'([^']+)'")


def _fixture_id_constants() -> dict[str, str]:
    """`{"TASK.nozzleUsage": "<uuid>"}` from the e2e fixture-id module."""
    source = FIXTURE_IDS.read_text()
    return {
        f"{group}.{name}": value
        for group, body in CONST_DECL.findall(source)
        for name, value in CONST_ENTRY.findall(body)
    }


#: Names the integration and e2e suites create as they run. None should ever be
#: committed. ``e2e`` is deliberately broad: the browser specs had no teardown at
#: all until they grew one, and eight of their leftovers reached git precisely
#: because every name carried a fresh ``Date.now()`` — so each leak read as a new
#: record rather than the same spec failing to clean up. Matching the prefix
#: catches them however they're named.
TEST_CREATED_MARKERS = (
    "temp asset",
    "probe",
    "test clean gutters",
    "test water the",
    "e2e",
)


def _records(payload: dict, key: str) -> list[dict]:
    section = payload.get("data", {}).get(key, {})
    return list(section.values()) if isinstance(section, dict) else list(section)


def test_seeded_fixture_has_no_test_created_records() -> None:
    payload = json.loads(FIXTURE.read_text())
    offenders = [
        f"{key}: {record.get('name')!r}"
        for key in ("tasks", "assets")
        for record in _records(payload, key)
        if any(m in (record.get("name") or "").lower() for m in TEST_CREATED_MARKERS)
    ]
    assert not offenders, (
        "The committed integration fixture contains records the test suite creates at "
        "runtime, which means a local run was committed. Restore it with "
        "`git checkout -- tests/integration/ha_config/` and re-commit.\n  "
        + "\n  ".join(offenders)
    )


def test_seeded_fixture_has_no_archived_assets() -> None:
    """Nothing in the seed should start out archived.

    ``test_archive_asset_hides_data_without_deleting_it`` asserts a freshly created
    asset is *not* archived, and picks its subject by name. A committed archived
    leftover is exactly what broke it.
    """
    payload = json.loads(FIXTURE.read_text())
    archived = [
        a.get("name") for a in _records(payload, "assets") if a.get("archived_at")
    ]
    assert not archived, f"seeded assets should not be archived: {archived}"


def test_every_id_the_capture_harnesses_click_is_seeded() -> None:
    """Nothing the screenshot/walkthrough tours open may go missing from the seed.

    The tours navigate by a stable seeded id (``data-detail-id="${TASK.nozzleUsage}"``),
    so dropping one from the fixture breaks the capture — and because the walkthrough
    is a *soft* gate, that surfaces only as a "capture failed" PR comment while every
    check stays green. Restoring the fixture by hand did exactly that once.
    """
    payload = json.loads(FIXTURE.read_text())
    seeded = {
        record.get("id")
        for key in ("tasks", "assets")
        for record in _records(payload, key)
    }
    constants = _fixture_id_constants()
    missing: dict[str, set[str]] = {}
    for script in sorted(E2E_DIR.glob("*.capture.ts")):
        wanted = set()
        for raw in DETAIL_ID.findall(script.read_text()):
            # An unresolvable `${GROUP.name}` is a typo'd constant, and stays in the
            # set under its own text so the failure names it rather than silently
            # dropping the assertion for that harness.
            ref = CONST_REF.match(raw)
            wanted.add(constants.get(f"{ref[1]}.{ref[2]}", raw) if ref else raw)
        if absent := wanted - seeded:
            missing[script.name] = absent
    assert not missing, (
        "capture harness(es) open a detail page for a record the seeded fixture no "
        f"longer has: {missing}. Restore it in "
        "tests/integration/ha_config/.storage/home_keeper."
    )
