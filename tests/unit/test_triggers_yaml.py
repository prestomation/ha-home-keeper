"""The Home Keeper triggers: ``api_surface.TRIGGERS``, ``triggers.yaml``, labels, icons.

``trigger.py`` builds its triggers from ``api_surface.TRIGGERS``. The editor reads
``triggers.yaml``, the labels in ``strings.json`` and each locale, and the icons in
``icons.json``. These tests keep all of them equal to the model, so a new bus event
with a payload cannot get a trigger with no description, label or icon.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

import custom_components.home_keeper.api_surface as api_surface

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)
_KEYS = [spec.key for spec in api_surface.TRIGGERS]


def _yaml() -> dict:
    data = yaml.safe_load((_COMPONENT_DIR / "triggers.yaml").read_text())
    # Home Assistant drops the keys that start with a dot (the YAML anchors).
    return {key: value for key, value in data.items() if not key.startswith(".")}


def _string_files() -> list[Path]:
    return [
        _COMPONENT_DIR / "strings.json",
        *sorted(_COMPONENT_DIR.glob("translations/*.json")),
    ]


def test_each_fired_event_with_a_payload_has_1_trigger() -> None:
    fired = [
        spec
        for spec in api_surface.EVENTS
        if spec.direction == "fired" and spec.payload != "none"
    ]
    assert [spec.event for spec in api_surface.TRIGGERS] == [s.name for s in fired]
    assert len(set(_KEYS)) == len(_KEYS)
    assert "register_companions" not in _KEYS
    assert "task_overdue" in _KEYS


def test_trigger_key_is_the_bus_name_without_the_domain() -> None:
    for spec in api_surface.TRIGGERS:
        assert spec.event == f"home_keeper_{spec.key}"
        assert re.fullmatch(r"[a-z][a-z0-9_]*", spec.key), spec.key


def test_only_task_part_and_appliance_triggers_take_a_target() -> None:
    targeted = {spec.payload for spec in api_surface.TRIGGERS if spec.targeted}
    untargeted = {spec.payload for spec in api_surface.TRIGGERS if not spec.targeted}
    assert targeted == {"task", "stock", "asset"}
    assert untargeted == {"companion", "declarative_companion", "data_transfer"}


def test_triggers_yaml_lists_each_trigger_in_order() -> None:
    assert list(_yaml()) == _KEYS


def test_triggers_yaml_targets_follow_the_model() -> None:
    data = _yaml()
    for spec in api_surface.TRIGGERS:
        entry = data[spec.key]
        if spec.targeted:
            assert entry == {"target": {"entity": [{"integration": "home_keeper"}]}}, (
                spec.key
            )
        else:
            assert not entry, spec.key


def test_each_trigger_has_a_name_and_a_description_in_every_language() -> None:
    files = _string_files()
    assert len(files) == 17
    for path in files:
        strings = json.loads(path.read_text(encoding="utf-8"))
        triggers = strings["triggers"]
        assert list(triggers) == _KEYS, path.name
        labels = strings["entity"]["event"]["home_keeper_events"]["state_attributes"]
        for key, text in triggers.items():
            assert set(text) == {"name", "description"}, (path.name, key)
            # 1 label for 1 event: the trigger and the event type say the same.
            assert text["name"] == labels["event_type"]["state"][key], (path.name, key)
            assert text["description"].strip(), (path.name, key)


def test_english_descriptions_are_1_short_sentence() -> None:
    strings = json.loads((_COMPONENT_DIR / "strings.json").read_text())
    for key, text in strings["triggers"].items():
        description = text["description"]
        assert description.startswith("Triggers when "), key
        assert description.endswith(".") and description.count(".") == 1, key
        assert len(description.split()) <= 20, key


def test_translations_en_matches_strings() -> None:
    strings = json.loads((_COMPONENT_DIR / "strings.json").read_text())
    english = json.loads((_COMPONENT_DIR / "translations" / "en.json").read_text())
    assert english["triggers"] == strings["triggers"]


def test_each_trigger_has_an_icon() -> None:
    icons = json.loads((_COMPONENT_DIR / "icons.json").read_text())
    assert list(icons) == ["triggers"]
    assert list(icons["triggers"]) == _KEYS
    for key, icon in icons["triggers"].items():
        assert re.fullmatch(r"mdi:[a-z0-9-]+", icon["trigger"]), key
