"""The adapters of the parity registry (``tests/fixtures/parity.json``).

1 call of the shipped Python function per rule id. ``test_shared_cases.py`` and
``test_parity_corpus.py`` both use them; ``frontend/test/parity-adapters.js`` is the
TypeScript twin. An adapter only turns a case into the function's arguments and its
result into the form that the case file states. It holds no rule of its own.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import hk_assets as assets
import hk_notifications as notifications
import hk_profiles as profiles
import hk_reconcile as reconcile
import hk_sensor_tasks as sensor_tasks

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = json.loads((ROOT / "tests/fixtures/parity.json").read_text())

# A notification length that no task carries, so the adapter can tell "the task's own
# length" from "the fallback" in what snooze_hours_for returns.
_FALLBACK_HOURS = 9999


def _when(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _profile(case: dict[str, Any], data: dict[str, Any]) -> bool:
    now = _when(case.get("now") or data["now"])
    return profiles.matches_filter(case["task"], case["filter"], now=now)


def _quantity(case: dict[str, Any], _data: dict[str, Any]) -> str:
    return assets.format_quantity(case["value"], case["unit"], case.get("lang") or "en")


def _snooze(case: dict[str, Any], _data: dict[str, Any]) -> int | None:
    hours = notifications.snooze_hours_for(
        case["input"], {"snooze_hours": _FALLBACK_HOURS}
    )
    return None if hours == _FALLBACK_HOURS else hours


def _use_count(case: dict[str, Any], _data: dict[str, Any]) -> int:
    return reconcile.uses_since_replacement(
        case["input"]["use"], case["input"]["replace"] or {}
    )


def _usage(case: dict[str, Any], _data: dict[str, Any]) -> dict[str, float]:
    task = {
        "recurrence_type": "sensor",
        "sensor": {"mode": "usage"},
        "completions": case["input"],
    }
    return sensor_tasks.usage_interval_stats(task)


ADAPTERS: dict[str, Callable[[dict[str, Any], dict[str, Any]], Any]] = {
    "profile_filter": _profile,
    "companion_keys": lambda c, _d: sorted(profiles.companion_keys(c["input"])),
    "quantity_format": _quantity,
    "decimal_mark": lambda c, _d: assets.decimal_mark(c["input"]),
    "part_low": lambda c, _d: assets.part_is_low(c["input"]),
    "part_tracks_stock": lambda c, _d: assets.part_tracks_stock(c["input"]),
    "icon": lambda c, _d: notifications.normalize_icon(c["input"]),
    "snooze_hours": _snooze,
    "buy_task": lambda c, _d: reconcile.buy_source(c["input"]) is not None,
    "use_count": _use_count,
    "usage_intervals": _usage,
    "edge_sensor_modes": lambda c, _d: sensor_tasks.holds_edge_state(c["input"]),
}
