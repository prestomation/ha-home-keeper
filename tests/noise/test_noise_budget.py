"""Noise budget: how much each action writes to the logbook, the recorder and the store.

Each test is 1 named scenario. It does 1 action on the shared Home Assistant and checks
the counts against ``baseline.json``: logbook rows, flips to and from unavailable,
``home_keeper_*`` events, store writes and entry reloads. Some scenarios are pinned at
0. Issue #467 is why: a rename loop on restart and a reload on each options change
filled the logbook, and no test saw it.

The scenarios run in file order and share state. Run the file whole, with
``bash ci/test-noise.sh``.
"""

from __future__ import annotations

import datetime as dt
import time
from typing import Any

from conftest import Baseline, HomeAssistantClient, check, measure

HK = "home_keeper"
COUNTS_SENSOR = "sensor.home_keeper_tasks"


def _run(
    ha: HomeAssistantClient, baseline: Baseline, name: str, action: Any, **kw: Any
) -> Any:
    measured, result = measure(ha, action, **kw)
    check(baseline, name, measured)
    return result


def _add(ha: HomeAssistantClient, name: str, **extra: Any) -> str:
    data = {"name": name, "recurrence_type": "floating", "interval": 30, "unit": "days"}
    return str(ha.call(HK, "add_task", {**data, **extra})["task_id"])


def _tick(ha: HomeAssistantClient) -> None:
    # The 5-minute clock only calls async_request_refresh. Updating an entity of the
    # coordinator runs the same refresh now.
    ha.call("homeassistant", "update_entity", {"entity_id": COUNTS_SENSOR})


def _device_asset(ha: HomeAssistantClient) -> tuple[str, str]:
    assets = ha.call(HK, "list_assets", {})["assets"]
    asset = next(a for a in assets if a.get("device_id"))
    return str(asset["device_id"]), str(asset["id"])


def _profiles(ha: HomeAssistantClient, profiles: list[dict[str, Any]]) -> Any:
    return ha.ws({"type": "home_keeper/set_options", "options": {"profiles": profiles}})


def _profile(name: str, sync_to: str = "") -> dict[str, Any]:
    return {
        "id": "noise_profile",
        "name": name,
        "filter": {},
        "sync": {"entity_id": sync_to, "two_way": True, "vanish_as_completed": False},
    }


# --- Startup and quiet time ----------------------------------------------------------


def test_cold_start(ha: HomeAssistantClient, baseline: Baseline) -> None:
    # Counts since the probe set up, which is before Home Keeper. Must run first.
    boot = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=10)
    _run(ha, baseline, "cold_start", None, reset=False, since=boot)


def test_idle_tick(ha: HomeAssistantClient, baseline: Baseline) -> None:
    _run(ha, baseline, "idle_tick", lambda: (_tick(ha), _tick(ha)))


# --- No-op calls ---------------------------------------------------------------------


def test_noop_set_options(ha: HomeAssistantClient, baseline: Baseline) -> None:
    _run(
        ha,
        baseline,
        "noop_set_options",
        lambda: ha.call(HK, "set_options", {"one_off_retention_days": 0}),
    )


# --- A normal day --------------------------------------------------------------------


def test_add_task(ha: HomeAssistantClient, baseline: Baseline, shared: dict) -> None:
    shared["task"] = _run(ha, baseline, "add_task", lambda: _add(ha, "Noise task"))


def test_update_task_notes(
    ha: HomeAssistantClient, baseline: Baseline, shared: dict
) -> None:
    data = {"task_id": shared["task"], "notes": "Check the seal."}
    _run(ha, baseline, "update_task_notes", lambda: ha.call(HK, "update_task", data))


def test_noop_update_task(
    ha: HomeAssistantClient, baseline: Baseline, shared: dict
) -> None:
    data = {"task_id": shared["task"], "notes": "Check the seal."}
    _run(ha, baseline, "noop_update_task", lambda: ha.call(HK, "update_task", data))


def test_rename_task_without_device(
    ha: HomeAssistantClient, baseline: Baseline, shared: dict
) -> None:
    data = {"task_id": shared["task"], "name": "Noise task renamed"}
    _run(
        ha,
        baseline,
        "rename_task_without_device",
        lambda: ha.call(HK, "update_task", data),
    )


def test_disable_task_without_device(
    ha: HomeAssistantClient, baseline: Baseline, shared: dict
) -> None:
    data = {"task_id": shared["task"], "enabled": False}
    _run(
        ha,
        baseline,
        "disable_task_without_device",
        lambda: ha.call(HK, "update_task", data),
    )
    ha.call(HK, "update_task", {"task_id": shared["task"], "enabled": True})
    ha.settle()


def test_complete_task(
    ha: HomeAssistantClient, baseline: Baseline, shared: dict
) -> None:
    data = {"task_id": shared["task"]}
    _run(ha, baseline, "complete_task", lambda: ha.call(HK, "complete_task", data))


def test_skip_task(ha: HomeAssistantClient, baseline: Baseline, shared: dict) -> None:
    data = {"task_id": shared["task"]}
    _run(ha, baseline, "skip_task", lambda: ha.call(HK, "skip_task", data))


def test_snooze_task(ha: HomeAssistantClient, baseline: Baseline, shared: dict) -> None:
    data = {"task_id": shared["task"], "hours": 24}
    _run(ha, baseline, "snooze_task", lambda: ha.call(HK, "snooze_task", data))


def test_delete_task(ha: HomeAssistantClient, baseline: Baseline, shared: dict) -> None:
    data = {"task_id": shared["task"]}
    _run(ha, baseline, "delete_task", lambda: ha.call(HK, "delete_task", data))


def test_complete_short_interval_task(
    ha: HomeAssistantClient, baseline: Baseline
) -> None:
    task = _add(ha, "Noise short interval", interval=2)
    ha.settle()
    data = {"task_id": task}
    _run(
        ha,
        baseline,
        "complete_short_interval_task",
        lambda: ha.call(HK, "complete_task", data),
    )
    ha.call(HK, "delete_task", data)
    ha.settle()


def test_device_task_lifecycle(
    ha: HomeAssistantClient, baseline: Baseline, shared: dict
) -> None:
    device, asset = _device_asset(ha)
    shared["asset"] = asset
    task = _run(
        ha,
        baseline,
        "add_task_on_device",
        lambda: _add(ha, "Noise device task", device_id=device),
    )
    data = {"task_id": task}
    _run(
        ha,
        baseline,
        "complete_task_on_device",
        lambda: ha.call(HK, "complete_task", data),
    )
    _run(
        ha, baseline, "delete_task_on_device", lambda: ha.call(HK, "delete_task", data)
    )


def test_noop_update_asset(
    ha: HomeAssistantClient, baseline: Baseline, shared: dict
) -> None:
    data = {"asset_id": shared["asset"], "notes": "Noise notes"}
    ha.call(HK, "update_asset", data)
    ha.settle()
    _run(ha, baseline, "noop_update_asset", lambda: ha.call(HK, "update_asset", data))


# --- Options, syncs and profiles ----------------------------------------------------


def test_change_option(ha: HomeAssistantClient, baseline: Baseline) -> None:
    _run(
        ha,
        baseline,
        "change_option",
        lambda: ha.call(HK, "set_options", {"cost_windows": [30, 90]}),
    )


def test_toggle_problem_sync(ha: HomeAssistantClient, baseline: Baseline) -> None:
    for state in (False, True):
        _run(
            ha,
            baseline,
            f"problem_sync_{'on' if state else 'off'}",
            lambda state=state: ha.call(
                HK, "set_options", {"sync_problem_sensors": state}
            ),
        )


def test_toggle_shopping_sync(ha: HomeAssistantClient, baseline: Baseline) -> None:
    for entity in ("todo.shopping_list", ""):
        _run(
            ha,
            baseline,
            f"shopping_sync_{'on' if entity else 'off'}",
            lambda entity=entity: ha.call(
                HK, "set_options", {"shopping_list_entity": entity}
            ),
        )


def test_profiles_and_todo_sync(ha: HomeAssistantClient, baseline: Baseline) -> None:
    steps = (
        ("profile_add", [_profile("Noise")]),
        ("profile_edit", [_profile("Noise renamed")]),
        ("todo_sync_on", [_profile("Noise renamed", "todo.family_chores")]),
        ("todo_sync_off", [_profile("Noise renamed")]),
        ("profile_delete", []),
    )
    for name, profiles in steps:
        _run(ha, baseline, name, lambda p=profiles: _profiles(ha, p))


# --- Language and transfer -----------------------------------------------------------


def test_language_change(ha: HomeAssistantClient, baseline: Baseline) -> None:
    for lang in ("de", "en"):
        _run(
            ha,
            baseline,
            f"language_{lang}",
            lambda lang=lang: ha.call(
                "hk_noise_probe", "set_language", {"language": lang}
            ),
        )


def test_import_own_export(ha: HomeAssistantClient, baseline: Baseline) -> None:
    exported = ha.call(HK, "export_data", {})
    document = exported.get("document", exported)
    # The first import fills default fields that the fixture's records lack (D6), so
    # the budget is for the second one: the same document again.
    ha.call(HK, "import_data", {"document": document})
    ha.settle()
    _run(
        ha,
        baseline,
        "import_same_document",
        lambda: ha.call(HK, "import_data", {"document": document}),
    )


# --- Scale ---------------------------------------------------------------------------


def test_hundred_tasks(
    ha: HomeAssistantClient, baseline: Baseline, shared: dict
) -> None:
    ids: list[str] = []
    _run(
        ha,
        baseline,
        "add_100_tasks",
        lambda: ids.extend(_add(ha, f"Noise bulk {i}") for i in range(100)),
    )
    shared["bulk"] = ids
    _run(ha, baseline, "idle_tick_100_tasks", lambda: (_tick(ha), _tick(ha)))


# --- Restart (last: it sets the probe counts to 0) -----------------------------------


def test_restart(ha: HomeAssistantClient, baseline: Baseline) -> None:
    def restart() -> None:
        try:
            ha.call("homeassistant", "restart", {})
        except Exception:
            pass  # the connection can close before the reply
        # Wait for the old process to stop, so wait_running sees the new one.
        deadline = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=60)
        while dt.datetime.now(dt.UTC) < deadline:
            try:
                ha.http.get("http://localhost:8123/api/", timeout=2)
            except Exception:
                break
            time.sleep(0.5)
        ha.wait_running()

    _run(ha, baseline, "restart", restart, reset=False)
    _run(ha, baseline, "idle_tick_after_restart", lambda: (_tick(ha), _tick(ha)))
