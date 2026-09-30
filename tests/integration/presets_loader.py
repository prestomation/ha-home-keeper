"""Load the shipped preset catalog straight from the component source.

``declarative_presets.py`` imports only its two data modules, and none of the three
imports Home Assistant, so they load by path as a small package with no HA
install. Reading the catalog here rather than restating a preset means a test
exercises what actually ships: the same defaults the panel's preset picker hands
the Add dialog.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import ModuleType

_COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "home_keeper"
_PACKAGE = "hk_presets"


def load_declarative_presets() -> ModuleType:
    """Return ``declarative_presets``, loaded with its data modules."""
    if f"{_PACKAGE}.declarative_presets" in sys.modules:
        return sys.modules[f"{_PACKAGE}.declarative_presets"]
    package = types.ModuleType(_PACKAGE)
    package.__path__ = [str(_COMPONENT)]
    sys.modules[_PACKAGE] = package
    module: ModuleType | None = None
    for name in (
        "declarative_preset_text",
        "declarative_presets_catalog",
        "declarative_presets",
    ):
        spec = importlib.util.spec_from_file_location(
            f"{_PACKAGE}.{name}", _COMPONENT / f"{name}.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    assert module is not None
    return module
