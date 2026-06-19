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


def test_set_options_toggles_problem_sync(ha):
    # Baseline: syncing is on in the test config, so the mirror task exists.
    assert _wait_present(ha, True), "expected the synced task at start"

    # Turn syncing off via the service → entry reloads → synced task removed.
    call_service(ha, "home_keeper", "set_options", {"sync_problem_sensors": False})
    assert _wait_present(ha, False), (
        "disabling sync via set_options should remove the synced task"
    )

    # Turn it back on → the task is recreated. Leaves the config as it started.
    call_service(ha, "home_keeper", "set_options", {"sync_problem_sensors": True})
    assert _wait_present(ha, True), (
        "re-enabling sync via set_options should recreate the synced task"
    )
