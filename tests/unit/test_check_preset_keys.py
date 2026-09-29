"""The pure half of ``ci/check_preset_keys.py``: which keys are missing upstream."""

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "ci" / "check_preset_keys.py"
_spec = importlib.util.spec_from_file_location("check_preset_keys", _SCRIPT)
assert _spec and _spec.loader
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

ENTRY = {
    "domain": "demo",
    "duties": [
        {"keys": ["filter_time_left", "brush_time_left"]},
        {"platform": "binary_sensor", "keys": ["salt_low"]},
    ],
}


def test_no_key_is_missing_when_the_translations_name_them_all():
    translations = {
        "entity": {
            "sensor": {"filter_time_left": {}, "brush_time_left": {}},
            "binary_sensor": {"salt_low": {}},
        }
    }
    assert check.missing_keys(ENTRY, translations) == []


def test_a_key_is_missing_when_its_platform_does_not_name_it():
    translations = {
        "entity": {
            # The binary sensor key under the wrong platform does not count.
            "sensor": {"filter_time_left": {}, "salt_low": {}},
        }
    }
    assert check.missing_keys(ENTRY, translations) == [
        ("sensor", "brush_time_left"),
        ("binary_sensor", "salt_low"),
    ]


def test_every_key_is_missing_from_a_file_with_no_entity_section():
    assert len(check.missing_keys(ENTRY, {"config": {}})) == 3


def test_the_script_reads_the_shipped_catalog():
    assert len(check._integrations()) > 50
