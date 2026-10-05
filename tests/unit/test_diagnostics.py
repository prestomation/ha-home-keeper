"""Unit tests for what the diagnostics dump redacts (B20-1).

Diagnostics are attached to public GitHub issues. ``async_redact_data`` matches a key
exactly, so each free-text or private key must be named in ``TO_REDACT`` itself: the
task's ``notes`` did not cover a completion's ``note``.

``diagnostics.py`` imports Home Assistant, so it loads over the shared stub tree with
a fake ``coordinator`` sibling. The fake ``async_redact_data`` is a copy of Home
Assistant's (``homeassistant/components/diagnostics/util.py``), because the rule under
test is "exact key match, recursive into dicts and lists".
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import hk.assets as assets
import hk.models as models
import hk.recurrence as recurrence
import pytest
from ha_stubs import install_ha_stubs

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "custom_components" / "home_keeper"
)
NOW = datetime(2026, 6, 1, 12, tzinfo=UTC)
REDACTED = "**REDACTED**"


def _redact(data, to_redact):
    if not isinstance(data, (Mapping, list)):
        return data
    if isinstance(data, list):
        return [_redact(val, to_redact) for val in data]
    redacted = {**data}
    for key, value in redacted.items():
        if value is None or (isinstance(value, str) and not value):
            continue
        if key in to_redact:
            redacted[key] = REDACTED
        elif isinstance(value, (Mapping, list)):
            redacted[key] = _redact(value, to_redact)
    return redacted


def _fake(name: str, **attrs: object) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    return module


def _load_diagnostics() -> types.ModuleType:
    install_ha_stubs()
    fakes = {
        "homeassistant.components.diagnostics": _fake(
            "homeassistant.components.diagnostics", async_redact_data=_redact
        ),
        "homeassistant.config_entries": _fake(
            "homeassistant.config_entries", ConfigEntry=object
        ),
        "homeassistant.helpers.device_registry": _fake(
            "homeassistant.helpers.device_registry", DeviceEntry=object
        ),
        "hk.coordinator": _fake("hk.coordinator", HomeKeeperCoordinator=object),
    }
    saved = {name: sys.modules.get(name) for name in fakes}
    sys.modules.update(fakes)
    try:
        spec = importlib.util.spec_from_file_location(
            "hk.diagnostics", str(_COMPONENT_DIR / "diagnostics.py")
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module


diagnostics = _load_diagnostics()

SECRETS = (
    "Paid Bob 120 cash, gate code 4471",
    "Away at 12 Elm St until Sunday",
    "person.bob",
    "/local/receipt.jpg",
    "SN-SECRET-1",
    "Acme Mutual",
    "PN-777",
    "Acme Parts",
    "https://share.example/abc?token=xyz",
    "https://ex.com/filter",
    "private task notes",
)


def _task() -> dict:
    task = models.build_task(
        {
            "name": "Clean filter",
            "recurrence_type": "floating",
            "interval": 1,
            "unit": "months",
            "notes": "private task notes",
        },
        now=NOW,
    )
    task = recurrence.apply_completion(
        task,
        NOW,
        now=NOW,
        metadata={
            "note": SECRETS[0],
            "who": SECRETS[2],
            "photo": SECRETS[3],
            "cost": 120.0,
        },
    )
    return recurrence.skip_occurrence(
        task, now=NOW, metadata={"note": SECRETS[1], "who": SECRETS[2]}
    )


def _asset(task: dict) -> dict:
    asset = assets.build_asset(
        {
            "name": "Furnace",
            "serial_number": SECRETS[4],
            "cost": 2499.0,
            "metadata": [{"type": "text", "label": "Insurer", "value": SECRETS[5]}],
            "documents": [{"kind": "link", "name": "Manual", "url": SECRETS[8]}],
            "parts": [
                {
                    "name": "Filter",
                    "cost": 39.5,
                    "vendor": SECRETS[7],
                    "part_number": SECRETS[6],
                    "url": SECRETS[9],
                }
            ],
        },
        now=NOW,
    )
    assets.append_task_history(
        asset, assets.build_archived_history(task, archived_at=NOW.isoformat())
    )
    return asset


class _Store:
    def __init__(self, tasks: list[dict], asset_list: list[dict]) -> None:
        self._tasks = tasks
        self._assets = asset_list

    def list_tasks(self) -> list[dict]:
        return self._tasks

    def list_assets(self) -> list[dict]:
        return self._assets

    def get_shopping_items(self) -> dict:
        return {}


def _entry(store: _Store) -> types.SimpleNamespace:
    return types.SimpleNamespace(runtime_data=types.SimpleNamespace(store=store))


def _dump() -> tuple[dict, dict, dict]:
    task = _task()
    asset = _asset(task)
    entry = _entry(_Store([task], [asset]))
    full = asyncio.run(diagnostics.async_get_config_entry_diagnostics(None, entry))
    device = types.SimpleNamespace(
        id="dev1",
        name="Furnace",
        identifiers={("home_keeper", f"asset_{asset['id']}")},
    )
    per_device = asyncio.run(
        diagnostics.async_get_device_diagnostics(None, entry, device)
    )
    return full, per_device, task


@pytest.mark.parametrize("which", ["entry", "device"])
def test_no_private_value_survives(which: str) -> None:
    full, per_device, _ = _dump()
    text = json.dumps(full if which == "entry" else per_device)
    leaked = [secret for secret in SECRETS if secret in text]
    assert not leaked, leaked


def test_completion_and_skip_notes_are_redacted() -> None:
    full, _, _ = _dump()
    task = full["tasks"][0]
    assert task["completions"][0]["note"] == REDACTED
    assert task["skips"][0]["note"] == REDACTED
    archived = full["assets"][0]["task_history"][0]["completions"][0]
    assert archived["note"] == REDACTED


def test_schedule_fields_are_kept() -> None:
    # The dump must stay useful for debugging, so structure is not redacted.
    full, _per_device, task = _dump()
    dumped = full["tasks"][0]
    assert dumped["next_due"] == task["next_due"]
    assert dumped["completions"][0]["ts"] == task["completions"][0]["ts"]
    assert full["assets"][0]["parts"][0]["name"] == "Filter"
    assert full["counts"] == {
        "tasks": 1,
        "assets": 1,
        "parts": 1,
        "virtual_devices": 1,
    }
