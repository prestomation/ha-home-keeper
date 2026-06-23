"""Fixtures and helpers for Home Keeper Docker integration tests.

Auth is bootstrapped via HA's onboarding API (no pre-seeded auth files needed).
The onboarding endpoint works without authentication when onboarding hasn't been
completed yet.
"""

import time

import pytest
import requests

HA_URL = "http://localhost:8123"
HA_STARTUP_TIMEOUT = 120  # seconds


def _wait_for_ha():
    deadline = time.monotonic() + HA_STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{HA_URL}/api/", timeout=5)
            if r.status_code in (200, 401):
                return
        except requests.ConnectionError:
            pass
        time.sleep(2)
    raise TimeoutError(f"Home Assistant did not start within {HA_STARTUP_TIMEOUT}s")


def _complete_onboarding():
    r = requests.post(
        f"{HA_URL}/api/onboarding/users",
        json={
            "client_id": f"{HA_URL}/",
            "name": "Test",
            "username": "test",
            "password": "testtest1",
            "language": "en",
        },
        timeout=10,
    )
    if r.status_code == 200:
        auth_code = r.json()["auth_code"]
    elif r.status_code == 403:
        return _login("test", "testtest1")
    else:
        raise RuntimeError(
            f"Failed to create onboarding user: {r.status_code} {r.text}"
        )

    r = requests.post(
        f"{HA_URL}/auth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": f"{HA_URL}/",
        },
        timeout=10,
    )
    r.raise_for_status()
    access_token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    for endpoint, payload in [
        ("core_config", {}),
        ("analytics", {}),
        (
            "integration",
            {"client_id": f"{HA_URL}/", "redirect_uri": f"{HA_URL}/?auth_callback=1"},
        ),
    ]:
        requests.post(
            f"{HA_URL}/api/onboarding/{endpoint}",
            headers=headers,
            json=payload,
            timeout=10,
        )

    return access_token


def _login(username, password):
    r = requests.post(
        f"{HA_URL}/auth/login_flow",
        json={
            "client_id": f"{HA_URL}/",
            "handler": ["homeassistant", None],
            "redirect_uri": f"{HA_URL}/?auth_callback=1",
        },
        timeout=10,
    )
    r.raise_for_status()
    flow_id = r.json()["flow_id"]

    r = requests.post(
        f"{HA_URL}/auth/login_flow/{flow_id}",
        json={"username": username, "password": password, "client_id": f"{HA_URL}/"},
        timeout=10,
    )
    r.raise_for_status()
    result = r.json()

    r = requests.post(
        f"{HA_URL}/auth/token",
        data={
            "grant_type": "authorization_code",
            "code": result["result"],
            "client_id": f"{HA_URL}/",
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def ha_token():
    _wait_for_ha()
    return _complete_onboarding()


def _wait_for_running(session):
    """Block until HA finishes starting (CoreState RUNNING).

    The `ha` fixture otherwise only waits for Home Keeper's own entity to appear,
    which can happen *before* HA finishes booting the rest of the config —
    notably the configuration.yaml automations that capture Home Keeper events
    into input_text sentinels. A slow startup (extra integrations, a loaded CI
    box) would then let an early test fire an event before its capture automation
    is listening, dropping the event and failing the test intermittently. Gating
    on RUNNING removes that race for the whole suite.
    """
    deadline = time.monotonic() + HA_STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        try:
            r = session.get(f"{HA_URL}/api/config", timeout=5)
            if r.status_code == 200 and r.json().get("state") == "RUNNING":
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise TimeoutError(
        f"Home Assistant did not reach RUNNING within {HA_STARTUP_TIMEOUT}s"
    )


@pytest.fixture(scope="session")
def ha(ha_token):
    session = requests.Session()
    session.headers.update(
        {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    )
    session.base_url = HA_URL

    # Gate on HA fully started so event-capture automations are listening, then
    # wait for the Home Keeper to-do entity to appear (integration loaded).
    _wait_for_running(session)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            r = session.get(f"{HA_URL}/api/states")
            if r.status_code == 200:
                ids = [s["entity_id"] for s in r.json()]
                if any(eid.startswith("todo.home_keeper") for eid in ids):
                    break
        except Exception:
            pass
        time.sleep(2)

    return session


def get_state(ha, entity_id):
    r = ha.get(f"{HA_URL}/api/states/{entity_id}")
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def call_service(ha, domain, service, data=None, return_response=False):
    url = f"{HA_URL}/api/services/{domain}/{service}"
    if return_response:
        url += "?return_response"
    r = ha.post(url, json=data or {})
    r.raise_for_status()
    return r.json()


def list_states(ha):
    r = ha.get(f"{HA_URL}/api/states")
    r.raise_for_status()
    return r.json()


def poll_state(ha, entity_id, condition, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state_obj = get_state(ha, entity_id)
        if state_obj is not None:
            try:
                if condition(state_obj["state"]):
                    return state_obj["state"]
            except (ValueError, TypeError):
                pass
        time.sleep(1)
    state_obj = get_state(ha, entity_id)
    state_val = state_obj["state"] if state_obj else "<entity not found>"
    raise TimeoutError(f"Timed out waiting for {entity_id}. Last state: {state_val}")
