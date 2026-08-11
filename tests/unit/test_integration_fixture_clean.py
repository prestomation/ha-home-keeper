"""The committed integration fixture must not carry runtime-mutated state.

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
from pathlib import Path

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "integration"
    / "ha_config"
    / ".storage"
    / "home_keeper"
)

#: Names the integration suite creates as it runs. None should ever be committed.
TEST_CREATED_MARKERS = ("temp asset", "probe", "test clean gutters", "test water the")


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
