"""Pytest configuration for Home Keeper unit tests.

The recurrence engine and task model are pure Python (they import nothing from
Home Assistant), so we load them in isolation here under a synthetic ``hk``
package. This lets the high-value core tests run without the full HA test harness
while still pointing coverage at the real source files in
``custom_components/home_keeper``.

Tests that need a real Home Assistant runtime (store, entities, panel
registration) live under ``tests/integration`` and run against the Docker HA
container instead.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_COMPONENT_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "home_keeper"


def _load_pure_modules() -> None:
    """Load const/recurrence/models as an isolated ``hk`` package (no HA imports)."""
    if "hk" in sys.modules:
        return
    pkg = types.ModuleType("hk")
    pkg.__path__ = [str(_COMPONENT_DIR)]  # type: ignore[attr-defined]
    sys.modules["hk"] = pkg
    for name in ("const", "recurrence", "models"):
        spec = importlib.util.spec_from_file_location(
            f"hk.{name}", str(_COMPONENT_DIR / f"{name}.py")
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"hk.{name}"] = module
        spec.loader.exec_module(module)
    # Convenience top-level aliases for tests.
    sys.modules["hk_const"] = sys.modules["hk.const"]
    sys.modules["hk_recurrence"] = sys.modules["hk.recurrence"]
    sys.modules["hk_models"] = sys.modules["hk.models"]


_load_pure_modules()
