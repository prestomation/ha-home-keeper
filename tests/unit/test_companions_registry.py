"""Unit tests for the HA-bound companion registry guards (``companions.py``).

These cover the abuse bounds added for N12.3: the registration schema's ``vol.Length``
limits and the registry's ``MAX_COMPANIONS`` count cap. Unlike the pure catalog tests
(``test_companions.py``), ``companions.py`` imports Home Assistant + voluptuous, so the
whole module is skipped when those aren't installed (the pure-logic subset runs without
them); CI's full unit suite installs Home Assistant and exercises these.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("homeassistant")
vol = pytest.importorskip("voluptuous")

_COMPONENT_DIR = (
    Path(__file__).resolve().parents[2] / "custom_components" / "home_keeper"
)


def _companions():
    """Load ``companions.py`` under the synthetic ``hk`` package (conftest set it up).

    ``test_coordinator_purge`` installs a *fake* ``hk.companions`` stub into
    ``sys.modules`` (with only ``async_reconcile``), so a plain "already imported?"
    check can hand back that stub. Reload the real module whenever the cached one is
    missing the schema symbol.
    """
    module = sys.modules.get("hk.companions")
    if module is None or not hasattr(module, "REGISTER_COMPANION_SCHEMA"):
        spec = importlib.util.spec_from_file_location(
            "hk.companions", str(_COMPONENT_DIR / "companions.py")
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules["hk.companions"] = module
        spec.loader.exec_module(module)
    return module


def test_register_schema_rejects_oversized_fields():
    c = _companions()
    base = {"domain": "acme", "name": "Acme"}
    with pytest.raises(vol.Invalid):  # name over 100 chars
        c.REGISTER_COMPANION_SCHEMA({**base, "name": "x" * 101})
    with pytest.raises(vol.Invalid):  # description over 500
        c.REGISTER_COMPANION_SCHEMA({**base, "description": "y" * 501})
    with pytest.raises(vol.Invalid):  # icon over 100
        c.REGISTER_COMPANION_SCHEMA({**base, "icon": "z" * 101})
    with pytest.raises(vol.Invalid):  # docs_url over 500
        c.REGISTER_COMPANION_SCHEMA({**base, "docs_url": "https://ex.com/" + "a" * 500})
    with pytest.raises(vol.Invalid):  # more than 50 capabilities
        c.REGISTER_COMPANION_SCHEMA(
            {**base, "capabilities": [f"c{i}" for i in range(51)]}
        )


def test_register_schema_accepts_reasonable_descriptor():
    c = _companions()
    out = c.REGISTER_COMPANION_SCHEMA(
        {
            "domain": "acme",
            "name": "Acme",
            "icon": "mdi:paw",
            "description": "Does things.",
            "docs_url": "https://example.com/docs",
            "capabilities": ["a", "b"],
        }
    )
    assert out["domain"] == "acme"
    assert out["capabilities"] == ["a", "b"]


def test_registry_caps_new_domains_but_allows_updates():
    c = _companions()
    reg = c.CompanionRegistry(object())  # register() never touches hass
    for i in range(c.MAX_COMPANIONS):
        reg.register({"domain": f"d{i}", "name": f"D{i}"})
    assert len(reg._registered) == c.MAX_COMPANIONS

    # A brand-new domain past the cap is refused (not stored).
    reg.register({"domain": "overflow", "name": "Nope"})
    assert "overflow" not in reg._registered
    assert len(reg._registered) == c.MAX_COMPANIONS

    # Updating an already-registered domain still applies past the cap.
    updated = reg.register({"domain": "d0", "name": "Renamed"})
    assert updated["name"] == "Renamed"
    assert reg._registered["d0"]["name"] == "Renamed"
    assert len(reg._registered) == c.MAX_COMPANIONS
