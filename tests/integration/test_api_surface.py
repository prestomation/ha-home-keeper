"""The API-surface model, checked against a running Home Assistant.

``tests/unit/test_api_surface.py`` proves the model matches the integration's
*source*. That is most of the job, but two things only a real Home Assistant can
answer: whether every modelled action is actually registered on the bus, and
whether unloading really takes them all away again. The second is what went wrong
with ``set_task_meter`` — registered on setup, absent from the teardown list, and
so still callable after the entry unloaded until Home Assistant restarted.

Both rest on Home Assistant framework contracts (service registration, the
config-entry unload lifecycle), which a unit test mocks away, so they belong
here — see AGENTS.md, "Anything resting on an HA framework contract needs an
integration-level assertion".
"""

import importlib.util
import sys
import time
from pathlib import Path

import pytest
import requests
from conftest import HA_URL
from ha_registry import ws_send

_ROOT = Path(__file__).resolve().parents[2]


def _api_surface():
    """Load the pure model, reusing the generator's HA-free loader.

    ``ci/test-python-integration.sh`` runs pytest from inside this directory, so
    the repo-root ``conftest.py`` and its ``hk_*`` aliases aren't in play. The
    generator already needs to import the model without Home Assistant installed;
    borrow that rather than repeating the stub-parent dance here.
    """
    spec = importlib.util.spec_from_file_location(
        "generate_api_docs", _ROOT / "ci" / "generate_api_docs.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.load_surface()


api_surface = _api_surface()


def _home_keeper_services(ha) -> set[str]:
    response = ha.get(f"{HA_URL}/api/services")
    response.raise_for_status()
    for domain in response.json():
        if domain["domain"] == "home_keeper":
            return set(domain["services"])
    return set()


def test_registered_services_match_the_model(ha) -> None:
    """A running Home Keeper offers exactly the modelled actions.

    The unit test reads the registration calls; this reads the service registry,
    so a registration behind a condition that never runs, or one silently lost to
    an exception during setup, still fails.
    """
    registered = _home_keeper_services(ha)
    modelled = set(api_surface.SERVICE_NAMES)
    assert registered == modelled, {
        "registered_but_not_modelled": sorted(registered - modelled),
        "modelled_but_not_registered": sorted(modelled - registered),
    }


def _token(ha) -> str:
    return ha.headers["Authorization"].split(" ", 1)[1]


def _entry_id(ha) -> str:
    entries = ws_send(
        _token(ha), {"type": "config_entries/get", "domain": "home_keeper"}
    )
    assert entries.get("success"), entries
    return entries["result"][0]["entry_id"]


def _set_entry_disabled(ha, entry_id: str, disabled: bool) -> dict:
    """Enable or disable the config entry.

    Disabling is a websocket command, not a REST route — there is no
    ``/api/config/config_entries/entry/<id>/disable``.
    """
    result = ws_send(
        _token(ha),
        {
            "type": "config_entries/disable",
            "entry_id": entry_id,
            "disabled_by": "user" if disabled else None,
        },
    )
    assert result.get("success"), result
    return result["result"]


def _wait_until(predicate, timeout: int = 60) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


def test_unloading_removes_every_service(ha) -> None:
    """Disabling the entry takes every action off the bus, leaving none behind.

    This is the check that would have caught ``set_task_meter``: it was missing
    from the teardown list, so it stayed callable against an integration that had
    unloaded. Now that the teardown iterates the model, one straggler here means
    either the model or the ``async_loaded_entries`` gate is wrong — and that gate
    has been quietly dead once already.
    """
    entry_id = _entry_id(ha)
    try:
        result = _set_entry_disabled(ha, entry_id, True)
        # Home Keeper implements async_unload_entry, so Home Assistant must be able
        # to take it down in place. Needing a restart would mean the unload path
        # itself is broken, and the rest of this test could not observe anything.
        assert not result.get("require_restart"), result
        gone = _wait_until(lambda: not _home_keeper_services(ha))
        leftover = sorted(_home_keeper_services(ha))
        assert gone, {
            "still_registered_after_unload": leftover,
            "why": "async_unload_entry must remove every SERVICE_NAMES entry",
        }
    finally:
        # Every later test in this suite drives a loaded Home Keeper, so put the
        # entry back before anything else runs — and fail loudly rather than
        # silently leaving the container in a state nothing else can use.
        _set_entry_disabled(ha, entry_id, False)
        restored = _wait_until(
            lambda: _home_keeper_services(ha) == set(api_surface.SERVICE_NAMES)
        )
        if not restored:
            pytest.fail(
                "Home Keeper did not come back after re-enabling its config entry; "
                f"services now: {sorted(_home_keeper_services(ha))}"
            )
