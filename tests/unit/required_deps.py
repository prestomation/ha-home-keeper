"""Import a test dependency, or fail — do not go quiet.

``pytest.importorskip`` is the wrong tool for a package the project installs. A
skip reads as "this lane does not cover that", so a missing install looks the
same as a deliberate exclusion. #309 shipped a red pull request that way: the
sandbox had no ``hypothesis``, two whole test files skipped at collection, and
the local run looked green.

So the rule is the install list. ``requirements-test.txt`` is what
``ci/install-deps.sh`` and ``ci/setup-ci-deps.sh`` (the session hook) install,
so every package named there must be importable. ``require`` fails the
collection of a file that needs one and cannot import it. A package that is
*not* on that list is optional on purpose — ``jsonschema`` and
``voluptuous-openapi`` are held back so ``voluptuous`` does not change what the
suite covers — and ``optional`` skips for those, as before.

``HK_ALLOW_MISSING_DEPS=1`` turns the failure back into a skip, for a bare
``pip install pytest`` run that only wants the pure-logic tests.
"""

from __future__ import annotations

import importlib
import os
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_REQUIREMENTS = _ROOT / "requirements-test.txt"

# The import name is not the package name for every distribution.
_DIST_FOR = {"yaml": "PyYAML", "babel": "Babel"}
# The other way round, for the whole-list check below. A distribution that is
# not here is checked under its own name, lowercased, with "-" as "_" — which
# is right for most of them, and keeps a new requirement checked by default.
_IMPORT_NAME = {
    "pyyaml": "yaml",
    "pytest-cov": "pytest_cov",
    "pytest-timeout": "pytest_timeout",
}


def _installed_by_ci() -> set[str]:
    """The distribution names in ``requirements-test.txt``, lowercased."""
    names: set[str] = set()
    for line in _REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        # "-r other.txt" and "-e ." name a file, not a package. Nothing here
        # imports one, and reading it as a package name would fail the run for
        # a package that does not exist.
        if line.startswith("-"):
            continue
        name = re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0].strip()
        if name:
            names.add(name.lower())
    return names


def is_required(import_name: str) -> bool:
    """Does the project install this package for every unit-test lane?"""
    dist = _DIST_FOR.get(import_name, import_name)
    return dist.lower() in _installed_by_ci()


def require(
    import_name: str,
    *,
    reason: str,
    installed_by: str = "requirements-test.txt",
    allow_module_level: bool = True,
):
    """Import ``import_name``, or fail the tests that need it.

    ``reason`` says what the package is for, and shows in the failure.
    ``installed_by`` names the file that installs it, for a lane that installs
    its own extras (``ci/install-schema-deps.sh``).
    """
    try:
        return importlib.import_module(import_name)
    except ImportError as err:
        dist = _DIST_FOR.get(import_name, import_name)
        if os.environ.get("HK_ALLOW_MISSING_DEPS"):
            pytest.skip(
                f"{dist} is not installed ({reason}); "
                "HK_ALLOW_MISSING_DEPS is set, so these tests skip",
                allow_module_level=allow_module_level,
            )
        pytest.fail(
            f"{dist} is not installed, so these tests cannot run: {reason}. "
            f"{installed_by} installs it, so a missing install is a broken "
            "environment and not a smaller test suite. Run "
            "'bash ci/setup-ci-deps.sh' to repair it. Set "
            f"HK_ALLOW_MISSING_DEPS=1 to skip instead. ({err})",
            pytrace=False,
        )


def optional(import_name: str, *, reason: str):
    """Import a package the project holds back on purpose, or skip.

    It still fails when the package is on the install list, because then the
    caller is wrong about which packages are optional.
    """
    if is_required(import_name):
        return require(import_name, reason=reason)
    return pytest.importorskip(import_name, reason=reason)


def missing_required() -> list[str]:
    """The packages ``requirements-test.txt`` names that do not import."""
    out = []
    for dist in _installed_by_ci():
        import_name = _IMPORT_NAME.get(dist, dist.replace("-", "_"))
        try:
            importlib.import_module(import_name)
        except ImportError:
            out.append(dist)
    return sorted(out)
