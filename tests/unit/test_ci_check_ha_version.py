"""Unit tests for ``ci/check-ha-version.py``'s release selection.

The script guards against a CI job silently type-checking a months-old Home
Assistant (#199). A guard that picks the wrong "newest" would fail just as
quietly as the bug it exists to catch, so the selection is pure and tested here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from packaging.version import Version

_SCRIPT = Path(__file__).resolve().parents[2] / "ci" / "check-ha-version.py"


def _load():
    # The filename has a hyphen, so it is not importable as a module name.
    spec = importlib.util.spec_from_file_location("check_ha_version", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


newest = _load().newest


def _files(*, yanked: bool = False) -> list[dict]:
    return [{"filename": "homeassistant-x-py3-none-any.whl", "yanked": yanked}]


def test_picks_the_highest_stable_and_ignores_prereleases() -> None:
    releases = {
        "2026.2.3": _files(),
        "2026.8.0b6": _files(),
        "2026.8.1": _files(),
    }
    assert newest(releases, allow_prerelease=False) == Version("2026.8.1")


def test_prerelease_channel_can_outrank_the_newest_stable() -> None:
    releases = {"2026.8.1": _files(), "2026.9.0b1": _files()}

    assert newest(releases, allow_prerelease=True) == Version("2026.9.0b1")
    # Without --pre the beta must not be expected, or every stable job goes red.
    assert newest(releases, allow_prerelease=False) == Version("2026.8.1")


def test_version_ordering_is_numeric_not_lexicographic() -> None:
    # "2026.10.0" sorts *below* "2026.9.0" as a string — the trap this guard
    # would fall into if it compared the raw keys.
    releases = {"2026.9.0": _files(), "2026.10.0": _files()}
    assert newest(releases, allow_prerelease=False) == Version("2026.10.0")


@pytest.mark.parametrize(
    ("label", "bad"),
    [("fileless", []), ("fully yanked", _files(yanked=True))],
    ids=["fileless", "fully-yanked"],
)
def test_uninstallable_releases_are_skipped(label: str, bad: list[dict]) -> None:
    releases = {"2026.8.1": _files(), "2026.9.0": bad}
    assert newest(releases, allow_prerelease=False) == Version("2026.8.1"), label


def test_partially_yanked_release_still_counts() -> None:
    # One yanked wheel among several does not make the release uninstallable.
    releases = {
        "2026.8.1": _files(),
        "2026.9.0": [{"yanked": True}, {"yanked": False}],
    }
    assert newest(releases, allow_prerelease=False) == Version("2026.9.0")


def test_unparseable_versions_are_ignored() -> None:
    releases = {"2026.8.1": _files(), "not-a-version": _files()}
    assert newest(releases, allow_prerelease=False) == Version("2026.8.1")


def test_no_installable_release_yields_none() -> None:
    # Signals "cannot verify" to the caller rather than failing the job.
    assert newest({}, allow_prerelease=False) is None
    assert newest({"2026.8.0b1": _files()}, allow_prerelease=False) is None
