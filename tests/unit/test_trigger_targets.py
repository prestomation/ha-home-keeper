"""Unit tests for ``trigger_targets.py``: what a trigger target means for an event.

The module is pure. ``trigger.py`` resolves a target with Home Assistant's own
helpers and hands the result here, so each rule is tested without Home Assistant.
"""

from __future__ import annotations

import pytest

import custom_components.home_keeper.trigger_targets as tt

TASK = "3f1c2d4e5a6b4c7d8e9f0a1b2c3d4e5f"
OTHER_TASK = "9a8b7c6d5e4f4a3b2c1d0e9f8a7b6c5d"
ASSET = "1111aaaa2222bbbb3333cccc4444dddd"
PART = "5555eeee6666ffff7777aaaa8888bbbb"
OTHER_PART = "0000aaaa0000bbbb0000cccc0000dddd"
DEVICE = "dev_heater"
SERVICE = "dev_service"


def refs(
    entities=(),
    device_ids=(),
    area_ids=(),
    label_ids=(),
    service_device_id=SERVICE,
) -> tt.TargetRefs:
    return tt.target_refs(
        entities,
        device_ids=device_ids,
        area_ids=area_ids,
        label_ids=label_ids,
        service_device_id=service_device_id,
    )


def task_payload(**extra) -> dict:
    return {
        "task_id": TASK,
        "device_id": None,
        "area_id": None,
        "labels": [],
        **extra,
    }


# ── Unique id shapes ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("suffix", ["done", "next_due", "overdue"])
def test_a_task_entity_names_its_task(suffix: str) -> None:
    got = refs([(f"home_keeper_{TASK}_{suffix}", DEVICE)])
    assert got.task_ids == frozenset({TASK})
    assert not got.everything
    assert got.device_ids == frozenset()


@pytest.mark.parametrize("suffix", ["stock", "low_stock"])
def test_a_part_entity_names_its_part(suffix: str) -> None:
    got = refs([(f"home_keeper_asset_{ASSET}_part_{PART}_{suffix}", DEVICE)])
    assert got.part_keys == frozenset({(ASSET, PART)})
    assert got.task_ids == frozenset()
    assert got.asset_ids == frozenset()


def test_a_part_id_that_ends_like_a_suffix_keeps_its_whole_id() -> None:
    got = refs([(f"home_keeper_asset_{ASSET}_part_x_low_low_stock", DEVICE)])
    assert got.part_keys == frozenset({(ASSET, "x_low")})


def test_a_metadata_entity_names_its_appliance() -> None:
    got = refs([(f"home_keeper_asset_{ASSET}_meta_warranty", DEVICE)])
    assert got.asset_ids == frozenset({ASSET})
    assert got.task_ids == frozenset()


@pytest.mark.parametrize(
    "unique_id",
    [
        "home_keeper_tasks",
        "home_keeper_calendar",
        "home_keeper_events",
        "home_keeper_profile_p1_tasks",
        f"home_keeper_{TASK}_unknown",
        "other_integration_thing",
        "",
    ],
)
def test_other_unique_ids_name_nothing(unique_id: str) -> None:
    got = refs([(unique_id, DEVICE)])
    assert got == refs()


def test_an_entity_on_the_service_device_means_every_event() -> None:
    assert refs([("home_keeper_tasks", SERVICE)]).everything
    assert refs([("home_keeper_events", SERVICE)]).everything


def test_the_service_device_as_a_device_means_every_event() -> None:
    assert refs(device_ids=[SERVICE]).everything
    assert not refs(device_ids=[DEVICE]).everything


def test_no_service_device_means_no_wildcard() -> None:
    got = refs([("home_keeper_tasks", None)], device_ids=["x"], service_device_id=None)
    assert not got.everything
    assert got.device_ids == frozenset({"x"})


def test_refs_keep_the_targeted_devices_areas_and_labels() -> None:
    got = refs(device_ids=[DEVICE], area_ids=["garage"], label_ids=["lbl"])
    assert got.device_ids == frozenset({DEVICE})
    assert got.area_ids == frozenset({"garage"})
    assert got.label_ids == frozenset({"lbl"})


# ── Task events ──────────────────────────────────────────────────────────────


def test_task_event_matches_a_target_on_its_task_entity() -> None:
    target = refs([(f"home_keeper_{TASK}_overdue", "dev_self")])
    assert tt.matches("task", task_payload(device_id="gone"), target)
    assert not tt.matches("task", task_payload(task_id=OTHER_TASK), target)


def test_task_event_matches_its_device() -> None:
    target = refs(device_ids=[DEVICE])
    assert tt.matches("task", task_payload(device_id=DEVICE), target)
    assert not tt.matches("task", task_payload(device_id="dev_other"), target)
    assert not tt.matches("task", task_payload(), target)


def test_task_event_matches_its_area() -> None:
    target = refs(area_ids=["garage"])
    assert tt.matches("task", task_payload(area_id="garage"), target)
    assert not tt.matches("task", task_payload(area_id="kitchen"), target)
    assert not tt.matches("task", task_payload(), target)


def test_task_event_matches_one_of_its_labels() -> None:
    target = refs(label_ids=["outdoor"])
    assert tt.matches("task", task_payload(labels=["x", "outdoor"]), target)
    assert not tt.matches("task", task_payload(labels=["x"]), target)
    assert not tt.matches("task", task_payload(labels=None), target)


def test_task_event_with_no_match_does_not_fire() -> None:
    assert not tt.matches("task", task_payload(), refs())


def test_everything_matches_each_payload() -> None:
    target = refs(device_ids=[SERVICE])
    assert tt.matches("task", task_payload(), target)
    assert tt.matches("stock", {"asset_id": ASSET, "part_id": PART}, target)
    assert tt.matches("asset", {"asset_id": ASSET}, target)


def test_a_payload_with_no_target_rule_always_matches() -> None:
    assert tt.matches("companion", {"domain": "x"}, refs())


# ── Part and appliance events ────────────────────────────────────────────────


def stock_payload(**extra) -> dict:
    return {"asset_id": ASSET, "part_id": PART, "device_id": DEVICE, **extra}


def test_stock_event_matches_its_part_entity_only() -> None:
    target = refs([(f"home_keeper_asset_{ASSET}_part_{PART}_stock", DEVICE)])
    assert tt.matches("stock", stock_payload(device_id=None), target)
    assert not tt.matches("stock", stock_payload(part_id=OTHER_PART), target)


def test_stock_event_matches_its_appliance_and_device() -> None:
    by_meta = refs([(f"home_keeper_asset_{ASSET}_meta_m1", None)])
    assert tt.matches("stock", stock_payload(device_id=None), by_meta)
    by_device = refs(device_ids=[DEVICE])
    assert tt.matches("stock", stock_payload(asset_id="a2"), by_device)
    assert not tt.matches("stock", stock_payload(device_id="dev_other"), by_device)


def test_stock_event_ignores_a_task_target() -> None:
    target = refs([(f"home_keeper_{TASK}_overdue", None)], area_ids=["garage"])
    assert not tt.matches("stock", stock_payload(device_id=None), target)


def test_asset_event_matches_its_appliance_part_or_device() -> None:
    payload = {"asset_id": ASSET, "device_id": DEVICE}
    by_meta = refs([(f"home_keeper_asset_{ASSET}_meta_m1", None)])
    by_part = refs([(f"home_keeper_asset_{ASSET}_part_{PART}_low_stock", None)])
    by_device = refs(device_ids=[DEVICE])
    assert tt.matches("asset", payload, by_meta)
    assert tt.matches("asset", payload, by_part)
    assert tt.matches("asset", payload, by_device)
    assert not tt.matches("asset", {"asset_id": "a2", "device_id": None}, by_part)
    assert not tt.matches("asset", {"asset_id": "a2", "device_id": None}, by_device)
