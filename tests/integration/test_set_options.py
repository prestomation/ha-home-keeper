"""Integration coverage for the ``set_options`` service / options write path.

The test config enables ``sync_problem_sensors`` and ships a ``device_class:
problem`` template sensor, so a synced task exists. Turning the option off via the
service must reload the entry and remove the synced task; turning it back on must
recreate it. This exercises options.async_set_options + the update-listener reload +
the problem-sensor reconcile end to end.
"""

import time

from conftest import call_service

SENSOR = "binary_sensor.sump_pump_problem"


def _synced_present(ha) -> bool:
    """Whether the mirror task for SENSOR currently exists.

    Raises if the entry is mid-reload (list_tasks 500s with "No active coordinator")
    so callers can tell a real "absent" from a transient reload window and retry,
    rather than mistaking the blip for the task having been removed.
    """
    resp = call_service(ha, "home_keeper", "list_tasks", {}, return_response=True)
    tasks = resp.get("service_response", resp)["tasks"]
    return any(
        (t.get("source") or {}).get("problem_sensor", {}).get("entity_id") == SENSOR
        for t in tasks
    )


def _wait_present(ha, present: bool, timeout=30) -> bool:
    """Poll until the synced task's presence matches *present* (ignoring reloads)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if _synced_present(ha) == present:
                return True
        except Exception:
            pass  # entry mid-reload — retry
        time.sleep(1)
    return False


def _wait_stable_present(ha, present: bool, timeout=60) -> bool:
    """Like _wait_present, but require the result to hold for two consecutive reads.

    ``list_tasks`` works as soon as ``entry.runtime_data`` is set — which happens
    early in ``async_setup_entry``, before the reload has fully finished. Requiring a
    stable reading avoids acting on a mid-reload snapshot (and toggling again into a
    *concurrent* reload, which is what the rapid off→on flip below would otherwise
    race into).
    """
    deadline = time.monotonic() + timeout
    hits = 0
    while time.monotonic() < deadline:
        try:
            ok = _synced_present(ha) == present
        except Exception:
            ok = False  # entry mid-reload — retry
        hits = hits + 1 if ok else 0
        if hits >= 2:
            return True
        time.sleep(1)
    return False


def test_set_options_toggles_problem_sync(ha):
    # Baseline: syncing is on in the test config, so the mirror task exists.
    assert _wait_present(ha, True), "expected the synced task at start"

    # Turn syncing off via the service → entry reloads → synced task removed. Wait
    # for the reload to fully settle before toggling back so the two reloads don't
    # overlap (a list_tasks read can succeed mid-setup).
    call_service(ha, "home_keeper", "set_options", {"sync_problem_sensors": False})
    assert _wait_stable_present(ha, False), (
        "disabling sync via set_options should remove the synced task"
    )

    # Turn it back on → the task is recreated. Leaves the config as it started.
    call_service(ha, "home_keeper", "set_options", {"sync_problem_sensors": True})
    assert _wait_stable_present(ha, True), (
        "re-enabling sync via set_options should recreate the synced task"
    )


def test_set_options_exclude_takes_effect_immediately(ha):
    """Adding an entity exclusion removes its synced task synchronously.

    ``set_options`` awaits the reload, so the reconcile has run by the time the
    call returns — the synced task is gone on the very next read, no polling. This
    is what makes the panel's Settings change "take effect right away": the panel
    refreshes its task list as soon as the service resolves. Regression guard.
    """
    assert _wait_present(ha, True), "expected the synced task at start"

    # Exclude the sensor; the service returns only after the reconcile reload.
    call_service(
        ha,
        "home_keeper",
        "set_options",
        {"problem_sensor_exclude_entities": [SENSOR]},
    )
    assert not _synced_present(ha), (
        "excluding the sensor should remove its synced task immediately (no wait)"
    )

    # Clear the exclusion → the task is recreated, again on the next read. Restores
    # the config to how it started for the following tests.
    call_service(
        ha,
        "home_keeper",
        "set_options",
        {"problem_sensor_exclude_entities": []},
    )
    assert _synced_present(ha), (
        "clearing the exclusion should recreate the synced task immediately (no wait)"
    )
