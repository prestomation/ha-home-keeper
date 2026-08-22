"""Pytest configuration for Home Keeper unit tests.

The recurrence engine and task model are pure Python (they import nothing from
Home Assistant), so we load them in isolation here under a synthetic ``hk``
package. This lets the high-value core tests run without the full HA test harness
while still pointing coverage at the real source files in
``custom_components/home_keeper``.

The modules are *executed* under their real dotted name
(``custom_components.home_keeper.<mod>``) with stub parent packages, so the
package ``__init__.py`` — which does import Home Assistant — never runs.
``hk.<mod>`` and the flat ``hk_<mod>`` aliases then point at those same module
objects, which is what the tests import. Executing under the real name matters
for mutation testing: mutmut derives a mutant's key from the file path and
matches it against the function's ``__module__``, so a module executed as
``hk.recurrence`` would leave every mutant looking untested (see
``ci/test-mutation-python.sh``).

Nothing in the suite imports the real ``custom_components.home_keeper`` package
in-process — ``tests/integration`` and ``tests/upgrade`` drive a Docker Home
Assistant over REST/WS — so the stub parents shadow nothing.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CUSTOM_COMPONENTS_DIR = _ROOT / "custom_components"
_COMPONENT_DIR = _CUSTOM_COMPONENTS_DIR / "home_keeper"

_PKG = "custom_components.home_keeper"
_PURE_MODULES = (
    "const",
    "recurrence",
    "models",
    "assets",
    "documents",
    "events",
    "transitions",
    "reconcile",
    "shopping",
    "problem_tasks",
    "sensor_tasks",
    "inventory",
    "companions_catalog",
    "profiles",
    "notifications",
    "tags",
    "card_resource",
)


def _stub_package(name: str, path: Path) -> None:
    """Register an empty package for ``name`` so relative imports resolve.

    Real ``custom_components.home_keeper`` would execute an ``__init__.py`` full
    of Home Assistant imports; the stub gives the pure modules a parent to hang
    ``from .const import ...`` off without it.
    """
    if name in sys.modules:
        return
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[name] = pkg


def _load_pure_modules() -> None:
    """Load the pure core as ``hk`` / ``hk_*`` aliases (no HA imports)."""
    if "hk" in sys.modules:
        return
    _stub_package("custom_components", _CUSTOM_COMPONENTS_DIR)
    _stub_package(_PKG, _COMPONENT_DIR)
    for name in _PURE_MODULES:
        spec = importlib.util.spec_from_file_location(
            f"{_PKG}.{name}", str(_COMPONENT_DIR / f"{name}.py")
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{_PKG}.{name}"] = module
        spec.loader.exec_module(module)
    # ``hk.<mod>`` and the flat ``hk_<mod>`` names the tests use are aliases of
    # the very same module objects, so only one copy of the pure core is loaded.
    #
    # ``hk`` stays a *distinct* package object rather than another alias of
    # ``custom_components.home_keeper``. Python resolves ``from . import x``
    # through the parent's ``__name__``, so aliasing the two would make a module
    # loaded as ``hk.coordinator`` (which test_coordinator_purge.py and
    # test_calendar.py do, against fake ``hk.*`` siblings) reach for
    # ``custom_components.home_keeper.companions`` and drag in the real
    # HA-importing module instead of the fake.
    _stub_package("hk", _COMPONENT_DIR)
    for name in _PURE_MODULES:
        module = sys.modules[f"{_PKG}.{name}"]
        sys.modules[f"hk.{name}"] = module
        sys.modules[f"hk_{name}"] = module


_load_pure_modules()
