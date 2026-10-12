"""The oldest supported Home Assistant is named in 1 file and must agree."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read_env(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


ENV = _read_env((ROOT / "ci" / "oldest-ha.env").read_text())
MAJOR_MINOR = ".".join(ENV["OLDEST_HA_MIN"].split(".")[:2])


def _numbers(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def test_env_has_every_key():
    assert set(ENV) == {"OLDEST_HA", "OLDEST_HA_MIN"}


def test_hacs_json_minimum_matches():
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["homeassistant"] == ENV["OLDEST_HA_MIN"]


def test_readme_badge_matches():
    assert f"Home%20Assistant-{MAJOR_MINOR}%2B" in (ROOT / "README.md").read_text()


def test_tested_version_is_not_below_the_minimum():
    assert _numbers(ENV["OLDEST_HA"]) >= _numbers(ENV["OLDEST_HA_MIN"])


def test_tested_version_is_in_the_same_minor_release_as_the_minimum():
    # HACS offers the install from OLDEST_HA_MIN. CI must test that minor release.
    assert ENV["OLDEST_HA"].split(".")[:2] == ENV["OLDEST_HA_MIN"].split(".")[:2]


def test_read_env_skips_comments_and_blank_lines():
    assert _read_env("# note\n\nA=1\n B = two \n") == {"A": "1", "B": "two"}
