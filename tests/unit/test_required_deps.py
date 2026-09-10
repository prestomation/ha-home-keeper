"""The dependency gate itself, which is only useful if it really fails.

A guard that goes quiet is the defect it is there to prevent, so these tests
state that ``require`` raises rather than skips.
"""

from __future__ import annotations

import pytest
import required_deps


def test_a_required_package_that_is_missing_fails_the_tests(monkeypatch):
    monkeypatch.setattr(required_deps, "_DIST_FOR", {"nowhere": "PyYAML"})
    with pytest.raises(pytest.fail.Exception) as err:
        required_deps.require("nowhere", reason="it parses services.yaml")
    assert "PyYAML is not installed" in str(err.value)
    assert "it parses services.yaml" in str(err.value)


def test_hk_allow_missing_deps_turns_the_failure_back_into_a_skip(monkeypatch):
    monkeypatch.setenv("HK_ALLOW_MISSING_DEPS", "1")
    with pytest.raises(pytest.skip.Exception):
        required_deps.require("nowhere_at_all", reason="a bare pytest install")


def test_an_installed_package_is_returned():
    assert required_deps.require("json", reason="the standard library") is not None


def test_the_install_list_decides_what_is_required():
    # requirements-test.txt names these two, under other import names.
    assert required_deps.is_required("hypothesis")
    assert required_deps.is_required("yaml")
    assert required_deps.is_required("babel")
    # Held back on purpose: voluptuous-openapi pulls voluptuous in.
    assert not required_deps.is_required("jsonschema")
    assert not required_deps.is_required("voluptuous_openapi")


def test_optional_skips_only_for_a_package_the_project_holds_back():
    with pytest.raises(pytest.skip.Exception):
        required_deps.optional("nothing_holds_this", reason="not on the list")


def test_nothing_the_project_installs_is_missing():
    assert required_deps.missing_required() == []


def test_an_option_line_is_not_read_as_a_package(monkeypatch, tmp_path):
    """An option line names a file, and a file is not a package."""
    listing = tmp_path / "requirements-test.txt"
    listing.write_text(
        "-r base.txt\n-e .\n# a comment\nBabel\nhypothesis>=6 ; python_version>'3.9'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(required_deps, "_REQUIREMENTS", listing)
    assert required_deps._installed_by_ci() == {"babel", "hypothesis"}
    assert required_deps.missing_required() == []
