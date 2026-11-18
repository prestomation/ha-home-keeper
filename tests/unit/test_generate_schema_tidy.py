"""``ci/generate_schema.py``'s clean-up step, in the lane that every PR runs.

The full published-schema gate (``test_generate_schema.py``) runs only where
``HK_SCHEMA_GATE`` is set. This file tests ``_tidy`` alone, which needs neither Home
Assistant nor the converter.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "ci" / "generate_schema.py"


def _load():
    spec = importlib.util.spec_from_file_location("generate_schema", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generate_schema = _load()


def test_a_list_length_becomes_an_item_count():
    node = {
        "type": "array",
        "items": {"type": "string"},
        "maxLength": 12,
        "minLength": 1,
    }
    assert generate_schema._tidy(node) == {
        "type": "array",
        "items": {"type": "string"},
        "maxItems": 12,
        "minItems": 1,
    }


def test_a_string_length_stays_a_string_length():
    node = {"type": "string", "maxLength": 35}
    assert generate_schema._tidy(node) == {"type": "string", "maxLength": 35}


def test_a_nested_list_length_is_fixed_too():
    node = {"anyOf": [{"type": "null"}, {"type": "array", "maxLength": 12}]}
    assert generate_schema._tidy(node) == {
        "anyOf": [{"type": "null"}, {"type": "array", "maxItems": 12}]
    }
