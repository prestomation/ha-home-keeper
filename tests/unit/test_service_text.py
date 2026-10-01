"""Service help text that must agree with the service schema.

* B21-5: ``hours`` and ``until`` of ``snooze_task`` are ``vol.Exclusive`` in one
  group, so a call that sets both fails. The help text must say so, and must not
  say that one field is ignored.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

_COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "home_keeper"
_RULE = "Do not set Hours and Until in the same call."


def _fields_from_strings(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["services"]["snooze_task"]["fields"]


def test_b21_5_the_schema_rejects_hours_with_until():
    source = (_COMPONENT / "__init__.py").read_text(encoding="utf-8")
    assert 'vol.Exclusive("hours", "deferral")' in source
    assert 'vol.Exclusive("until", "deferral")' in source


@pytest.mark.parametrize("path", ["strings.json", "translations/en.json"])
@pytest.mark.parametrize("field", ["hours", "until"])
def test_b21_5_the_strings_say_to_set_only_one(path, field):
    description = _fields_from_strings(_COMPONENT / path)[field]["description"]
    assert description.endswith(_RULE)
    assert "Ignored" not in description
    assert "unused" not in description


@pytest.mark.parametrize("field", ["hours", "until"])
def test_b21_5_services_yaml_says_to_set_only_one(field):
    services = yaml.safe_load((_COMPONENT / "services.yaml").read_text())
    description = services["snooze_task"]["fields"][field]["description"]
    assert description.endswith(_RULE)
    assert "Ignored" not in description
    assert "does not use" not in description
