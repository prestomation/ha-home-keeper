"""The problem-sensor sync reacts to a device's area and labels (B18-10).

``problem_sync.py`` imports Home Assistant's ``binary_sensor`` component, so this
suite skips when Home Assistant is not installed. Its only sibling is the pure
``const``, which ``conftest`` has already loaded under ``hk``.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

pytest.importorskip("homeassistant.components.binary_sensor")

_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "custom_components"
    / "home_keeper"
    / "problem_sync.py"
)


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("hk.problem_sync_b18_10", _PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


problem_sync = _load()


def _entity(domain="binary_sensor", device_class="problem", original=None):
    return types.SimpleNamespace(
        domain=domain, device_class=device_class, original_device_class=original
    )


def _sync(entities, *, enabled=True):
    """A sync over a fake registry. Returns it and the list of scheduled jobs."""
    jobs: list[object] = []
    hass = types.SimpleNamespace(async_create_task=lambda coro: jobs.append(coro))
    entry = types.SimpleNamespace(
        options={"sync_problem_sensors": enabled}, entry_id="e1"
    )
    sync = problem_sync.ProblemSensorSync(hass, entry, coordinator=None)
    sync._resubscribe_state = lambda: jobs.append("resubscribe")

    async def _reconcile() -> None:
        return None

    sync._async_reconcile = _reconcile
    problem_sync.er = types.SimpleNamespace(
        async_get=lambda hass: "registry",
        async_entries_for_device=lambda reg, device_id: entities.get(device_id, []),
    )
    return sync, jobs


def _event(action="update", device_id="dev1", changes=None):
    data = {"action": action, "device_id": device_id}
    if changes is not None:
        data["changes"] = changes
    return types.SimpleNamespace(data=data)


def _ran(jobs) -> bool:
    for job in jobs:
        if hasattr(job, "close"):
            job.close()
    return "resubscribe" in jobs and len(jobs) == 2


@pytest.mark.parametrize("field", ["area_id", "labels"])
def test_b18_10_an_area_or_label_change_reconciles(field):
    sync, jobs = _sync({"dev1": [_entity()]})
    sync._handle_device_update(_event(changes={field: None}))
    assert _ran(jobs)


def test_b18_10_original_device_class_counts():
    sync, jobs = _sync({"dev1": [_entity(device_class=None, original="problem")]})
    sync._handle_device_update(_event(changes={"area_id": "a"}))
    assert _ran(jobs)


@pytest.mark.parametrize(
    ("entities", "event", "enabled"),
    [
        # A name change does not change what the sync does.
        ({"dev1": [_entity()]}, _event(changes={"name_by_user": "x"}), True),
        ({"dev1": [_entity()]}, _event(changes={}), True),
        ({"dev1": [_entity()]}, _event(), True),
        ({"dev1": [_entity()]}, _event(action="create", changes={"area_id": 1}), True),
        # The device holds no problem binary sensor.
        (
            {"dev1": [_entity(device_class="moisture")]},
            _event(changes={"area_id": 1}),
            True,
        ),
        ({"dev1": [_entity(domain="sensor")]}, _event(changes={"area_id": 1}), True),
        ({}, _event(changes={"area_id": 1}), True),
        # The sync is off.
        ({"dev1": [_entity()]}, _event(changes={"area_id": 1}), False),
    ],
)
def test_b18_10_other_device_events_are_ignored(entities, event, enabled):
    sync, jobs = _sync(entities, enabled=enabled)
    sync._handle_device_update(event)
    assert jobs == []
