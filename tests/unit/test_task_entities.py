"""Per-task device-page entity names and the entity-set key (#377)."""

from __future__ import annotations

from typing import Any

import hk_task_entities as te
import pytest

DEVICE = "Dishwasher Leak Sensor"


def _companion_task(
    name: str = "Check on Dishwasher Leak Sensor",
    companion: Any = "Leak",
    *,
    blocked: bool = True,
) -> dict[str, Any]:
    return {
        "id": "t1",
        "name": name,
        "device_id": "dev1",
        "enabled": True,
        "source": {
            "declarative_companion": {
                "spec_id": "s1",
                "entity_registry_id": "e1",
                "entity_id": "binary_sensor.dishwasher_leak_sensor_water_leak",
            }
        },
        "managed_by": {"display_name": companion, "completion_blocked": blocked},
    }


def _task(name: str) -> dict[str, Any]:
    return {"id": "t2", "name": name, "device_id": "dev1", "enabled": True}


# ── companion_name ─────────────────────────────────────────────────────────────


def test_companion_name_reads_display_name_of_a_companion_task() -> None:
    assert (
        te.companion_name(_companion_task(companion="  Low battery ")) == "Low battery"
    )


def test_companion_name_is_none_without_a_companion_source() -> None:
    # A problem-sensor task stamps a display name too; it is not a companion.
    task = _task("Water leak")
    task["managed_by"] = {"display_name": "Home Keeper", "completion_blocked": True}
    assert te.companion_name(task) is None


@pytest.mark.parametrize("companion", ["", "   ", None, 5])
def test_companion_name_is_none_for_a_blank_or_bad_display_name(companion: Any) -> None:
    assert te.companion_name(_companion_task(companion=companion)) is None


def test_companion_name_is_none_without_managed_by() -> None:
    task = _companion_task()
    del task["managed_by"]
    assert te.companion_name(task) is None
    task["managed_by"] = "not a dict"
    assert te.companion_name(task) is None


# ── entity_name_prefix ─────────────────────────────────────────────────────────


def test_companion_task_uses_the_companion_name() -> None:
    assert te.entity_name_prefix(_companion_task(), DEVICE) == "Leak"


def test_companion_task_without_a_companion_name_falls_back_to_the_task_name() -> None:
    task = _companion_task(name="Battery: Dishwasher Leak Sensor", companion="")
    assert te.entity_name_prefix(task, DEVICE) == "Battery"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Device name at the start, with the separator after it trimmed.
        ("Dishwasher Leak Sensor: Replace battery", "Replace battery"),
        ("Dishwasher Leak Sensor - filter", "filter"),
        ("Dishwasher Leak Sensor \u2013 filter", "filter"),
        ("Dishwasher Leak Sensor is wet", "is wet"),
        # Device name at the end.
        ("Replace battery: Dishwasher Leak Sensor", "Replace battery"),
        ("Check on Dishwasher Leak Sensor", "Check on"),
        # Case does not matter.
        ("dishwasher leak sensor: Descale", "Descale"),
        # Whole words only.
        ("Dishwasher Leak Sensors check", "Dishwasher Leak Sensors check"),
        ("Check XDishwasher Leak Sensor", "Check XDishwasher Leak Sensor"),
        # In the middle it stays.
        ("Clean Dishwasher Leak Sensor pad", "Clean Dishwasher Leak Sensor pad"),
        # Nothing left: keep the whole name.
        ("Dishwasher Leak Sensor", "Dishwasher Leak Sensor"),
        ("Dishwasher Leak Sensor:", "Dishwasher Leak Sensor:"),
        # Surrounding spaces go.
        ("  Descale  ", "Descale"),
    ],
)
def test_other_task_drops_the_device_name(name: str, expected: str) -> None:
    assert te.entity_name_prefix(_task(name), DEVICE) == expected


def test_device_name_at_both_ends_is_cut_once_from_each() -> None:
    task = _task("Sensor check Sensor")
    assert te.entity_name_prefix(task, "Sensor") == "check"


def test_device_name_with_regex_characters_is_literal() -> None:
    assert te.entity_name_prefix(_task("A.B (1): Clean"), "A.B (1)") == "Clean"
    assert te.entity_name_prefix(_task("AxB (1): Clean"), "A.B (1)") == (
        "AxB (1): Clean"
    )


def test_device_name_is_trimmed_before_it_is_matched() -> None:
    assert te.entity_name_prefix(_task("Kettle: Descale"), "  Kettle ") == "Descale"


@pytest.mark.parametrize("device", [None, "", "   "])
def test_no_device_name_keeps_the_task_name(device: str | None) -> None:
    assert te.entity_name_prefix(_task(" Kettle: Descale "), device) == (
        "Kettle: Descale"
    )


@pytest.mark.parametrize("name", [None, "", "  "])
def test_blank_task_name_gives_an_empty_prefix(name: str | None) -> None:
    assert te.entity_name_prefix({"name": name}, DEVICE) == ""


# ── entity_set_key ─────────────────────────────────────────────────────────────


def test_entity_set_key_of_no_task() -> None:
    assert te.entity_set_key(None) == (None, False, None, None, False)
    assert te.entity_set_key({}) == (None, False, None, None, False)


def test_entity_set_key_fields() -> None:
    assert te.entity_set_key(_companion_task()) == (
        "dev1",
        True,
        "Check on Dishwasher Leak Sensor",
        "Leak",
        True,
    )
    assert te.entity_set_key({"id": "x", "name": "N"}) == (None, True, "N", None, False)
    assert te.entity_set_key({"id": "x", "enabled": False})[1] is False


def test_entity_set_key_changes_on_companion_rename() -> None:
    assert te.entity_set_key(_companion_task(companion="Leak")) != te.entity_set_key(
        _companion_task(companion="Water leak")
    )


def test_entity_set_key_changes_on_completion_blocked() -> None:
    assert te.entity_set_key(_companion_task(blocked=True)) != te.entity_set_key(
        _companion_task(blocked=False)
    )


def test_entity_set_key_ignores_other_fields() -> None:
    a = _companion_task()
    b = {**_companion_task(), "notes": "new", "next_due": "2026-01-01T00:00:00+00:00"}
    assert te.entity_set_key(a) == te.entity_set_key(b)
