"""The integration presets' templates, rendered by a real Home Assistant.

The integration presets compare a reading in hours whatever time unit the entity
reports, and they do it in Jinja: ``state | float`` times a table of factors keyed by
``attributes.unit_of_measurement``. Only Home Assistant's own template engine can say
whether that text renders as meant (its ``float`` filter raises on a bad value where
plain Jinja's returns 0), so these tests send the shipped templates through the
companion preview, which renders each match with the watcher's own renderer.

The container config has two duration sensors for this: 600 minutes (10 hours) and 3
days (72 hours). ``sensor.demo_printer_hours`` reads 780 h, the Battery Notes stub's
sensor reads 42 %, and ``input_number.hk_demo_meter`` has no unit at all.
"""

from __future__ import annotations

from typing import Any

from ha_registry import ws_send
from presets_loader import load_declarative_presets

presets = load_declarative_presets()

FILTER = "sensor.hk_demo_filter_time_left"
BRUSH = "sensor.hk_demo_brush_time_left"
PRINTER = "sensor.demo_printer_hours"
BATTERY = "sensor.e2e_battery_device_battery"


def _preset_trigger(preset_id: str) -> dict[str, Any]:
    """The trigger of the shipped preset *preset_id*.

    The tests name presets with one plain limit, so the verdict depends on the reading
    and the unit alone: Roborock's time left is under 24 h, and a robot mower's wear
    counter is over 100 h.
    """
    preset = presets.preset_by_id(preset_id)
    assert preset is not None, preset_id
    return dict(preset["default_spec"]["trigger"])


def _verdicts(
    ha, trigger: dict[str, Any], regex: str, domain: str = "sensor"
) -> dict[str, Any]:
    """Preview *trigger* over the entities *regex* matches; entity id -> row."""
    token = ha.headers["Authorization"].split(" ", 1)[1]
    reply = ws_send(
        token,
        {
            "type": "home_keeper/preview_declarative_companion",
            "companion": {
                "name": "Preset template probe",
                "selection": {"domain": domain, "entity_regex": regex},
                "trigger": trigger,
                "task_template": {"name_template": "{{ friendly_name }}"},
            },
        },
    )
    assert reply.get("success"), reply
    return {row["entity_id"]: row for row in reply["result"]["matched"]}


def test_the_time_left_template_compares_every_unit_in_hours(ha):
    trigger = _preset_trigger("roborock_life_low")
    assert trigger["mode"] == "template"
    assert trigger["template"].endswith("< 24 }}"), trigger
    rows = _verdicts(ha, trigger, rf"{FILTER}|{BRUSH}".replace(".", r"\."))
    # 600 min is 10 h, under the 24 h limit; 3 d is 72 h, over it. Read as plain
    # numbers, 600 would be over and 3 under: the opposite verdicts.
    assert rows[FILTER]["trigger_now"] is True, rows[FILTER]
    assert rows[BRUSH]["trigger_now"] is False, rows[BRUSH]


def test_the_time_left_template_reads_a_percentage_against_the_floor(ha):
    # Some models report the life left as a percentage under the same key. 42 % is
    # over the 10 % floor, so it is not low.
    rows = _verdicts(
        ha, _preset_trigger("roborock_life_low"), BATTERY.replace(".", r"\.")
    )
    assert rows[BATTERY]["trigger_now"] is False, rows[BATTERY]


def test_the_time_left_template_decides_nothing_without_a_unit(ha):
    rows = _verdicts(
        ha,
        _preset_trigger("roborock_life_low"),
        r"input_number\.hk_demo_meter",
        domain="input_number",
    )
    # A reading with no unit is not a time left. The template fails to render, and a
    # failed render neither opens nor closes a task.
    row = rows["input_number.hk_demo_meter"]
    assert row["trigger_now"] is None
    assert row["trigger_error"]


def test_the_wear_template_converts_time_and_keeps_other_units(ha):
    trigger = _preset_trigger("husqvarna_automower_wear_high")
    assert trigger["template"].endswith("> 100 }}"), trigger
    rows = _verdicts(ha, trigger, rf"{PRINTER}|{BATTERY}".replace(".", r"\."))
    # 780 h is over the 100 h limit. 42 in a unit that is not a time is compared as
    # it is, and it is under the limit.
    assert rows[PRINTER]["trigger_now"] is True, rows[PRINTER]
    assert rows[BATTERY]["trigger_now"] is False, rows[BATTERY]
